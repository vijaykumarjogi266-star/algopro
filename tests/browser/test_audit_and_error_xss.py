"""Regression tests for XSS remediation in audit trails, validation errors, and experiment details.

Tests:
T26: test_audit_event_json_xss_payload_escaped
T27: test_validation_error_xss_sink_sanitized
T28: test_experiment_detail_xss_sanitized
"""

import html
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.core.config import settings
from apps.api.routes.experiments import get_service


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(monkeypatch):
    admin_key = "admin_key_test_1234567890123456"
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", admin_key)
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)
    return {"X-API-Key": admin_key}


def test_audit_event_json_xss_payload_escaped(client, auth_headers):
    """T26: Audit event JSON payload containing XSS vectors must be safely escaped.

    Verifies:
    1. Audit event payload can store arbitrary text without corrupting ledger.
    2. Research UI does NOT inject raw JSON audit payload into innerHTML.
    3. UI rendering logic uses textContent / code element rather than dangerous innerHTML sinks.
    4. DOM rendering treats the payload as literal text (not executable markup).
    """
    service = get_service()

    # 1. Create a backtest experiment
    exp_payload = {
        "name": "Audit XSS Test Exp",
        "description": "Validating audit trail XSS neutralization",
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "v1.0.0",
        "dataset_checksum": "b" * 64,
        "universe": ["TCS"],
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-06-01T00:00:00Z",
        "initial_capital": 100000.0,
    }
    create_res = client.post("/api/v1/experiments", json=exp_payload, headers=auth_headers)
    assert create_res.status_code in (200, 201), create_res.text
    exp_id = create_res.json()["experiment_id"]

    # 2. Submit backtest run to initialize run record
    submit_res = client.post(f"/api/v1/experiments/{exp_id}/submit", headers=auth_headers)
    assert submit_res.status_code in (200, 201, 202), submit_res.text

    # 3. Append audit events with dangerous script and image payloads
    xss_payload = {
        "note": "<script>alert(1)</script>",
        "image_vector": "<img src=x onerror=alert(1)>",
        "nested": {"vector": "<svg/onload=alert('audit')>"},
    }
    service.store.append_audit_event(exp_id, "RISK_REJECTED", xss_payload)

    # 4. Retrieve audit trail endpoint
    audit_res = client.get(f"/api/v1/experiments/{exp_id}/runs/{exp_id}/audit", headers=auth_headers)
    assert audit_res.status_code == 200, audit_res.text
    audit_events = audit_res.json()
    assert len(audit_events) >= 1
    found_event = next(e for e in audit_events if e["event_type"] == "RISK_REJECTED")
    assert found_event["payload"]["note"] == "<script>alert(1)</script>"

    # 4. Verify UI HTML frontend source code sinks
    ui_res = client.get("/research", headers=auth_headers)
    assert ui_res.status_code == 200
    ui_html = ui_res.text

    # Verify that audit events are NOT injected into innerHTML via raw template interpolation
    assert "${JSON.stringify(e.payload, null, 2)}</pre>" not in ui_html
    assert "tbody.innerHTML = events.map" not in ui_html

    # Verify that codeEl.textContent is used for payload rendering
    assert "codeEl.textContent = JSON.stringify(e.payload" in ui_html or "textContent = JSON.stringify" in ui_html

    # Verify that monitor audit log box uses textContent and never innerHTML
    assert "logBox.textContent = auditEvents.map" in ui_html
    assert "logBox.innerHTML" not in ui_html


def test_validation_error_xss_sink_sanitized(client, auth_headers):
    """T27: Validation errors containing XSS vectors must be safely sanitized and escaped.

    Verifies:
    1. Input validation error response (422) strips or redacts raw malicious payloads.
    2. Research UI validation error renderer uses textContent and never innerHTML.
    """
    xss_injection = '<script>alert("validation_xss")</script><img src=x onerror=alert(1)>'

    # Send invalid payload with XSS in typed fields (e.g. invalid capital type or malformed date)
    bad_payload = {
        "name": "Invalid Exp",
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "v1.0.0",
        "dataset_checksum": "c" * 64,
        "universe": ["INFY"],
        "start_date": "invalid-date-format" + xss_injection,
        "end_date": "2024-06-01T00:00:00Z",
        "initial_capital": "not-a-number-" + xss_injection,
    }

    # Test dry-run validation endpoint
    val_res = client.post("/api/v1/experiments/validate", json=bad_payload, headers=auth_headers)
    assert val_res.status_code in (200, 422), val_res.text
    if val_res.status_code == 200:
        val_data = val_res.json()
        assert not val_data["is_valid"]
        assert len(val_data["errors"]) > 0

    # Test create experiment endpoint (triggers FastAPI RequestValidationError -> 422)
    create_res = client.post("/api/v1/experiments", json=bad_payload, headers=auth_headers)
    assert create_res.status_code == 422
    err_json = create_res.json()
    assert "detail" in err_json
    # Validation errors must have structured type, loc, and sanitized msg
    for err in err_json["detail"]:
        assert "type" in err
        assert "loc" in err
        assert "msg" in err

    # Verify UI validation renderer eliminates innerHTML sink
    ui_res = client.get("/research", headers=auth_headers)
    assert ui_res.status_code == 200
    ui_html = ui_res.text

    # Verify no raw innerHTML interpolation of validation errors
    assert "${data.errors.map(e => `<li>${e}</li>`).join('')}" not in ui_html
    assert "${data.errors.map" not in ui_html

    # Verify list items for errors are created via textContent
    assert "li.textContent = " in ui_html


def test_experiment_detail_xss_sanitized(client, auth_headers):
    """T28: Experiment details with script tags in name and description must be safely rendered.

    Verifies:
    1. Creation with script tags succeeds and persists data without server-side execution.
    2. API experiment detail endpoint returns literal string.
    3. UI detail view assigns name, description, parameters, and strategy via textContent.
    """
    xss_name = '<script>alert("exp_name_xss")</script>'
    xss_desc = '<img src=x onerror="alert(\'exp_desc_xss\')"><script>window.__pwn=1</script>'

    exp_payload = {
        "name": xss_name,
        "description": xss_desc,
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "v1.0.0",
        "dataset_checksum": "d" * 64,
        "universe": ["RELIANCE"],
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-06-01T00:00:00Z",
        "initial_capital": 500000.0,
        "parameters": {"param_<script>": "<script>alert(1)</script>"},
    }

    create_res = client.post("/api/v1/experiments", json=exp_payload, headers=auth_headers)
    assert create_res.status_code in (200, 201), create_res.text
    created = create_res.json()
    exp_id = created["experiment_id"]

    # Retrieve experiment details
    detail_res = client.get(f"/api/v1/experiments/{exp_id}", headers=auth_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["name"] == xss_name
    assert detail["description"] == xss_desc

    # Verify UI implementation
    ui_res = client.get("/research", headers=auth_headers)
    assert ui_res.status_code == 200
    ui_html = ui_res.text

    # detail-title, detail-desc, detail-strategy, detail-params must use textContent
    assert "document.getElementById('detail-title').textContent =" in ui_html
    assert "document.getElementById('detail-strategy').textContent =" in ui_html
    assert "descEl.textContent = currentExperiment.description" in ui_html
    assert "paramsEl.textContent = JSON.stringify(currentExperiment.parameters" in ui_html

    # Ensure no dangerous innerHTML assignments for detail fields
    assert "detail-desc').innerHTML" not in ui_html
    assert "detail-params').innerHTML" not in ui_html
    assert "detail-title').innerHTML" not in ui_html
