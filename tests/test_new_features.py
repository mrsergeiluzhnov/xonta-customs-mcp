from datetime import date
from pathlib import Path

import pytest

from xonta_customs import invoice
from xonta_customs.recycling import RecyclingError, calc_recycling_fee

FIX = Path(__file__).parent / "fixtures"
D2026 = date(2026, 11, 5)


# ------------------------------------------------------------ recycling fee, checked against independent 2026 figures

@pytest.mark.parametrize(
    "kwargs,expected",
    [
        # commercial, petrol <=1 l, <=160 hp: 297 600 new / 552 000 older (+20% vs 2025)
        (dict(engine="ice", power_hp=100, engine_volume_cc=998), 297_600),
        (dict(engine="ice", power_hp=100, engine_volume_cc=998, older_than_3_years=True), 552_000),
        # 1-2 l, 160-190 hp: 900 000 / 1 492 800
        (dict(engine="ice", power_hp=170, engine_volume_cc=1998), 900_000),
        (dict(engine="ice", power_hp=170, engine_volume_cc=1998, older_than_3_years=True), 1_492_800),
        # personal use, <=160 hp, <=3 l: 3 400 / 5 200
        (dict(engine="ice", power_hp=150, engine_volume_cc=1998, personal_use=True), 3_400),
        (dict(engine="ice", power_hp=150, engine_volume_cc=2999, personal_use=True, older_than_3_years=True), 5_200),
        # personal use, 3-3.5 l: no preference: 2 584 000 / 3 956 200
        (dict(engine="ice", power_hp=150, engine_volume_cc=3456, personal_use=True), 2_584_000),
        (dict(engine="ice", power_hp=150, engine_volume_cc=3456, personal_use=True, older_than_3_years=True), 3_956_200),
        # personal use EV up to 80 hp: 3 400
        (dict(engine="ev", power_hp=75, personal_use=True), 3_400),
        # parallel hybrid counts as ICE
        (dict(engine="hybrid_parallel", power_hp=170, engine_volume_cc=1998), 900_000),
    ],
)
def test_recycling_2026(kwargs, expected):
    r = calc_recycling_fee(on=D2026, **kwargs)
    assert r["recycling_fee_rub"] == expected


def test_recycling_ev_december_2025():
    # ConsultantPlus example: EV from 205.95 kW, coefficient 152 -> 3 040 000 (Dec 2025)
    r = calc_recycling_fee(engine="ev", power_kw=235.4, on=date(2025, 12, 10))
    assert r["coefficient"] == 152
    assert r["recycling_fee_rub"] == 3_040_000


def test_recycling_band_edges_kw():
    # 117.68 kW is the top of band 4, 117.69 starts band 5
    a = calc_recycling_fee(engine="ice", power_kw=117.68, engine_volume_cc=1600, on=D2026)
    b = calc_recycling_fee(engine="ice", power_kw=117.69, engine_volume_cc=1600, on=D2026)
    assert a["coefficient"] == 40.04 and b["coefficient"] == 45


def test_recycling_future_years_and_personal_above_160hp():
    r2030 = calc_recycling_fee(engine="ice", power_hp=100, engine_volume_cc=998, on=date(2031, 3, 1))
    assert r2030["coefficient"] == 21.79
    r = calc_recycling_fee(engine="ice", power_hp=200, engine_volume_cc=1998, personal_use=True, on=D2026)
    assert r["coefficient"] == 47.64 and "не применяется" in r["notes"][0]


def test_recycling_eaeu_extra_and_errors():
    r = calc_recycling_fee(engine="ice", power_hp=150, engine_volume_cc=1998, personal_use=True, on=D2026, eaeu_extra_rub=500_000)
    assert r["recycling_fee_rub"] == 503_400
    with pytest.raises(RecyclingError):
        calc_recycling_fee(engine="ice", power_hp=150, on=D2026)
    with pytest.raises(RecyclingError):
        calc_recycling_fee(engine="ice", power_hp=150, engine_volume_cc=1500, on=date(2025, 6, 1))


# ------------------------------------------------------------ invoice parsing

def test_parse_chinese_markdown_invoice():
    res = invoice.parse_invoice_text((FIX / "invoice_cn.md").read_text(encoding="utf-8"))
    h = res["header"]
    assert h["invoice_no"] == "HX-2026-1105"
    assert h["date"] == "2026-10-28"
    assert h["incoterms"] == "FOB" and h["incoterms_place"].startswith("Ningbo")
    assert h["country_of_origin"] == "CN"
    assert "NINGBO HUAXIN" in h["seller"]
    assert res["currency"] == "USD"
    assert res["items_count"] == 3
    shoes, tee, pump = res["items"]
    assert shoes["quantity"] == 1200 and shoes["unit_price"] == 18.5 and shoes["amount"] == 22200
    assert shoes["net_weight_kg"] == 960 and shoes["hs_code_supplier"] == "64039900"
    assert shoes["tnved_search"] == "640399"
    assert shoes["origin"] == "CN"
    assert tee["hs_code_supplier"] is None
    assert "хлопчатобумажн" in tee["tnved_search"] and "майки" in tee["tnved_search"]
    # 40 x 95 = 3 800, invoice says 3 900 -> warning; and lines sum 32 400 matches total
    assert any("Строка 3" in w for w in res["warnings"])
    assert res["total_amount_items"] == 32400
    assert "FOB" in res["customs_value_note"]


def test_parse_xlsx_invoice(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["PROFORMA INVOICE"])
    ws.append(["Invoice No.: PI-555", None, "Terms: CIF Saint Petersburg"])
    ws.append([])
    ws.append(["序号", "品名", "数量", "单价(RMB)", "金额(RMB)", "净重(KG)"])
    ws.append([1, "铝锅 aluminium cookware set", 500, 60, 30000, 900])
    ws.append([2, "轮胎 truck tyre 315/80R22.5", 20, 900, 18000, 1200])
    ws.append([None, "合计", 520, None, 48000, 2100])
    p = tmp_path / "pi.xlsx"
    wb.save(p)
    res = invoice.parse_invoice_file(p)
    assert res["header"]["invoice_no"] == "PI-555"
    assert res["header"]["incoterms"] == "CIF"
    assert res["currency"] == "CNY"
    assert [i["amount"] for i in res["items"]] == [30000, 18000]
    assert "посуда" in res["items"][0]["tnved_search"]
    assert "шины" in res["items"][1]["tnved_search"]
    assert res["warnings"] == []


def test_number_formats():
    assert invoice._num("1,234.50") == 1234.5
    assert invoice._num("1 234,50") == 1234.5
    assert invoice._num("1.234,50") == 1234.5
    assert invoice._num("USD 12.5") == 12.5
    assert invoice._num("¥3,000") == 3000
    assert invoice._num("960 kgs") == 960
    assert invoice._num("n/a") is None


def test_no_table():
    res = invoice.parse_invoice_text("Hello, please see attached")
    assert res["items"] == [] and res["warnings"]


@pytest.mark.parametrize("url", ["http://127.0.0.1:8765/health", "http://localhost/x", "file:///etc/passwd", "http://10.0.0.5/a.xlsx", "http://169.254.169.254/latest"])
def test_ssrf_blocked(url):
    with pytest.raises(ValueError):
        invoice.check_public_url(url)


def test_tariff_on_second_sheet_with_arrows(tmp_path):
    """tws.by export: a title sheet first, codes on the second sheet, levels joined by an arrow."""
    from openpyxl import Workbook
    from xonta_customs import store

    wb = Workbook()
    ws = wb.active
    ws.title = "Система TWS"
    ws.append([None, "Список кодов на второй вкладке", "https://www.tws.by/"])
    ws.append(["Справочник кодов ТНВЭД с подробностями", "https://www.tws.by/tws/tnved"])
    ws2 = wb.create_sheet("ТНВЭД")
    ws2.append(["Код", "Наименование", "Тариф", "Подробности"])
    ws2.append(["0101291000", "лошади: \U0001F83A прочие: \U0001F83A убойные", "5%", "подробнее"])
    ws2.append(["6403990000", "прочая обувь с верхом из натуральной кожи", "10%, но не менее 1.5 EUR за 1 пар", "подробнее"])
    path = tmp_path / "tws.xlsx"
    wb.save(path)

    db = tmp_path / "t.sqlite"
    assert store.load_tariff(path, "test", db=db) == 2
    con = store.connect(db)
    rows = dict(con.execute("SELECT code, name FROM tnved").fetchall())
    duty = con.execute("SELECT duty_raw FROM tnved WHERE code='6403990000'").fetchone()[0]
    con.close()
    assert rows["0101291000"] == "лошади: прочие: убойные"
    assert duty.startswith("10%")
