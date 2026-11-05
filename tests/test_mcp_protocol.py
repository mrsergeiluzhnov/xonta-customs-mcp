"""End-to-end over real MCP stdio: list tools and call each one."""

import json
import os
import sys
from pathlib import Path

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from xonta_customs import store

FIX = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.asyncio


def _payload(res):
    assert not res.is_error, res
    if res.structured_content is not None:
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(res.content[0].text)


@pytest.fixture()
def params(tmp_path):
    os.environ["XONTA_CUSTOMS_DATA"] = str(tmp_path)
    store.load_tariff(FIX / "tariff_sample.csv", "test fixture")
    env = dict(os.environ)
    return StdioServerParameters(command=sys.executable, args=["-m", "xonta_customs.server"], env=env)


async def test_tools_over_stdio(params):
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            assert set(tools) == {
                "tnved_search", "tnved_code_info", "calc_import_payments", "customs_clearance_fee",
                "antidumping_check", "classification_rulings_search", "exchange_rates", "server_status",
                "calc_recycling_fee", "parse_invoice",
            }
            for t in tools.values():
                assert t.description and len(t.description) > 40
                assert t.annotations.read_only_hint is True

            found = _payload(await s.call_tool("tnved_search", {"query": "насос шестеренный"}))
            assert found["results"][0]["code"] == "8413603100"

            info = _payload(await s.call_tool("tnved_code_info", {"code": "7320101100", "origin_country": "CN"}))
            assert info["duty_rate"]["kind"] == "ad_valorem"
            assert info["antidumping_measures"][0]["id"] == "leaf-springs-cn"

            # shoes from China, 1 000 pairs, 20 000 CNY; fixed rates so no network is needed
            calc = _payload(await s.call_tool("calc_import_payments", {
                "customs_value": 20000, "currency": "CNY", "code": "6403990000",
                "quantity_pair": 1000, "exchange_rates": {"CNY": 11.0, "EUR": 95.0},
            }))
            # value 220 000 RUB; 10% = 22 000; 2 EUR*1000*95 = 190 000 -> duty 190 000
            assert calc["duty_rub"] == 190000
            assert calc["vat_rub"] == round((220000 + 190000) * 0.22, 2)
            assert calc["customs_fee_rub"] == 2462
            assert "disclaimer" in calc

            fee = _payload(await s.call_tool("customs_clearance_fee", {"total_customs_value_rub": 3_000_000}))
            assert fee["fee_rub"] == 18465

            ad = _payload(await s.call_tool("antidumping_check", {"product": "алюминиевая посуда", "origin_country": "CN"}))
            assert ad["count"] == 1

            ru = _payload(await s.call_tool("classification_rulings_search", {"query": "картридж предколоночный"}))
            assert ru["results"][0]["tnved"] == "8421"

            inv = _payload(await s.call_tool("parse_invoice", {"invoice_text": (FIX / "invoice_cn.md").read_text(encoding="utf-8")}))
            assert inv["items_count"] == 3 and inv["currency"] == "USD"

            rf = _payload(await s.call_tool("calc_recycling_fee", {"engine": "ice", "power_hp": 170, "engine_volume_cc": 1998, "on_date": "2026-11-05"}))
            assert rf["recycling_fee_rub"] == 900000

            car = _payload(await s.call_tool("calc_import_payments", {"customs_value": 2000000, "duty_rate": "15", "recycling_fee_rub": 900000}))
            assert car["total_with_recycling_fee_rub"] == car["total_payments_rub"] + 900000

            bad = _payload(await s.call_tool("parse_invoice", {"file_url": "http://127.0.0.1:8765/health.xlsx"}))
            assert bad["error"] == "parse_error"

            st = _payload(await s.call_tool("server_status", {}))
            assert st["tariff"]["loaded"] is True
