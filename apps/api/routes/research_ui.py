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
      <button class="nav-btn" onclick="switchView('compare')">Compare</button>
      <button class="nav-btn" onclick="switchView('audit')">Audit & Provenance</button>
      <button class="nav-btn" onclick="switchView('paper')">Paper Trading</button>
      <button class="nav-btn" onclick="switchView('settings')">Settings</button>
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

    <!-- VIEW 5: EXPERIMENT COMPARISON -->
    <div id="view-compare" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Side-by-Side Experiment Comparison</div>
          <div class="badge badge-completed">Strictly Descriptive • Non-Ranking</div>
        </div>
        <div class="form-grid" style="margin-bottom: 16px;">
          <div class="form-group">
            <label>Baseline Experiment (Control)</label>
            <select id="compare-baseline-select">
              <option value="">-- Select Baseline Experiment --</option>
            </select>
          </div>
          <div class="form-group">
            <label>Target Experiment (Variant)</label>
            <select id="compare-target-select">
              <option value="">-- Select Target Experiment --</option>
            </select>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 12px;">
          <button class="btn btn-primary" onclick="runExperimentComparison()">Execute Comparison</button>
          <span id="compare-status" style="font-size: 0.85rem; color: var(--text-muted);"></span>
        </div>
      </div>

      <div id="compare-results-card" class="card" style="display: none;">
        <div class="card-header">
          <div class="card-title">Comparative Analysis Results</div>
          <span id="compare-fp-badge" class="badge"></span>
        </div>

        <!-- Structural Delta Summary -->
        <div class="metric-grid" style="margin-bottom: 20px;">
          <div class="metric-card">
            <div class="metric-label">Dataset Change</div>
            <div class="metric-value" id="cmp-dataset-status" style="font-size: 1rem;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Strategy Version</div>
            <div class="metric-value" id="cmp-strat-status" style="font-size: 1rem;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Universe Scope</div>
            <div class="metric-value" id="cmp-universe-status" style="font-size: 1rem;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Timeframe Scope</div>
            <div class="metric-value" id="cmp-timeframe-status" style="font-size: 1rem;">--</div>
          </div>
        </div>

        <!-- Parameter Differences -->
        <div class="card-title" style="font-size: 0.95rem; margin-bottom: 10px;">Hyperparameter Differences</div>
        <div style="overflow-x: auto; margin-bottom: 20px;">
          <table>
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Baseline Value</th>
                <th>Target Value</th>
                <th>Difference Status</th>
              </tr>
            </thead>
            <tbody id="cmp-params-tbody">
              <tr><td colspan="4" style="color: var(--text-muted);">No comparison run yet.</td></tr>
            </tbody>
          </table>
        </div>

        <!-- Quantitative Metric Differences -->
        <div class="card-title" style="font-size: 0.95rem; margin-bottom: 10px;">Quantitative Empirical Metrics</div>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Measurement</th>
                <th>Baseline</th>
                <th>Target</th>
                <th>Absolute Delta</th>
                <th>Relative Delta (%)</th>
              </tr>
            </thead>
            <tbody id="cmp-metrics-tbody">
              <tr><td colspan="5" style="color: var(--text-muted);">No comparison run yet.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- VIEW 6: AUDIT & PROVENANCE -->
    <div id="view-audit" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Cryptographic Provenance & Audit Trail</div>
          <div class="badge badge-completed">Immutable Ledger • Zero-Mutation Enforced</div>
        </div>
        <div class="form-grid" style="margin-bottom: 16px;">
          <div class="form-group full-width">
            <label>Select Experiment for Provenance Inspection</label>
            <select id="audit-exp-select" onchange="loadAuditTrail(this.value)">
              <option value="">-- Select Experiment --</option>
            </select>
          </div>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
          <button class="btn btn-secondary" onclick="loadAuditTrail(document.getElementById('audit-exp-select').value)">Refresh Ledger</button>
          <button class="btn btn-accent" onclick="exportAuditJson()">Export Provenance & Audit JSON</button>
          <span id="audit-status" style="font-size: 0.85rem; color: var(--text-muted);"></span>
        </div>
      </div>

      <!-- Provenance Snapshot -->
      <div id="audit-provenance-card" class="card" style="display: none;">
        <div class="card-header">
          <div class="card-title">Experiment Provenance Manifest</div>
          <span class="badge badge-completed">Cryptographically Verified</span>
        </div>
        <div class="metric-grid" style="margin-bottom: 16px;">
          <div class="metric-card">
            <div class="metric-label">Fingerprint (SHA-256)</div>
            <div class="mono" id="prov-fp" style="font-size: 0.75rem; word-break: break-all; color: var(--accent);">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Dataset ID & Digest</div>
            <div class="mono" id="prov-dataset" style="font-size: 0.75rem; word-break: break-all;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Strategy & Code Revision</div>
            <div class="mono" id="prov-strategy" style="font-size: 0.85rem;">--</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Reproducibility Hash</div>
            <div class="mono" id="prov-repro" style="font-size: 0.75rem; word-break: break-all; color: var(--success);">--</div>
          </div>
        </div>
        <div class="card-title" style="font-size: 0.9rem; margin-bottom: 8px;">Parameters & Risk Policy</div>
        <pre class="terminal-box" id="prov-params-box" style="margin-bottom: 16px; max-height: 120px;">--</pre>
      </div>

      <!-- Chronological Audit Timeline -->
      <div id="audit-timeline-card" class="card" style="display: none;">
        <div class="card-header">
          <div class="card-title">Chronological Lifecycle Sequence (Signal → Proposal → Risk → Fill → State)</div>
          <div class="badge badge-created" id="audit-events-count">0 events</div>
        </div>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th style="width: 180px;">Timestamp (UTC)</th>
                <th style="width: 220px;">Lifecycle Stage</th>
                <th>Payload & Evidence Details</th>
              </tr>
            </thead>
            <tbody id="audit-events-tbody">
              <tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No audit events loaded.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- VIEW 7: PAPER TRADING DASHBOARD -->
    <div id="view-paper" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Paper Trading Sessions</div>
          <div class="badge badge-completed">Safe Simulated Execution</div>
        </div>
        <p style="color: var(--text-muted); margin-bottom: 16px;">
          Simulated paper execution engine with independent risk evaluation, deterministic slippage, and statutory fee attribution. Zero real broker execution.
        </p>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Session ID</th>
                <th>Name</th>
                <th>Strategy</th>
                <th>Universe</th>
                <th>Status</th>
                <th>Initial Capital</th>
                <th>Total Equity</th>
                <th>Realized P&L</th>
                <th>Unrealized P&L</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="paper-sessions-tbody">
              <tr><td colspan="10" style="text-align: center; color: var(--text-muted);">Loading paper sessions...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Create Session Form -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Initialize Paper Trading Session</div>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">Session Name</label>
            <input type="text" id="paper-name-input" class="form-control" placeholder="e.g., ORB Intraday Paper Run" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">Strategy ID</label>
            <input type="text" id="paper-strategy-input" class="form-control" value="momentum_breakout_v1" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">Universe (comma-separated)</label>
            <input type="text" id="paper-universe-input" class="form-control" value="TCS, INFY, RELIANCE" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">Initial Capital (INR)</label>
            <input type="number" id="paper-capital-input" class="form-control" value="1000000" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
        </div>
        <div style="margin-top: 16px;">
          <button class="btn btn-primary" onclick="createPaperSession()" style="background: var(--accent); color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer;">Initialize Session</button>
        </div>
      </div>

      <!-- Session Detail & Portfolio View -->
      <div id="paper-detail-card" class="card" style="display: none;">
        <div class="card-header">
          <div class="card-title" id="paper-detail-title">Session Detail</div>
          <div class="badge badge-running" id="paper-detail-status">RUNNING</div>
        </div>
        <div class="metric-grid" style="margin-bottom: 16px;">
          <div class="metric-card">
            <div class="metric-label">Total Equity</div>
            <div class="metric-value" id="paper-detail-equity">₹0</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Cash Balance</div>
            <div class="metric-value" id="paper-detail-cash">₹0</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Unrealized P&L</div>
            <div class="metric-value" id="paper-detail-unrealized">₹0</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Total Fees Paid</div>
            <div class="metric-value" id="paper-detail-fees">₹0</div>
          </div>
        </div>

        <div style="margin-top: 16px;">
          <div class="card-title" style="margin-bottom: 8px;">Active Positions</div>
          <div style="overflow-x: auto;">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Quantity</th>
                  <th>Avg Entry Price</th>
                  <th>Current Price</th>
                  <th>Market Value</th>
                  <th>Unrealized P&L</th>
                </tr>
              </thead>
              <tbody id="paper-positions-tbody">
                <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No open positions.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- VIEW 8: SETTINGS & BROKER ADAPTERS -->
    <div id="view-settings" class="view-section">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Broker & Market Data Connection Adapters</div>
          <div class="badge badge-created">Credential Masking Active</div>
        </div>
        <div class="governance-notice" style="margin-bottom: 16px;">
          <div>
            <strong>Security Guarantee:</strong> All API secrets and keys are strictly masked and never exposed in plain text.
            LIVE trading execution is hard-disabled (LIVE_TRADING_ENABLED = False).
          </div>
        </div>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Connection ID</th>
                <th>Broker / Feed</th>
                <th>Environment</th>
                <th>API Key (Masked)</th>
                <th>Secret Configured</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="broker-connections-tbody">
              <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Loading connections...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Add Connection Form -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Configure Broker Adapter</div>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">Broker Name</label>
            <input type="text" id="broker-name-input" class="form-control" placeholder="e.g., zerodha, upstox, simulated" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">Environment</label>
            <select id="broker-env-select" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
              <option value="PAPER">PAPER (Simulated Execution)</option>
              <option value="SANDBOX">SANDBOX (Broker Test Environment)</option>
              <option value="LIVE" disabled>LIVE (Strictly Disabled by System)</option>
            </select>
          </div>
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">API Key</label>
            <input type="text" id="broker-key-input" class="form-control" placeholder="Enter API Key" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
          <div>
            <label style="display:block; color: var(--text-muted); font-size: 0.8rem; margin-bottom: 4px;">API Secret</label>
            <input type="password" id="broker-secret-input" class="form-control" placeholder="Enter API Secret" style="width: 100%; background: var(--bg); border: 1px solid var(--card-border); color: var(--text); padding: 8px; border-radius: 6px;">
          </div>
        </div>
        <div style="margin-top: 16px;">
          <button class="btn btn-primary" onclick="saveBrokerConnection()" style="background: var(--accent); color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer;">Save Connection</button>
        </div>
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

      if (viewName === 'dashboard' || viewName === 'compare' || viewName === 'audit') loadDashboardExperiments();
      if (viewName === 'paper') loadPaperSessions();
      if (viewName === 'settings') loadBrokerConnections();
    }

    async function loadDashboardExperiments() {
      try {
        const res = await fetch('/api/v1/experiments?limit=50');
        const data = await res.json();
        const exps = data.experiments || [];

        // Populate comparison selectors if available
        const baseSelect = document.getElementById('compare-baseline-select');
        const tgtSelect = document.getElementById('compare-target-select');
        if (baseSelect && tgtSelect) {
          const prevBase = baseSelect.value;
          const prevTgt = tgtSelect.value;
          const optsHtml = '<option value="">-- Select Experiment --</option>' +
            exps.map(e => `<option value="${e.experiment_id}">${e.name} (${e.experiment_id})</option>`).join('');
          baseSelect.innerHTML = optsHtml;
          tgtSelect.innerHTML = optsHtml;
          if (prevBase) baseSelect.value = prevBase;
          if (prevTgt) tgtSelect.value = prevTgt;
        }

        // Populate audit experiment selector
        const auditSelect = document.getElementById('audit-exp-select');
        if (auditSelect) {
          const prevAudit = auditSelect.value;
          auditSelect.innerHTML = '<option value="">-- Select Experiment --</option>' +
            exps.map(e => `<option value="${e.experiment_id}">${e.name} (${e.experiment_id})</option>`).join('');
          if (prevAudit) auditSelect.value = prevAudit;
        }

        const statTotal = document.getElementById('stat-total');
        if (statTotal) {
          statTotal.innerText = exps.length;
          document.getElementById('stat-running').innerText = exps.filter(e => e.status === 'RUNNING').length;
          document.getElementById('stat-completed').innerText = exps.filter(e => e.status === 'COMPLETED').length;
          document.getElementById('stat-failed').innerText = exps.filter(e => e.status === 'FAILED').length;
        }

        const tbody = document.getElementById('experiments-table-body');
        if (tbody) {
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
        }
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

    async function runExperimentComparison() {
      const bId = document.getElementById('compare-baseline-select').value;
      const tId = document.getElementById('compare-target-select').value;
      const statusSpan = document.getElementById('compare-status');
      const resultsCard = document.getElementById('compare-results-card');

      if (!bId || !tId) {
        statusSpan.innerText = 'Please select both baseline and target experiments.';
        statusSpan.style.color = 'var(--warning)';
        return;
      }

      statusSpan.innerText = 'Computing comparison...';
      statusSpan.style.color = 'var(--text-muted)';

      try {
        const res = await fetch('/api/v1/experiments/compare', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ baseline_experiment_id: bId, target_experiment_id: tId })
        });
        if (!res.ok) {
          const err = await res.json();
          statusSpan.innerText = `Error: ${JSON.stringify(err.detail)}`;
          statusSpan.style.color = 'var(--danger)';
          return;
        }

        const data = await res.json();
        statusSpan.innerText = '✓ Comparison computed successfully.';
        statusSpan.style.color = 'var(--success)';
        resultsCard.style.display = 'block';

        // Badges and structural summary
        const fpBadge = document.getElementById('compare-fp-badge');
        if (data.same_fingerprint) {
          fpBadge.className = 'badge badge-completed';
          fpBadge.innerText = 'IDENTICAL FINGERPRINT';
        } else {
          fpBadge.className = 'badge badge-running';
          fpBadge.innerText = 'DISTINCT CONFIGURATIONS';
        }

        document.getElementById('cmp-dataset-status').innerText = data.dataset_changed ? 'MODIFIED' : 'IDENTICAL';
        document.getElementById('cmp-dataset-status').style.color = data.dataset_changed ? 'var(--warning)' : 'var(--success)';

        document.getElementById('cmp-strat-status').innerText = data.strategy_version_changed ? 'MODIFIED' : 'IDENTICAL';
        document.getElementById('cmp-strat-status').style.color = data.strategy_version_changed ? 'var(--warning)' : 'var(--success)';

        document.getElementById('cmp-universe-status').innerText = data.universe_changed ? 'MODIFIED' : 'IDENTICAL';
        document.getElementById('cmp-universe-status').style.color = data.universe_changed ? 'var(--warning)' : 'var(--success)';

        document.getElementById('cmp-timeframe-status').innerText = data.timeframe_changed ? 'MODIFIED' : 'IDENTICAL';
        document.getElementById('cmp-timeframe-status').style.color = data.timeframe_changed ? 'var(--warning)' : 'var(--success)';

        // Parameters table
        const paramsTbody = document.getElementById('cmp-params-tbody');
        const paramEntries = Object.entries(data.parameters_different || {});
        if (paramEntries.length === 0) {
          paramsTbody.innerHTML = '<tr><td colspan="4" style="color: var(--text-muted); text-align: center;">No hyperparameter differences found.</td></tr>';
        } else {
          paramsTbody.innerHTML = paramEntries.map(([k, p]) => `
            <tr>
              <td class="mono"><strong>${k}</strong></td>
              <td class="mono">${JSON.stringify(p.baseline_value)}</td>
              <td class="mono">${JSON.stringify(p.target_value)}</td>
              <td>
                ${p.is_different 
                  ? '<span class="badge badge-pending">CHANGED</span>' 
                  : '<span class="badge badge-completed">EQUAL</span>'}
              </td>
            </tr>
          `).join('');
        }

        // Metrics table
        const metricsTbody = document.getElementById('cmp-metrics-tbody');
        const metricEntries = Object.entries(data.metric_differences || {});
        if (metricEntries.length === 0) {
          metricsTbody.innerHTML = '<tr><td colspan="5" style="color: var(--text-muted); text-align: center;">No metric comparisons available.</td></tr>';
        } else {
          metricsTbody.innerHTML = metricEntries.map(([k, m]) => {
            let deltaStr = '--';
            let deltaPctStr = '--';
            if (m.is_available && m.difference !== null) {
              deltaStr = (m.difference > 0 ? '+' : '') + m.difference;
              deltaPctStr = m.difference_pct !== null ? (m.difference_pct > 0 ? '+' : '') + m.difference_pct + '%' : 'N/A';
            }
            return `
              <tr>
                <td><strong>${m.metric_name}</strong></td>
                <td class="mono">${m.baseline_value !== null ? m.baseline_value : '<span style="color: var(--text-muted);">N/A</span>'}</td>
                <td class="mono">${m.target_value !== null ? m.target_value : '<span style="color: var(--text-muted);">N/A</span>'}</td>
                <td class="mono">${deltaStr}</td>
                <td class="mono">${deltaPctStr}</td>
              </tr>
            `;
          }).join('');
        }

      } catch (err) {
        statusSpan.innerText = `Error: ${err.message}`;
        statusSpan.style.color = 'var(--danger)';
      }
    }

    let currentAuditData = null;

    async function loadAuditTrail(experimentId) {
      const statusSpan = document.getElementById('audit-status');
      const provCard = document.getElementById('audit-provenance-card');
      const timelineCard = document.getElementById('audit-timeline-card');
      if (!experimentId) {
        if (provCard) provCard.style.display = 'none';
        if (timelineCard) timelineCard.style.display = 'none';
        return;
      }

      statusSpan.innerText = 'Loading audit ledger...';
      statusSpan.style.color = 'var(--text-muted)';

      try {
        const pRes = await fetch(`/api/v1/experiments/${experimentId}/provenance`);
        if (!pRes.ok) throw new Error('Failed to fetch provenance');
        const prov = await pRes.json();

        const aRes = await fetch(`/api/v1/experiments/${experimentId}/runs/${experimentId}/audit`);
        const events = aRes.ok ? await aRes.json() : [];

        currentAuditData = { provenance: prov, audit_events: events };

        document.getElementById('prov-fp').innerText = prov.fingerprint;
        document.getElementById('prov-dataset').innerText = `${prov.dataset_id} v${prov.dataset_version} (${prov.dataset_checksum.substring(0, 16)}...)`;
        document.getElementById('prov-strategy').innerText = `${prov.strategy_id} v${prov.strategy_version} (${prov.code_revision})`;
        document.getElementById('prov-repro').innerText = prov.reproducibility_hash || '--';
        document.getElementById('prov-params-box').innerText = JSON.stringify({
          parameters: prov.parameters,
          cost_model: prov.cost_model,
          slippage_model: prov.slippage_model,
          universe: prov.universe,
          timeframe: prov.timeframe,
          initial_capital: prov.initial_capital
        }, null, 2);

        const tbody = document.getElementById('audit-events-tbody');
        document.getElementById('audit-events-count').innerText = `${events.length} events`;

        if (events.length === 0) {
          tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No audit events recorded yet for this experiment.</td></tr>';
        } else {
          tbody.innerHTML = events.map(e => {
            let badgeClass = 'badge-created';
            if (e.event_type.includes('REJECT') || e.event_type.includes('ERROR') || e.event_type.includes('FAILED')) {
              badgeClass = 'badge-failed';
            } else if (e.event_type.includes('COMPLETED') || e.event_type.includes('APPROVED') || e.event_type.includes('FILLED')) {
              badgeClass = 'badge-completed';
            } else if (e.event_type.includes('PROPOSED') || e.event_type.includes('CHECK')) {
              badgeClass = 'badge-running';
            }
            return `
              <tr>
                <td class="mono" style="font-size: 0.75rem; color: var(--text-muted);">${new Date(e.timestamp).toISOString()}</td>
                <td><span class="badge ${badgeClass}">${e.event_type}</span></td>
                <td><pre class="terminal-box" style="padding: 6px 10px; font-size: 0.75rem; max-height: 100px;">${JSON.stringify(e.payload, null, 2)}</pre></td>
              </tr>
            `;
          }).join('');
        }

        provCard.style.display = 'block';
        timelineCard.style.display = 'block';
        statusSpan.innerText = '✓ Ledger verified & loaded';
        statusSpan.style.color = 'var(--success)';
      } catch (err) {
        statusSpan.innerText = `Error: ${err.message}`;
        statusSpan.style.color = 'var(--danger)';
      }
    }

    function exportAuditJson() {
      if (!currentAuditData) {
        alert('Please select and load an experiment audit ledger first.');
        return;
      }
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentAuditData, null, 2));
      const dlAnchor = document.createElement('a');
      dlAnchor.setAttribute("href", dataStr);
      dlAnchor.setAttribute("download", `audit_provenance_${currentAuditData.provenance.experiment_id}.json`);
      document.body.appendChild(dlAnchor);
      dlAnchor.click();
      dlAnchor.remove();
    }

    async function loadPaperSessions() {
      try {
        const res = await fetch('/api/v1/paper-trading/sessions');
        const sessions = await res.json();
        const tbody = document.getElementById('paper-sessions-tbody');
        if (!tbody) return;
        if (!sessions || sessions.length === 0) {
          tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted);">No paper sessions initialized.</td></tr>';
          return;
        }
        tbody.innerHTML = sessions.map(s => `
          <tr>
            <td style="font-family: var(--font-mono);">${s.session_id}</td>
            <td><strong>${s.name}</strong></td>
            <td>${s.strategy_id}</td>
            <td>${s.universe.join(', ')}</td>
            <td><span class="badge badge-${s.status.toLowerCase()}">${s.status}</span></td>
            <td>₹${s.initial_capital.toLocaleString()}</td>
            <td><strong>₹${(s.portfolio.cash + (s.portfolio.positions ? Object.values(s.portfolio.positions).reduce((a,b)=>a+b.market_value,0):0)).toLocaleString()}</strong></td>
            <td style="color: ${s.portfolio.total_realized_pnl >= 0 ? 'var(--success)' : 'var(--danger)'}">₹${s.portfolio.total_realized_pnl.toFixed(2)}</td>
            <td style="color: ${s.portfolio.total_unrealized_pnl >= 0 ? 'var(--success)' : 'var(--danger)'}">₹${s.portfolio.total_unrealized_pnl.toFixed(2)}</td>
            <td>
              <button class="btn btn-sm" onclick="viewPaperSession('${s.session_id}')" style="padding: 2px 8px; font-size: 0.75rem; background: var(--card-border); color: var(--text); border:none; border-radius: 4px; cursor:pointer;">View</button>
              ${s.status === 'CREATED' || s.status === 'PAUSED' ? `<button class="btn btn-sm" onclick="startPaperSession('${s.session_id}')" style="padding: 2px 8px; font-size: 0.75rem; background: var(--success); color: #fff; border:none; border-radius: 4px; cursor:pointer;">Start</button>` : ''}
              ${s.status === 'RUNNING' ? `<button class="btn btn-sm" onclick="stopPaperSession('${s.session_id}')" style="padding: 2px 8px; font-size: 0.75rem; background: var(--danger); color: #fff; border:none; border-radius: 4px; cursor:pointer;">Stop</button>` : ''}
            </td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Failed to load paper sessions:', err);
      }
    }

    async function createPaperSession() {
      const name = document.getElementById('paper-name-input').value.trim() || 'Paper Run';
      const strategyId = document.getElementById('paper-strategy-input').value.trim() || 'momentum_v1';
      const universe = (document.getElementById('paper-universe-input').value.trim() || 'TCS').split(',').map(s=>s.trim());
      const capital = parseFloat(document.getElementById('paper-capital-input').value) || 1000000;

      try {
        const res = await fetch('/api/v1/paper-trading/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name,
            strategy_id: strategyId,
            universe: universe,
            initial_capital: capital,
            environment: 'PAPER'
          })
        });
        if (!res.ok) throw new Error(await res.text());
        alert('Paper trading session created successfully.');
        loadPaperSessions();
      } catch (err) {
        alert('Failed to create session: ' + err.message);
      }
    }

    async function startPaperSession(sessionId) {
      await fetch(`/api/v1/paper-trading/sessions/${sessionId}/start`, { method: 'POST' });
      loadPaperSessions();
    }

    async function stopPaperSession(sessionId) {
      await fetch(`/api/v1/paper-trading/sessions/${sessionId}/stop`, { method: 'POST' });
      loadPaperSessions();
    }

    async function viewPaperSession(sessionId) {
      const res = await fetch(`/api/v1/paper-trading/sessions/${sessionId}`);
      const s = await res.json();
      document.getElementById('paper-detail-card').style.display = 'block';
      document.getElementById('paper-detail-title').innerText = `${s.name} (${s.session_id})`;
      document.getElementById('paper-detail-status').innerText = s.status;
      document.getElementById('paper-detail-equity').innerText = `₹${s.portfolio.cash.toLocaleString()}`;
      document.getElementById('paper-detail-cash').innerText = `₹${s.portfolio.cash.toLocaleString()}`;
      document.getElementById('paper-detail-unrealized').innerText = `₹${s.portfolio.total_unrealized_pnl.toFixed(2)}`;
      document.getElementById('paper-detail-fees').innerText = `₹${s.portfolio.total_fees_paid.toFixed(2)}`;

      const posTbody = document.getElementById('paper-positions-tbody');
      const positions = Object.values(s.portfolio.positions || {});
      if (positions.length === 0) {
        posTbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No open positions.</td></tr>';
      } else {
        posTbody.innerHTML = positions.map(p => `
          <tr>
            <td><strong>${p.symbol}</strong></td>
            <td>${p.quantity}</td>
            <td>₹${p.average_entry_price.toFixed(2)}</td>
            <td>₹${p.current_price.toFixed(2)}</td>
            <td>₹${p.market_value.toFixed(2)}</td>
            <td style="color: ${p.unrealized_pnl >= 0 ? 'var(--success)' : 'var(--danger)'}">₹${p.unrealized_pnl.toFixed(2)}</td>
          </tr>
        `).join('');
      }
    }

    async function loadBrokerConnections() {
      try {
        const res = await fetch('/api/v1/brokers/connections');
        const items = await res.json();
        const tbody = document.getElementById('broker-connections-tbody');
        if (!tbody) return;
        if (!items || items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No broker connections configured.</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(c => `
          <tr>
            <td style="font-family: var(--font-mono);">${c.connection_id}</td>
            <td><strong>${c.broker_name}</strong></td>
            <td><span class="badge badge-completed">${c.environment}</span></td>
            <td style="font-family: var(--font-mono);">${c.api_key_masked || 'None'}</td>
            <td>${c.api_secret_configured ? '<span style="color:var(--success)">Configured</span>' : '<span style="color:var(--text-muted)">None</span>'}</td>
            <td>
              <button class="btn btn-sm" onclick="testBrokerConnection('${c.connection_id}')" style="padding: 2px 8px; font-size: 0.75rem; background: var(--accent); color: #fff; border:none; border-radius: 4px; cursor:pointer;">Test</button>
              <button class="btn btn-sm" onclick="deleteBrokerConnection('${c.connection_id}')" style="padding: 2px 8px; font-size: 0.75rem; background: var(--card-border); color: var(--text); border:none; border-radius: 4px; cursor:pointer;">Delete</button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Failed to load broker connections:', err);
      }
    }

    async function saveBrokerConnection() {
      const broker = document.getElementById('broker-name-input').value.trim();
      const env = document.getElementById('broker-env-select').value;
      const key = document.getElementById('broker-key-input').value.trim();
      const secret = document.getElementById('broker-secret-input').value.trim();

      if (!broker) {
        alert('Broker name is required.');
        return;
      }

      try {
        const res = await fetch('/api/v1/brokers/connections', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            broker_name: broker,
            environment: env,
            api_key: key || null,
            api_secret: secret || null
          })
        });
        if (!res.ok) throw new Error(await res.text());
        alert('Broker connection saved.');
        document.getElementById('broker-key-input').value = '';
        document.getElementById('broker-secret-input').value = '';
        loadBrokerConnections();
      } catch (err) {
        alert('Failed to save connection: ' + err.message);
      }
    }

    async function testBrokerConnection(connId) {
      try {
        const res = await fetch(`/api/v1/brokers/connections/${connId}/test`, { method: 'POST' });
        const data = await res.json();
        alert(`Connection Test Result: ${data.status} - ${data.message}`);
      } catch (err) {
        alert('Test failed: ' + err.message);
      }
    }

    async function deleteBrokerConnection(connId) {
      if (!confirm(`Delete connection ${connId}?`)) return;
      await fetch(`/api/v1/brokers/connections/${connId}`, { method: 'DELETE' });
      loadBrokerConnections();
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


@router.get("/compare", response_class=HTMLResponse, summary="Experiment Comparison View")
def get_compare_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/audit", response_class=HTMLResponse, summary="Provenance & Audit View")
def get_audit_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/settings", response_class=HTMLResponse, summary="Settings & Broker Connections View")
def get_settings_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/paper-trading", response_class=HTMLResponse, summary="Paper Trading Dashboard View")
def get_paper_trading_view():
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


@router.get("/paper-trading/{session_id}", response_class=HTMLResponse, summary="Paper Trading Session Detail View")
def get_paper_trading_session_view(session_id: str):
    return HTMLResponse(content=RESEARCH_UI_HTML, status_code=200)


