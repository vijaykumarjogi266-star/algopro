export default function StrategiesPage() {
  const strategies = [
    {
      id: "strat_orb_01",
      name: "Opening Range Breakout (ORB)",
      version: "1.0.0",
      description: "Identifies early volatility expansion and range breaks during the first 15/30 minutes of Indian market session.",
      indicators: ["ATR", "Volume Ratio", "Day High/Low"],
      waitPolicy: "Active: Defaults to WAIT if volume threshold < 1.5x 20-period average.",
      status: "CONTRACT_READY",
    },
    {
      id: "strat_vwap_rev_01",
      name: "VWAP Mean Reversion",
      version: "1.0.0",
      description: "Detects intraday price stretches beyond 2 standard deviations of volume-weighted average price for mean reversion.",
      indicators: ["VWAP", "Standard Deviation Bands", "RSI (Evidence only)"],
      waitPolicy: "Active: Defaults to WAIT during high ADX trending regimes.",
      status: "CONTRACT_READY",
    },
    {
      id: "strat_mom_pullback_01",
      name: "Momentum / Trend Pullback",
      version: "1.0.0",
      description: "Enters multi-day swing pullbacks towards key 20 EMA and 50 SMA support levels during established structural trends.",
      indicators: ["EMA 20", "SMA 50", "ATR Volatility Channel"],
      waitPolicy: "Active: Defaults to WAIT if higher-timeframe trend is flat or conflicting.",
      status: "CONTRACT_READY",
    },
  ];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">Strategy Framework & Registered Candidates</h2>
        <p className="text-slate-400 text-xs mt-1">
          All strategies implement the unified BaseStrategy contract. Principle 11: Indicators provide evidence; Principle 2: WAIT is a valid decision.
        </p>
      </div>

      <div className="space-y-4">
        {strategies.map((strat) => (
          <div key={strat.id} className="p-5 rounded-lg bg-surface border border-surface-border space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <span className="font-bold text-white text-sm">{strat.name}</span>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                  v{strat.version}
                </span>
              </div>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                {strat.status}
              </span>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">{strat.description}</p>

            <div className="pt-2 border-t border-surface-border flex flex-wrap gap-4 text-xs font-mono text-slate-400">
              <div>
                <span className="text-slate-500">Indicators: </span>
                <span className="text-accent">{strat.indicators.join(", ")}</span>
              </div>
              <div>
                <span className="text-slate-500">WAIT Discipline: </span>
                <span className="text-amber-400">{strat.waitPolicy}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
