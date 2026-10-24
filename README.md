# load test studio

нагрузочный тест на k6 в github codespaces. без установки, без карты, с веб-панелью.

[открыть сайт](https://uxuxs82.github.io/loadtest-codespace/) · [создать codespace](https://codespaces.new/uxuxs82/loadtest-codespace?quickstart=1) · [github](https://github.com/uxuxs82/loadtest-codespace)

## что умеет

- target, vus, duration, ramp-up, think time и user agent
- кнопка full power: 500 vu, 1000 min, два куска по 500 min
- кампания помнит прогресс после перезапуска того же codespace
- summary.json и лог каждого куска
- защита от private и loopback target
- остановка теста одной кнопкой

## быстрый старт

1. нажми [создать codespace](https://codespaces.new/uxuxs82/loadtest-codespace?quickstart=1).
2. дождись установки k6 и flask. это занимает минуту или две.
3. codespaces откроет порт 8000. если вкладка не открылась, открой вкладку ports и нажми открыть 8000.
4. впиши свой target, подтверди, что сайт твой, и нажми full power.
5. первый кусок идет 500 минут. после него кампания встает на паузу.
6. останови и снова запусти тот же codespace из [github codespaces](https://github.com/codespaces). открой порт 8000 и нажми continue campaign.

важно: для продолжения нужен тот же codespace. новый codespace начинает с нуля, потому что `results/` не хранится в git.

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

## cli

если панель не нужна, можно запустить один кусок из терминала:

```bash
bash scripts/full-power.sh https://example.com/
```

переменные:

```bash
VUS=500 DURATION=500m RAMP_UP=5s THINK_TIME=0 bash scripts/full-power.sh https://example.com/
```

## тесты

```bash
python3 -m unittest discover -s tests -t . -v
```

## файлы

- `app.py`: flask api, кампания и запуск k6
- `loadtest.js`: сценарий k6
- `static/`: веб-панель
- `.devcontainer/`: установка k6 и автозапуск панели
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
