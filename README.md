# Xonta Customs RU

MCP server for importing goods into Russia and the Eurasian Economic Union (EAEU).
Free and open source.

<!-- mcp-name: ru.xonta/customs -->

[Русская версия ниже](#xonta-customs-ru--по-русски)

## What it does

Gives an AI agent the customs tools a Russian broker uses every day:

| Tool | What it returns |
|---|---|
| `parse_invoice` | Line items from a supplier invoice or packing list (Chinese, English, Russian headers): qty, price, amount, weights, HS code, Incoterms, origin, arithmetic checks, a TN VED search hint per line |
| `tnved_search` | TN VED EAEU (ТН ВЭД ЕАЭС) codes by product words or code prefix, with duty rates |
| `tnved_code_info` | Name, parent headings, parsed ETT duty rate, antidumping measures, EEC rulings for a code |
| `calc_import_payments` | Duty (ad valorem, specific, combined), antidumping, excise, VAT 22% / 10%, 2026 customs fee, total in RUB |
| `calc_recycling_fee` | Car recycling fee (утильсбор) for M1 vehicles by engine, volume, power, age and year (Dec 2025–2030), commercial and personal-use tables |
| `customs_clearance_fee` | 2026 customs clearance fee by declaration value, with the full bracket table |
| `antidumping_check` | EAEU antidumping measures by code, product and origin country, with EEC decisions |
| `classification_rulings_search` | EEC decisions on classification of specific goods (binding in all EAEU countries) |
| `exchange_rates` | Official Bank of Russia rates used for customs payments |
| `server_status` | Data versions and sources |

What sets it apart:

- **Specific and combined rates.** "10%, but not less than 2 EUR per pair" is parsed and computed, not skipped.
- **Every number has a source.** Fees cite the Government decree, measures cite EEC decisions, rates cite the Bank of Russia.
- **No made-up numbers.** If a rate can't be parsed or a measure's rate is unknown, the server says so and asks for it.
- **Russian legal context for 2026:** VAT 22%, new customs fee scale, EAEU trade defence measures,
  the December 2025 power-based recycling fee for cars.
- **From invoice to payments.** A Chinese invoice goes in, customs-ready lines come out:
  the supplier's HS code is used as the first 6 digits of TN VED, Incoterms tell what to add for customs value.

All results are informational. The final code and payments are decided by the declarant and customs.

## Connect

### Hosted (no install)

```
https://mcp.xonta.ru/customs/mcp
```

Claude Desktop / Cursor / any client with remote MCP support:

```json
{
  "mcpServers": {
    "xonta-customs": { "url": "https://mcp.xonta.ru/customs/mcp" }
  }
}
```

### Local (stdio)

```bash
uvx xonta-customs-mcp
```

```json
{
  "mcpServers": {
    "xonta-customs": { "command": "uvx", "args": ["xonta-customs-mcp"] }
  }
}
```

The local server needs the tariff table for code search (calculation works without it if you pass the rate):

```bash
uvx --from xonta-customs-mcp xonta-customs-load-tariff tnved.xlsx --source "ETT EAEU, export of 05.11.2026"
```

Any `.xlsx` or `.csv` with a header row containing a code column and a name column works;
the duty rate and unit columns are picked up when present.

## Example

> Shoes with leather uppers from China, 1 000 pairs, invoice value 20 000 CNY. What will customs cost?

The agent calls `tnved_search("обувь с верхом из натуральной кожи")`, then
`calc_import_payments(customs_value=20000, currency="CNY", code="6403990000", quantity_pair=1000)`
and gets duty by the specific part of the combined rate, VAT 22% on top, the 2026 fee and the total.

> Here is the supplier's invoice (PDF). Work out the payments.

`parse_invoice(file_url=...)` returns three lines with quantities, prices, net weights and HS codes,
plus a note that FOB terms need freight and insurance added. Each line then goes through
`tnved_search` and `calc_import_payments`.

> A 2 l, 170 hp car, 2 years old, imported by a company. Recycling fee?

`calc_recycling_fee(engine="ice", power_hp=170, engine_volume_cc=1998)` → coefficient 45, 900 000 RUB in 2026.

## Data and sources

| Data | Source | Updated |
|---|---|---|
| TN VED EAEU and ETT rates | Decision of the EEC Council No. 80 of 14.09.2021, loaded from an export file | on load |
| Customs fees 2026 | Government Decree No. 1637 of 28.11.2024 as amended by No. 1638 of 23.10.2025 | 01.01.2026 |
| Import VAT | Tax Code art. 164 as amended by Federal Law No. 425-FZ | 01.01.2026 |
| Antidumping measures | EEC Board decisions renewed in 2026 (partial list) | 05.11.2026 |
| Classification rulings | EEC Board decisions (partial list) | 05.11.2026 |
| Exchange rates | Bank of Russia, daily | live |
| Car recycling fee | Government Decree No. 1291 of 26.12.2013, annex section I, as amended by No. 1713 of 01.11.2025 | 01.12.2025, schedule to 2030 |

Contributions of new measures and rulings are welcome: edit `src/xonta_customs/data/*.json` and open a PR.

## Self-hosting

```bash
pip install xonta-customs-mcp
xonta-customs-load-tariff tnved.xlsx
ALLOWED_HOSTS=mcp.example.com xonta-customs-mcp --http --host 127.0.0.1 --port 8765
```

Endpoints: `/mcp` (Streamable HTTP), `/health`, `/.well-known/mcp/server-card.json`.
See `deploy/` for systemd and nginx examples, and `Dockerfile`.

PDF and scanned invoices are converted to Markdown by DocParse
(`io.github.mrsergeiluzhnov/docparse` in the MCP registry). Set `DOCPARSE_URL` (endpoint that takes `{"url": ...}` and
returns Markdown) and optionally `DOCPARSE_TOKEN`. Without it, `.xlsx`/`.csv` invoices still work,
and any client can pass invoice text directly in `invoice_text`. File links pointing to private or
local addresses are refused.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT. Made by [Xonta](https://xonta.ru).

---

# Xonta Customs RU — по-русски

Бесплатный MCP-сервер для импорта в Россию и ЕАЭС. Даёт ИИ-агенту инструменты таможенного брокера.

## Инструменты

| Инструмент | Что делает |
|---|---|
| `parse_invoice` | Разбор инвойса или упаковочного листа поставщика (китайские, английские, русские заголовки): позиции, количество, цены, веса, HS-код, Инкотермс, проверка арифметики, подсказка для поиска ТН ВЭД |
| `tnved_search` | Подбор кодов ТН ВЭД ЕАЭС по описанию товара или началу кода, со ставками пошлин |
| `tnved_code_info` | Наименование, вышестоящие позиции, ставка ЕТТ в разобранном виде, антидемпинг, решения ЕЭК по коду |
| `calc_import_payments` | Пошлина (адвалорная, специфическая, комбинированная), антидемпинг, акциз, НДС 22% / 10%, сбор 2026 года, итог в рублях |
| `calc_recycling_fee` | Утильсбор на легковые автомобили по таблице с 01.12.2025 (по мощности), на 2026–2030 годы, для бизнеса и для личного пользования |
| `customs_clearance_fee` | Сбор за таможенные операции 2026 года по стоимости декларации |
| `antidumping_check` | Антидемпинговые меры ЕАЭС по коду, товару и стране происхождения |
| `classification_rulings_search` | Решения Коллегии ЕЭК о классификации отдельных товаров |
| `exchange_rates` | Официальные курсы ЦБ РФ |
| `server_status` | Версии и источники данных |

## Чем отличается

- Считает **специфические и комбинированные ставки**: «10%, но не менее 2 евро за пару».
- **У каждой цифры есть источник**: постановление, решение ЕЭК, курс ЦБ.
- **Не выдумывает цифры**: если ставку не удалось разобрать или размер антидемпинговой пошлины неизвестен, сервер прямо об этом говорит.
- **Учитывает 2026 год**: НДС 22%, новая шкала сборов, действующие меры защиты рынка ЕАЭС, утильсбор по мощности.
- **От инвойса до платежей**: китайский инвойс на входе, готовые строки для расчёта на выходе.

Результаты справочные. Окончательно код и платежи определяют декларант и таможня.

## Подключение

### Удалённо, без установки

```
https://mcp.xonta.ru/customs/mcp
```

Claude Desktop, Cursor и любой клиент с поддержкой удалённых MCP-серверов:

```json
{
  "mcpServers": {
    "xonta-customs": { "url": "https://mcp.xonta.ru/customs/mcp" }
  }
}
```

### Локально (stdio)

```bash
uvx xonta-customs-mcp
```

```json
{
  "mcpServers": {
    "xonta-customs": { "command": "uvx", "args": ["xonta-customs-mcp"] }
  }
}
```

Для поиска кодов локальному серверу нужна таблица ТН ВЭД. Расчёт работает и без неё, если передать ставку:

```bash
uvx --from xonta-customs-mcp xonta-customs-load-tariff tnved.xlsx --source "ЕТТ ЕАЭС, выгрузка от 05.11.2026"
```

Подойдёт любой `.xlsx` или `.csv` со строкой заголовков, где есть колонки кода и наименования.
Колонки ставки и единицы измерения подхватываются, если они есть.

## Примеры

> Обувь с верхом из натуральной кожи из Китая, 1 000 пар, по инвойсу 20 000 юаней. Сколько заплатим на таможне?

Агент вызывает `tnved_search("обувь с верхом из натуральной кожи")`, затем
`calc_import_payments(customs_value=20000, currency="CNY", code="6403990000", quantity_pair=1000)`
и получает пошлину по специфической части комбинированной ставки, НДС 22% сверху, сбор 2026 года и итог.

> Вот инвойс поставщика (PDF). Посчитай платежи.

`parse_invoice(file_url=...)` возвращает три позиции с количеством, ценами, весом нетто и HS-кодами,
и предупреждает, что при условиях FOB к таможенной стоимости нужно добавить фрахт и страховку.
Дальше каждая позиция проходит через `tnved_search` и `calc_import_payments`.

> Автомобиль 2 л, 170 л. с., 2 года, ввозит компания. Какой утильсбор?

`calc_recycling_fee(engine="ice", power_hp=170, engine_volume_cc=1998)` → коэффициент 45, 900 000 рублей в 2026 году.

## Данные и источники

| Данные | Источник | Обновлено |
|---|---|---|
| ТН ВЭД ЕАЭС и ставки ЕТТ | Решение Совета ЕЭК № 80 от 14.09.2021, загружается из файла выгрузки | при загрузке |
| Таможенные сборы 2026 | Постановление Правительства № 1637 от 28.11.2024 в редакции № 1638 от 23.10.2025 | 01.01.2026 |
| НДС при ввозе | Ст. 164 НК РФ в редакции Федерального закона № 425-ФЗ | 01.01.2026 |
| Антидемпинговые меры | Решения Коллегии ЕЭК, продлённые в 2026 году (неполный список) | 05.11.2026 |
| Решения о классификации | Решения Коллегии ЕЭК (неполный список) | 05.11.2026 |
| Курсы валют | Банк России, ежедневно | в реальном времени |
| Утильсбор на автомобили | Постановление Правительства № 1291 от 26.12.2013, приложение, раздел I, в редакции № 1713 от 01.11.2025 | 01.12.2025, график до 2030 |

Новые меры и решения можно добавить самому: правьте `src/xonta_customs/data/*.json` и присылайте pull request.

## Своя установка

```bash
pip install xonta-customs-mcp
xonta-customs-load-tariff tnved.xlsx
ALLOWED_HOSTS=mcp.example.com xonta-customs-mcp --http --host 127.0.0.1 --port 8765
```

Адреса: `/mcp` (Streamable HTTP), `/health`, `/.well-known/mcp/server-card.json`.
Примеры для systemd и nginx в папке `deploy/`, есть `Dockerfile`.

PDF и сканы инвойсов переводятся в Markdown через DocParse (`io.github.mrsergeiluzhnov/docparse` в реестре MCP).
Укажите `DOCPARSE_URL` (адрес, который принимает `{"url": ...}` и отдаёт Markdown) и при необходимости `DOCPARSE_TOKEN`.
Без этого инвойсы в `.xlsx`/`.csv` всё равно разбираются, а текст инвойса клиент может передать сам в `invoice_text`.
Ссылки на файлы с частных и локальных адресов сервер не открывает.

## Разработка

```bash
pip install -e ".[dev]"
pytest
```

## Лицензия

MIT. Сделано в [Xonta](https://xonta.ru).
