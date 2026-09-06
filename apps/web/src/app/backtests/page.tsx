export default function BacktestsPage() {
  const sampleBacktests = [
    {
      id: "EXP-2026-ORB-01",
      strategy: "Opening Range Breakout (ORB)",
      symbol: "NIFTY50",
      timeframe: "15m",
      trades: 48,
      winRate: "58.3%",
      profitFactor: "1.82",
      sharpe: "1.45",
      maxDD: "-4.2%",
      totalReturn: "+14.8%",
      gitCommit: "473419e",
      status: "REPRODUCIBLE",
    },
    {
      id: "EXP-2026-VWAP-02",
      strategy: "VWAP Mean Reversion",
      symbol: "RELIANCE",
      timeframe: "5m",
      trades: 62,
      winRate: "51.6%",
      profitFactor: "1.64",
      sharpe: "1.28",
      maxDD: "-5.8%",
      totalReturn: "+11.2%",
      gitCommit: "473419e",
      status: "REPRODUCIBLE",
    },
  ];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">Backtesting Engine & Results</h2>
        <p className="text-slate-400 text-xs mt-1">
          Strict look-ahead protection, realistic Indian transaction costs (STT, GST, SEBI), and full reproducibility.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">COST MODEL APPLIED</div>
          <div className="text-sm font-semibold text-white mt-1">NSE Equity Delivery & Intraday</div>
          <div className="text-[11px] text-slate-400 mt-2">
            STT 0.1%, Brokerage ₹20/order, GST 18%, Stamp Duty 0.015%
          </div>
        </div>
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">SLIPPAGE MODEL</div>
          <div className="text-sm font-semibold text-white mt-1">0.05 pt Tick + 5 bps Spread</div>
          <div className="text-[11px] text-slate-400 mt-2">
            Simulates realistic liquidity friction during fast market orders
          </div>
        </div>
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">AUDIT REPRODUCIBILITY</div>
          <div className="text-sm font-semibold text-white mt-1">Git Hash + Data Version</div>
          <div className="text-[11px] text-slate-400 mt-2">
            Principle 7: Every backtest execution is cryptographically reproducible
          </div>
        </div>
      </div>

      <div className="rounded-lg bg-surface border border-surface-border overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Simulated Experiment Runs</h3>
          <span className="text-xs text-accent font-mono">Stage 1 Verified Contracts</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-black/30 text-slate-400 border-b border-surface-border">
              <tr>
                <th className="p-3">Experiment ID</th>
                <th className="p-3">Strategy</th>
                <th className="p-3">Symbol</th>
                <th className="p-3">Trades</th>
                <th className="p-3">Win Rate</th>
                <th className="p-3">Profit Factor</th>
                <th className="p-3">Sharpe</th>
                <th className="p-3">Max DD</th>
                <th className="p-3">Return</th>
                <th className="p-3">Git Hash</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-slate-300">
              {sampleBacktests.map((b) => (
                <tr key={b.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="p-3 text-accent">{b.id}</td>
                  <td className="p-3 font-sans font-medium text-white">{b.strategy}</td>
                  <td className="p-3">{b.symbol} ({b.timeframe})</td>
                  <td className="p-3">{b.trades}</td>
                  <td className="p-3">{b.winRate}</td>
                  <td className="p-3">{b.profitFactor}</td>
                  <td className="p-3">{b.sharpe}</td>
                  <td className="p-3 text-rose-400">{b.maxDD}</td>
                  <td className="p-3 text-emerald-400">{b.totalReturn}</td>
                  <td className="p-3 text-slate-400">{b.gitCommit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
