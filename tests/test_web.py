import asyncio

import pytest

from xonta_customs.web import BrowserCard


async def _call(path, accept, method="GET"):
    hit, sent = [], []

    async def app(scope, receive, send):
        hit.append(scope["path"])

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": method, "path": path, "headers": [(b"accept", accept.encode())]}
    await BrowserCard(app, "https://example.test/mcp")(scope, None, send)
    return hit, sent


@pytest.mark.asyncio
async def test_browser_gets_page_clients_get_mcp():
    hit, sent = await _call("/mcp", "text/html,application/xhtml+xml")
    assert not hit and sent[0]["status"] == 200 and b"https://example.test/mcp" in sent[1]["body"]
    assert b"xonta.dev/passport" in sent[1]["body"]
    hit, sent = await _call("/mcp", "text/event-stream")
    assert hit == ["/mcp"] and not sent
    hit, sent = await _call("/mcp", "application/json, text/event-stream", "POST")
    assert hit == ["/mcp"]
    hit, sent = await _call("/", "*/*")
    assert not hit and sent[0]["status"] == 200
