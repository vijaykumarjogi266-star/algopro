#!/usr/bin/env python3
"""
Algo Lab — Autonomous EOD Research & Strategy Decision Bot Runner.
CLI runner to manually or chronologically invoke the research bot.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services.research_engine.decision_bot import AutonomousResearchBot

def main():
    print("=" * 70)
    print("ALGO LAB — AUTONOMOUS QUANTITATIVE RESEARCH & STRATEGY DECISION BOT")
    print("Executing EOD Audit, Multi-Strategy Backtesting & Decision Allocation")
    print("=" * 70)
    
    bot = AutonomousResearchBot()
    manifest = bot.run_eod_research_cycle()
    
    print("\n[DECISION MANIFEST SUMMARY]")
    print(f"Target Session:     {manifest['target_session_date']}")
    print(f"Market Regime:      {manifest['market_regime']}")
    print(f"Allocated Strategy: {manifest['selected_strategy']} ({manifest['risk_multiplier']}x)")
    print(f"Decision Reason:    {manifest['allocation_reason']}")
    print("\nCandidate Evaluations:")
    for c in manifest["candidate_evaluations"]:
        print(f"  • {c['strategy']:<24}: DSR={c['dsr']:.4f} | PF={c['profit_factor']:.2f} | WinRate={c['win_rate_pct']}% | MaxDD={c['max_drawdown_pct']}% | Robust={c['is_robust']}")
    print("=" * 70)

if __name__ == "__main__":
    main()
