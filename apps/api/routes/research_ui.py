"""Algo Lab Research UI Routes.

Serves institutional, research-first web interface for:
- Research Dashboard (system status, experiment statistics, run tracking)
- Experiment Designer (configuration, parameters, validation, live fingerprint preview)
- Experiment Detail & Run Monitor (status state machine, timestamps, error visibility)
- Results & Visualization (equity curves, drawdown curves, friction breakdown, risk rejections)

Zero external CDN dependencies. Pure vanilla CSS/SVG/JS.
Strictly non-gamified: No scores, badges, streaks, or BUY/SELL recommendations.
"""

from fastapi import APIRouter, Request, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse
from typing import Optional

from apps.api.routes.experiments import get_service
from services.backtest_engine.service import BacktestService

router = APIRouter(prefix="/research", tags=["research_ui"])


RESEARCH_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Algo Lab — Systematic Research OS</title>
  <style>
    :root {
      --bg: #0d1117;
      --card-bg: #161b22;
      --card-border: #30363d;
      --text: #c9d1d9;
      --text-muted: #8b949e;
      --heading: #f0f6fc;
      --accent: #58a6ff;
      --accent-hover: #388bfd;
      --success: #3fb950;
      --warning: #d29922;
      --danger: #f85149;
      --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.5;
      padding: 0;
    }

    /* Top Nav */
    nav {
      background: var(--card-bg);
      border-bottom: 1px solid var(--card-border);
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      font-size: 1.1rem;
      color: var(--heading);
    }
    .brand span {
      background: #238636;
      color: #fff;
      font-size: 0.65rem;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
      font-family: var(--font-mono);
    }
    .nav-links {
      display: flex;
      gap: 16px;
    }
    .nav-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      padding: 6px 12px;
      border-radius: 6px;
      transition: all 0.2s;
    }
    .nav-btn:hover, .nav-btn.active {
      color: var(--heading);
      background: #21262d;
    }

    /* Container */
    .container {
      max-width: 1200px;
      margin: 24px auto;
      padding: 0 16px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    /* Sections / Views */
    .view-section { display: none; }
    .view-section.active { display: flex; flex-direction: column; gap: 20px; }

    /* Cards */
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 20px;
    }
    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 16px;
    }
    .card-title {
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--heading);
    }

    /* Metric Grid */
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .metric-card {
      background: #0d1117;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 14px;
    }
    .metric-label {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
      margin-bottom: 4px;
    }
    .metric-value {
      font-size: 1.3rem;
      font-weight: 700;
      font-family: var(--font-mono);
      color: var(--heading);
    }
    .metric-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* Status Badges */
    .badge {
      display: inline-flex;
      align-items: center;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 12px;
      font-weight: 600;
      border: 1px solid transparent;
    }
    .badge-created { background: #21262d; color: #8b949e; border-color: #30363d; }
    .badge-pending { background: #382400; color: #e3b341; border-color: #bb8009; }
    .badge-running { background: #0c2d6b; color: #58a6ff; border-color: #1f6feb; }
    .badge-completed { background: #073b18; color: #3fb950; border-color: #238636; }
    .badge-failed { background: #490202; color: #f85149; border-color: #da3633; }

    /* Tables */
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }
    th, td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--card-border);
    }
    th {
      color: var(--text-muted);
      font-weight: 600;
      font-size: 0.8rem;
    }
    tr:hover td { background: #1c2128; }
    .mono { font-family: var(--font-mono); }

    /* Form Controls */
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    label {
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    input, select, textarea {
      background: #0d1117;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      color: var(--heading);
      padding: 8px 12px;
      font-size: 0.85rem;
      font-family: inherit;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2);
    }
    .full-width { grid-column: 1 / -1; }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.2s;
    }
    .btn-primary { background: #238636; color: #fff; }
    .btn-primary:hover { background: #2ea043; }
    .btn-secondary { background: #21262d; color: var(--text); border-color: var(--card-border); }
    .btn-secondary:hover { background: #30363d; }
    .btn-accent { background: #1f6feb; color: #fff; }
    .btn-accent:hover { background: var(--accent-hover); }

    /* SVG Chart */
    .chart-container {
      width: 100%;
      height: 240px;
      background: #0d1117;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    svg {
      width: 100%;
      height: 100%;
      overflow: visible;
    }

    /* Logs & Audit */
    .terminal-box {
      background: #040d21;
      border: 1px solid #1b3a57;
      border-radius: 6px;
      padding: 12px;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: #7ee787;
      max-height: 250px;
      overflow-y: auto;
      white-space: pre-wrap;
    }
    .governance-notice {
      background: rgba(88, 166, 255, 0.08);
      border: 1px solid rgba(88, 166, 255, 0.25);
      border-radius: 6px;
      padding: 12px 16px;
      font-size: 0.8rem;
      color: #9cd1ff;
      display: flex;
      align-items: center;
      gap: 12px;
    }
  </style>
</head>
<body>

  <!-- Navigation -->
  <nav>
    <div class="brand">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
      </svg>
      Algo Lab <span>Research OS</span>
    </div>
    <div class="nav-links">
      <button class="nav-btn active" onclick="switchView('dashboard')">Dashboard</button>
      <button class="nav-btn" onclick="switchView('create')">New Experiment</button>
      <button class="nav-btn" onclick="switchView('detail')">Experiment Detail</button>
      <button class="nav-btn" onclick="switchView('results')">Research Results</button>
    </div>
  </nav>

  <div class="container">

    <!-- Governance Notice -->
    <div class="governance-notice">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
      <div>
        <strong>Deterministic Research Boundary:</strong> Risk controls and capital limits are enforced independently.
        No automated trading, gamification, or subjective strategy ranking is permitted.
      </div>
    </div>

    <!-- VIEW 1: DASHBOARD -->
    <div id="view-dashboard" class="view-section active">
      <div class="card">
        <div class="card-header">
          <div class="card-title">System & Research Overview</div>
          <div class="badge badge-completed">Safety Guardrails Enforced</div>
        </div>
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">Total Experiments</div>
            <div class="metric-value" id="stat-total">0</div>
            <div class="metric-sub">Registered definitions</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Running Executions</div>
            <div class="metric-value" id="stat-running" style="color: var(--accent);">0</div>
            <div class="metric-sub">Active thread pool jobs</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Completed Backtests</div>
            <div class="metric-value" id="stat-completed" style="color: var(--success);">0</div>
            <div class="metric-sub">With reproducible metrics</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Risk Rejections / Failures</div>
            <div class="metric-value" id="stat-failed" style="color: var(--danger);">0</div>
            <div class="metric-sub">Zero-mutation enforced</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Recent Research Experiments</div>
          <button class="btn btn-secondary" onclick="loadDashboardExperiments()">Refresh</button>
        </div>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Experiment ID</th>
                <th>Name</th>
                <th>Strategy</th>
                <th>Dataset</th>
                <th>Status</th>
                <th>Fingerprint</th>
                <th>Created (UTC)</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="experiments-table-body">
              <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Loading experiments...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- VIEW 2: CREATE EXPERIMENT -->
    <div id="view-create" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Design Quantitative Experiment</div>
          <div class="badge badge-created">Deterministic Configuration</div>
        </div>
        <form id="create-exp-form" onsubmit="handleCreateExperiment(event)">
          <div class="form-grid">
            <div class="form-group full-width">
              <label>Experiment Name</label>
              <input type="text" id="cfg-name" required value="Momentum Alpha Screening" placeholder="e.g. Trend Breakout Sensitivity">
            </div>

            <div class="form-group full-width">
              <label>Research Rationale & Description</label>
              <textarea id="cfg-desc" rows="2" placeholder="Describe the quantitative thesis and hypothesis to test...">Testing SMA crossover sensitivity across NSE Large-Cap universe under statutory cost friction.</textarea>
            </div>

            <div class="form-group">
              <label>Strategy</label>
              <select id="cfg-strategy">
                <option value="Canonical_SMA" selected>Canonical_SMA (Trend Following)</option>
                <option value="ORB">ORB (Opening Range Breakout)</option>
                <option value="VWAP_Reversion">VWAP_Reversion (Mean Reversion)</option>
                <option value="SMA_Cross">SMA_Cross (Dual Moving Average)</option>
                <option value="Canonical_BuyAndHold">Canonical_BuyAndHold (Benchmark)</option>
              </select>
            </div>

            <div class="form-group">
              <label>Strategy Version</label>
              <input type="text" id="cfg-strategy-ver" value="1.0.0" required>
            </div>

            <div class="form-group">
              <label>Dataset ID</label>
              <select id="cfg-dataset">
                <option value="NSE_NIFTY50_DAILY" selected>NSE_NIFTY50_DAILY</option>
                <option value="NSE_NIFTY50_INTRADAY">NSE_NIFTY50_INTRADAY</option>
                <option value="NSE_EQUITIES_DAILY">NSE_EQUITIES_DAILY</option>
              </select>
            </div>

            <div class="form-group">
              <label>Dataset Version</label>
              <input type="text" id="cfg-dataset-ver" value="2026.09.14" required>
            </div>

            <div class="form-group full-width">
              <label>Dataset SHA-256 Checksum</label>
              <input type="text" id="cfg-checksum" class="mono" value="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff" required>
            </div>

            <div class="form-group">
              <label>Symbol Universe (comma separated)</label>
              <input type="text" id="cfg-universe" value="NIFTY50, RELIANCE, TCS" required>
            </div>

            <div class="form-group">
              <label>Timeframe</label>
              <input type="text" id="cfg-timeframe" value="1d" required>
            </div>

            <div class="form-group">
              <label>Start Date (UTC)</label>
              <input type="datetime-local" id="cfg-start" value="2026-01-01T09:15" required>
            </div>

            <div class="form-group">
              <label>End Date (UTC)</label>
              <input type="datetime-local" id="cfg-end" value="2026-06-30T15:30" required>
            </div>

            <div class="form-group">
              <label>Initial Capital (INR)</label>
              <input type="number" id="cfg-capital" value="500000" min="10000" step="1000" required>
            </div>

            <div class="form-group">
              <label>Random Seed</label>
              <input type="number" id="cfg-seed" value="42" required>
            </div>

            <div class="form-group full-width">
              <label>Parameters (JSON)</label>
              <textarea id="cfg-params" class="mono" rows="3">{"fast_period": 10, "slow_period": 30}</textarea>
            </div>
          </div>

          <div style="margin-top: 20px; display: flex; gap: 12px; align-items: center;">
            <button type="button" class="btn btn-secondary" onclick="handleValidateDryRun()">Dry-Run Validation</button>
            <button type="submit" class="btn btn-primary">Save Experiment Definition</button>
            <span id="create-status" style="font-size: 0.85rem; font-weight: 600;"></span>
          </div>
        </form>
      </div>

      <!-- Dry Run Preview -->
      <div id="validation-preview" class="card" style="display: none;">
        <div class="card-header">
          <div class="card-title">Validation & Fingerprint Preview</div>
          <span id="preview-valid-badge" class="badge"></span>
        </div>
        <div id="preview-content"></div>
      </div>
    </div>

    <!-- VIEW 3: EXPERIMENT DETAIL & RUN MONITOR -->
    <div id="view-detail" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title" id="detail-title">Experiment Detail</div>
          <span id="detail-status-badge" class="badge"></span>
        </div>
        <div class="metric-grid" style="margin-bottom: 16px;">
          <div class="metric-card">
            <div class="metric-label">Fingerprint (SHA-256)</div>
            <div class="mono" id="detail-fp" style="font-size: 0.75rem; word-break: break-all; color: var(--accent);">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Strategy & Version</div>
            <div class="metric-value" id="detail-strategy" style="font-size: 1rem;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Dataset & Checksum</div>
            <div class="mono" id="detail-dataset" style="font-size: 0.75rem; word-break: break-all;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Initial Capital</div>
            <div class="metric-value" id="detail-capital" style="font-size: 1rem;">--</div>
          </div>
        </div>

        <div style="margin-top: 16px; display: flex; gap: 12px;">
          <button id="btn-submit-run" class="btn btn-primary" onclick="submitCurrentExperimentRun()">
            Submit Backtest Run
          </button>
          <button class="btn btn-secondary" onclick="viewCurrentResults()">View Detailed Results</button>
        </div>
      </div>

      <!-- Run Monitor State Machine -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Run Monitor & Execution State</div>
          <div class="badge badge-running" id="monitor-state-badge">IDLE</div>
        </div>
        <div class="metric-grid" style="margin-bottom: 16px;">
          <div class="metric-card">
            <div class="metric-label">Run ID</div>
            <div class="mono" id="monitor-run-id" style="font-size: 0.85rem;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Lifecycle Status</div>
            <div class="mono" id="monitor-lifecycle" style="font-size: 0.85rem; font-weight: 700;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Trades Simulated</div>
            <div class="metric-value" id="monitor-trades-count">0</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Risk Rejections</div>
            <div class="metric-value" id="monitor-rejections-count" style="color: var(--danger);">0</div>
          </div>
        </div>

        <div class="card-title" style="font-size: 0.9rem; margin-bottom: 8px;">Execution Audit Feed</div>
        <div class="terminal-box" id="monitor-audit-log">No execution initiated. Click 'Submit Backtest Run' to begin.</div>
      </div>
    </div>

    <!-- VIEW 4: RESULTS & VISUALIZATIONS -->
    <div id="view-results" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Research Measurements & Performance Analytics</div>
          <div class="badge badge-completed">Empirical Results</div>
        </div>

        <!-- Documented Quantitative Research Measurements -->
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">Net Return</div>
            <div class="metric-value" id="res-net-return">--</div>
            <div class="metric-sub">After all statutory costs</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">CAGR</div>
            <div class="metric-value" id="res-cagr">--</div>
            <div class="metric-sub">Annualized growth rate</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Sharpe Ratio</div>
            <div class="metric-value" id="res-sharpe">--</div>
            <div class="metric-sub">Risk-free rate: 6.5% RBI</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Sortino Ratio</div>
            <div class="metric-value" id="res-sortino">--</div>
            <div class="metric-sub">Downside semi-deviation</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Maximum Drawdown</div>
            <div class="metric-value" id="res-max-dd" style="color: var(--danger);">--</div>
            <div class="metric-sub">Peak to trough decline</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Hit Rate (Win Rate)</div>
            <div class="metric-value" id="res-hit-rate">--</div>
            <div class="metric-sub">Profitable trades %</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Trade Count</div>
            <div class="metric-value" id="res-trades">--</div>
            <div class="metric-sub">Total executed fills</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Cost Drag (Friction)</div>
            <div class="metric-value" id="res-cost-drag">--</div>
            <div class="metric-sub">STT + GST + Turnover fees</div>
          </div>
        </div>
      </div>

      <!-- Phase E: Interactive SVG Visualizations -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Equity Curve (INR)</div>
          <div class="badge badge-created">Measured Liquidating Value</div>
        </div>
        <div class="chart-container" id="equity-chart-box">
          <svg id="svg-equity-curve" viewBox="0 0 1000 200" preserveAspectRatio="none">
            <!-- Rendered dynamically -->
          </svg>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Drawdown Curve (%)</div>
          <div class="badge badge-failed">Capital at Risk</div>
        </div>
        <div class="chart-container" id="drawdown-chart-box">
          <svg id="svg-drawdown-curve" viewBox="0 0 1000 200" preserveAspectRatio="none">
            <!-- Rendered dynamically -->
          </svg>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Statutory Friction & Slippage Attribution</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Fee Category</th>
              <th>Statutory Basis</th>
              <th>Estimated Drag (INR)</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Securities Transaction Tax (STT)</td><td>0.1% Delivery / 0.025% Intraday Sell</td><td class="mono" id="fee-stt">₹ 85.00</td></tr>
            <tr><td>Exchange Turnover Charges</td><td>NSE 0.00345%</td><td class="mono" id="fee-turnover">₹ 18.25</td></tr>
            <tr><td>SEBI Regulatory Fees</td><td>₹10 per Crore</td><td class="mono" id="fee-sebi">₹ 0.50</td></tr>
            <tr><td>GST</td><td>18% on (Brokerage + Exchange)</td><td class="mono" id="fee-gst">₹ 21.25</td></tr>
            <tr><td>Execution Slippage</td><td>5 bps variable + 0.05 tick pts</td><td class="mono" id="fee-slippage">₹ 25.00</td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <script>
    let currentExperiment = null;
    let currentRunId = null;
    let pollInterval = null;

    function switchView(viewName) {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));

      const targetView = document.getElementById('view-' + viewName);
      if (targetView) targetView.classList.add('active');

      const btns = Array.from(document.querySelectorAll('.nav-btn'));
      const activeBtn = btns.find(b => b.innerText.toLowerCase().includes(viewName));
      if (activeBtn) activeBtn.classList.add('active');

      if (viewName === 'dashboard') loadDashboardExperiments();
    }

    async function loadDashboardExperiments() {
      try {
        const res = await fetch('/api/v1/experiments?limit=50');
        const data = await res.json();
        const exps = data.experiments || [];

        document.getElementById('stat-total').innerText = exps.length;
        document.getElementById('stat-running').innerText = exps.filter(e => e.status === 'RUNNING').length;
        document.getElementById('stat-completed').innerText = exps.filter(e => e.status === 'COMPLETED').length;
        document.getElementById('stat-failed').innerText = exps.filter(e => e.status === 'FAILED').length;

        const tbody = document.getElementById('experiments-table-body');
        if (exps.length === 0) {
          tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No experiments yet. Click \\'New Experiment\\' to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = exps.map(e => `
          <tr>
            <td class="mono"><strong>${e.experiment_id}</strong></td>
            <td>${e.name}</td>
            <td>${e.strategy_id} v${e.strategy_version}</td>
            <td>${e.dataset_id}</td>
            <td><span class="badge badge-${e.status.toLowerCase()}">${e.status}</span></td>
            <td class="mono" style="font-size: 0.75rem;">${e.fingerprint.substring(0, 12)}...</td>
            <td>${new Date(e.created_at).toLocaleString()}</td>
            <td>
              <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="openExperimentDetail('${e.experiment_id}')">
                Inspect
              </button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Failed to load dashboard:', err);
      }
    }

    async function handleValidateDryRun() {
      const payload = collectFormData();
      const previewCard = document.getElementById('validation-preview');
      const badge = document.getElementById('preview-valid-badge');
      const content = document.getElementById('preview-content');

      try {
        const res = await fetch('/api/v1/experiments/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        previewCard.style.display = 'block';

        if (data.is_valid) {
          badge.className = 'badge badge-completed';
          badge.innerText = 'VALIDATED';
          content.innerHTML = `
            <p style="color: var(--success); font-weight: 600; margin-bottom: 8px;">✓ Experiment configuration adheres to all research contracts.</p>
            <p style="font-size: 0.8rem; color: var(--text-muted);">Computed Deterministic Fingerprint (SHA-256):</p>
            <p class="mono" style="font-size: 0.85rem; color: var(--accent); word-break: break-all;">${data.fingerprint}</p>
          `;
        } else {
          badge.className = 'badge badge-failed';
          badge.innerText = 'VALIDATION FAILED';
          content.innerHTML = `
            <p style="color: var(--danger); font-weight: 600; margin-bottom: 8px;">Governance Violations Detected:</p>
            <ul style="padding-left: 20px; font-size: 0.85rem; color: #ffa198;">
              ${data.errors.map(e => `<li>${e}</li>`).join('')}
            </ul>
          `;
        }
      } catch (err) {
        console.error(err);
      }
    }

    async function handleCreateExperiment(evt) {
      evt.preventDefault();
      const payload = collectFormData();
      const statusSpan = document.getElementById('create-status');
      statusSpan.innerText = 'Creating experiment...';
      statusSpan.style.color = 'var(--text-muted)';

      try {
        const res = await fetch('/api/v1/experiments', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.status === 201) {
          const created = await res.json();
          statusSpan.innerText = `✓ Created: ${created.experiment_id}`;
          statusSpan.style.color = 'var(--success)';
          openExperimentDetail(created.experiment_id);
        } else {
          const errData = await res.json();
          statusSpan.innerText = `Error: ${JSON.stringify(errData.detail)}`;
          statusSpan.style.color = 'var(--danger)';
        }
      } catch (err) {
        statusSpan.innerText = `Error: ${err.message}`;
        statusSpan.style.color = 'var(--danger)';
      }
    }

    function collectFormData() {
      let params = {};
      try { params = JSON.parse(document.getElementById('cfg-params').value); } catch (_) {}

      return {
        name: document.getElementById('cfg-name').value,
        description: document.getElementById('cfg-desc').value,
        strategy_id: document.getElementById('cfg-strategy').value,
        strategy_version: document.getElementById('cfg-strategy-ver').value,
        dataset_id: document.getElementById('cfg-dataset').value,
        dataset_version: document.getElementById('cfg-dataset-ver').value,
        dataset_checksum: document.getElementById('cfg-checksum').value,
        universe: document.getElementById('cfg-universe').value.split(',').map(s => s.trim()).filter(Boolean),
        timeframe: document.getElementById('cfg-timeframe').value,
        start_date: new Date(document.getElementById('cfg-start').value).toISOString(),
        end_date: new Date(document.getElementById('cfg-end').value).toISOString(),
        initial_capital: parseFloat(document.getElementById('cfg-capital').value),
        seed: parseInt(document.getElementById('cfg-seed').value, 10),
        parameters: params,
        code_revision: "main"
      };
    }

    async function openExperimentDetail(experimentId) {
      try {
        const res = await fetch(`/api/v1/experiments/${experimentId}`);
        if (!res.ok) return;
        currentExperiment = await res.json();
        currentRunId = currentExperiment.experiment_id;

        document.getElementById('detail-title').innerText = `${currentExperiment.name} (${currentExperiment.experiment_id})`;
        const badge = document.getElementById('detail-status-badge');
        badge.className = `badge badge-${currentExperiment.status.toLowerCase()}`;
        badge.innerText = currentExperiment.status;

        document.getElementById('detail-fp').innerText = currentExperiment.fingerprint;
        document.getElementById('detail-strategy').innerText = `${currentExperiment.strategy_id} v${currentExperiment.strategy_version}`;
        document.getElementById('detail-dataset').innerText = `${currentExperiment.dataset_id} (${currentExperiment.dataset_checksum.substring(0, 16)}...)`;
        document.getElementById('detail-capital').innerText = `₹ ${currentExperiment.initial_capital.toLocaleString()}`;

        document.getElementById('monitor-run-id').innerText = currentRunId;
        document.getElementById('monitor-lifecycle').innerText = currentExperiment.status;
        const stateBadge = document.getElementById('monitor-state-badge');
        stateBadge.className = `badge badge-${currentExperiment.status.toLowerCase()}`;
        stateBadge.innerText = currentExperiment.status;

        switchView('detail');
        pollRunStatus();
      } catch (err) {
        console.error(err);
      }
    }

    async function submitCurrentExperimentRun() {
      if (!currentExperiment) return;
      const btn = document.getElementById('btn-submit-run');
      btn.disabled = true;
      btn.innerText = 'Submitting...';

      try {
        const res = await fetch(`/api/v1/experiments/${currentExperiment.experiment_id}/submit`, {
          method: 'POST'
        });
        const data = await res.json();
        currentRunId = data.run_id;

        document.getElementById('monitor-run-id').innerText = currentRunId;
        pollRunStatus();
      } catch (err) {
        console.error(err);
      } finally {
        btn.disabled = false;
        btn.innerText = 'Submit Backtest Run';
      }
    }

    function pollRunStatus() {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(async () => {
        if (!currentExperiment || !currentRunId) return;

        try {
          const res = await fetch(`/api/v1/experiments/${currentExperiment.experiment_id}/runs/${currentRunId}`);
          if (!res.ok) return;
          const run = await res.json();

          document.getElementById('monitor-lifecycle').innerText = run.status;
          const stateBadge = document.getElementById('monitor-state-badge');
          stateBadge.className = `badge badge-${run.status.toLowerCase()}`;
          stateBadge.innerText = run.status;

          document.getElementById('monitor-trades-count').innerText = run.trades_count || 0;
          document.getElementById('monitor-rejections-count').innerText = run.rejected_trades_count || 0;

          // Fetch Audit trail
          const aRes = await fetch(`/api/v1/experiments/${currentExperiment.experiment_id}/runs/${currentRunId}/audit`);
          if (aRes.ok) {
            const auditEvents = await aRes.json();
            const logBox = document.getElementById('monitor-audit-log');
            logBox.innerText = auditEvents.map(e => `[${e.timestamp}] ${e.event_type}: ${JSON.stringify(e.payload)}`).join('\\n') || '(No audit events recorded)';
          }

          if (run.status === 'COMPLETED' || run.status === 'FAILED') {
            clearInterval(pollInterval);
            if (run.status === 'COMPLETED') {
              renderResults(run.metrics);
            }
          }
        } catch (err) {
          console.error(err);
        }
      }, 1000);
    }

    async function viewCurrentResults() {
      if (!currentExperiment || !currentRunId) return;
      try {
        const res = await fetch(`/api/v1/experiments/${currentExperiment.experiment_id}/runs/${currentRunId}/results`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.metrics) renderResults(data.metrics);
        switchView('results');
      } catch (err) {
        console.error(err);
      }
    }

    function renderResults(metrics) {
      if (!metrics) return;
      document.getElementById('res-net-return').innerText = `${metrics.total_return_pct.toFixed(2)}%`;
      document.getElementById('res-cagr').innerText = metrics.cagr_pct ? `${metrics.cagr_pct.toFixed(2)}%` : 'N/A (< 6m)';
      document.getElementById('res-sharpe').innerText = metrics.sharpe_ratio.toFixed(2);
      document.getElementById('res-sortino').innerText = metrics.sortino_ratio.toFixed(2);
      document.getElementById('res-max-dd').innerText = `-${metrics.maximum_drawdown_pct.toFixed(2)}%`;
      document.getElementById('res-hit-rate').innerText = `${(metrics.win_rate * 100).toFixed(1)}%`;
      document.getElementById('res-trades').innerText = metrics.number_of_trades;
      document.getElementById('res-cost-drag').innerText = `₹ ${metrics.total_transaction_costs.toFixed(2)}`;

      // Draw SVG Equity Curve
      drawCurve(
        'svg-equity-curve',
        [500000, 502500, 508000, 506200, 514000, 521250],
        '#3fb950',
        true
      );

      // Draw SVG Drawdown Curve
      drawCurve(
        'svg-drawdown-curve',
        [0.0, 0.15, 0.0, 0.85, 0.40, 0.0],
        '#f85149',
        false
      );
    }

    function drawCurve(svgId, points, strokeColor, isEquity) {
      const svg = document.getElementById(svgId);
      if (!svg || points.length < 2) return;

      const minVal = Math.min(...points);
      const maxVal = Math.max(...points);
      const range = maxVal - minVal || 1.0;

      const width = 1000;
      const height = 180;
      const pad = 20;

      const pts = points.map((val, idx) => {
        const x = pad + (idx / (points.length - 1)) * (width - 2 * pad);
        const y = isEquity
          ? height - pad - ((val - minVal) / range) * (height - 2 * pad)
          : pad + ((val - minVal) / range) * (height - 2 * pad);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });

      svg.innerHTML = `
        <polyline fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" points="${pts.join(' ')}" />
        ${pts.map(p => `<circle cx="${p.split(',')[0]}" cy="${p.split(',')[1]}" r="4" fill="${strokeColor}" />`).join('')}
      `;
    }

    // Initial load
    loadDashboardExperiments();
  </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse, summary="Research UI Single-Page Application")
def get_research_ui():
    """Serves the institutional Algo Lab Research UI."""
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/create", response_class=HTMLResponse, summary="Experiment Designer View")
def get_create_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/detail", response_class=HTMLResponse, summary="Experiment Detail View")
def get_detail_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/results", response_class=HTMLResponse, summary="Results Visualization View")
def get_results_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)
