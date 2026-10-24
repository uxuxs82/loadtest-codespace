#!/usr/bin/env python3
import argparse
import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = "uxuxs82/loadtest-codespace"
WORKSPACE = "/workspaces/loadtest-codespace"
DEFAULT_DISPLAY = "loadtest-runner"
DEFAULT_MACHINE = "standardLinux32gb"
API = "http://127.0.0.1:8000"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "loadtest-codespace"
CONFIG_FILE = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "loadtest-codespace"
TERMINAL = ("completed", "failed", "stopped")


class CliError(Exception):
    pass


def load_config():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def gh(args, timeout=120, stdin=None):
    if not shutil.which("gh"):
        raise CliError("gh не установлен. поставь github cli и выполни gh auth login")
    try:
        return subprocess.run(
            ["gh", *args],
            input=stdin,
            stdin=subprocess.DEVNULL if stdin is None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CliError(f"gh не ответил за {timeout} секунд") from exc


def gh_ok(args, timeout=120, stdin=None):
    result = gh(args, timeout=timeout, stdin=stdin)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise CliError(message or f"gh завершился с кодом {result.returncode}")
    return result


def list_codespaces():
    result = gh(["codespace", "list", "--json", "name,displayName,repository,state,machineName"], timeout=60)
    if result.returncode != 0:
        raise CliError((result.stderr or result.stdout).strip() or "не удалось получить список codespaces")
    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise CliError("gh вернул непонятный список codespaces") from exc
    return [item for item in items if item.get("repository", "").lower() == REPO.lower()]


def find_codespace(items, config):
    wanted = config.get("codespace")
    if wanted:
        for item in items:
            if item.get("name") == wanted:
                return item
    for item in items:
        if item.get("displayName") == DEFAULT_DISPLAY:
            return item
    return None


def start_codespace(name):
    result = gh(
        ["api", "--method", "POST", "-H", "Accept: application/vnd.github+json", f"/user/codespaces/{name}/start"],
        timeout=120,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise CliError(message or "не удалось запустить codespace")


def wait_available(name, timeout=420):
    deadline = time.time() + timeout
    printed = False
    while time.time() < deadline:
        items = list_codespaces()
        item = next((entry for entry in items if entry.get("name") == name), None)
        if item:
            state = item.get("state")
            if state == "Available":
                return item
            if state in ("Unavailable", "Failed", "Deleted"):
                raise CliError(f"codespace в состоянии {state}")
            if not printed:
                print(f"жду codespace ({state})...")
                printed = True
        time.sleep(3)
    raise CliError("codespace не запустился за отведенное время")


def ensure_codespace(create=True):
    config = load_config()
    items = list_codespaces()
    item = find_codespace(items, config)
    if not item and create:
        print("создаю codespace loadtest-runner...")
        result = gh(
            [
                "codespace",
                "create",
                "-R",
                REPO,
                "-b",
                "main",
                "-m",
                DEFAULT_MACHINE,
                "-d",
                DEFAULT_DISPLAY,
                "--idle-timeout",
                "240m",
                "--default-permissions",
            ],
            timeout=600,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise CliError(message or "не удалось создать codespace")
        deadline = time.time() + 180
        while time.time() < deadline and not item:
            item = find_codespace(list_codespaces(), config)
            if not item:
                time.sleep(3)
        if not item:
            raise CliError("codespace создан, но не появился в списке")
    if not item:
        return None
    name = item["name"]
    state = item.get("state")
    if state == "ShuttingDown":
        print("жду остановки codespace...")
        deadline = time.time() + 120
        while time.time() < deadline:
            fresh = next((entry for entry in list_codespaces() if entry.get("name") == name), None)
            if fresh:
                item = fresh
                state = fresh.get("state")
            if state in ("Shutdown", "Stopped", "Available"):
                break
            time.sleep(3)
    if state in ("Shutdown", "Stopped"):
        print("запускаю codespace...")
        start_codespace(name)
        item = wait_available(name)
    elif state in ("Starting", "Provisioning", "Queued"):
        item = wait_available(name)
    elif state != "Available":
        raise CliError(f"codespace в состоянии {state}")
    config["codespace"] = name
    config["display_name"] = item.get("displayName") or DEFAULT_DISPLAY
    config["repository"] = REPO
    config["machine"] = item.get("machineName") or DEFAULT_MACHINE
    save_config(config)
    return name


def ssh_raw(name, script, timeout=120):
    return gh(["codespace", "ssh", "-c", name, "--", script], timeout=timeout)


def ssh_ok(name, script, timeout=120):
    result = ssh_raw(name, script, timeout=timeout)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise CliError(message or f"ssh завершился с кодом {result.returncode}")
    return result


def health_ok(text):
    try:
        return json.loads(text).get("status") == "ok"
    except (json.JSONDecodeError, AttributeError):
        return False


def panel_health(name):
    for _ in range(3):
        try:
            health = ssh_raw(name, f"curl -fsS --max-time 4 {API}/healthz", timeout=60)
        except CliError:
            health = None
        if health is not None and health.returncode == 0 and health_ok(health.stdout):
            return True
        time.sleep(1)
    return False


def panel_process(name):
    result = ssh_raw(name, "pgrep -f '[p]ython3 app.py' > /dev/null", timeout=45)
    return result.returncode == 0


def ensure_app(name):
    if panel_health(name):
        return
    if not panel_process(name):
        start = f"cd {WORKSPACE} && mkdir -p results && setsid -f bash .devcontainer/start.sh > results/ui.log 2>&1 < /dev/null"
        result = ssh_raw(name, start, timeout=60)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise CliError(message or "не удалось запустить панель")
        time.sleep(2)
    for _ in range(30):
        if panel_health(name):
            return
        time.sleep(2)
    log = ssh_raw(name, f"tail -n 20 {WORKSPACE}/results/ui.log", timeout=60)
    message = (log.stdout or log.stderr or "").strip()
    raise CliError("панель не поднялась" + (f"\n{message}" if message else ""))


def api(name, method, path, payload=None, timeout=30):
    url = API + path
    if payload is None:
        script = f"curl -sS --max-time {timeout} -X {method} -w '\\n%{{http_code}}' {url}"
    else:
        encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
        script = (
            f"printf %s {encoded} | base64 -d | "
            f"curl -sS --max-time {timeout} -X {method} -H 'Content-Type: application/json' "
            f"--data-binary @- -w '\\n%{{http_code}}' {url}"
        )
    result = ssh_raw(name, script, timeout=timeout + 20)
    raw = (result.stdout or "").strip()
    if not raw:
        message = (result.stderr or "").strip()
        raise CliError(message or "панель не ответила")
    body, _, code = raw.rpartition("\n")
    if not code.isdigit():
        raise CliError(raw)
    status = int(code)
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {"raw": body}
    if status >= 400:
        message = data.get("error") if isinstance(data, dict) else None
        raise CliError(message or f"панель вернула http {status}")
    return data


def api_text(name, path, timeout=60):
    result = ssh_raw(name, f"curl -fsS --max-time {timeout} {API}{path}", timeout=timeout + 20)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise CliError(message or "не удалось скачать файл")
    return result.stdout


def fmt_seconds(value):
    total = max(0, int(value or 0))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def parse_minutes(value):
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([smh]?)", text)
    if not match:
        raise CliError("время укажи как 10m, 2h или 600 (минуты)")
    number = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    if unit == "s":
        minutes = math.ceil(number / 60)
    elif unit == "h":
        minutes = math.ceil(number * 60)
    else:
        minutes = math.ceil(number)
    if not 1 <= minutes <= 10000:
        raise CliError("время должно быть от 1 минуты до 10000 минут")
    return minutes


def parse_vus(value):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CliError("vus должен быть целым числом") from exc
    if not 1 <= number <= 1000:
        raise CliError("vus должен быть от 1 до 1000")
    return number


def print_status(data, verbose=False):
    status = data.get("status") or "idle"
    config = data.get("config") or {}
    target = config.get("target") or "-"
    vus = config.get("vus") or "-"
    minutes = config.get("duration_minutes")
    duration = f"{minutes} min" if minutes else "-"
    print(f"статус: {status}   target: {target}   vus: {vus}   кусок: {duration}   прошло: {fmt_seconds(data.get('elapsed_seconds'))}")
    if data.get("run_id"):
        print(f"run: {data['run_id']}   exit: {data.get('exit_code') if data.get('exit_code') is not None else '-'}")
    if data.get("error"):
        print(f"ошибка: {data['error']}")
    campaign = data.get("campaign")
    if campaign:
        current = campaign.get("current_chunk")
        chunk = f"chunk {current} / {campaign.get('chunks_total')}" if current else f"{campaign.get('chunks_completed')} / {campaign.get('chunks_total')} chunks"
        print(
            f"кампания: {campaign.get('completed_minutes')} / {campaign.get('total_minutes')} min   "
            f"{campaign.get('status')}   {chunk}"
        )
    if verbose and data.get("log"):
        print()
        print(data["log"])


def stop_codespace(name):
    items = list_codespaces()
    item = next((entry for entry in items if entry.get("name") == name), None)
    if not item or item.get("state") in ("Shutdown", "Stopped"):
        return
    print("останавливаю codespace, чтобы не тратить квоту...")
    result = gh(["codespace", "stop", "-c", name], timeout=300)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        print(f"не удалось остановить codespace: {message}")


def finish_note(data):
    if not data:
        return
    campaign = data.get("campaign")
    status = data.get("status")
    if campaign and campaign.get("status") == "paused":
        print("кампания на паузе. следующий кусок: k6 continue")
    elif campaign and campaign.get("status") == "completed":
        print("кампания завершена. summary: k6 summary --all")
    elif status == "completed":
        print("готово. summary: k6 summary")
    elif status == "stopped":
        print("тест остановлен")
    elif status == "failed":
        print("тест упал. лог: k6 logs")


def stream_status(name, interval=10):
    script = (
        f"while true; do curl -sS --max-time 10 {API}/status; "
        f"printf '\\n__LT_END__\\n'; sleep {interval}; done"
    )
    try:
        process = subprocess.Popen(
            ["gh", "codespace", "ssh", "-c", name, "--", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise CliError(f"не удалось открыть ssh: {exc}") from exc
    buffer = []
    last_key = None
    last_print = 0.0
    final = None
    try:
        for line in process.stdout:
            if line.strip() != "__LT_END__":
                buffer.append(line)
                continue
            raw = "".join(buffer).strip()
            buffer = []
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            final = data
            campaign = data.get("campaign") or {}
            key = (data.get("status"), campaign.get("status"), campaign.get("current_chunk"))
            moment = time.time()
            if key != last_key or moment - last_print >= 60:
                print_status(data)
                print()
                last_key = key
                last_print = moment
            if data.get("status") in TERMINAL:
                break
    except KeyboardInterrupt:
        print("слежение прервано, тест продолжается на сервере")
        final = None
    finally:
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
    return final


def run_and_follow(name, final, keep):
    if final:
        print()
        finish_note(final)
        if not keep and final.get("status") in TERMINAL:
            stop_codespace(name)


def download_summary(name, run_id, folder):
    text = api_text(name, f"/summary/{run_id}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"summary-{run_id}.json"
    path.write_text(text, encoding="utf-8")
    print(path)
    return path


def download_log(name, run_id, folder):
    text = api_text(name, f"/log/{run_id}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"run-{run_id}.log"
    path.write_text(text, encoding="utf-8")
    print(path)
    return path


def connected(create=True):
    name = ensure_codespace(create=create)
    if not name:
        raise CliError("codespace не найден. создай его командой k6 up")
    ensure_app(name)
    return name


def status_data(name):
    return api(name, "GET", "/status")


def command_run(args):
    if not args.url:
        raise CliError("укажи url: k6 https://example.com/ 10 1m")
    name = connected()
    current = status_data(name)
    if current.get("status") in ("running", "stopping"):
        raise CliError("тест уже идет. смотри k6 status или останови k6 stop")
    if current.get("campaign"):
        state = current["campaign"].get("status")
        if state == "paused":
            raise CliError("кампания на паузе. продолжай k6 continue или сбрось k6 reset")
        raise CliError("кампания уже есть. сбрось ее командой k6 reset")
    full = bool(args.full)
    if args.vu is not None:
        vus = parse_vus(args.vu)
    elif args.vus_pos is not None:
        vus = parse_vus(args.vus_pos)
    else:
        vus = 500 if full else 10
    if args.time is not None:
        minutes = parse_minutes(args.time)
    elif args.time_pos is not None:
        minutes = parse_minutes(args.time_pos)
    else:
        minutes = 1000 if full else 1
    campaign = full or args.campaign or minutes > 600
    chunk = args.chunk if args.chunk is not None else 500
    if not 1 <= chunk <= 600:
        raise CliError("chunk должен быть от 1 до 600 минут")
    ramp = args.ramp
    if not 0 <= ramp <= 600:
        raise CliError("ramp должен быть от 0 до 600 секунд")
    think = args.think
    if not 0 <= think <= 60:
        raise CliError("think должен быть от 0 до 60 секунд")
    if args.interval < 1:
        raise CliError("interval должен быть не меньше 1 секунды")
    user_agent = (args.ua or "loadtest-codespace/1.0").strip()
    if not user_agent or len(user_agent) > 300 or "\n" in user_agent or "\r" in user_agent:
        raise CliError("user agent пустой или слишком длинный")
    payload = {
        "target": args.url,
        "vus": vus,
        "ramp_up_seconds": ramp,
        "think_time_seconds": think,
        "user_agent": user_agent,
    }
    if campaign:
        payload["total_minutes"] = minutes
        payload["chunk_minutes"] = min(chunk, minutes)
        print(f"запускаю кампанию: {vus} vu, {minutes} min, куски по {payload['chunk_minutes']} min")
        result = api(name, "POST", "/start-campaign", payload)
    else:
        payload["duration_minutes"] = minutes
        print(f"запускаю тест: {vus} vu, {minutes} min")
        result = api(name, "POST", "/start", payload)
    print()
    print_status(result)
    if args.no_follow:
        return
    print()
    final = stream_status(name, args.interval)
    run_and_follow(name, final, args.keep)


def command_status(args):
    config = load_config()
    items = list_codespaces()
    item = find_codespace(items, config)
    if not item:
        print("codespace не создан. запусти k6 up")
        return
    name = item["name"]
    config["codespace"] = name
    save_config(config)
    print(f"codespace: {name}   state: {item.get('state')}   machine: {item.get('machineName')}")
    if item.get("state") != "Available":
        print("остановлен. k6 up запустит его снова")
        return
    try:
        ensure_app(name)
        data = status_data(name)
    except CliError as exc:
        print(f"панель недоступна: {exc}")
        return
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print_status(data, verbose=args.log)
    campaign = data.get("campaign")
    if campaign and args.log:
        for chunk in campaign.get("chunks") or []:
            code = f" exit={chunk['exit_code']}" if chunk.get("exit_code") is not None else ""
            print(f"  {chunk['index']:02d}  {chunk['minutes']} min  {chunk['status']}{code}")


def command_up(args):
    name = connected()
    print(f"codespace: {name}")
    print(f"панель: https://{name}-8000.app.github.dev")
    if args.log:
        data = status_data(name)
        print_status(data, verbose=True)


def command_continue(args):
    name = connected()
    result = api(name, "POST", "/continue")
    print_status(result)
    if args.no_follow:
        return
    print()
    final = stream_status(name, args.interval)
    run_and_follow(name, final, args.keep)


def command_stop(args):
    name = connected()
    result = api(name, "POST", "/stop")
    print_status(result)


def command_reset(args):
    name = connected()
    result = api(name, "POST", "/reset")
    print_status(result)


def command_logs(args):
    name = connected()
    data = status_data(name)
    run_id = data.get("run_id")
    if not run_id:
        raise CliError("еще не было запусков")
    if args.full:
        text = api_text(name, f"/log/{run_id}")
        print(text)
    else:
        text = data.get("log") or api_text(name, f"/log/{run_id}")
        print("\n".join(text.splitlines()[-200:]))
    if args.save:
        download_log(name, run_id, DATA_DIR)


def command_summary(args):
    name = connected()
    data = status_data(name)
    folder = Path(args.out).expanduser() if args.out else DATA_DIR
    run_ids = []
    if args.all:
        campaign = data.get("campaign")
        if not campaign:
            raise CliError("активной кампании нет")
        for chunk in campaign.get("chunks") or []:
            if chunk.get("summary_url") and chunk.get("run_id"):
                run_ids.append(chunk["run_id"])
        if not run_ids:
            raise CliError("готовых summary пока нет")
    else:
        run_id = data.get("run_id")
        if not run_id or not data.get("summary_url"):
            raise CliError("summary текущего запуска еще нет")
        run_ids.append(run_id)
    for run_id in run_ids:
        download_summary(name, run_id, folder)


def command_down(args):
    config = load_config()
    item = find_codespace(list_codespaces(), config)
    if not item:
        print("codespace не создан")
        return
    if item.get("state") in ("Shutdown", "Stopped"):
        print("codespace уже остановлен")
        return
    gh_ok(["codespace", "stop", "-c", item["name"]], timeout=300)
    print("codespace остановлен")


def command_destroy(args):
    config = load_config()
    item = find_codespace(list_codespaces(), config)
    if not item:
        print("codespace не создан")
        return
    name = item["name"]
    if not args.yes:
        answer = input(f"удалить {name}? state и результаты пропадут. [y/N] ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("отмена")
            return
    gh_ok(["codespace", "delete", "-c", name, "--force"], timeout=300)
    if config.get("codespace") == name:
        config.pop("codespace", None)
        save_config(config)
    print("codespace удален")


def build_run_parser():
    parser = argparse.ArgumentParser(prog="k6", description="нагрузочный тест через github codespaces")
    parser.add_argument("url", nargs="?", help="target url")
    parser.add_argument("vus_pos", nargs="?", type=int, help="число vu")
    parser.add_argument("time_pos", nargs="?", help="длительность: 10m, 2h, 600")
    parser.add_argument("-u", "--vu", type=int, help="число vu, по умолчанию 10")
    parser.add_argument("-t", "--time", help="длительность, по умолчанию 1m")
    parser.add_argument("--ramp", type=int, default=5, help="ramp-up в секундах, по умолчанию 5")
    parser.add_argument("--think", type=float, default=0.0, help="think time в секундах, по умолчанию 0")
    parser.add_argument("--ua", help="user agent")
    parser.add_argument("--chunk", type=int, help="длина куска кампании, по умолчанию 500")
    parser.add_argument("--campaign", action="store_true", help="резать длительность на куски")
    parser.add_argument("--full", action="store_true", help="пресет 500 vu, 1000 min, куски по 500")
    parser.add_argument("--no-follow", action="store_true", help="не следить за тестом")
    parser.add_argument("--keep", action="store_true", help="не останавливать codespace после теста")
    parser.add_argument("--interval", type=int, default=10, help="интервал слежения в секундах")
    return parser


def build_main_parser():
    parser = argparse.ArgumentParser(prog="k6", description="нагрузочный тест через github codespaces")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="запустить тест")
    for action in build_run_parser()._actions:
        if action.dest == "help":
            continue
        run._add_action(action)
    status = sub.add_parser("status", help="показать состояние")
    status.add_argument("--json", action="store_true")
    status.add_argument("--log", action="store_true")
    up = sub.add_parser("up", help="запустить codespace и панель")
    up.add_argument("--log", action="store_true")
    cont = sub.add_parser("continue", help="продолжить кампанию")
    cont.add_argument("--no-follow", action="store_true")
    cont.add_argument("--keep", action="store_true")
    cont.add_argument("--interval", type=int, default=10)
    sub.add_parser("stop", help="остановить тест")
    reset = sub.add_parser("reset", help="сбросить кампанию")
    logs = sub.add_parser("logs", help="показать лог")
    logs.add_argument("--full", action="store_true")
    logs.add_argument("--save", action="store_true")
    summary = sub.add_parser("summary", help="скачать summary")
    summary.add_argument("--all", action="store_true")
    summary.add_argument("--out")
    sub.add_parser("down", help="остановить codespace")
    destroy = sub.add_parser("destroy", help="удалить codespace")
    destroy.add_argument("-y", "--yes", action="store_true")
    sub.add_parser("help", help="показать помощь")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_main_parser()
    commands = {"run", "status", "up", "continue", "stop", "reset", "logs", "summary", "down", "destroy", "help"}
    if not argv or argv[0] in ("-h", "--help"):
        parser.print_help()
        return 0
    if argv[0] not in commands:
        argv.insert(0, "run")
    args = parser.parse_args(argv)
    if args.command == "help":
        parser.print_help()
        return 0
    handlers = {
        "run": command_run,
        "status": command_status,
        "up": command_up,
        "continue": command_continue,
        "stop": command_stop,
        "reset": command_reset,
        "logs": command_logs,
        "summary": command_summary,
        "down": command_down,
        "destroy": command_destroy,
    }
    handlers[args.command](args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CliError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("прервано", file=sys.stderr)
        sys.exit(130)
