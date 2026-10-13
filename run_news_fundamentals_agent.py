#!/usr/bin/env python3
"""
Algo Lab — Run News & Market Fundamentals Assistant (CLI Runner)
Interactive quantamental research assistant & multi-interval scheduled collector.
Collects data from all available sources (Google News, ET, Moneycontrol, LiveMint, yfinance)
and manages scheduled multi-tier harvesting intervals.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

# Ensure project root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.market_intelligence.news_fundamental_contracts import CollectionScheduleConfig
from services.market_intelligence.assistant_engine import MarketIntelligenceAssistant
from services.market_intelligence.news_fundamental_agent import DEFAULT_UNIVERSE


def main():
    parser = argparse.ArgumentParser(description="Algo Lab News & Fundamentals Intelligence Assistant")
    # Assistant Query Commands
    parser.add_argument("--ask", type=str, help="Ask the assistant a natural language question (e.g. 'Compare TCS and INFY', 'Any alerts?')")
    parser.add_argument("--briefing", action="store_true", help="Generate executive macro and equity market briefing")
    parser.add_argument("--alerts", action="store_true", help="Show breaking high-urgency alerts from past 24h")
    parser.add_argument("--compare", nargs="+", help="Compare two or more symbols head-to-head (e.g. --compare TCS.NS INFY.NS)")
    parser.add_argument("--symbol", type=str, help="Evaluate a specific symbol dossier (e.g. RELIANCE.NS, TCS.NS)")
    parser.add_argument("--check-trade", type=str, help="Check if trade is allowed for a symbol (returns boolean + narrative)")
    parser.add_argument("--universe", action="store_true", help="Evaluate the entire default benchmark universe (8 liquid NSE equities)")
    parser.add_argument("--select-stocks", action="store_true", help="Run multi-factor stock selection & portfolio stratification")
    parser.add_argument("--history-selections", action="store_true", help="Display previous stock selection runs from SQLite database")
    parser.add_argument("--decide", type=str, help="Make actionable entry decision on a symbol (combines technical signal with quantamental health)")
    parser.add_argument("--history-decisions", action="store_true", help="Display previous trade gating decisions from SQLite database")
    parser.add_argument("--eod", nargs="?", const="latest", help="Display EOD performance report from database (e.g. --eod or --eod 2026-10-13)")
    parser.add_argument("--research", action="store_true", help="Display autonomous quantitative research strategy decision from database")
    parser.add_argument("--signal", type=str, default="BUY", help="Proposed technical signal for decision evaluation (default: BUY)")
    parser.add_argument("--price", type=float, default=0.0, help="Current asset market price for decision evaluation")


    # Multi-Interval Scheduling Commands
    parser.add_argument("--run-cycle", action="store_true", help="Execute one multi-interval scheduled collection cycle")
    parser.add_argument("--daemon", action="store_true", help="Run assistant scheduler daemon continuously in the foreground")
    parser.add_argument("--status", action="store_true", help="Show assistant collection intervals, record counts, and schedule status")

    # Configuration options
    parser.add_argument("--news-interval", type=int, default=15, help="News collection interval in minutes (default: 15)")
    parser.add_argument("--macro-interval", type=int, default=60, help="Macro collection interval in minutes (default: 60)")
    parser.add_argument("--fund-interval", type=int, default=12, help="Fundamentals collection interval in hours (default: 12)")
    parser.add_argument("--offline", action="store_true", help="Force deterministic offline mode (no network calls)")

    args = parser.parse_args()

    schedule_cfg = CollectionScheduleConfig(
        news_interval_minutes=args.news_interval,
        macro_interval_minutes=args.macro_interval,
        fundamentals_interval_hours=args.fund_interval,
    )

    assistant = MarketIntelligenceAssistant(
        db_path=os.path.join(PROJECT_ROOT, "data", "market_intelligence.db"),
        intelligence_dir=os.path.join(PROJECT_ROOT, "data", "intelligence"),
        schedule_config=schedule_cfg,
        force_offline=args.offline,
    )

    from services.market_intelligence.stock_decision_engine import StockDecisionEngine

    decision_engine = StockDecisionEngine(assistant.agent)

    # Stock Selection Routine
    if args.select_stocks:
        manifest = decision_engine.run_stock_selection()
        print("\n" + "=" * 75)
        print("ALGO LAB — QUANTAMENTAL STOCK SELECTION & UNIVERSE STRATIFICATION")
        print(f"Timestamp: {manifest.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 75)
        print(f"\n🌟 TOP PICKS (Highest Conviction): {', '.join(manifest.top_picks)}")
        print(f"✅ APPROVED ACTIVE PORTFOLIO:      {', '.join(manifest.selected_portfolio)}")
        print(f"🚫 EXCLUDED / VETOED:              {', '.join(manifest.excluded_portfolio) or 'None'}")
        print("\nFull Candidate Stratification Leaderboard:")
        print(f"{'Rank':<5} {'Symbol':<14} {'Tier':<22} {'Score':<8} {'F-Score':<8} {'ROE %':<8} {'Upside %':<10} {'Alloc':<6}")
        print("-" * 85)
        for c in manifest.candidates:
            upside_str = f"{c.analyst_upside_pct:+.1f}%" if c.analyst_upside_pct is not None else "N/A"
            tier_short = c.tier.value.replace("TIER_", "T").replace("_", " ")
            print(f"{c.rank:<5} {c.symbol:<14} {tier_short:<22} {c.quantamental_score:+6.1f}   {c.piotroski_f_score}/9      {c.roe_pct:5.1f}%   {upside_str:<10} {c.allocation_multiplier*100:3.0f}%")
        print("-" * 85)
        print(f"\nAudit Rationale: {manifest.narrative}\n")
        return

    # Stock Selection History from Database
    if args.history_selections:
        selections = decision_engine.get_recent_stock_selections(limit=5)
        print("\n" + "=" * 75)
        print("ALGO LAB — PERSISTED STOCK SELECTION HISTORY (SQLite)")
        print("=" * 75)
        if not selections:
            print("No stock selection runs found in database. Run --select-stocks to execute.")
        else:
            for s in selections:
                t_str = s["generated_at"][:19].replace("T", " ")
                print(f"Selection ID: {s['selection_id']} ({t_str} UTC)")
                print(f"Top Picks:    {', '.join(s['top_picks'])}")
                print(f"Approved:     {', '.join(s['selected_portfolio'])}")
                print(f"Excluded:     {', '.join(s['excluded_portfolio']) or 'None'}")
                print(f"Candidates:   {s['candidate_count']} symbols evaluated")
                print(f"Rationale:    {s['narrative']}")
                print("-" * 75)
        print()
        return

    # Real-Time Actionable Trade Decision
    if args.decide:
        sym = args.decide.upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym += ".NS"
        sig = args.signal.upper()
        res = decision_engine.evaluate_entry_decision(sym, sig, args.price)

        action_badge = "✅ APPROVE_BUY" if res.action.value == "APPROVE_BUY" else ("🚫 VETO" if res.action.value == "VETO" else "⏳ WAIT")
        print("\n" + "=" * 65)
        print(f"ALGO LAB — ACTIONABLE TRADING DECISION: {sym}")
        print("=" * 65)
        print(f"Proposed Technical Signal: {sig}")
        print(f"Decision Action:           {action_badge}")
        print(f"Approved Sizing Scale:     {res.approved_quantity_scale*100:.0f}% of max capital per trade")
        print(f"Conviction Score:          {res.conviction_score:.1f} / 100.0")
        print(f"Red Flag Warning:          {'YES 🚨' if res.red_flag_alert else 'NO'}")
        print("-" * 65)
        print(f"Decision Reason: {res.reason}")
        print("=" * 65 + "\n")
        return

    # Trade Decision History from Database
    if args.history_decisions:
        decisions = decision_engine.get_recent_trade_decisions(limit=20)
        print("\n" + "=" * 80)
        print("ALGO LAB — PERSISTED TRADE DECISION AUDIT TRAIL (SQLite)")
        print("=" * 80)
        if not decisions:
            print("No trade decisions logged in database yet. Use --decide <SYMBOL> to evaluate.")
        else:
            print(f"{'Timestamp':<20} {'Symbol':<12} {'Signal':<7} {'Action':<15} {'Scale':<7} {'Conviction':<10} {'Reason'}")
            print("-" * 80)
            for d in decisions:
                t_str = d["evaluated_at"][:19].replace("T", " ")
                action_badge = d["action"]
                scale_str = f"{d['approved_quantity_scale']*100:.0f}%"
                reason_short = d["reason"][:40] + ("..." if len(d["reason"]) > 40 else "")
                print(f"{t_str:<20} {d['symbol']:<12} {d['proposed_signal']:<7} {action_badge:<15} {scale_str:<7} {d['conviction_score']:<10.1f} {reason_short}")
        print("=" * 80 + "\n")
        return

    # EOD Report from Database
    if args.eod:
        target_date = None if args.eod == "latest" else args.eod
        report = assistant.get_eod_report(target_date)
        if not report:
            print(f"\nNo EOD report found in database{' for ' + target_date if target_date else ''}.\n")
        else:
            print("\n" + report["report_markdown"] + "\n")
        return

    # Autonomous Quantitative Research Strategy Decision from Database
    if args.research:
        strat = assistant.get_latest_research_strategy_decision()
        if not strat:
            print("\nNo quantitative research decisions found in database.\n")
        else:
            print("\n" + "=" * 70)
            print(f"ALGO LAB — QUANTITATIVE STRATEGY RESEARCH ALLOCATION ({strat['decision_date']})")
            print("=" * 70)
            print(f"Target Session Date:  {strat['target_session_date']}")
            print(f"Detected Regime:      {strat['market_regime']}")
            print(f"Selected Strategy:    {strat['selected_strategy']}")
            print(f"Risk Multiplier:      {strat['risk_multiplier']}x")
            print(f"Allocation Rationale: {strat['allocation_reason']}")
            print("\nCandidate Strategy Backtest Robustness Matrix:")
            print(f"{'Strategy':<28} {'Trades':<8} {'Win %':<8} {'PF':<8} {'Sharpe':<8} {'DSR':<8} {'Status'}")
            print("-" * 75)
            for c in strat.get("candidate_evaluations", []):
                stat_str = "ROBUST (SELECTED)" if c.get("is_robust") else "REJECTED"
                print(f"{c['strategy']:<28} {c.get('trades_count', 0):<8} {c.get('win_rate_pct', 0.0):<8.1f} {c.get('profit_factor', 0.0):<8.2f} {c.get('sharpe_ratio', 0.0):<8.2f} {c.get('dsr', 0.0):<8.4f} {stat_str}")
            print("=" * 75 + "\n")
        return

    if args.ask:
        print(f"\n[ALGO LAB ASSISTANT] Question: \"{args.ask}\"\n")
        answer = assistant.ask(args.ask)
        print(answer)
        print()
        return

    # 2. Executive Briefing
    if args.briefing:
        briefing = assistant.get_market_briefing()
        print("\n" + briefing + "\n")
        return

    # 3. High Urgency Alerts
    if args.alerts:
        alerts = assistant.get_breaking_alerts()
        print("\n" + "=" * 65)
        print("ALGO LAB ASSISTANT — BREAKING HIGH URGENCY ALERTS (PAST 24H)")
        print("=" * 65)
        if not alerts:
            print("✅ No high-urgency regulatory, governance, or debt alerts detected.")
        else:
            for a in alerts:
                print(f"🚨 [{a['symbol']}] {a['title']}")
                print(f"   Source: {a['source']} | Sentiment: {a['sentiment']:+.2f} | Published: {a['published_at']}")
        print("=" * 65 + "\n")
        return

    # 4. Compare Assets
    if args.compare:
        clean_symbols = []
        for s in args.compare:
            s_up = s.upper()
            if not s_up.endswith(".NS") and not s_up.endswith(".BO"):
                s_up += ".NS"
            clean_symbols.append(s_up)
        comp_md = assistant.compare_assets(clean_symbols)
        print("\n" + comp_md + "\n")
        return

    # 5. Check Trade Permission
    if args.check_trade:
        sym = args.check_trade.upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym += ".NS"
        allowed, narrative, mult = assistant.agent.is_trade_allowed(sym)
        status_str = "✅ PERMITTED" if allowed else "🚫 BLOCKED"
        print(f"\n[TRADE GATE] Symbol: {sym}")
        print(f"Status: {status_str}")
        print(f"Allocation Scale: {mult*100:.0f}%")
        print(f"Audit Narrative: {narrative}\n")
        return

    # 6. Single Symbol Dossier
    if args.symbol:
        sym = args.symbol.upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym += ".NS"
        print(f"\n[ALGO LAB ASSISTANT] Dossier for {sym}...")
        answer = assistant.ask(sym)
        print(answer + "\n")
        return

    # 7. Collection Status
    if args.status:
        st = assistant.get_status()
        print("\n" + "=" * 65)
        print("ALGO LAB ASSISTANT — HARVESTING SCHEDULE & DATABASE STATUS")
        print("=" * 65)
        print(f"Database:                  {st['database_path']}")
        print(f"Total News Articles:       {st['total_news_articles']}")
        print(f"Total Macro Items:         {st['total_macro_items']}")
        print(f"Total Fund Snapshots:      {st['total_fundamental_snapshots']}")
        print(f"Total Calendar Events:     {st.get('total_calendar_events', 0)}")
        print(f"Total Analyst Consensus:   {st.get('total_analyst_consensus', 0)}")
        print(f"Total Quant Manifests:     {st.get('total_quantamental_manifests', 0)}")
        print(f"Total Stock Selections:    {st.get('total_stock_selections', 0)}")
        print(f"Total Selection Candidates:{st.get('total_selection_candidates', 0)}")
        print(f"Total Trade Decisions:     {st.get('total_trade_decisions', 0)}")
        print(f"Total EOD Reports:         {st.get('total_eod_reports', 0)}")
        print(f"Total Research Decisions:  {st.get('total_research_strategy_decisions', 0)}")
        print("\nConfigured Intervals:")
        print(f"  Tier 1 (News Stream):       Every {st['schedule_intervals']['news_minutes']} minutes")
        print(f"  Tier 2 (Macro Watch):       Every {st['schedule_intervals']['macro_minutes']} minutes")
        print(f"  Tier 3 (Fundamentals):      Every {st['schedule_intervals']['fundamentals_hours']} hours")
        print("\nLast Execution History:")
        for tier, data in st["schedule_tiers"].items():
            print(f"  [{tier}]: Last run at {data['last_run']} ({data['records']} items collected)")
        print("=" * 65 + "\n")
        return

    # 8. Run Scheduled Collection Cycle (Single Iteration)
    if args.run_cycle:
        print("\n[ALGO LAB ASSISTANT] Running multi-interval scheduled harvesting cycle...")
        res = assistant.run_scheduled_cycle()
        print(f"Tiers Executed:         {', '.join(res['tiers_executed']) or 'None (All tiers within interval)'}")
        print(f"News Collected:         {res['news_count']}")
        print(f"Macro News Collected:   {res['macro_count']}")
        print(f"Fundamentals Refreshed: {res['fundamentals_updated']}")
        print("Cycle completed.\n")
        return

    # 9. Scheduled Daemon Mode
    if args.daemon:
        print("\n" + "=" * 70)
        print("ALGO LAB ASSISTANT — MULTI-INTERVAL SCHEDULER DAEMON STARTED")
        print(f"Tier 1 (News Stream):  Every {args.news_interval} minutes")
        print(f"Tier 2 (Macro Watch):  Every {args.macro_interval} minutes")
        print(f"Tier 3 (Fundamentals): Every {args.fund_interval} hours")
        print("=" * 70 + "\n")
        try:
            while True:
                res = assistant.run_scheduled_cycle()
                if res["tiers_executed"]:
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] Ran tiers: {', '.join(res['tiers_executed'])} | News: {res['news_count']}, Macro: {res['macro_count']}, Fund: {res['fundamentals_updated']}")
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nScheduler daemon stopped by user.")
        return

    # Default: Run full universe evaluation & print summary
    print("\n" + "=" * 70)
    print("ALGO LAB ASSISTANT — QUANTAMENTAL NEWS & FUNDAMENTALS EVALUATION")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Target Universe: {len(DEFAULT_UNIVERSE)} symbols")
    print(f"Sources: Google News, Economic Times, Moneycontrol, LiveMint, yfinance")
    print("=" * 70)

    manifests = assistant.agent.evaluate_universe(DEFAULT_UNIVERSE)

    print("\nLeaderboard Summary:")
    print(f"{'Rank':<5} {'Symbol':<14} {'Bias':<16} {'Score':<8} {'Fund':<8} {'Sent':<8} {'Gate':<10}")
    print("-" * 70)
    for i, m in enumerate(manifests, 1):
        gate = "ALLOW" if m.allow_trading else "BLOCK"
        print(f"{i:<5} {m.symbol:<14} {m.bias.value:<16} {m.composite_score:+6.1f}   {m.fundamental_score:5.1f}   {m.sentiment_score:+6.1f}   {gate:<10}")
    print("-" * 70)

    if args.report:
        report_md = assistant.agent.generate_intelligence_report(manifests)
        report_file = os.path.join(PROJECT_ROOT, "data", "intelligence", f"report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md")
        with open(report_file, "w") as f:
            f.write(report_md)
        print(f"\nReport written to: {report_file}")
        print("\n" + report_md)


if __name__ == "__main__":
    main()
