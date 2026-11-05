"""Official exchange rates of the Bank of Russia (cbr.ru XML_daily).

Customs payments are converted at the CBR rate in force on the day the
declaration is registered (ст. 39 ТК ЕАЭС).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import date

import httpx

URL = "https://www.cbr.ru/scripts/XML_daily.asp"
_cache: dict[str, tuple[float, dict]] = {}
_TTL = 3600


def parse_xml(content: bytes) -> dict:
    root = ET.fromstring(content)
    rates = {}
    for v in root.findall("Valute"):
        code = v.findtext("CharCode")
        nominal = float(v.findtext("Nominal").replace(",", "."))
        value = float(v.findtext("Value").replace(",", "."))
        rates[code] = value / nominal
    return {"date": root.get("Date"), "rates": rates}


async def fetch_rates(on: date | None = None) -> dict:
    key = (on or date.today()).isoformat()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    params = {"date_req": on.strftime("%d/%m/%Y")} if on else {}
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "xonta-customs-mcp"}) as c:
        r = await c.get(URL, params=params)
        r.raise_for_status()
    data = parse_xml(r.content)
    data["source"] = "Банк России, cbr.ru/scripts/XML_daily.asp"
    _cache[key] = (time.time(), data)
    return data
