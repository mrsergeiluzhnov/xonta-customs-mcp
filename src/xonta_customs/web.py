"""Страница для человека, который открыл адрес MCP-сервера в браузере.

Программы (MCP-клиенты) шлют POST или GET с Accept: text/event-stream и получают то же, что раньше.
Браузер шлёт GET с Accept: text/html и вместо технической ошибки видит, что это за сервер и как его подключить.
"""
from __future__ import annotations

import html
import json

CARD = {
    "key": "xonta-customs",
    "name": "Xonta Customs RU",
    "passport": "ag_f531c6b2d4",
    "repo": "https://github.com/mrsergeiluzhnov/xonta-customs-mcp",
    "en": "MCP server for importing goods into Russia and the EAEU: supplier invoice parsing, TN VED codes, duties, VAT, customs fees, car recycling fee, antidumping measures and classification rulings. Every number comes with its source.",
    "ru": "MCP-сервер для ввоза товаров в Россию и ЕАЭС: разбор инвойса поставщика, коды ТН ВЭД, пошлины, НДС, таможенные сборы, утильсбор, антидемпинг и решения ЕЭК по классификации. У каждой цифры есть источник."
}

_STYLE = """:root{--bg:#fbfaf7;--ink:#1d1c1a;--ink2:#5c5a55;--line:#e3e0d8;--card:#fff;--acc:#1f5f8b;--code:#f1efe9}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--ink:#ecebe6;--ink2:#a6a39b;--line:#2e2d2a;--card:#1b1a18;--acc:#7db4dd;--code:#1f1e1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:36px 16px 56px}a{color:var(--acc)}h1{font-size:28px;line-height:1.2;margin:0 0 8px}
h2{font-size:17px;margin:26px 0 6px}.lede{color:var(--ink2);margin:0 0 6px}.muted{color:var(--ink2);font-size:14px}
pre{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);border-radius:6px;padding:12px 14px;white-space:pre-wrap;word-break:break-all}
hr{border:0;border-top:1px solid var(--line);margin:34px 0}.links a{margin-right:14px;white-space:nowrap}"""


def render(public_url: str) -> str:
    c, e = CARD, html.escape
    cfg = json.dumps({"mcpServers": {c["key"]: {"url": public_url}}}, indent=2)
    passport = f"https://xonta.dev/passport/?id={c['passport']}"
    links = lambda lang: (  # noqa: E731
        f'<p class="links"><a href="{e(c["repo"])}">GitHub</a>'
        f'<a href="{e(passport)}&amp;lang={lang}">{"Паспорт сервера" if lang == "ru" else "Server passport"}</a>'
        f'<a href="{"https://mcp.xonta.ru/" if lang == "ru" else "https://xonta.dev/mcp/"}">{"Другие серверы Xonta" if lang == "ru" else "Other Xonta servers"}</a></p>'
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(c["name"])} — MCP server</title><meta name="description" content="{e(c["en"])}"><meta name="robots" content="noindex"><style>{_STYLE}</style></head>
<body><main>
<h1>{e(c["name"])}</h1>
<p class="lede">{e(c["en"])}</p>
<p class="muted">This address is an MCP server for AI agents, not a web page. Add it to Claude, Cursor or any other MCP client:</p>
<pre>{e(cfg)}</pre>
<p class="muted">Free, no sign-up, no keys.</p>
{links("en")}
<hr>
<h2>{e(c["name"])} — по-русски</h2>
<p class="lede">{e(c["ru"])}</p>
<p class="muted">Это адрес MCP-сервера для ИИ-агентов, а не веб-страница. Добавьте его в Claude, Cursor или другой MCP-клиент, настройка та же, что выше. Бесплатно, без регистрации и ключей.</p>
{links("ru")}
<p class="muted">Xonta · <a href="https://xonta.dev/?utm_source={e(c["key"])}&amp;utm_medium=endpoint">xonta.dev</a></p>
</main></body></html>"""


class BrowserCard:
    """ASGI-обёртка: GET от браузера на / или /mcp получает страницу, всё остальное идёт в MCP-приложение."""

    def __init__(self, app, public_url: str):
        self.app, self.page = app, render(public_url).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and scope["path"] in ("/", "/mcp", "/mcp/"):
            accept = dict(scope.get("headers") or []).get(b"accept", b"").decode("latin-1").lower()
            if scope["path"] == "/" or ("text/html" in accept and "text/event-stream" not in accept):
                await send({"type": "http.response.start", "status": 200, "headers": [
                    (b"content-type", b"text/html; charset=utf-8"), (b"cache-control", b"public, max-age=600"),
                    (b"content-length", str(len(self.page)).encode()), (b"vary", b"Accept")]})
                await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else self.page})
                return
        await self.app(scope, receive, send)
