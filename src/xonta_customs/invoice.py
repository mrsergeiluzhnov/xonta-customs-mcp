"""Commercial invoice / packing list parsing (Chinese suppliers first).

Input is Markdown or plain text (e.g. the output of DocParse), or an .xlsx/.csv file.
The parser finds the goods table by its header (English, Chinese or Russian column names),
reads line items, header fields (invoice number, date, currency, Incoterms, parties, origin)
and checks arithmetic. It never invents values: missing fields stay null.
"""

from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

import httpx

# ------------------------------------------------------------------ column dictionary

COLUMNS: dict[str, tuple[str, ...]] = {
    "line_no": ("no.", "no", "item no", "№", "序号", "п/п"),
    "description": (
        "description of goods", "description", "goods", "commodity", "product name", "item name",
        "product", "name of goods", "品名", "货物名称", "商品名称", "产品名称", "货名", "描述",
        "наименование", "товар", "описание",
    ),
    "model": ("model", "specification", "spec", "型号", "规格", "модель", "артикул", "art.no", "art no"),
    "material": ("material", "材质", "材料", "материал"),
    "brand": ("brand", "trademark", "品牌", "商标", "марка", "бренд"),
    "hs_code": ("hs code", "h.s. code", "h.s.code", "hs", "hscode", "海关编码", "hs编码", "商品编码", "税号", "тн вэд", "код тн вэд"),
    "quantity": ("quantity", "qty", "q'ty", "数量", "количество", "кол-во"),
    "unit": ("unit", "uom", "单位", "ед. изм", "ед.изм", "ед"),
    "unit_price": ("unit price", "price", "单价", "цена"),
    "amount": ("amount", "total amount", "total value", "total price", "value", "金额", "总价", "总金额", "сумма", "стоимость"),
    "net_weight": ("n.w.", "n.w", "nw", "net weight", "net wt", "净重", "нетто", "вес нетто"),
    "gross_weight": ("g.w.", "g.w", "gw", "gross weight", "gross wt", "毛重", "брутто", "вес брутто"),
    "packages": ("ctns", "cartons", "packages", "pkgs", "箱数", "件数", "мест"),
    "origin": ("origin", "country of origin", "原产地", "产地", "страна происхождения"),
}

INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")

CURRENCY_PATTERNS = [
    (r"\bUSD\b|US\$|美元|\$", "USD"),
    (r"\bCNY\b|\bRMB\b|人民币|¥|￥", "CNY"),
    (r"\bEUR\b|€|欧元", "EUR"),
    (r"\bRUB\b|руб|₽", "RUB"),
    (r"\bAED\b", "AED"),
    (r"\bTRY\b", "TRY"),
]

COUNTRY_WORDS = {
    "china": "CN", "p.r.china": "CN", "prc": "CN", "中国": "CN", "китай": "CN",
    "turkey": "TR", "türkiye": "TR", "турция": "TR",
    "india": "IN", "индия": "IN", "vietnam": "VN", "вьетнам": "VN",
    "korea": "KR", "корея": "KR", "japan": "JP", "日本": "JP", "япония": "JP",
    "germany": "DE", "германия": "DE", "italy": "IT", "италия": "IT",
    "kazakhstan": "KZ", "казахстан": "KZ", "uae": "AE", "оаэ": "AE",
}

# Small glossary to turn supplier wording into TN VED (Russian) search words.
GLOSSARY = {
    "shoe": "обувь", "shoes": "обувь", "sneaker": "обувь", "sneakers": "обувь", "boots": "обувь", "鞋": "обувь",
    "leather": "кожа", "皮": "кожа", "cotton": "хлопчатобумажн", "棉": "хлопчатобумажн",
    "polyester": "синтетическ", "涤纶": "синтетическ", "t-shirt": "майки фуфайки", "tshirt": "майки фуфайки", "t恤": "майки фуфайки",
    "jacket": "куртки", "夹克": "куртки", "dress": "платья", "连衣裙": "платья", "knitted": "трикотажн", "针织": "трикотажн",
    "pump": "насосы", "泵": "насосы", "gear": "шестеренные", "齿轮": "шестеренные", "hydraulic": "гидравлическ", "液压": "гидравлическ",
    "bearing": "подшипники", "轴承": "подшипники", "valve": "краны клапаны", "阀": "краны клапаны",
    "motor": "двигатели", "电机": "двигатели", "cable": "провода кабели", "电缆": "провода кабели", "wire": "провода",
    "led": "светодиод", "lamp": "светильники", "灯": "светильники", "light": "светильники",
    "battery": "аккумуляторы", "电池": "аккумуляторы", "lithium": "литий-ионные",
    "phone": "телефонные аппараты", "手机": "телефонные аппараты", "laptop": "вычислительные машины портативные",
    "toy": "игрушки", "toys": "игрушки", "玩具": "игрушки", "furniture": "мебель", "家具": "мебель",
    "chair": "мебель для сидения", "椅": "мебель для сидения", "table": "мебель", "桌": "мебель",
    "spring": "рессоры пружины", "leaf spring": "рессоры листовые", "板簧": "рессоры листовые",
    "tyre": "шины", "tire": "шины", "tires": "шины", "tyres": "шины", "轮胎": "шины",
    "cookware": "посуда", "pot": "посуда", "pan": "посуда", "锅": "посуда", "aluminium": "алюминиев", "aluminum": "алюминиев", "铝": "алюминиев",
    "steel": "стальн", "钢": "стальн", "stainless": "коррозионностойк", "不锈钢": "коррозионностойк", "pipe": "трубы", "tube": "трубы", "管": "трубы",
    "plastic": "пластмасс", "塑料": "пластмасс", "glass": "стекло", "玻璃": "стекло",
    "bag": "сумки", "包": "сумки", "backpack": "рюкзаки", "背包": "рюкзаки",
    "cosmetic": "косметическ", "化妆品": "косметическ", "perfume": "духи", "香水": "духи",
    "filter": "фильтры", "过滤器": "фильтры", "cartridge": "картриджи", "screw": "винты", "bolt": "болты", "螺栓": "болты",
    "tool": "инструменты", "工具": "инструменты", "drill": "дрели", "printer": "принтеры", "打印机": "принтеры",
    "solar": "фотоэлектрическ", "太阳能": "фотоэлектрическ", "inverter": "преобразователи статические", "逆变器": "преобразователи статические",
    "charger": "зарядные устройства", "充电器": "зарядные устройства", "camera": "камеры", "摄像头": "камеры",
    "tea": "чай", "茶": "чай", "juice": "соки", "果汁": "соки", "lemon": "лимонный",
}

_HDR_PATTERNS = {
    "invoice_no": r"(?:invoice\s*(?:no\.?|number|#)|发票号(?:码)?|инвойс\s*№|счет\s*№)\s*[:：]?\s*([A-Za-z0-9\-/_.]+)",
    "date": r"(?:date|日期|дата)\s*[:：]?\s*([0-9]{4}[-./年][0-9]{1,2}[-./月][0-9]{1,2}日?|[0-9]{1,2}[-./][0-9]{1,2}[-./][0-9]{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})",
    "contract_no": r"(?:contract\s*(?:no\.?|number)|合同号|контракт\s*№)\s*[:：]?\s*([A-Za-z0-9\-/_.]+)",
}
_PARTY_PATTERNS = {
    "seller": r"(?:seller|shipper|exporter|vendor|卖方|发货人|出口商|продавец|отправитель)\s*[:：]\s*(.+)",
    "buyer": r"(?:buyer|consignee|importer|买方|收货人|进口商|покупатель|получатель)\s*[:：]\s*(.+)",
}


# ------------------------------------------------------------------ helpers

def _num(cell) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    s = str(cell).strip()
    if not s:
        return None
    s = re.sub(r"(USD|CNY|RMB|EUR|US\$|[$¥￥€₽]|kgs?|кг|pcs|шт|pairs?|sets?)", "", s, flags=re.I).strip()
    s = s.replace(" ", " ").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d+", s):
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+,\d+", s):
        s = s.replace(".", "").replace(",", ".")
    m = re.fullmatch(r"-?\d+(\.\d+)?", s)
    return float(s) if m else None


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("\n", " ")).strip().lower()


def _match_columns(header: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    normalized = [_norm(h) for h in header]
    # longest synonyms first so "unit price" beats "unit", "total amount" beats "total"
    pairs = sorted(((syn, key) for key, syns in COLUMNS.items() for syn in syns), key=lambda x: -len(x[0]))
    taken: set[int] = set()
    for syn, key in pairs:
        if key in cols:
            continue
        for i, h in enumerate(normalized):
            if i in taken or not h:
                continue
            # bilingual headers like "品名 Description" or "Unit Price (USD)"
            if h == syn or re.search(r"(^|[\s/(（])" + re.escape(syn) + r"($|[\s/)）:.])", h) or (re.search(r"[一-鿿]", syn) and syn in h):
                cols[key] = i
                taken.add(i)
                break
    return cols


def _is_header(cols: dict[str, int]) -> bool:
    return "description" in cols and ("quantity" in cols or "amount" in cols or "unit_price" in cols)


def _detect_currency(text: str) -> str | None:
    for pat, code in CURRENCY_PATTERNS:
        if re.search(pat, text, flags=re.I):
            return code
    return None


def tnved_hint(description: str, model: str | None = None, material: str | None = None) -> str | None:
    text = " ".join(x for x in (description, material, model) if x).lower()
    words: list[str] = []
    for term in sorted(GLOSSARY, key=len, reverse=True):
        if re.search(r"[一-鿿]", term):
            hit = term in text
        else:
            hit = re.search(r"\b" + re.escape(term) + r"\b", text) is not None
        if hit and GLOSSARY[term] not in words:
            words.append(GLOSSARY[term])
            text = text.replace(term, " ")
    if not words and re.search(r"[а-яё]", text):
        return description
    return " ".join(words) or None


# ------------------------------------------------------------------ table extraction

def _markdown_tables(text: str) -> list[list[list[str]]]:
    tables, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 3:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            cur.append(cells)
        else:
            if cur:
                tables.append(cur)
                cur = []
    if cur:
        tables.append(cur)
    return tables


def _delimited_table(text: str) -> list[list[list[str]]]:
    lines = [l for l in text.splitlines() if l.strip()]
    for delim in ("\t", ";"):
        rows = [l.split(delim) for l in lines if l.count(delim) >= 3]
        if len(rows) >= 2:
            return [rows]
    return []


def _rows_from_file(path: Path) -> list[list]:
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                rows.append(["" if v is None else v for v in r])
            rows.append([])
        return rows
    if suf in (".csv", ".tsv", ".txt"):
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "gb18030", "cp1251"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        delim = max(",;\t", key=first.count)
        return list(csv.reader(io.StringIO(text), delimiter=delim))
    raise ValueError("Сам разбираю .xlsx и .csv; PDF и сканы — через DocParse (DOCPARSE_URL)")


# ------------------------------------------------------------------ main parser

def _parse_rows(rows: list[list], fallback_currency: str | None) -> tuple[list[dict], dict | None, list[str]]:
    warnings: list[str] = []
    header_idx, cols = None, {}
    for i, r in enumerate(rows):
        c = _match_columns([str(x) for x in r])
        if _is_header(c):
            header_idx, cols = i, c
            break
    if header_idx is None:
        return [], None, ["Не нашёл таблицу товаров: нужна строка заголовков с описанием и количеством или суммой."]

    header_text = " ".join(str(x) for x in rows[header_idx])
    col_currency = _detect_currency(header_text)
    items, total_row = [], None
    for r in rows[header_idx + 1:]:
        if not any(str(x).strip() for x in r):
            if items:
                break
            continue

        def cell(key):
            i = cols.get(key)
            return r[i] if i is not None and i < len(r) else None

        desc = str(cell("description") or "").strip()
        joined = " ".join(str(x) for x in r).lower()
        if re.search(r"\b(total|sub-?total|grand total|итого|всего)\b|合计|总计|小计", joined):
            total_row = {
                "quantity": _num(cell("quantity")),
                "amount": _num(cell("amount")),
                "net_weight_kg": _num(cell("net_weight")),
                "gross_weight_kg": _num(cell("gross_weight")),
            }
            break
        qty, price, amount = _num(cell("quantity")), _num(cell("unit_price")), _num(cell("amount"))
        if not desc or (qty is None and amount is None):
            continue
        hs = re.sub(r"\D", "", str(cell("hs_code") or "")) or None
        item = {
            "line": len(items) + 1,
            "description": desc,
            "model": (str(cell("model")).strip() or None) if cell("model") not in (None, "") else None,
            "material": (str(cell("material")).strip() or None) if cell("material") not in (None, "") else None,
            "brand": (str(cell("brand")).strip() or None) if cell("brand") not in (None, "") else None,
            "hs_code_supplier": hs,
            "quantity": qty,
            "unit": (str(cell("unit")).strip() or None) if cell("unit") not in (None, "") else None,
            "unit_price": price,
            "amount": amount,
            "net_weight_kg": _num(cell("net_weight")),
            "gross_weight_kg": _num(cell("gross_weight")),
            "packages": _num(cell("packages")),
            "origin": None,
        }
        org = cell("origin")
        if org:
            item["origin"] = COUNTRY_WORDS.get(str(org).strip().lower(), str(org).strip())
        if amount is None and qty is not None and price is not None:
            item["amount"] = round(qty * price, 2)
            item["amount_computed"] = True
        elif amount is not None and qty and price is not None and abs(qty * price - amount) > max(0.01 * amount, 0.02):
            warnings.append(f"Строка {item['line']}: количество × цена = {round(qty * price, 2)}, а в сумме {amount}")
        if hs:
            item["tnved_search"] = hs[:6] if len(hs) >= 6 else hs
            item["tnved_note"] = "Первые 6 знаков HS-кода поставщика совпадают с ТН ВЭД; последние 4 знака ТН ВЭД подберите по тарифу"
        else:
            item["tnved_search"] = tnved_hint(desc, item["model"], item["material"])
        if not item["brand"] and re.search(r"\b(brand|trademark)\b", desc, re.I):
            warnings.append(f"Строка {item['line']}: проверьте бренд — важно для параллельного импорта и маркировки")
        items.append(item)

    currency = col_currency or fallback_currency
    return items, total_row | {"currency": currency} if total_row else None, warnings


def parse_invoice_text(text: str) -> dict:
    tables = _markdown_tables(text) or _delimited_table(text)
    flat_text = text
    return _assemble(tables, flat_text)


def parse_invoice_file(path: Path) -> dict:
    rows = _rows_from_file(path)
    flat_text = "\n".join(" ".join(str(c) for c in r if str(c).strip()) for r in rows)
    return _assemble([rows], flat_text)


def _assemble(tables: list[list[list]], flat_text: str) -> dict:
    head: dict = {}
    for key, pat in _HDR_PATTERNS.items():
        m = re.search(pat, flat_text, flags=re.I)
        head[key] = m.group(1).strip() if m else None
    for key, pat in _PARTY_PATTERNS.items():
        m = re.search(pat, flat_text, flags=re.I)
        head[key] = m.group(1).strip()[:200] if m else None

    m = re.search(r"\b(" + "|".join(INCOTERMS) + r")\b[\s,:]*([A-Za-z一-鿿 .\-]{2,40})?", flat_text)
    head["incoterms"] = m.group(1) if m else None
    head["incoterms_place"] = (m.group(2) or "").strip(" .,-") or None if m else None

    origin = None
    m = re.search(r"(?:country\s+of\s+origin|origin|made\s+in|原产地|产地|страна\s+происхождения)\s*[:：]?\s*([A-Za-z.一-鿿Ѐ-ӿ ]{2,30})", flat_text, flags=re.I)
    if m:
        word = m.group(1).strip().lower().split("\n")[0]
        origin = next((v for k, v in COUNTRY_WORDS.items() if k in word), None)
    head["country_of_origin"] = origin
    currency = _detect_currency(flat_text)

    items, totals, warnings = [], None, []
    for t in tables:
        it, tot, w = _parse_rows(t, currency)
        if it:
            items, totals, warnings = it, tot, w
            break
    if not items:
        warnings = warnings or ["В тексте нет таблицы товаров."]

    cur = (totals or {}).get("currency") or currency
    sum_amount = round(sum(i["amount"] or 0 for i in items), 2) if items else None
    if totals and totals.get("amount") is not None and sum_amount is not None and abs(totals["amount"] - sum_amount) > 0.05:
        warnings.append(f"Сумма строк {sum_amount} не совпадает с итогом инвойса {totals['amount']}")
    if items and any(i["net_weight_kg"] is None for i in items):
        warnings.append("Не у всех позиций есть вес нетто — он нужен для специфических ставок (за кг)")
    for i in items:
        if i["origin"] is None:
            i["origin"] = origin

    customs_value_note = None
    inc = head.get("incoterms")
    if inc in ("EXW", "FCA", "FAS", "FOB"):
        customs_value_note = (
            f"Условия {inc}: в таможенную стоимость нужно добавить перевозку и страховку до границы ЕАЭС "
            "(ст. 40 ТК ЕАЭС). Стоимость по инвойсу — только основа."
        )
    elif inc in ("CFR", "CIF", "CPT", "CIP"):
        customs_value_note = (
            f"Условия {inc}: перевозка до указанного места уже в цене. Если место назначения дальше границы ЕАЭС, "
            "расходы после границы можно вычесть при подтверждении документами."
        )
    elif inc in ("DAP", "DPU", "DDP"):
        customs_value_note = f"Условия {inc}: из цены вычитаются расходы после ввоза (перевозка по ЕАЭС, при DDP — платежи)."

    return {
        "header": head,
        "currency": cur,
        "items": items,
        "items_count": len(items),
        "total_amount_items": sum_amount,
        "invoice_totals": totals,
        "customs_value_note": customs_value_note,
        "warnings": warnings,
        "next_steps": [
            "Для каждой позиции: tnved_search по полю tnved_search, затем tnved_code_info с origin_country",
            "calc_import_payments с amount (+ перевозка/страховка до границы), currency и весом нетто",
        ],
    }


# ------------------------------------------------------------------ DocParse

async def docparse_to_markdown(file_url: str) -> str:
    """Convert a document (PDF, scan, DOCX) to Markdown via a DocParse instance.

    DOCPARSE_URL   endpoint that accepts JSON {"url": ...} and returns Markdown
                   (as text/markdown, or JSON with one of: markdown, text, content)
    DOCPARSE_TOKEN optional bearer token for internal calls
    """
    endpoint = os.environ.get("DOCPARSE_URL")
    if not endpoint:
        raise RuntimeError(
            "DocParse не настроен на этом сервере. Сконвертируйте документ в Markdown "
            "(например, MCP-сервером io.github.mrsergeiluzhnov/docparse) и передайте текст в invoice_text."
        )
    check_public_url(file_url)
    headers = {"User-Agent": "xonta-customs-mcp"}
    token = os.environ.get("DOCPARSE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=120, headers=headers) as c:
        r = await c.post(endpoint, json={"url": file_url, "format": "markdown"})
        r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "json" in ctype:
        data = r.json()
        for key in ("markdown", "text", "content", "result"):
            val = data.get(key) if isinstance(data, dict) else None
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, dict):
                for k2 in ("markdown", "text", "content"):
                    if isinstance(val.get(k2), str):
                        return val[k2]
        raise RuntimeError("DocParse вернул JSON без поля markdown/text/content")
    return r.text


def check_public_url(url: str) -> None:
    """Refuse URLs that point to the server's own network (SSRF protection)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Нужна ссылка http(s)")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror as e:
        raise ValueError(f"Не удалось найти хост {u.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("Ссылки на внутренние и локальные адреса запрещены")


async def fetch_file(url: str, dest_dir: Path) -> Path:
    check_public_url(url)
    async with httpx.AsyncClient(timeout=60, follow_redirects=False, headers={"User-Agent": "xonta-customs-mcp"}) as c:
        r = await c.get(url)
        hops = 0
        while r.is_redirect and hops < 3:
            nxt = str(r.next_request.url)
            check_public_url(nxt)
            r = await c.get(nxt)
            hops += 1
        r.raise_for_status()
    if len(r.content) > 20 * 1024 * 1024:
        raise ValueError("Файл больше 20 МБ")
    name = re.sub(r"[^\w.\-]", "_", url.split("?")[0].rsplit("/", 1)[-1]) or "invoice"
    p = dest_dir / name
    p.write_bytes(r.content)
    return p
