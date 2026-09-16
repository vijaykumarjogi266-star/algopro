"""Integration tests for Stage 6 Web UI (Paper Trading Dashboard & Settings)."""

import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_settings_view_rendering(client: AsyncClient):
    """Verify /research/settings renders broker connection manager and credential masking notice."""
    res = await client.get("/research/settings")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    text = res.text
    assert "Broker & Market Data Connection Adapters" in text
    assert "Credential Masking Active" in text
    assert "LIVE trading execution is hard-disabled" in text
    assert "broker-connections-tbody" in text


@pytest.mark.asyncio
async def test_paper_trading_view_rendering(client: AsyncClient):
    """Verify /research/paper-trading renders session dashboard and controls."""
    res = await client.get("/research/paper-trading")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    text = res.text
    assert "Paper Trading Sessions" in text
    assert "Initialize Paper Trading Session" in text
    assert "paper-sessions-tbody" in text
    assert "paper-detail-card" in text


@pytest.mark.asyncio
async def test_paper_trading_session_detail_view(client: AsyncClient):
    """Verify /research/paper-trading/{session_id} route returns valid UI HTML."""
    res = await client.get("/research/paper-trading/sess_test_12345")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


@pytest.mark.asyncio
async def test_stage6_zero_gamification_and_offline_isolation(client: AsyncClient):
    """Verify zero gamification and zero external CDN dependencies across Stage 6 UI."""
    res = await client.get("/research")
    html = res.text.lower()

    # Zero gamification invariant
    forbidden_terms = [
        "badge-gold", "badge-silver", "streak", "leaderboard",
        "strategy score", "best strategy", "winner", "points earned"
    ]
    for term in forbidden_terms:
        assert term not in html, f"Forbidden gamification term '{term}' found"

    # Zero external CDN dependencies
    forbidden_cdns = ["cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com", "fonts.googleapis.com"]
    for cdn in forbidden_cdns:
        assert cdn not in html, f"External CDN dependency '{cdn}' found in HTML"
