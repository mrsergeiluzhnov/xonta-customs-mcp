"""Recycling fee (утилизационный сбор) for passenger cars, category M1.

Fee = base rate (20 000 RUB) x coefficient. The coefficient depends on engine type,
engine volume, power (kW), age (up to 3 years / older) and the period (Dec 2025, then by year
2026-2030). Personal-use imports by individuals have their own table with 0.17 / 0.26 for
small engines.

Cars released in another EAEU country (Kazakhstan, Kyrgyzstan, Armenia, Belarus) and brought
to Russia: since 2026 the fee is УС = УСед + Ктп + Кндс + Ка, where the extra terms are the
differences in duty, VAT and excise vs. Russian clearance. The caller passes them if known.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from importlib import resources

HP_TO_KW = 0.73549875


class RecyclingError(ValueError):
    pass


@lru_cache(maxsize=1)
def table() -> dict:
    return json.loads(resources.files("xonta_customs").joinpath("data", "recycling_m1.json").read_text(encoding="utf-8"))


def _period_index(on: date) -> int:
    for p in table()["periods"]:
        start = date.fromisoformat(p["from"])
        end = date.fromisoformat(p["to"]) if p["to"] else None
        if on >= start and (end is None or on <= end):
            return p["index"]
    raise RecyclingError("Таблица действует с 01.12.2025; для более ранних дат расчёт не поддерживается")


def _band(power_kw: float, bands: list) -> int:
    p = round(power_kw, 2)
    for i, upper in enumerate(bands):
        if upper is None or p <= upper:
            return i
    raise AssertionError


def _volume_index(volume_cc: float) -> int:
    for i, upper in enumerate(table()["volume_bands_cc"]):
        if upper is None or volume_cc <= upper:
            return i
    raise AssertionError


def _band_label(i: int, bands: list) -> str:
    lo = 0 if i == 0 else bands[i - 1] + 0.01
    hi = bands[i]
    if i == 0:
        return f"не выше {hi:g} кВт"
    if hi is None:
        return f"{lo:g} кВт и более"
    return f"{lo:g}–{hi:g} кВт"


def calc_recycling_fee(
    *,
    engine: str,
    power_hp: float | None = None,
    power_kw: float | None = None,
    engine_volume_cc: float | None = None,
    older_than_3_years: bool = False,
    personal_use: bool = False,
    on: date | None = None,
    eaeu_extra_rub: float = 0.0,
) -> dict:
    engine = engine.lower()
    if engine not in ("ice", "hybrid_parallel", "ev", "hybrid_series"):
        raise RecyclingError("engine: ice (бензин/дизель), hybrid_parallel, ev (электро) или hybrid_series (последовательный гибрид)")
    if power_kw is None and power_hp is None:
        raise RecyclingError("Нужна мощность: power_hp или power_kw")
    kw = power_kw if power_kw is not None else power_hp * HP_TO_KW
    if kw <= 0:
        raise RecyclingError("Мощность должна быть больше нуля")
    on = on or date.today()
    t = table()
    pi = _period_index(on)
    col = pi * 2 + (1 if older_than_3_years else 0)
    scope = t["personal"] if personal_use else t["general"]

    notes: list[str] = []
    if engine in ("ev", "hybrid_series"):
        bands = t["ev_power_bands_kw"]
        bi = _band(kw, bands)
        coef = scope["ev"][bi][col]
        group = "электромобиль / последовательный гибрид"
    else:
        if not engine_volume_cc or engine_volume_cc <= 0:
            raise RecyclingError("Для ДВС и параллельных гибридов нужен объём двигателя engine_volume_cc")
        bands = t["power_bands_kw"]
        bi = _band(kw, bands)
        vi = _volume_index(engine_volume_cc)
        coef = scope["ice"][vi][bi][col]
        vb = t["volume_bands_cc"]
        group = (
            f"ДВС, объём {'до ' + str(vb[vi]) if vb[vi] else 'свыше ' + str(vb[vi - 1])} куб. см"
        )

    base = t["base_rate_rub"]
    fee = round(base * coef, 2)
    preferential = personal_use and coef in (0.17, 0.26)
    if personal_use and not preferential:
        notes.append(
            "Льготная ставка для личного пользования не применяется: мощность выше 160 л.с. "
            "(80 л.с. для электромобилей) или объём больше 3 л."
        )
    if preferential:
        notes.append(
            "Льгота для личного пользования: автомобиль ставится на учёт на плательщика в течение 12 месяцев, "
            "не более одного льготного ввоза в 12 месяцев; при продаже в течение 12 месяцев сбор доплачивается."
        )
    if eaeu_extra_rub:
        notes.append("Добавлены доплаты Ктп + Кндс + Ка за выпуск в другой стране ЕАЭС.")
    else:
        notes.append(
            "Если автомобиль выпущен в другой стране ЕАЭС, к сбору добавляются разницы в пошлине, НДС и акцизе "
            "(Ктп + Кндс + Ка) — передайте их суммой в eaeu_extra_rub."
        )

    period = t["periods"][pi]
    return {
        "recycling_fee_rub": round(fee + eaeu_extra_rub, 2),
        "base_fee_rub": fee,
        "eaeu_extra_rub": eaeu_extra_rub,
        "base_rate_rub": base,
        "coefficient": coef,
        "group": group,
        "power_kw": round(kw, 2),
        "power_hp": round(kw / HP_TO_KW, 1),
        "power_band": _band_label(bi, bands),
        "age": "старше 3 лет" if older_than_3_years else "не старше 3 лет",
        "table": "личное пользование (I.3/I.4)" if personal_use else "общий порядок (I.1/I.2)",
        "period": f"с {period['from']}" + (f" по {period['to']}" if period["to"] else ""),
        "source": t["source"],
        "notes": notes,
    }
