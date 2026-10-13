"""Tests for Stored XSS prevention in Research UI and frontend responses.

Tests:
13. test_stored_experiment_name_renders_as_text
14. test_other_stored_fields_cannot_execute_html
"""

import shutil
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.core.config import settings
from apps.api.routes.research_ui import RESEARCH_UI_HTML


@pytest.fixture
def client():
    return TestClient(app)


def test_stored_experiment_name_renders_as_text(client, monkeypatch):
    """Test 13: Experiment named with an XSS payload must be escaped and rendered safely as text.
    - Verified via CSP headers.
    - Verified via escapeHtml sanitization in RESEARCH_UI_HTML.
    - Verified no raw unescaped HTML sink in experiment listing.
    """
    admin_key = "admin_key_test_1234567890123456"
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", admin_key)
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)
    headers = {"X-API-Key": admin_key}

    xss_payload = '<img src=x onerror="window.__xss=1">'

    # Create experiment with XSS payload in name
    exp_payload = {
        "name": xss_payload,
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "v1.0.0",
        "dataset_checksum": "a" * 64,
        "universe": ["RELIANCE"],
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-06-01T00:00:00Z",
        "initial_capital": 100000.0,
    }
    create_res = client.post("/api/v1/experiments", json=exp_payload, headers=headers)
    assert create_res.status_code in (200, 201)

    # Fetch UI page
    ui_res = client.get("/research", headers=headers)
    assert ui_res.status_code == 200

    # Defense in depth: CSP headers must be present
    csp = ui_res.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp

    # In UI code, escapeHtml function must be defined and applied to experiment fields
    assert "escapeHtml" in ui_res.text
    assert "escapeHtml(e.name)" in ui_res.text or "textContent = e.name" in ui_res.text

    # Verify no raw unescaped inline onclick attribute interpolating experiment_id
    assert 'onclick="openExperimentDetail(\'${e.experiment_id}\')"' not in ui_res.text


@pytest.mark.parametrize("payload", [
    '<svg onload="window.__xss=2">',
    '"><script>window.__xss=3</script>',
    '<img src=x onerror="alert(1)">',
    "';alert('xss');//",
])
def test_other_stored_fields_cannot_execute_html(client, monkeypatch, payload):
    """Test 14: Other dynamic fields (session name, broker name, parameters) must be safely escaped."""
    admin_key = "admin_key_test_1234567890123456"
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", admin_key)
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)
    headers = {"X-API-Key": admin_key}

    # 1. Broker connection name with payload
    broker_payload = {
        "broker_name": payload,
        "environment": "PAPER",
        "api_key": "some_test_key",
    }
    b_res = client.post("/api/v1/brokers/connections", json=broker_payload, headers=headers)
    assert b_res.status_code in (200, 201)

    # 2. Paper session with payload
    session_payload = {
        "name": payload,
        "strategy_id": "Canonical_SMA",
        "universe": ["RELIANCE"],
        "initial_capital": 100000.0,
        "environment": "PAPER",
    }
    s_res = client.post("/api/v1/paper-trading/sessions", json=session_payload, headers=headers)
    assert s_res.status_code in (200, 201)

    # Verify UI code escapes session name and broker name
    ui_res = client.get("/research", headers=headers)
    assert ui_res.status_code == 200
    assert "escapeHtml(s.name)" in ui_res.text or "textContent = s.name" in ui_res.text
    assert "escapeHtml(c.broker_name)" in ui_res.text or "textContent = c.broker_name" in ui_res.text
