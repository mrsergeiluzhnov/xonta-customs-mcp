"""Parsing of EAEU Common Customs Tariff (ETT) duty rate strings.

Rates in the tariff look like:
    "5"
    "0"
    "10, но не менее 0,3 евро за 1 кг"
    "0,6 евро за 1 кг"
    "15, но не менее 2,5 евро за 1 пару"
    "5 плюс 0,2 евро за 1 кг"
    "4, но не менее 1,5 долл. США за 1 шт"

The parser turns them into a structured DutyRate. Anything it does not
understand is kept as raw text and marked unparsed, so the caller never
gets a made-up number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

_NUM = r"(\d+(?:[.,]\d+)?)"

_CURRENCY_WORDS = {
    "евро": "EUR",
    "eur": "EUR",
    "долл": "USD",
    "usd": "USD",
    "руб": "RUB",
}

# per-unit wording -> normalized unit code
_UNITS = [
    (r"см\s*3|см3|куб\.?\s*см", "cm3"),  # must be checked before m3
    (r"1000\s*шт", "1000pcs"),
    (r"1\s*кг|кг", "kg"),
    (r"1\s*пар[уа]|пар", "pair"),
    (r"1\s*шт|шт", "pcs"),
    (r"1000\s*л|1000\s*литр", "1000l"),
    (r"1\s*л\b|литр", "l"),
    (r"1\s*м2|1\s*м\s*2|м2", "m2"),
    (r"1\s*м3|м3", "m3"),
    (r"1\s*т\b|тонн", "t"),
]


@dataclass
class SpecificPart:
    amount: float
    currency: str  # EUR / USD / RUB
    unit: str  # kg, pcs, pair, l, m2, cm3, ...
    unit_text: str


@dataclass
class DutyRate:
    raw: str
    kind: str  # "free", "ad_valorem", "specific", "combined_min", "combined_plus", "unparsed"
    ad_valorem_pct: float | None = None
    specific: SpecificPart | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def describe(self) -> str:
        if self.kind == "free":
            return "0% (беспошлинно)"
        if self.kind == "ad_valorem":
            return f"{self.ad_valorem_pct:g}% от таможенной стоимости"
        sp = self.specific
        if self.kind == "specific" and sp:
            return f"{sp.amount:g} {sp.currency} за {sp.unit_text}"
        if self.kind == "combined_min" and sp:
            return (
                f"{self.ad_valorem_pct:g}%, но не менее {sp.amount:g} {sp.currency} за {sp.unit_text}"
            )
        if self.kind == "combined_plus" and sp:
            return f"{self.ad_valorem_pct:g}% плюс {sp.amount:g} {sp.currency} за {sp.unit_text}"
        return f"не удалось разобрать ставку: {self.raw!r}"


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def _parse_specific(text: str) -> SpecificPart | None:
    t = text.lower()
    m = re.search(_NUM + r"\s*(евро|eur|долл\.?\s*сша|долл|usd|руб)", t)
    if not m:
        return None
    amount = _to_float(m.group(1))
    cur_word = m.group(2)
    currency = next((v for k, v in _CURRENCY_WORDS.items() if cur_word.startswith(k)), None)
    if currency is None:
        return None
    tail = t[m.end():]
    um = re.search(r"за\s+(.+)$", tail)
    if not um:
        return None
    unit_text = um.group(1).strip().rstrip(".;")
    unit = None
    for pattern, code in _UNITS:
        if re.search(pattern, unit_text):
            unit = code
            break
    if unit is None:
        return None
    return SpecificPart(amount=amount, currency=currency, unit=unit, unit_text=unit_text)


def parse_rate(raw: str | float | int | None) -> DutyRate:
    if raw is None:
        return DutyRate(raw="", kind="unparsed")
    if isinstance(raw, (int, float)):
        val = float(raw)
        return DutyRate(raw=str(raw), kind="free" if val == 0 else "ad_valorem", ad_valorem_pct=val)

    text = " ".join(str(raw).split())
    low = text.lower()
    if low in ("", "-", "—"):
        return DutyRate(raw=text, kind="unparsed")
    if low in ("св", "св.", "свободно", "0", "0,0", "0.0"):
        return DutyRate(raw=text, kind="free", ad_valorem_pct=0.0)

    # pure percentage, optionally with "%" and an optional note in brackets
    m = re.fullmatch(_NUM + r"\s*%?(\s*\(.*\))?", low)
    if m:
        val = _to_float(m.group(1))
        return DutyRate(raw=text, kind="free" if val == 0 else "ad_valorem", ad_valorem_pct=val)

    # combined: "X, но не менее ..." / "X% но не менее ..."
    m = re.match(_NUM + r"\s*%?\s*,?\s*но\s+не\s+менее\s+(.+)$", low)
    if m:
        sp = _parse_specific(m.group(2))
        if sp:
            return DutyRate(raw=text, kind="combined_min", ad_valorem_pct=_to_float(m.group(1)), specific=sp)
        return DutyRate(raw=text, kind="unparsed")

    # combined: "X плюс ..."
    m = re.match(_NUM + r"\s*%?\s*,?\s*плюс\s+(.+)$", low)
    if m:
        sp = _parse_specific(m.group(2))
        if sp:
            return DutyRate(raw=text, kind="combined_plus", ad_valorem_pct=_to_float(m.group(1)), specific=sp)
        return DutyRate(raw=text, kind="unparsed")

    # purely specific: "0,6 евро за 1 кг"
    sp = _parse_specific(low)
    if sp and re.match(r"^\s*" + _NUM + r"\s*(евро|eur|долл|usd|руб)", low):
        return DutyRate(raw=text, kind="specific", specific=sp)

    return DutyRate(raw=text, kind="unparsed")
