"""Xonta Customs RU — MCP server for importing goods into Russia / the EAEU."""

from __future__ import annotations

import argparse
import os
from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

import tempfile
from pathlib import Path

from . import __version__, cbr, invoice, store
from .calc import CalcError, Quantities, calculate
from .fees import FEES_SOURCE, fee_table, import_fee
from .rates import parse_rate
from .recycling import RecyclingError, calc_recycling_fee as _calc_recycling_fee

DISCLAIMER = (
    "Справочный расчёт, не таможенное решение. Код ТН ВЭД и платежи окончательно "
    "определяют декларант и таможенный орган; для спорных товаров получите предварительное "
    "решение о классификации. / Informational only, not a customs ruling."
)

INSTRUCTIONS = """Tools for importing goods into Russia and the Eurasian Economic Union (EAEU):
supplier invoice parsing (Chinese/English/Russian), TN VED EAEU (ТН ВЭД ЕАЭС) code search, ETT duty rates,
full import payments calculation (duty incl. specific/combined rates, antidumping, excise, VAT 22%/10%,
customs clearance fee 2026), car recycling fee (утильсбор), EAEU antidumping measures,
EEC classification rulings and Bank of Russia exchange rates.
Typical flow: parse_invoice -> tnved_search -> tnved_code_info -> calc_import_payments.
For cars add calc_recycling_fee. All results are informational; always show the disclaimer to the end user."""

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RO_NET = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

mcp = MCPServer(
    name="xonta-customs-ru",
    title="Xonta Customs RU",
    description="Russia / EAEU import: TN VED codes, duties, VAT, fees, antidumping, classification rulings",
    instructions=INSTRUCTIONS,
    website_url="https://xonta.ru",
    version=__version__,
)


def _no_tariff() -> dict:
    return {
        "error": "tariff_not_loaded",
        "message": (
            "Таблица ТН ВЭД/ЕТТ не загружена на этом сервере. Администратор: выполните "
            "`xonta-customs-load-tariff <файл.xlsx>`. Расчёт платежей работает и без неё, "
            "если передать duty_rate явно."
        ),
    }


@mcp.tool(annotations=RO)
def tnved_search(
    query: Annotated[str, Field(description="Product description in Russian (e.g. 'насос шестеренный гидравлический') or a code prefix like '8413' or '8413603100'")],
    limit: Annotated[int, Field(ge=1, le=50, description="Max results")] = 10,
) -> dict:
    """Search the TN VED EAEU (ТН ВЭД ЕАЭС) commodity nomenclature by product words or code prefix.

    Returns candidate 10-digit codes with official names and the ETT import duty rate.
    Use the candidates to pick a code, then call tnved_code_info for details.
    Text search matches nomenclature wording, so use technical terms (material, function),
    not brand names. Results are candidates, not a classification decision.
    """
    if not store.tariff_meta().get("loaded"):
        return _no_tariff()
    items = store.search(query, limit)
    return {"query": query, "results": items, "count": len(items), "disclaimer": DISCLAIMER}


@mcp.tool(annotations=RO)
def tnved_code_info(
    code: Annotated[str, Field(description="TN VED EAEU code, 4-10 digits, spaces allowed, e.g. '8413 60 310 0'")],
    origin_country: Annotated[str | None, Field(description="ISO 3166-1 alpha-2 country of origin, e.g. 'CN', to check antidumping measures")] = None,
) -> dict:
    """Get everything known about one TN VED EAEU code.

    Returns the official name with parent headings, the ETT import duty rate parsed into
    ad valorem / specific / combined parts, EAEU antidumping measures that may apply
    (filtered by origin country if given) and EEC classification rulings for this heading.
    """
    info = store.get_code(code) if store.tariff_meta().get("loaded") else None
    rate = parse_rate(info["duty_raw"]) if info and info.get("duty_raw") else None
    return {
        "code": store.normalize_code(code),
        "code_formatted": store.format_code(code),
        "found_in_tariff": info is not None,
        "tariff": info,
        "duty_rate": None if rate is None else rate.to_dict() | {"description": rate.describe()},
        "antidumping_measures": store.find_measures(code, origin_country, info["name"] if info else None),
        "classification_rulings": store.find_rulings(None, code),
        "tariff_status": store.tariff_meta(),
        "disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=RO_NET)
async def calc_import_payments(
    customs_value: Annotated[float, Field(gt=0, description="Customs value of the goods (usually CIF to the EAEU border) in `currency`")],
    currency: Annotated[str, Field(description="Currency of customs_value: RUB, CNY, USD, EUR, etc.")] = "RUB",
    code: Annotated[str | None, Field(description="TN VED EAEU code; its ETT duty rate is used if duty_rate is not given")] = None,
    duty_rate: Annotated[str | None, Field(description="Duty rate as in the tariff, overrides the code: '10', '0', '0,6 евро за 1 кг', '15, но не менее 2,5 евро за 1 пару'")] = None,
    vat_rate: Annotated[Literal[22, 10, 0], Field(description="Import VAT rate in 2026: 22 general, 10 for goods on Government lists (some food, children's goods, medical), 0 if exempt")] = 22,
    antidumping_rate_pct: Annotated[float, Field(ge=0, le=500, description="Antidumping/countervailing/special duty rate in % of customs value, if a measure applies")] = 0.0,
    excise_rub: Annotated[float, Field(ge=0, description="Excise in RUB if the goods are excisable (alcohol, tobacco, fuel, cars)")] = 0.0,
    quantity_kg: Annotated[float | None, Field(ge=0, description="Net weight in kg, needed for per-kg specific rates")] = None,
    quantity_pcs: Annotated[float | None, Field(ge=0, description="Pieces, for per-piece rates")] = None,
    quantity_pair: Annotated[float | None, Field(ge=0, description="Pairs (footwear)")] = None,
    quantity_l: Annotated[float | None, Field(ge=0, description="Litres")] = None,
    quantity_m2: Annotated[float | None, Field(ge=0, description="Square metres")] = None,
    quantity_cm3: Annotated[float | None, Field(ge=0, description="Engine displacement in cm3")] = None,
    exchange_rates: Annotated[dict[str, float] | None, Field(description="RUB per 1 unit, e.g. {'CNY': 11.2, 'EUR': 92.5}. If omitted, Bank of Russia rates for `on_date` are fetched")] = None,
    on_date: Annotated[str | None, Field(description="Declaration date YYYY-MM-DD for exchange rates; default today")] = None,
    recycling_fee_rub: Annotated[float, Field(ge=0, description="Car recycling fee (утильсбор) in RUB from calc_recycling_fee, to show the full cost of importing a vehicle. Not part of the VAT base")] = 0.0,
) -> dict:
    """Calculate import customs payments into Russia for one goods item, in RUB.

    Computes: import duty by the EAEU ETT rate (ad valorem, specific per kg/pcs/pair/litre,
    or combined 'X%, but not less than Y EUR per unit'), antidumping duty, excise, import VAT
    ((customs value + duty + antidumping + excise) x 22% or 10%) and the 2026 customs clearance
    fee by customs value bracket. Converts currencies at Bank of Russia rates.
    Returns a line-by-line breakdown with sources.
    """
    cur = currency.strip().upper()
    fx = dict(exchange_rates or {})
    fx_source = "переданы в запросе" if exchange_rates else None

    rate_text = duty_rate
    tariff_row = None
    if rate_text is None:
        if not code:
            return {"error": "need_rate", "message": "Передайте code или duty_rate."}
        if not store.tariff_meta().get("loaded"):
            return _no_tariff()
        tariff_row = store.get_code(code)
        if not tariff_row or not tariff_row.get("duty_raw"):
            return {"error": "rate_not_found", "message": f"Нет ставки для кода {store.format_code(code)} в загруженном тарифе. Передайте duty_rate."}
        rate_text = tariff_row["duty_raw"]
    rate = parse_rate(rate_text)

    need = {cur} - {"RUB"}
    if rate.specific and rate.specific.currency != "RUB":
        need.add(rate.specific.currency)
    missing = [c for c in need if c not in fx]
    if missing:
        try:
            d = date.fromisoformat(on_date) if on_date else None
            got = await cbr.fetch_rates(d)
        except Exception as e:  # network or parse error
            return {"error": "fx_unavailable", "message": f"Не удалось получить курсы ЦБ ({e}). Передайте exchange_rates.", "need": missing}
        for c in missing:
            if c not in got["rates"]:
                return {"error": "fx_unknown", "message": f"ЦБ не публикует курс {c}"}
            fx[c] = got["rates"][c]
        fx_source = f"{got['source']}, курс на {got['date']}"

    value_rub = customs_value if cur == "RUB" else customs_value * fx[cur]
    qty = Quantities(kg=quantity_kg, pcs=quantity_pcs, pair=quantity_pair, l=quantity_l, m2=quantity_m2, cm3=quantity_cm3)
    try:
        result = calculate(
            customs_value_rub=value_rub,
            rate=rate,
            qty=qty,
            fx=fx,
            vat_rate_pct=float(vat_rate),
            antidumping_rate_pct=antidumping_rate_pct,
            excise_rub=excise_rub,
        )
    except CalcError as e:
        return {"error": "calc_error", "message": str(e)}

    if recycling_fee_rub:
        result["recycling_fee_rub"] = round(recycling_fee_rub, 2)
        result["total_with_recycling_fee_rub"] = round(result["total_payments_rub"] + recycling_fee_rub, 2)
        result["notes"].append("Утильсбор платится отдельно от таможенных платежей и не входит в базу НДС.")
    result["input"] = {"customs_value": customs_value, "currency": cur, "code": code, "duty_rate_text": rate_text}
    result["exchange_rates_used"] = {k: v for k, v in fx.items() if k in need}
    result["exchange_rates_source"] = fx_source
    if code:
        measures = store.find_measures(code, None, tariff_row["name"] if tariff_row else None)
        if measures and not antidumping_rate_pct:
            result["warnings"] = [
                "По этому коду или товару есть меры защиты рынка ЕАЭС — проверьте antidumping_check "
                "и передайте antidumping_rate_pct, если страна происхождения под мерой."
            ]
    result["disclaimer"] = DISCLAIMER
    return result


@mcp.tool(annotations=RO)
def calc_recycling_fee(
    engine: Annotated[Literal["ice", "hybrid_parallel", "ev", "hybrid_series"], Field(description="ice = petrol/diesel; hybrid_parallel counts as ICE; ev = electric; hybrid_series = series hybrid (counts as EV)")],
    power_hp: Annotated[float | None, Field(gt=0, description="Engine power in horsepower (л.с.); for EVs the 30-minute max power")] = None,
    power_kw: Annotated[float | None, Field(gt=0, description="Engine power in kW, alternative to power_hp")] = None,
    engine_volume_cc: Annotated[float | None, Field(gt=0, description="Engine displacement in cm3 (required for ice and hybrid_parallel)")] = None,
    older_than_3_years: Annotated[bool, Field(description="True if more than 3 years have passed since the production date")] = False,
    personal_use: Annotated[bool, Field(description="Imported by an individual for personal use (preferential 3 400 / 5 200 RUB up to 160 hp and 3 l)")] = False,
    on_date: Annotated[str | None, Field(description="Date YYYY-MM-DD the fee is calculated for; default today. Tables run Dec 2025 - 2030")] = None,
    eaeu_extra_rub: Annotated[float, Field(ge=0, description="For cars released in another EAEU country: sum of Ктп + Кндс + Ка (duty, VAT, excise differences), if known")] = 0.0,
) -> dict:
    """Recycling fee (утилизационный сбор) for a passenger car (category M1) imported into Russia.

    Uses the official coefficient table (Decree 1291 as amended by Decree 1713 of 01.11.2025):
    base rate 20 000 RUB x coefficient by engine type, volume, power band (kW), age and year
    (Dec 2025, 2026 ... 2030). Covers the commercial table and the personal-use table
    (0.17 / 0.26 for up to 160 hp and up to 3 l). Returns the coefficient, band and source.
    """
    try:
        res = _calc_recycling_fee(
            engine=engine,
            power_hp=power_hp,
            power_kw=power_kw,
            engine_volume_cc=engine_volume_cc,
            older_than_3_years=older_than_3_years,
            personal_use=personal_use,
            on=date.fromisoformat(on_date) if on_date else None,
            eaeu_extra_rub=eaeu_extra_rub,
        )
    except (RecyclingError, ValueError) as e:
        return {"error": "recycling_error", "message": str(e)}
    res["disclaimer"] = DISCLAIMER
    return res


@mcp.tool(annotations=RO_NET)
async def parse_invoice(
    invoice_text: Annotated[str | None, Field(description="Invoice or packing list as Markdown or plain text, e.g. the output of DocParse. Tables with English, Chinese (品名, 数量, 单价, 金额, 净重) or Russian headers")] = None,
    file_url: Annotated[str | None, Field(description="Public link to the invoice file: .xlsx/.csv are parsed directly; PDF/scans/DOCX go through DocParse when the server has it configured")] = None,
) -> dict:
    """Parse a supplier's commercial invoice or packing list into customs-ready line items.

    Extracts invoice number, date, parties, currency, Incoterms and country of origin, and for each
    line: description, model, material, supplier HS code, quantity, unit, price, amount, net and
    gross weight. Checks arithmetic (qty x price, sum vs total), explains what to add to the invoice
    value for customs value under the given Incoterms, and suggests a TN VED search query per line
    (HS code first 6 digits or Russian keywords). Feed the lines to tnved_search and calc_import_payments.
    """
    if not invoice_text and not file_url:
        return {"error": "need_input", "message": "Передайте invoice_text или file_url."}
    try:
        if invoice_text:
            res = invoice.parse_invoice_text(invoice_text)
            res["parsed_from"] = "text"
        else:
            low = file_url.lower().split("?")[0]
            if low.endswith((".xlsx", ".xlsm", ".csv", ".tsv")):
                with tempfile.TemporaryDirectory() as d:
                    p = await invoice.fetch_file(file_url, Path(d))
                    res = invoice.parse_invoice_file(p)
                res["parsed_from"] = "file"
            else:
                md = await invoice.docparse_to_markdown(file_url)
                res = invoice.parse_invoice_text(md)
                res["parsed_from"] = "docparse"
    except (ValueError, RuntimeError) as e:
        return {"error": "parse_error", "message": str(e)}
    except Exception as e:  # network errors
        return {"error": "fetch_error", "message": f"Не удалось получить файл: {e}"}
    res["disclaimer"] = DISCLAIMER
    return res


@mcp.tool(annotations=RO)
def customs_clearance_fee(
    total_customs_value_rub: Annotated[float, Field(ge=0, description="Total customs value of all goods in the declaration, RUB")],
) -> dict:
    """Customs clearance fee (сбор за таможенные операции) for an import declaration into Russia in 2026.

    The fee depends on the total customs value of the declaration: from 1 231 RUB (up to 200 000)
    to 73 860 RUB (over 10 million). Also returns the full bracket table and the legal source.
    """
    return {
        "fee_rub": import_fee(total_customs_value_rub),
        "brackets": fee_table(),
        "source": FEES_SOURCE,
    }


@mcp.tool(annotations=RO)
def antidumping_check(
    code: Annotated[str | None, Field(description="TN VED EAEU code or prefix")] = None,
    origin_country: Annotated[str | None, Field(description="ISO alpha-2 country of origin, e.g. CN, UA, AZ")] = None,
    product: Annotated[str | None, Field(description="Product words in Russian or English, e.g. 'грузовые шины'")] = None,
) -> dict:
    """Check EAEU trade defence measures (antidumping duties) by code, product and origin country.

    Returns matching measures with the Eurasian Economic Commission decision, the decision that
    sets duty rates per producer, expiry date and a link. The bundled list covers measures
    renewed in 2026 and is not exhaustive: absence of a match is not proof that no measure applies.
    """
    if not (code or product):
        return {"error": "need_input", "message": "Передайте code или product."}
    data = store.antidumping_data()
    found = store.find_measures(code, origin_country, product)
    return {
        "matches": found,
        "count": len(found),
        "list_updated": data["updated"],
        "coverage_note": data["note"],
        "disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=RO)
def classification_rulings_search(
    query: Annotated[str | None, Field(description="Product words, e.g. 'прицел тепловизионный'")] = None,
    code: Annotated[str | None, Field(description="TN VED code or heading, e.g. '9013'")] = None,
) -> dict:
    """Search EEC (Eurasian Economic Commission) decisions on classification of specific goods.

    These decisions are binding for all EAEU customs and are the strongest evidence for a code.
    Returns the decision number and date, the product, the TN VED code or heading and a source link.
    """
    if not (query or code):
        return {"error": "need_input", "message": "Передайте query или code."}
    data = store.rulings_data()
    res = store.find_rulings(query, code)
    return {"results": res, "count": len(res), "list_updated": data["updated"], "note": data["note"]}


@mcp.tool(annotations=RO_NET)
async def exchange_rates(
    currencies: Annotated[list[str] | None, Field(description="Currency codes, e.g. ['CNY','USD','EUR']; all if omitted")] = None,
    on_date: Annotated[str | None, Field(description="Date YYYY-MM-DD; default today")] = None,
) -> dict:
    """Official Bank of Russia exchange rates (RUB per 1 unit) used for customs payments."""
    try:
        got = await cbr.fetch_rates(date.fromisoformat(on_date) if on_date else None)
    except Exception as e:
        return {"error": "fx_unavailable", "message": str(e)}
    rates = got["rates"]
    if currencies:
        rates = {c.upper(): rates.get(c.upper()) for c in currencies}
    return {"date": got["date"], "rates_rub": rates, "source": got["source"]}


@mcp.tool(annotations=RO)
def server_status() -> dict:
    """Data versions of this server: tariff load date and source, antidumping and rulings list dates, fee table source."""
    return {
        "version": __version__,
        "tariff": store.tariff_meta(),
        "antidumping_list_updated": store.antidumping_data()["updated"],
        "rulings_list_updated": store.rulings_data()["updated"],
        "fees_source": FEES_SOURCE,
        "vat_2026": "22% общая, 10% льготная (ст. 164 НК РФ, ред. 425-ФЗ)",
        "recycling_fee_source": "Постановление № 1291, раздел I приложения, ред. Постановления № 1713 от 01.11.2025",
        "docparse_configured": bool(os.environ.get("DOCPARSE_URL")),
    }


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "version": __version__})


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"], include_in_schema=False)
async def server_card(_: Request) -> JSONResponse:
    tools = await mcp.list_tools()
    return JSONResponse(
        {
            "serverInfo": {"name": "xonta-customs-ru", "title": "Xonta Customs RU", "version": __version__},
            "description": "Russia / EAEU import: TN VED codes, duties, VAT, fees, antidumping, classification rulings",
            "authentication": {"required": False},
            "tools": [{"name": t.name, "description": t.description} for t in tools],
        }
    )


def main() -> None:
    ap = argparse.ArgumentParser(prog="xonta-customs-mcp")
    ap.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = ap.parse_args()
    if not args.http:
        mcp.run("stdio")
        return

    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts + ["127.0.0.1:*", "localhost:*"])
        if hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True, transport_security=security, host=args.host)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
