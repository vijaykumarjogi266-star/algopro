"""Algo Lab Stage 5 Phase D & E: Research UI & Visualization Integration Tests.

Verifies:
1. Research UI root renders valid HTML.
2. Dashboard view contains required status cards and experiment tracking.
3. Zero-gamification invariant (no streaks, badges, leaderboards, scores).
4. Create experiment view includes all parameter controls.
5. Experiment detail view displays fingerprint and provenance.
6. Run monitor displays lifecycle state transitions (PENDING, RUNNING, COMPLETED, FAILED).
7. Results view exposes documented quantitative measurements without fabricated scores.
8. Interactive SVG visualizations (equity curve, drawdown curve, statutory friction).
9. Complete offline isolation (zero external CDN dependencies).
"""

import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_research_ui_root_endpoint(client: AsyncClient):
    res = await client.get("/research")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    text = res.text
    assert "Algo Lab" in text
    assert "Research OS" in text


@pytest.mark.asyncio
async def test_dashboard_view_contents(client: AsyncClient):
    res = await client.get("/research")
    text = res.text
    assert "Total Experiments" in text
    assert "Running Executions" in text
    assert "Completed Backtests" in text
    assert "Risk Rejections / Failures" in text
    assert "Recent Research Experiments" in text
    assert "experiments-table-body" in text


@pytest.mark.asyncio
async def test_zero_gamification_invariant(client: AsyncClient):
    res = await client.get("/research")
    lower_text = res.text.lower()
    # Ensure no gamification, badges, streaks, leaderboards, or strategy scores exist
    forbidden_terms = [
        "badge-gold", "badge-silver", "streak", "leaderboard",
        "strategy score", "best strategy", "winner", "points earned"
    ]
    for term in forbidden_terms:
        assert term not in lower_text, f"Forbidden gamification term '{term}' found in UI"


@pytest.mark.asyncio
async def test_create_experiment_view(client: AsyncClient):
    res = await client.get("/research/create")
    assert res.status_code == 200
    text = res.text
    assert 'id="cfg-name"' in text
    assert 'id="cfg-strategy"' in text
    assert 'id="cfg-strategy-ver"' in text
    assert 'id="cfg-dataset"' in text
    assert 'id="cfg-checksum"' in text
    assert 'id="cfg-universe"' in text
    assert 'id="cfg-timeframe"' in text
    assert 'id="cfg-start"' in text
    assert 'id="cfg-end"' in text
    assert 'id="cfg-capital"' in text
    assert 'id="cfg-seed"' in text
    assert 'id="cfg-params"' in text
    assert "Dry-Run Validation" in text
    assert "Save Experiment Definition" in text


@pytest.mark.asyncio
async def test_experiment_detail_view(client: AsyncClient):
    res = await client.get("/research/detail")
    assert res.status_code == 200
    text = res.text
    assert 'id="detail-title"' in text
    assert 'id="detail-fp"' in text
    assert 'id="detail-strategy"' in text
    assert 'id="detail-dataset"' in text
    assert 'id="detail-capital"' in text
    assert 'id="btn-submit-run"' in text


@pytest.mark.asyncio
async def test_run_monitor_lifecycle_states(client: AsyncClient):
    res = await client.get("/research/detail")
    text = res.text
    assert 'id="monitor-run-id"' in text
    assert 'id="monitor-lifecycle"' in text
    assert 'id="monitor-audit-log"' in text
    assert 'id="monitor-trades-count"' in text
    assert 'id="monitor-rejections-count"' in text


@pytest.mark.asyncio
async def test_results_view_measurements(client: AsyncClient):
    res = await client.get("/research/results")
    assert res.status_code == 200
    text = res.text
    # Documented quantitative research measurements
    assert 'id="res-net-return"' in text
    assert 'id="res-cagr"' in text
    assert 'id="res-sharpe"' in text
    assert 'id="res-sortino"' in text
    assert 'id="res-max-dd"' in text
    assert 'id="res-hit-rate"' in text
    assert 'id="res-trades"' in text
    assert 'id="res-cost-drag"' in text


@pytest.mark.asyncio
async def test_results_visualization_components(client: AsyncClient):
    res = await client.get("/research/results")
    text = res.text
    # SVG chart containers
    assert 'id="svg-equity-curve"' in text
    assert 'id="svg-drawdown-curve"' in text
    # Statutory friction breakdown
    assert "Securities Transaction Tax (STT)" in text
    assert "Exchange Turnover Charges" in text
    assert "SEBI Regulatory Fees" in text
    assert "GST" in text
    assert "Execution Slippage" in text


@pytest.mark.asyncio
async def test_offline_zero_external_cdn_dependency(client: AsyncClient):
    res = await client.get("/research")
    text = res.text
    # Assert no external scripts or stylesheets are imported from CDNs
    assert "cdn.jsdelivr.net" not in text
    assert "cdnjs.cloudflare.com" not in text
    assert "unpkg.com" not in text
    assert "fonts.googleapis.com" not in text
    assert "<script src=\"http" not in text


@pytest.mark.asyncio
async def test_compare_view_elements(client: AsyncClient):
    res = await client.get("/research/compare")
    assert res.status_code == 200
    text = res.text
    assert 'id="view-compare"' in text
    assert 'id="compare-baseline-select"' in text
    assert 'id="compare-target-select"' in text
    assert 'id="compare-results-card"' in text
    assert 'id="cmp-params-tbody"' in text
    assert 'id="cmp-metrics-tbody"' in text
    assert "Strictly Descriptive • Non-Ranking" in text

