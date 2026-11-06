# Как запустить Xonta Customs RU и добавить его во все MCP-каталоги

Порядок важен: сначала сервер должен работать по публичному адресу и лежать на GitHub и PyPI,
потом его можно регистрировать. Каталоги проверяют адрес и репозиторий автоматически.

Имя сервера в реестрах: **`ru.xonta/customs`**
Публичный адрес: **`https://mcp.xonta.ru/customs/mcp`**
Пакет PyPI: **`xonta-customs-mcp`**
Репозиторий: **`github.com/mrsergeiluzhnov/xonta-customs-mcp`**

## Быстрый путь (3 команды)

```bash
# на своём компьютере, в распакованной папке (git-репозиторий с коммитом уже внутри)
bash scripts/publish.sh            # GitHub + PyPI + официальный реестр

# на VPS под root (после того как пакет появился на PyPI)
curl -O https://raw.githubusercontent.com/mrsergeiluzhnov/xonta-customs-mcp/main/scripts/deploy_vps.sh
bash deploy_vps.sh /tmp/tnved.xlsx # сервис + загрузка тарифа
```

Перед `publish.sh` один раз войдите в `gh` и выполните вход в реестр (шаг 4 ниже).
Затем nginx (шаг 2), каталоги (шаги 5–9). Ниже то же самое по шагам.

---

## Шаг 1. GitHub

```bash
cd xonta-customs-mcp
git init -b main
git add .
git commit -m "Customs MCP server for Russia and the EAEU"
gh repo create mrsergeiluzhnov/xonta-customs-mcp --public --source . --push \
  --description "MCP server for importing into Russia/EAEU: TN VED codes, duties, VAT, fees, antidumping"
gh repo edit --add-topic mcp,mcp-server,customs,tnved,eaeu,russia,import,hs-code,model-context-protocol
```

Файл `glama.json` в корне уже указывает вас владельцем, он нужен для Glama.

## Шаг 2. Сервер на VPS (Timeweb, рядом с DocParse)

```bash
sudo useradd -r -M -d /opt/xonta-customs -s /usr/sbin/nologin xcustoms
sudo -u xcustoms python3 -m venv /opt/xonta-customs/venv
sudo -u xcustoms /opt/xonta-customs/venv/bin/pip install xonta-customs-mcp   # после шага 3
# до публикации на PyPI: pip install git+https://github.com/mrsergeiluzhnov/xonta-customs-mcp

sudo -u xcustoms mkdir -p /opt/xonta-customs/data
```

**Загрузите таблицу ТН ВЭД со ставками.** Скачайте Excel с кодами и ставками ЕТТ
(например, бесплатная ежедневная выгрузка на tws.by/tws/tnved/download) и загрузите:

```bash
sudo -u xcustoms env XONTA_CUSTOMS_DATA=/opt/xonta-customs/data \
  /opt/xonta-customs/venv/bin/xonta-customs-load-tariff tnved.xlsx --source "tws.by, 05.11.2026"
```

Загрузчик сам находит колонки «Код», «Наименование», «Ставка». Если напишет, что не нашёл
заголовок, пришлите мне первые строки файла, поправлю. Выборочно сверьте 3–5 ставок
с Решением Совета ЕЭК № 80: выгрузка бесплатная и без гарантий.

Автообновление: `deploy/update_tariff.sh` + cron (внутри файла пример).

**Связка с DocParse** (для PDF и сканов инвойсов). DocParse работает на этом же VPS,
поэтому таможенный сервер зовёт его напрямую, без оплаты x402. Нужен внутренний адрес DocParse,
который принимает `POST {"url": "..."}` и отдаёт Markdown (как текст или JSON с полем
`markdown`/`text`/`content`). Если у DocParse такого входа нет, добавьте его, слушая только 127.0.0.1:

```bash
sudo -u xcustoms tee /opt/xonta-customs/docparse.env >/dev/null <<'EOF'
DOCPARSE_URL=http://127.0.0.1:<порт_docparse>/<путь>
DOCPARSE_TOKEN=<длинный_случайный_токен>
EOF
sudo chmod 600 /opt/xonta-customs/docparse.env
```

Без этого файла сервер всё равно разбирает Excel/CSV-инвойсы и текст, который агент передал сам.

**Запуск как сервиса:**

```bash
sudo cp deploy/xonta-customs.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now xonta-customs
curl -s 127.0.0.1:8765/health
```

**nginx:** вставьте блок из `deploy/nginx-mcp.xonta.ru.conf` в существующий `server` для
mcp.xonta.ru, затем `sudo nginx -t && sudo systemctl reload nginx`. Проверка:

```bash
curl -s https://mcp.xonta.ru/customs/health
curl -s -X POST https://mcp.xonta.ru/customs/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -c 300
```

Если на сервере включена защита от ботов (Cloudflare и т.п.), пропустите User-Agent
`SmitheryBot` и запросы к `/customs/` — иначе каталоги не смогут просканировать сервер.

## Шаг 3. PyPI

Нужен аккаунт на pypi.org и API-токен (Account settings → API tokens).

```bash
pip install build twine
python -m build
twine upload dist/*
```

В README уже есть строка `mcp-name: ru.xonta/customs` — по ней официальный реестр
проверяет, что пакет ваш. Не удаляйте её.

## Шаг 4. Официальный реестр MCP (главный, от него питаются остальные)

registry.modelcontextprotocol.io. Из него автоматически подтягивают серверы GitHub MCP Registry
(VS Code, Copilot), PulseMCP и другие агрегаторы. Ручной модерации нет.

Имя `ru.xonta/customs` требует доказать владение доменом xonta.ru. Проще всего через файл на сайте:

```bash
# 1. ключ (храните key.pem в секрете, не кладите в репозиторий)
openssl genpkey -algorithm Ed25519 -out key.pem
PUBLIC_KEY="$(openssl pkey -in key.pem -pubout -outform DER | tail -c 32 | base64)"
echo "v=MCPv1; k=ed25519; p=${PUBLIC_KEY}" > mcp-registry-auth

# 2. разместите файл так, чтобы он открывался по адресу
#    https://xonta.ru/.well-known/mcp-registry-auth   (в Django — через nginx alias или static)

# 3. установите mcp-publisher (macOS: brew install mcp-publisher;
#    Linux: бинарник из github.com/modelcontextprotocol/registry/releases)

# 4. вход и публикация (из папки проекта, где лежит server.json)
PRIVATE_KEY="$(openssl pkey -in key.pem -noout -text | grep -A3 'priv:' | tail -n +2 | tr -d ' :\n')"
mcp-publisher login http --domain xonta.ru --private-key "${PRIVATE_KEY}"
mcp-publisher validate
mcp-publisher publish

# 5. проверка
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=ru.xonta/customs"
```

Вместо файла можно добавить DNS-запись TXT на xonta.ru с тем же содержимым и войти
командой `mcp-publisher login dns --domain xonta.ru --private-key ...`.

**При каждом обновлении** поднимайте `version` в `pyproject.toml`, `src/xonta_customs/__init__.py` и `server.json`
(в двух местах; сейчас везде 0.2.1), выкладывайте на PyPI и повторяйте `mcp-publisher publish`.

## Шаг 5. Glama (glama.ai/mcp/servers)

Один из самых посещаемых каталогов; от его оценки зависят бейджи в awesome-списках.

1. Войдите через GitHub, «Add Server», укажите `https://github.com/mrsergeiluzhnov/xonta-customs-mcp`.
2. После индексации нажмите «Claim» — Glama проверит `glama.json`.
3. Во вкладке настроек сервера укажите Dockerfile из репозитория, чтобы Glama смогла
   запустить сервер и проверить инструменты. Это повышает оценку качества.
4. Отдельно добавьте удалённый адрес `https://mcp.xonta.ru/customs/mcp` в раздел
   remote/connectors, если Glama его не подтянет из официального реестра сама.

## Шаг 6. Smithery (smithery.ai)

1. Откройте smithery.ai/new, войдите через GitHub.
2. Выберите вариант с публичным URL и укажите `https://mcp.xonta.ru/customs/mcp`.
3. Smithery сам просканирует инструменты (авторизация не нужна).
   Если сканирование не пройдёт, есть карточка сервера:
   `https://mcp.xonta.ru/customs/.well-known/mcp/server-card.json`.
4. После публикации пройдите проверку в Settings → Verification.

## Шаг 7. awesome-mcp-servers (GitHub, 80k+ звёзд)

Сделайте форк `punkpeye/awesome-mcp-servers`, в `README.md` в разделе
**💰 Finance & Fintech** вставьте строку **по алфавиту** (между соседями по имени репозитория):

```markdown
- [mrsergeiluzhnov/xonta-customs-mcp](https://github.com/mrsergeiluzhnov/xonta-customs-mcp) [![mrsergeiluzhnov/xonta-customs-mcp MCP server](https://glama.ai/mcp/servers/mrsergeiluzhnov/xonta-customs-mcp/badges/score.svg)](https://glama.ai/mcp/servers/mrsergeiluzhnov/xonta-customs-mcp) 🐍 ☁️ 🏠 🍎 🪟 🐧 - Import into Russia and the EAEU: parses Chinese supplier invoices, finds TN VED EAEU codes, computes duties incl. specific and combined rates, import VAT 22%/10%, 2026 customs fees and the car recycling fee (утильсбор), checks EAEU antidumping measures and EEC classification rulings. Hosted `https://mcp.xonta.ru/customs/mcp` or `uvx xonta-customs-mcp`.
```

Заголовок PR: `Add xonta-customs-mcp (Russia/EAEU customs)`. Делайте после шага 5 — бейдж берётся из Glama.

Удалённый адрес отдельно добавьте в `punkpeye/awesome-remote-mcp-servers` тем же способом.

## Шаг 8. Остальные каталоги (формы на сайтах)

| Каталог | Как добавить |
|---|---|
| **PulseMCP** (pulsemcp.com) | подтягивает из официального реестра; если через пару дней сервера нет — форма Submit на сайте |
| **mcp.so** | кнопка Submit на сайте, ссылка на GitHub-репозиторий |
| **MCP Market** (mcpmarket.com) | форма Submit на сайте |
| **LobeHub MCP** (lobehub.com/mcp) | кнопка Submit MCP, ссылка на GitHub |
| **mcpservers.org** | форма Submit на сайте |
| **Cline MCP Marketplace** | issue в репозитории `cline/mcp-marketplace` со ссылкой на GitHub и логотипом 400×400 PNG |
| **Docker MCP Catalog** | PR в `docker/mcp-registry` (Dockerfile уже есть) |
| **GitHub MCP Registry** | автоматически из официального реестра |

Адреса форм у каталогов иногда меняются: если ссылки Submit не видно, ищите её в шапке
или подвале сайта.

## Шаг 9. Русскоязычная аудитория

- Пост в Xonta Live и карточка на xonta.ru / в AgentRadar.
- Статья на Хабре: «Бесплатный MCP-сервер для расчёта таможенных платежей: ТН ВЭД, НДС 22%,
  антидемпинг ЕАЭС». Показать живой пример с обувью из Китая — это лучше всего объясняет пользу.
- Каналы ВЭД и таможенных брокеров в Telegram: они первыми оценят расчёт комбинированных ставок.

## Что проверить после публикации

```bash
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=ru.xonta/customs" | head -c 500
```

И подключить сервер в Claude Desktop или Cursor по адресу `https://mcp.xonta.ru/customs/mcp`,
спросить: «Сколько будет стоить растаможка 1000 пар кожаной обуви из Китая за 20 000 юаней?»
