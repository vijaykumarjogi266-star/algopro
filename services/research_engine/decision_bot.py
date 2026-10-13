"""
Algo Lab — Autonomous Quantitative Research & Strategy Decision Bot.
Analyzes EOD trading results, backtests candidate quantitative strategies,
and autonomously determines optimal strategy allocation for the next session.
"""

import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

# Ensure root in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import yfinance as yf
from services.evaluation_engine.stat_metrics import StatisticalMetricsEngine
from services.observability.webhook_dispatcher import WebhookDispatcher
from apps.api.core.logging import get_logger

logger = get_logger("AutonomousResearchBot")


class AutonomousResearchBot:
    """
    Quantitative Research Bot responsible for:
    1. EOD trading audit & market regime classification.
    2. Multi-strategy comparative backtesting over recent market data.
    3. Autonomous decision allocation manifest generation.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        universe: Optional[List[str]] = None,
    ):
        self.db_path = db_path or os.path.join(PROJECT_ROOT, "data", "paper_trading.db")
        self.universe = universe or [
            "RELIANCE.NS",
            "TCS.NS",
            "INFY.NS",
            "HDFCBANK.NS",
            "ICICIBANK.NS",
            "SBIN.NS",
        ]
        self.dispatcher = WebhookDispatcher()
        self.decisions_dir = os.path.join(PROJECT_ROOT, "data", "decisions")
        self.intel_db_path = os.path.join(PROJECT_ROOT, "data", "market_intelligence.db")
        os.makedirs(self.decisions_dir, exist_ok=True)

    # -------------------------------------------------------------
    # 1. EOD Report Analysis & Regime Diagnostics
    # -------------------------------------------------------------
    def analyze_eod_performance(self) -> Dict[str, Any]:
        """Analyzes today's trading performance from paper database."""
        eod_summary = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_sessions": 0,
            "ending_equity": 50000.0,
            "realized_pnl": 0.0,
            "open_positions": 0,
            "market_regime": "UNKNOWN",
        }

        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM paper_sessions ORDER BY created_at DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    p_data = json.loads(row["portfolio_data"])
                    eod_summary["total_sessions"] = 1
                    eod_summary["ending_equity"] = p_data.get("total_equity", 50000.0)
                    eod_summary["realized_pnl"] = p_data.get("total_realized_pnl", 0.0)
                    eod_summary["open_positions"] = len(p_data.get("positions", {}))
                conn.close()
            except Exception as e:
                logger.warning(f"Error querying EOD database: {e}")

        # Classify Market Regime via RELIANCE / Benchmark daily data
        try:
            bench_df = yf.download("RELIANCE.NS", period="30d", interval="1d", progress=False)
            if hasattr(bench_df.columns, "levels") and len(bench_df.columns.levels) > 1:
                bench_df.columns = bench_df.columns.get_level_values(0)

            if len(bench_df) >= 20:
                closes = bench_df["Close"].values.astype(float)
                ret_20 = (closes[-1] - closes[-20]) / closes[-20]
                vol_20 = float(np.std(np.diff(closes) / closes[:-1]) * np.sqrt(252))

                if vol_20 > 0.35:
                    regime = "HIGH_VOLATILITY_CHOP"
                elif ret_20 > 0.03:
                    regime = "TRENDING_BULL"
                elif ret_20 < -0.03:
                    regime = "TRENDING_BEAR"
                else:
                    regime = "MEAN_REVERTING_RANGE"
                eod_summary["market_regime"] = regime
        except Exception as e:
            logger.warning(f"Regime classification fallback: {e}")
            eod_summary["market_regime"] = "MEAN_REVERTING_RANGE"

        return eod_summary

    # -------------------------------------------------------------
    # 2. Multi-Strategy Comparative Backtesting Engine
    # -------------------------------------------------------------
    def backtest_candidate_strategies(self, lookback_period: str = "60d") -> List[Dict[str, Any]]:
        """Backtests 4 candidate quantitative strategies across the universe."""
        results = []

        # Download market data for universe
        market_data: Dict[str, pd.DataFrame] = {}
        for sym in self.universe[:4]:  # Top liquid symbols
            try:
                df = yf.download(sym, period=lookback_period, interval="1h", progress=False)
                if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
                    df.columns = df.columns.get_level_values(0)
                if len(df) >= 40:
                    market_data[sym] = df
            except Exception as e:
                logger.warning(f"Failed to fetch backtest data for {sym}: {e}")

        if not market_data:
            return results

        # Candidate 1: VWAP Mean-Reversion
        vwap_trades = self._simulate_vwap_reversion(market_data)
        results.append(self._evaluate_strategy_metrics("STRAT_VWAP_REVERSION", vwap_trades))

        # Candidate 2: EMA Momentum Crossover (EMA 9 / 21)
        ema_trades = self._simulate_ema_crossover(market_data)
        results.append(self._evaluate_strategy_metrics("STRAT_EMA_MOMENTUM", ema_trades))

        # Candidate 3: Donchian 20-Bar Channel Breakout
        donchian_trades = self._simulate_donchian_breakout(market_data)
        results.append(self._evaluate_strategy_metrics("STRAT_DONCHIAN_BREAKOUT", donchian_trades))

        # Candidate 4: Bollinger Mean-Reversion (2.0 Std Dev)
        bb_trades = self._simulate_bollinger_reversion(market_data)
        results.append(self._evaluate_strategy_metrics("STRAT_BOLLINGER_REVERSION", bb_trades))

        return results

    def _simulate_vwap_reversion(self, data: Dict[str, pd.DataFrame]) -> List[float]:
        trades = []
        for sym, df in data.items():
            closes = df["Close"].values.astype(float)
            highs = df["High"].values.astype(float)
            lows = df["Low"].values.astype(float)
            typical = (highs + lows + closes) / 3.0
            std20 = pd.Series(closes).rolling(20).std().fillna(1.0).values

            pos = None
            for i in range(20, len(closes)):
                vwap = typical[i]
                lower = vwap - (1.5 * std20[i])
                if pos is None and closes[i] < lower:
                    pos = closes[i]
                elif pos is not None and (closes[i] >= vwap or closes[i] < pos * 0.98):
                    pnl_pct = (closes[i] - pos) / pos
                    trades.append(pnl_pct)
                    pos = None
        return trades

    def _simulate_ema_crossover(self, data: Dict[str, pd.DataFrame]) -> List[float]:
        trades = []
        for sym, df in data.items():
            closes = df["Close"].values.astype(float)
            ema9 = pd.Series(closes).ewm(span=9).mean().values
            ema21 = pd.Series(closes).ewm(span=21).mean().values

            pos = None
            for i in range(21, len(closes)):
                if pos is None and ema9[i] > ema21[i] and ema9[i-1] <= ema21[i-1]:
                    pos = closes[i]
                elif pos is not None and (ema9[i] < ema21[i] or closes[i] < pos * 0.98):
                    pnl_pct = (closes[i] - pos) / pos
                    trades.append(pnl_pct)
                    pos = None
        return trades

    def _simulate_donchian_breakout(self, data: Dict[str, pd.DataFrame]) -> List[float]:
        trades = []
        for sym, df in data.items():
            closes = df["Close"].values.astype(float)
            highs = df["High"].values.astype(float)
            lows = df["Low"].values.astype(float)
            high_20 = pd.Series(highs).rolling(20).max().shift(1).values
            low_20 = pd.Series(lows).rolling(20).min().shift(1).values

            pos = None
            for i in range(20, len(closes)):
                if pos is None and closes[i] > high_20[i]:
                    pos = closes[i]
                elif pos is not None and (closes[i] < low_20[i] or closes[i] < pos * 0.97):
                    pnl_pct = (closes[i] - pos) / pos
                    trades.append(pnl_pct)
                    pos = None
        return trades

    def _simulate_bollinger_reversion(self, data: Dict[str, pd.DataFrame]) -> List[float]:
        trades = []
        for sym, df in data.items():
            closes = df["Close"].values.astype(float)
            sma20 = pd.Series(closes).rolling(20).mean().values
            std20 = pd.Series(closes).rolling(20).std().fillna(1.0).values
            lower_bb = sma20 - (2.0 * std20)

            pos = None
            for i in range(20, len(closes)):
                if pos is None and closes[i] < lower_bb[i]:
                    pos = closes[i]
                elif pos is not None and (closes[i] >= sma20[i] or closes[i] < pos * 0.985):
                    pnl_pct = (closes[i] - pos) / pos
                    trades.append(pnl_pct)
                    pos = None
        return trades

    def _evaluate_strategy_metrics(self, strat_name: str, trades: List[float]) -> Dict[str, Any]:
        if not trades or len(trades) < 3:
            return {
                "strategy": strat_name,
                "trades_count": len(trades),
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "dsr": 0.0,
                "max_drawdown_pct": 0.0,
                "is_robust": False,
            }

        wins = [t for t in trades if t > 0]
        losses = [abs(t) for t in trades if t < 0]
        win_rate = (len(wins) / len(trades)) * 100
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = sum(losses) if losses else 1e-6
        profit_factor = gross_profit / gross_loss

        # Sharpe calculation
        returns_arr = np.array(trades)
        mean_ret = float(np.mean(returns_arr))
        std_ret = float(np.std(returns_arr)) if np.std(returns_arr) > 0 else 1.0
        sharpe = (mean_ret / std_ret) * np.sqrt(252 * 6)  # Approx hourly annualization

        # Deflated Sharpe Ratio (DSR) using Bailey & Lopez de Prado (2014)
        skew, kurt = StatisticalMetricsEngine.calculate_higher_moments(returns_arr)
        dsr, _ = StatisticalMetricsEngine.calculate_dsr(
            sharpe=sharpe,
            skew=skew,
            kurt=kurt,
            sample_size=len(trades),
            number_of_trials=4,
            var_trials=0.25,
        )

        # Max drawdown
        cum_ret = np.cumprod(1.0 + returns_arr)
        peak = np.maximum.accumulate(cum_ret)
        drawdowns = (peak - cum_ret) / peak
        max_dd = float(np.max(drawdowns)) * 100

        is_robust = dsr >= 0.50 and profit_factor >= 1.10 and max_dd <= 12.0

        return {
            "strategy": strat_name,
            "trades_count": len(trades),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "dsr": round(dsr, 4),
            "max_drawdown_pct": round(max_dd, 1),
            "is_robust": is_robust,
        }

    # -------------------------------------------------------------
    # 3. Autonomous Strategy Decision Allocation
    # -------------------------------------------------------------
    def make_strategy_allocation_decision(
        self,
        eod_diagnosis: Dict[str, Any],
        backtest_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Ranks strategies and decides tomorrow's production allocation.
        Adheres to Principle 1: Never force a trade, and Principle 2: WAIT is a valid decision.
        """
        regime = eod_diagnosis.get("market_regime", "MEAN_REVERTING_RANGE")
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        # Rank strategies by DSR * profit_factor
        ranked = sorted(
            backtest_results,
            key=lambda x: (x.get("is_robust", False), x.get("dsr", 0.0) * x.get("profit_factor", 0.0)),
            reverse=True,
        )

        chosen_strategy = "WAIT"
        decision_reason = "No candidate strategy met the strict robustness gate (DSR >= 0.50 and PF >= 1.10)."
        risk_multiplier = 0.0

        if ranked and ranked[0].get("is_robust"):
            top = ranked[0]
            chosen_strategy = top["strategy"]
            risk_multiplier = 1.0
            decision_reason = (
                f"Selected {top['strategy']} based on DSR={top['dsr']:.2f}, "
                f"PF={top['profit_factor']:.2f}, WinRate={top['win_rate_pct']}%, "
                f"compatible with {regime} market regime."
            )

        # Quantamental Stock Selection & Universe Stratification
        stock_selection_data = None
        try:
            from services.market_intelligence.stock_decision_engine import StockDecisionEngine
            stock_engine = StockDecisionEngine()
            stock_manifest = stock_engine.run_stock_selection(candidate_symbols=self.universe)
            stock_selection_data = {
                "top_picks": stock_manifest.top_picks,
                "approved_portfolio": stock_manifest.selected_portfolio,
                "excluded_portfolio": stock_manifest.excluded_portfolio,
                "narrative": stock_manifest.narrative,
            }
        except Exception as e:
            logger.warning(f"Stock selection integration failed: {e}")

        decision_manifest = {
            "decision_date": datetime.now(timezone.utc).isoformat(),
            "target_session_date": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d"),
            "market_regime": regime,
            "selected_strategy": chosen_strategy,
            "risk_multiplier": risk_multiplier,
            "allocation_reason": decision_reason,
            "candidate_evaluations": ranked,
            "stock_selection": stock_selection_data,
            "eod_audit": eod_diagnosis,
        }

        # Save decision manifest to disk
        manifest_path = os.path.join(self.decisions_dir, f"decision_{today_str}.json")
        with open(manifest_path, "w") as f:
            json.dump(decision_manifest, f, indent=2)

        logger.info(f"Autonomous Decision Manifest written to {manifest_path}")

        # Persist to SQLite Database
        self._persist_to_database(decision_manifest)

        # Dispatch Webhook Notification
        self.dispatcher.notify(
            title="Autonomous Quantitative Strategy Decision",
            message=f"Research bot completed EOD analysis and strategy backtesting.\n**Decision: {chosen_strategy}**",
            level="INFO" if chosen_strategy != "WAIT" else "WARNING",
            fields={
                "Regime": regime,
                "Selected Strategy": chosen_strategy,
                "Risk Multiplier": f"{risk_multiplier}x",
                "Rationale": decision_reason[:150],
                "Manifest": os.path.basename(manifest_path),
            },
        )

        return decision_manifest

    def _persist_to_database(self, decision_manifest: Dict[str, Any]):
        """Persists research decision to SQLite database."""
        try:
            dec_date = decision_manifest.get("decision_date", datetime.now(timezone.utc).isoformat())[:10]
            with sqlite3.connect(self.intel_db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS research_strategy_decisions (
                        decision_date TEXT PRIMARY KEY,
                        target_session_date TEXT NOT NULL,
                        evaluated_at TEXT NOT NULL,
                        market_regime TEXT NOT NULL,
                        selected_strategy TEXT NOT NULL,
                        risk_multiplier REAL NOT NULL,
                        allocation_reason TEXT NOT NULL,
                        candidate_evaluations_json TEXT NOT NULL,
                        stock_selection_json TEXT,
                        eod_audit_json TEXT,
                        decision_manifest_json TEXT NOT NULL
                    )
                """)
                cur.execute("""
                    INSERT OR REPLACE INTO research_strategy_decisions (
                        decision_date, target_session_date, evaluated_at, market_regime,
                        selected_strategy, risk_multiplier, allocation_reason,
                        candidate_evaluations_json, stock_selection_json, eod_audit_json,
                        decision_manifest_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dec_date,
                    decision_manifest.get("target_session_date", ""),
                    decision_manifest.get("decision_date", datetime.now(timezone.utc).isoformat()),
                    decision_manifest.get("market_regime", "UNKNOWN"),
                    decision_manifest.get("selected_strategy", "WAIT"),
                    float(decision_manifest.get("risk_multiplier", 1.0)),
                    decision_manifest.get("allocation_reason", ""),
                    json.dumps(decision_manifest.get("candidate_evaluations", [])),
                    json.dumps(decision_manifest.get("stock_selection", {})),
                    json.dumps(decision_manifest.get("eod_audit", {})),
                    json.dumps(decision_manifest),
                ))
                conn.commit()
            logger.info("Autonomous Decision Manifest persisted to market_intelligence.db")
        except Exception as e:
            logger.warning(f"Failed to persist research decision to database: {e}")

    def run_eod_research_cycle(self) -> Dict[str, Any]:
        """Executes full autonomous EOD research & decision cycle."""
        logger.info("Initiating Autonomous EOD Research & Strategy Decision Cycle...")
        eod_report = self.analyze_eod_performance()
        backtest_results = self.backtest_candidate_strategies()
        decision = self.make_strategy_allocation_decision(eod_report, backtest_results)
        return decision


if __name__ == "__main__":
    bot = AutonomousResearchBot()
    decision = bot.run_eod_research_cycle()
    print("\n" + "=" * 60)
    print("AUTONOMOUS STRATEGY DECISION MANIFEST:")
    print(f"Target Session: {decision['target_session_date']}")
    print(f"Market Regime:  {decision['market_regime']}")
    print(f"Decision:       {decision['selected_strategy']} ({decision['risk_multiplier']}x)")
    print(f"Rationale:      {decision['allocation_reason']}")
    print("=" * 60)
