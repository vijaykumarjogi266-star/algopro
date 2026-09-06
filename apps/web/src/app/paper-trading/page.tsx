export default function PaperTradingPage() {
  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">Paper Trading Simulation Engine</h2>
        <p className="text-slate-400 text-xs mt-1">
          Stage 1 Foundation: Simulated broker sandbox. Never transmits real orders to brokers.
        </p>
      </div>

      <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs">
        <span className="font-bold">Principle 25 Enforced:</span> Simulated paper broker active in memory. Real broker credentials & live order execution disabled.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">SIMULATED CAPITAL</div>
          <div className="text-xl font-bold text-white mt-1">₹10,00,000</div>
          <div className="text-[11px] text-slate-400 mt-1">Initial Cash Balance</div>
        </div>
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">CURRENT EQUITY</div>
          <div className="text-xl font-bold text-white mt-1">₹10,00,000</div>
          <div className="text-[11px] text-slate-400 mt-1">Cash + Unrealized P&L</div>
        </div>
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">ACTIVE POSITIONS</div>
          <div className="text-xl font-bold text-white mt-1">0 / 10</div>
          <div className="text-[11px] text-slate-400 mt-1">Hard Limit: Max 10</div>
        </div>
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">DAILY LOSS TRACKER</div>
          <div className="text-xl font-bold text-white mt-1">0.00%</div>
          <div className="text-[11px] text-slate-400 mt-1">Max Daily Stop: 3.0%</div>
        </div>
      </div>

      <div className="p-5 rounded-lg bg-surface border border-surface-border space-y-3">
        <h3 className="text-sm font-semibold text-white">Paper Execution Pipeline (Stage 1)</h3>
        <div className="text-xs font-mono text-slate-300 space-y-2">
          <div className="p-2.5 rounded bg-black/40 border border-surface-border">
            1. Market Data → Strict Validation (Monotonicity, OHLC sanity, Volume checks)
          </div>
          <div className="p-2.5 rounded bg-black/40 border border-surface-border">
            2. BaseStrategy → Evidentiary Signals (BUY, SELL, WAIT, EXIT)
          </div>
          <div className="p-2.5 rounded bg-black/40 border border-surface-border">
            3. Independent Risk Engine → Sizing & Hard Stop Loss Verification
          </div>
          <div className="p-2.5 rounded bg-black/40 border border-surface-border">
            4. Simulated Broker → In-memory fill with slippage & STT/GST fee attribution
          </div>
          <div className="p-2.5 rounded bg-black/40 border border-surface-border">
            5. Decision & Trade Journal → Auditable SQLite/PostgreSQL persistence
          </div>
        </div>
      </div>
    </div>
  );
}
