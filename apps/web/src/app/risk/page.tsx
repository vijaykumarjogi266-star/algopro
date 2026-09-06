export default function RiskPage() {
  const riskRules = [
    { name: "Max Capital Per Trade", value: "5.0% of Portfolio", enforced: "Hard Limit", desc: "No single position may risk or exceed 5% total portfolio capital." },
    { name: "Portfolio Max Drawdown Stop", value: "15.0%", enforced: "Hard Circuit Breaker", desc: "System enters liquidation/wait mode if drawdown reaches 15%." },
    { name: "Daily Loss Limit", value: "3.0%", enforced: "Session Freeze", desc: "Trading halted for session if cumulative realized/unrealized loss reaches 3%." },
    { name: "Mandatory Stop-Loss", value: "Required", enforced: "Order Validation", desc: "Orders without explicit stop-loss are rejected before broker submission." },
    { name: "Maximum Leverage", value: "1.0x (No margin debt)", enforced: "Non-Negotiable", desc: "Principle 20: No hidden leverage, no margin multiplier in initial stages." },
    { name: "Martingale Prohibition", value: "Strictly Banned", enforced: "Alpha Filter", desc: "Position sizing cannot increase after losing trades." },
  ];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">Risk Engine Architecture (Decoupled)</h2>
        <p className="text-slate-400 text-xs mt-1">
          Principle 14: Risk Engine remains strictly independent from Strategy/Alpha. Principle 15: AI cannot override hard controls.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {riskRules.map((rule) => (
          <div key={rule.name} className="p-4 rounded-lg bg-surface border border-surface-border space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white text-sm">{rule.name}</span>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">
                {rule.enforced}
              </span>
            </div>
            <div className="text-lg font-mono font-bold text-accent">{rule.value}</div>
            <p className="text-xs text-slate-400 leading-relaxed">{rule.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
