# load test studio

нагрузочный тест на k6 в github codespaces. без установки, без карты, с веб-панелью.

[открыть сайт](https://uxuxs82.github.io/loadtest-codespace/) · [создать codespace](https://codespaces.new/uxuxs82/loadtest-codespace?quickstart=1) · [github](https://github.com/uxuxs82/loadtest-codespace)

## что умеет

- target, vus, duration, ramp-up, think time и user agent
- запоминает последние target в браузере, подтверждение каждый раз не нужно
- кнопка full power: 500 vu, 1000 min, два куска по 500 min
- кампания помнит прогресс после перезапуска того же codespace
- summary.json и лог каждого куска
- защита от private и loopback target
- остановка теста одной кнопкой

## быстрый старт

1. нажми [создать codespace](https://codespaces.new/uxuxs82/loadtest-codespace?quickstart=1).
2. дождись установки k6 и flask. это занимает минуту или две.
3. codespaces откроет порт 8000. если вкладка не открылась, открой вкладку ports и нажми открыть 8000.
4. впиши свой target и нажми full power. панель запомнит его в браузере.
5. первый кусок идет 500 минут. после него кампания встает на паузу.
6. останови и снова запусти тот же codespace из [github codespaces](https://github.com/codespaces). открой порт 8000 и нажми continue campaign.

важно: для продолжения нужен тот же codespace. новый codespace начинает с нуля, потому что `results/` не хранится в git.

подтверждение владения убрано: панель доверяет тебе, но нагрузку давай только на свои сайты.

## постоянная панель

не создавай новый codespace на каждый тест. сделай один и сохрани ссылку на порт 8000 в закладки.

1. создай codespace один раз.
2. открой порт 8000.
3. скопируй адрес вида `https://<имя>-8000.app.github.dev` и сохрани в закладки.
4. дальше открывай эту закладку. если codespace остановлен, github предложит его запустить.
5. не удаляй codespace, тогда ссылка, настройки и кампания остаются.

это не отдельный хостинг, а твоя личная панель в codespaces. она живет, пока ты не удалишь codespace.

## настройки codespaces

- поставь idle timeout 240 минут в github settings -> codespaces. это максимум.
- держи вкладку панели открытой. каждый запрос `/status` дает вывод в терминал и сбрасывает idle timeout.
- после 12 часов codespace остановится. данные сохранятся. запусти его снова из [github codespaces](https://github.com/codespaces) и нажми continue campaign.
- devcontainer просит 4 ядра. если codespaces предложит 2, выбери 4 вручную.

## почему два куска

codespace живет максимум 12 часов, это 720 минут. 1000 минут это 16 часов 40 минут, поэтому один кусок не влезает.

full power режет 1000 минут на два куска по 500 минут. один кусок идет 8 часов 20 минут и спокойно влезает в 12 часов.

на 4 ядрах:

- 500 минут: около 33.3 core-hours
- 1000 минут: около 66.7 core-hours
- бесплатный лимит github: 120 core-hours в месяц

на 2 ядрах 1000 минут это около 33.3 core-hours, но 500 vu могут не влезть. devcontainer просит 4 ядра.

## настройки

- `target`: только публичный http или https
- `vus`: от 1 до 1000
- `duration`: для single run от 1 до 600 минут, для кампании общая длительность до 10000 минут
- `ramp-up`: от 0 до 600 секунд
- `think time`: от 0 до 60 секунд
- `user agent`: необязательно, по умолчанию `loadtest-codespace/1.0`
- `chunk`: от 1 до 600 минут, по умолчанию 500

## single run и кампания

`start once` запускает один тест. максимум 600 минут.

`full power` запускает кампанию. общая длительность режется на куски по `chunk` минут. после каждого куска кампания встает на паузу. следующий кусок запускается кнопкой `continue campaign`.

`reset campaign` убирает активную кампанию. старый `campaign.json` сохраняется в `results/campaign-<id>.json`, summary и логи остаются.

## локально

нужен k6 версии 2.3.0 и python 3.12 или новее.

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

открой `http://127.0.0.1:8000`.

## cli из termux

если панель не нужна, поставь команду `k6`. она сама поднимет codespace, запустит тест и скачает summary.

```bash
git clone https://github.com/uxuxs82/loadtest-codespace
cd loadtest-codespace
bash cli/install.sh
```

установщик кладет файл в `$PREFIX/bin/k6` в termux или в `~/.local/bin/k6` в обычном linux. нужен `gh`, авторизованный в github.

быстрый запуск:

```bash
k6 https://мой-сайт.ru/ 10 1m
k6 https://мой-сайт.ru/ 100 30m --think 1
k6 https://мой-сайт.ru/ --full --keep
```

`k6 <url> <vus> <time>` запускает один тест. если время больше 600 минут, тест автоматически станет кампанией с кусками по 500 минут. `--full` это пресет 500 vu и 1000 минут.

по умолчанию после завершения теста codespace останавливается, чтобы не тратить квоту. флаг `--keep` оставляет его запущенным для панели.

команды:

```bash
k6 status
k6 up
k6 continue
k6 stop
k6 logs
k6 summary
k6 summary --all
k6 reset
k6 down
k6 destroy
```

- `status`: состояние теста и кампании
- `up`: запустить codespace и панель, напечатать ссылку
- `continue`: запустить следующий кусок кампании
- `stop`: остановить текущий тест, codespace оставить
- `logs`: последние 200 строк лога, `--full` весь лог, `--save` сохранить
- `summary`: скачать summary текущего запуска, `--all` все куски кампании
- `reset`: сбросить кампанию
- `down`: остановить codespace
- `destroy`: удалить codespace вместе с результатами

файлы summary лежат в `~/.local/share/loadtest-codespace/`.

## тесты

```bash
python3 -m unittest discover -s tests -t . -v
```

## файлы

- `app.py`: flask api, кампания и запуск k6
- `loadtest.js`: сценарий k6
- `static/`: веб-панель
- `.devcontainer/`: установка k6 и автозапуск панели
- `cli/k6.py`: команда `k6` для termux
- `scripts/full-power.sh`: запуск одного куска из терминала
- `tests/`: тесты api

## ограничения

- давай нагрузку только на свои сайты.
- порт codespaces по умолчанию приватный. не делай его публичным.
- 500 vu на 1000 минут это очень много. сначала прогони короткий тест на 1-5 минут.
- cloudflare и другие защиты могут блокировать k6. попробуй другой user agent.
- состояние кампании лежит в `results/` и не коммитится. новый codespace начинает с нуля.
- codespaces не для постоянного хостинга. это разовый инструмент.

## лицензия

mit
