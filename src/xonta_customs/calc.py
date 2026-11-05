"""Import payments calculation for goods released for domestic consumption in Russia.

Order of calculation (НК РФ ст. 160, ТК ЕАЭС):
  duty         = by the ETT rate (ad valorem / specific / combined)
  antidumping  = customs value * rate (if a measure applies; rate given by caller)
  excise       = given by caller in RUB (rates depend on the product, not computed here)
  VAT          = (customs value + duty + antidumping + excise) * VAT rate
  fee          = by the bracket of total customs value (not part of the VAT base)
"""

from __future__ import annotations

from dataclasses import dataclass

from .fees import FEES_SOURCE, import_fee
from .rates import DutyRate

ALLOWED_VAT = (0.0, 10.0, 22.0)


class CalcError(ValueError):
    pass


@dataclass
class Quantities:
    kg: float | None = None
    pcs: float | None = None
    pair: float | None = None
    l: float | None = None
    m2: float | None = None
    m3: float | None = None
    cm3: float | None = None
    t: float | None = None

    def get(self, unit: str) -> float | None:
        if unit == "1000pcs":
            return None if self.pcs is None else self.pcs / 1000
        if unit == "1000l":
            return None if self.l is None else self.l / 1000
        return getattr(self, unit, None)


def _r(x: float) -> float:
    return round(x + 1e-9, 2)


def specific_duty_rub(rate: DutyRate, qty: Quantities, fx: dict[str, float]) -> float:
    sp = rate.specific
    assert sp is not None
    q = qty.get(sp.unit)
    if q is None:
        raise CalcError(
            f"Для специфической ставки нужна величина в единицах «{sp.unit_text}» "
            f"(параметр quantity_{sp.unit.replace('1000', '')})."
        )
    if sp.currency == "RUB":
        per_unit = sp.amount
    else:
        if sp.currency not in fx:
            raise CalcError(f"Нужен курс {sp.currency} к рублю")
        per_unit = sp.amount * fx[sp.currency]
    return q * per_unit


def calculate(
    *,
    customs_value_rub: float,
    rate: DutyRate,
    qty: Quantities,
    fx: dict[str, float],
    vat_rate_pct: float = 22.0,
    antidumping_rate_pct: float = 0.0,
    excise_rub: float = 0.0,
) -> dict:
    if customs_value_rub <= 0:
        raise CalcError("Таможенная стоимость должна быть больше нуля")
    if vat_rate_pct not in ALLOWED_VAT:
        raise CalcError("Ставка НДС на ввоз в 2026 году: 22, 10 или 0 (при льготе)")
    if antidumping_rate_pct < 0 or excise_rub < 0:
        raise CalcError("Антидемпинговая ставка и акциз не могут быть отрицательными")

    notes: list[str] = []
    av = None
    spec = None
    if rate.kind == "free":
        duty = 0.0
    elif rate.kind == "ad_valorem":
        duty = customs_value_rub * rate.ad_valorem_pct / 100
    elif rate.kind == "specific":
        duty = specific_duty_rub(rate, qty, fx)
    elif rate.kind == "combined_min":
        av = customs_value_rub * rate.ad_valorem_pct / 100
        spec = specific_duty_rub(rate, qty, fx)
        duty = max(av, spec)
        notes.append(
            "Комбинированная ставка: применена большая из адвалорной "
            f"({_r(av)} руб.) и специфической ({_r(spec)} руб.) частей."
        )
    elif rate.kind == "combined_plus":
        av = customs_value_rub * rate.ad_valorem_pct / 100
        spec = specific_duty_rub(rate, qty, fx)
        duty = av + spec
    else:
        raise CalcError(
            f"Ставку {rate.raw!r} не удалось разобрать автоматически. "
            "Передайте ставку явно в параметре duty_rate (например «10» или "
            "«10, но не менее 0,3 евро за 1 кг»)."
        )

    antidumping = customs_value_rub * antidumping_rate_pct / 100
    vat_base = customs_value_rub + duty + antidumping + excise_rub
    vat = vat_base * vat_rate_pct / 100
    fee = import_fee(customs_value_rub)
    total = duty + antidumping + excise_rub + vat + fee

    if vat_rate_pct == 10:
        notes.append("НДС 10% применяется только к товарам из перечней Правительства (ст. 164 НК РФ).")
    if antidumping_rate_pct:
        notes.append("Антидемпинговая пошлина посчитана от таможенной стоимости по переданной ставке.")
    notes.append(
        "Сбор за таможенные операции посчитан по одной декларации; при нескольких товарах "
        "в декларации сбор берётся с их общей таможенной стоимости."
    )

    return {
        "customs_value_rub": _r(customs_value_rub),
        "duty_rate": rate.describe(),
        "duty_rub": _r(duty),
        "duty_ad_valorem_part_rub": None if av is None else _r(av),
        "duty_specific_part_rub": None if spec is None else _r(spec),
        "antidumping_rate_pct": antidumping_rate_pct,
        "antidumping_rub": _r(antidumping),
        "excise_rub": _r(excise_rub),
        "vat_rate_pct": vat_rate_pct,
        "vat_base_rub": _r(vat_base),
        "vat_rub": _r(vat),
        "customs_fee_rub": fee,
        "customs_fee_source": FEES_SOURCE,
        "total_payments_rub": _r(total),
        "notes": notes,
    }
