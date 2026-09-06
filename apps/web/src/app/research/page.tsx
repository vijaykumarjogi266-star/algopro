export default function ResearchPage() {
  const datasets = [
    {
      id: "DS-NSE-EQ-DAILY-2024",
      symbol: "NSE NIFTY 500",
      timeframe: "1d",
      span: "2018-01-01 to 2024-12-31",
      version: "v1.2.0",
      quality: "VALIDATED",
      pointInTime: "Verified",
    },
    {
      id: "DS-NSE-NIFTY-5M-2024",
      symbol: "NIFTY Index Futures",
      timeframe: "5m",
      span: "2023-01-01 to 2024-12-31",
      version: "v1.0.1",
      quality: "VALIDATED",
      pointInTime: "Verified",
    },
  ];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">Research & Auditable Experiments</h2>
        <p className="text-slate-400 text-xs mt-1">
          Principle 9: Every dataset is versioned. Principle 10: Every experiment is auditable and immutable.
        </p>
      </div>

      <div className="rounded-lg bg-surface border border-surface-border overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border">
          <h3 className="text-sm font-semibold text-white">Versioned Research Datasets</h3>
        </div>
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-black/30 text-slate-400 border-b border-surface-border">
            <tr>
              <th className="p-3">Dataset ID</th>
              <th className="p-3">Universe</th>
              <th className="p-3">Timeframe</th>
              <th className="p-3">Temporal Span</th>
              <th className="p-3">Version</th>
              <th className="p-3">Point-in-Time Status</th>
              <th className="p-3">Quality Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border text-slate-300">
            {datasets.map((d) => (
              <tr key={d.id} className="hover:bg-slate-800/30">
                <td className="p-3 text-accent">{d.id}</td>
                <td className="p-3 font-sans font-medium text-white">{d.symbol}</td>
                <td className="p-3">{d.timeframe}</td>
                <td className="p-3 text-slate-400">{d.span}</td>
                <td className="p-3">{d.version}</td>
                <td className="p-3 text-emerald-400">{d.pointInTime}</td>
                <td className="p-3">
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {d.quality}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
