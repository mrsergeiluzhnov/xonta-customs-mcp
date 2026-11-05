"""Customs clearance fees (таможенные сборы за таможенные операции) for imports into Russia.

Source: Постановление Правительства РФ от 28.11.2024 № 1637
в редакции Постановления от 23.10.2025 № 1638 (с изм. от 27.11.2025 № 1907),
в силе с 01.01.2026.
"""

from __future__ import annotations

FEES_SOURCE = (
    "Постановление Правительства РФ от 28.11.2024 № 1637 "
    "(ред. Постановления от 23.10.2025 № 1638), действует с 01.01.2026"
)
FEES_VALID_FROM = "2026-01-01"

# (upper bound of total customs value in RUB inclusive, fee in RUB); None = no upper bound
IMPORT_FEE_BRACKETS: list[tuple[float | None, int]] = [
    (200_000, 1_231),
    (450_000, 2_462),
    (1_200_000, 4_924),
    (2_700_000, 13_541),
    (4_200_000, 18_465),
    (5_500_000, 21_344),
    (10_000_000, 49_240),
    (None, 73_860),
]

# When customs value is not determined/declared (by number of goods items in the declaration)
UNDECLARED_VALUE_FEES = [(50, 9_054), (100, 18_108), (None, 30_180)]


def import_fee(total_customs_value_rub: float) -> int:
    if total_customs_value_rub < 0:
        raise ValueError("customs value cannot be negative")
    for upper, fee in IMPORT_FEE_BRACKETS:
        if upper is None or total_customs_value_rub <= upper:
            return fee
    raise AssertionError("unreachable")


def undeclared_value_fee(goods_items: int) -> int:
    if goods_items < 1:
        raise ValueError("goods_items must be >= 1")
    for upper, fee in UNDECLARED_VALUE_FEES:
        if upper is None or goods_items <= upper:
            return fee
    raise AssertionError("unreachable")


def fee_table() -> list[dict]:
    rows = []
    lower = 0.0
    for upper, fee in IMPORT_FEE_BRACKETS:
        rows.append({"from_rub_exclusive": lower, "to_rub_inclusive": upper, "fee_rub": fee})
        lower = upper if upper is not None else lower
    return rows
