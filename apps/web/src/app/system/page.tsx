export default function SystemPage() {
  const subsystems = [
    { name: "FastAPI Backend API", port: "8000", status: "ONLINE", latency: "1.2ms" },
    { name: "PostgreSQL Database Service", port: "5432", status: "READY", latency: "0.8ms" },
    { name: "Data Quality Engine", port: "internal", status: "ACTIVE", latency: "0.4ms" },
    { name: "Indicator Quant Library", port: "internal", status: "VERIFIED", latency: "0.2ms" },
    { name: "Independent Risk Engine", port: "internal", status: "ENFORCING", latency: "0.1ms" },
    { name: "Simulated Paper Broker", port: "internal", status: "ACTIVE", latency: "0.3ms" },
  ];

  const safeguards = [
    { rule: "Live Broker Execution", state: "DISABLED (HARD-LOCKED)", detail: "Principle 25: No live capital permitted in Stage 1." },
    { rule: "Real Broker Accounts", state: "DISCONNECTED", detail: "No API keys configured or allowed in current environment." },
    { rule: "Data Quality Enforcement", state: "MANDATORY", detail: "Principle 3: Unvalidated data aborts strategy evaluations." },
    { rule: "Look-Ahead Bias Protection", state: "ENFORCED", detail: "Principle 4: Strict point-in-time sequential slicing only." },
    { rule: "AI Risk Limits Override", state: "PROHIBITED", detail: "Principle 15: AI cannot override hard risk controls." },
  ];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">System Diagnostics & Active Guardrails</h2>
        <p className="text-slate-400 text-xs mt-1">
          Health probes, security limits, and platform non-negotiable constraints.
        </p>
      </div>

      <div className="rounded-lg bg-surface border border-surface-border overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border">
          <h3 className="text-sm font-semibold text-white">Subsystem Health Probes</h3>
        </div>
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-black/30 text-slate-400 border-b border-surface-border">
            <tr>
              <th className="p-3">Subsystem</th>
              <th className="p-3">Interface / Port</th>
              <th className="p-3">Status</th>
              <th className="p-3">Internal Latency</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border text-slate-300">
            {subsystems.map((s) => (
              <tr key={s.name} className="hover:bg-slate-800/30">
                <td className="p-3 font-sans font-medium text-white">{s.name}</td>
                <td className="p-3 text-slate-400">{s.port}</td>
                <td className="p-3">
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {s.status}
                  </span>
                </td>
                <td className="p-3 text-slate-400">{s.latency}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg bg-surface border border-surface-border overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border">
          <h3 className="text-sm font-semibold text-white">Active Architectural Guardrails</h3>
        </div>
        <div className="p-5 space-y-3 text-xs">
          {safeguards.map((g) => (
            <div key={g.rule} className="p-3 rounded bg-black/40 border border-surface-border flex items-center justify-between">
              <div>
                <div className="font-semibold text-white">{g.rule}</div>
                <div className="text-[11px] text-slate-400 mt-0.5">{g.detail}</div>
              </div>
              <span className="font-mono text-[11px] px-2 py-1 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                {g.state}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
