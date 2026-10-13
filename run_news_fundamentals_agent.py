#!/usr/bin/env python3
"""
Algo Lab — Run News & Market Fundamentals Agent (CLI Runner)
Collects, processes, and evaluates real-time/point-in-time financial news and
equity fundamentals across the NSE universe.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

# Ensure project root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.market_intelligence.news_fundamental_agent import (
    NewsFundamentalAgent,
    DEFAULT_UNIVERSE,
)


def main():
    parser = argparse.ArgumentParser(description="Algo Lab News & Fundamentals Intelligence Agent")
    parser.add_argument("--universe", action="store_true", help="Evaluate the entire default benchmark universe (8 liquid NSE equities)")
    parser.add_argument("--symbol", type=str, help="Evaluate a specific symbol (e.g. RELIANCE.NS, TCS.NS)")
    parser.add_argument("--report", action="store_true", help="Generate and print full Markdown intelligence report")
    parser.add_argument("--offline", action="store_true", help="Force deterministic offline mode (no network calls)")
    parser.add_argument("--check-trade", type=str, help="Check if trade is allowed for a symbol (returns boolean + narrative)")

    args = parser.parse_args()

    agent = NewsFundamentalAgent(
        db_path=os.path.join(PROJECT_ROOT, "data", "market_intelligence.db"),
        intelligence_dir=os.path.join(PROJECT_ROOT, "data", "intelligence"),
        force_offline=args.offline,
    )

    if args.check_trade:
        sym = args.check_trade.upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym += ".NS"
        allowed, narrative, mult = agent.is_trade_allowed(sym)
        status_str = "✅ PERMITTED" if allowed else "🚫 BLOCKED"
        print(f"\n[TRADE GATE] Symbol: {sym}")
        print(f"Status: {status_str}")
        print(f"Allocation Multiplier: {mult*100:.0f}%")
        print(f"Audit Narrative: {narrative}\n")
        return

    if args.symbol:
        sym = args.symbol.upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym += ".NS"
        print(f"\n[ALGO LAB] Running News & Fundamentals Agent for {sym}...")
        manifest = agent.evaluate_symbol(sym)
        print("=" * 65)
        print(f"Symbol:               {manifest.symbol}")
        print(f"Composite Score:      {manifest.composite_score:+.1f} / 100.0")
        print(f"Bias:                 {manifest.bias.value}")
        print(f"Fundamental Health:   {manifest.fundamental_score:.1f} / 100.0")
        print(f"News Sentiment:       {manifest.sentiment_score:+.1f} / 100.0 (Articles: {manifest.recent_news_count})")
        print(f"Trade Gating:         {'PERMITTED' if manifest.allow_trading else 'BLOCKED'}")
        print(f"Allocation Scale:     {manifest.allocation_multiplier*100:.0f}%")
        print("-" * 65)
        print(f"Explainability: {manifest.narrative}")
        if manifest.catalysts:
            print("Catalysts:")
            for c in manifest.catalysts:
                print(f"  + {c}")
        if manifest.risks:
            print("Risks:")
            for r in manifest.risks:
                print(f"  - {r}")
        print("=" * 65 + "\n")
        return

    # Default to evaluating universe
    print("\n" + "=" * 70)
    print("ALGO LAB — QUANTAMENTAL NEWS & FUNDAMENTALS INTELLIGENCE RUN")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Target Universe: {len(DEFAULT_UNIVERSE)} symbols")
    print(f"Mode: {'OFFLINE (Deterministic)' if args.offline else 'LIVE (Online Feeds)'}")
    print("=" * 70)

    manifests = agent.evaluate_universe(DEFAULT_UNIVERSE)

    print("\nLeaderboard Summary:")
    print(f"{'Rank':<5} {'Symbol':<14} {'Bias':<16} {'Score':<8} {'Fund':<8} {'Sent':<8} {'Gate':<10}")
    print("-" * 70)
    for i, m in enumerate(manifests, 1):
        gate = "ALLOW" if m.allow_trading else "BLOCK"
        print(f"{i:<5} {m.symbol:<14} {m.bias.value:<16} {m.composite_score:+6.1f}   {m.fundamental_score:5.1f}   {m.sentiment_score:+6.1f}   {gate:<10}")
    print("-" * 70)

    if args.report:
        report_md = agent.generate_intelligence_report(manifests)
        report_file = os.path.join(PROJECT_ROOT, "data", "intelligence", f"report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md")
        with open(report_file, "w") as f:
            f.write(report_md)
        print(f"\nReport written to: {report_file}")
        print("\n" + report_md)


if __name__ == "__main__":
    main()
