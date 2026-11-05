from datetime import date
from pathlib import Path

import pytest

from xonta_customs import store
from xonta_customs.calc import CalcError, Quantities, calculate
from xonta_customs.cbr import parse_xml
from xonta_customs.fees import import_fee, undeclared_value_fee
from xonta_customs.rates import parse_rate

FIX = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------ rate parser

@pytest.mark.parametrize(
    "raw,kind,av,amount,cur,unit",
    [
        ("5", "ad_valorem", 5, None, None, None),
        ("0", "free", 0, None, None, None),
        ("св.", "free", 0, None, None, None),
        ("12,5", "ad_valorem", 12.5, None, None, None),
        ("10, но не менее 0,3 евро за 1 кг", "combined_min", 10, 0.3, "EUR", "kg"),
        ("15, но не менее 2,5 евро за 1 пару", "combined_min", 15, 2.5, "EUR", "pair"),
        ("0,6 евро за 1 кг", "specific", None, 0.6, "EUR", "kg"),
        ("4, но не менее 1,5 долл. США за 1 шт", "combined_min", 4, 1.5, "USD", "pcs"),
        ("5 плюс 0,2 евро за 1 кг", "combined_plus", 5, 0.2, "EUR", "kg"),
        ("1,5 евро за 1 см3", "specific", None, 1.5, "EUR", "cm3"),
    ],
)
def test_parse_rate(raw, kind, av, amount, cur, unit):
    r = parse_rate(raw)
    assert r.kind == kind
    if av is not None:
        assert r.ad_valorem_pct == av
    if amount is not None:
        assert r.specific.amount == amount
        assert r.specific.currency == cur
        assert r.specific.unit == unit


def test_parse_rate_unknown_is_not_guessed():
    r = parse_rate("см. примечание 3")
    assert r.kind == "unparsed"


# ------------------------------------------------------------ fees 2026

@pytest.mark.parametrize(
    "value,fee",
    [
        (1, 1231), (200_000, 1231), (200_000.01, 2462), (450_000, 2462),
        (1_200_000, 4924), (2_700_000, 13541), (4_200_000, 18465),
        (5_500_000, 21344), (10_000_000, 49240), (10_000_000.01, 73860),
    ],
)
def test_import_fee_brackets(value, fee):
    assert import_fee(value) == fee


def test_undeclared_value_fee():
    assert undeclared_value_fee(50) == 9054
    assert undeclared_value_fee(51) == 18108
    assert undeclared_value_fee(101) == 30180


# ------------------------------------------------------------ calculation, checked by hand

def test_ad_valorem_calc():
    # 1 000 000 RUB, duty 5% = 50 000; VAT base 1 050 000 * 22% = 231 000; fee 4 924
    r = calculate(customs_value_rub=1_000_000, rate=parse_rate("5"), qty=Quantities(), fx={})
    assert r["duty_rub"] == 50_000
    assert r["vat_rub"] == 231_000
    assert r["customs_fee_rub"] == 4924
    assert r["total_payments_rub"] == 50_000 + 231_000 + 4924


def test_combined_min_specific_wins():
    # shoes: 100 pairs, value 10 000 RUB, EUR = 100 RUB
    # ad valorem 10% = 1 000; specific 2 EUR * 100 pairs * 100 = 20 000 -> 20 000
    r = calculate(
        customs_value_rub=10_000,
        rate=parse_rate("10, но не менее 2 евро за 1 пару"),
        qty=Quantities(pair=100),
        fx={"EUR": 100.0},
    )
    assert r["duty_rub"] == 20_000
    assert r["vat_rub"] == round((10_000 + 20_000) * 0.22, 2)


def test_combined_min_ad_valorem_wins():
    # 1 000 kg t-shirts worth 3 000 000 RUB: 10% = 300 000; 0.3 EUR*1000*100 = 30 000
    r = calculate(
        customs_value_rub=3_000_000,
        rate=parse_rate("10, но не менее 0,3 евро за 1 кг"),
        qty=Quantities(kg=1000),
        fx={"EUR": 100.0},
    )
    assert r["duty_rub"] == 300_000
    assert r["customs_fee_rub"] == 18465


def test_antidumping_and_excise_in_vat_base():
    r = calculate(
        customs_value_rub=500_000,
        rate=parse_rate("5"),
        qty=Quantities(),
        fx={},
        antidumping_rate_pct=20,
        excise_rub=10_000,
    )
    # duty 25 000, AD 100 000, excise 10 000 -> base 635 000 -> VAT 139 700
    assert r["antidumping_rub"] == 100_000
    assert r["vat_base_rub"] == 635_000
    assert r["vat_rub"] == 139_700


def test_vat_10():
    r = calculate(customs_value_rub=100_000, rate=parse_rate("0"), qty=Quantities(), fx={}, vat_rate_pct=10)
    assert r["vat_rub"] == 10_000


def test_specific_needs_quantity():
    with pytest.raises(CalcError):
        calculate(customs_value_rub=1000, rate=parse_rate("0,6 евро за 1 кг"), qty=Quantities(), fx={"EUR": 90})


def test_rejects_unparsed_rate():
    with pytest.raises(CalcError):
        calculate(customs_value_rub=1000, rate=parse_rate("???"), qty=Quantities(), fx={})


def test_rejects_wrong_vat():
    with pytest.raises(CalcError):
        calculate(customs_value_rub=1000, rate=parse_rate("5"), qty=Quantities(), fx={}, vat_rate_pct=20)


# ------------------------------------------------------------ tariff store

@pytest.fixture()
def loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("XONTA_CUSTOMS_DATA", str(tmp_path))
    n = store.load_tariff(FIX / "tariff_sample.csv", "test fixture")
    return n


def test_load_and_search(loaded):
    assert loaded == 8
    hits = store.search("насос шестеренный")
    assert hits and hits[0]["code"] == "8413603100"
    assert store.search("8413")[0]["code"].startswith("8413")


def test_search_inflected_words(loaded):
    # "насосы шестеренные" vs "насос шестерённый" — stemming should still find it
    assert any(h["code"] == "8413603100" for h in store.search("насосов шестеренных"))


def test_get_code_with_parents(loaded):
    info = store.get_code("8413 60 310 0")
    assert info["duty_raw"] == "0"
    assert [p["code"] for p in info["parents"]] == ["84", "8413"]


def test_meta(loaded):
    m = store.tariff_meta()
    assert m["loaded"] and m["rows"] == "8" and m["source"] == "test fixture"


# ------------------------------------------------------------ reference data

def test_antidumping_by_code_and_origin():
    m = store.find_measures("7320101100", "CN", None, today=date(2026, 11, 5))
    assert [x["id"] for x in m] == ["leaf-springs-cn"]
    assert m[0]["active"] is True
    assert store.find_measures("7320101100", "DE", None) == []


def test_antidumping_by_keywords_and_expiry():
    m = store.find_measures(None, "CN", "Грузовые шины 315/80R22.5", today=date(2026, 12, 1))
    assert m and m[0]["id"] == "truck-tyres-cn" and m[0]["active"] is False


def test_rulings():
    assert store.find_rulings("тепловизионный прицел", None)[0]["number"] == "107"
    assert store.find_rulings(None, "9013100000")[0]["number"] == "107"
    assert store.find_rulings(None, "8421390000")[0]["number"] == "106"


def test_cbr_xml_parse():
    xml = (
        '<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="05.11.2026" name="Foreign Currency Market">'
        '<Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>1</Nominal>'
        '<Name>Yuan</Name><Value>11,2000</Value></Valute>'
        '<Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal>'
        '<Name>Yen</Name><Value>52,5000</Value></Valute></ValCurs>'
    ).encode("cp1251")
    d = parse_xml(xml)
    assert d["date"] == "05.11.2026"
    assert d["rates"]["CNY"] == 11.2
    assert d["rates"]["JPY"] == pytest.approx(0.525)
