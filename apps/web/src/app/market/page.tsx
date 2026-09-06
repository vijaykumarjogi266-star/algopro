export default function MarketPage() {
  const instruments = [
    { symbol: "NIFTY 50", name: "NIFTY 50 Index", exchange: "NSE", segment: "INDEX", tickSize: "₹0.05", lotSize: 25, listed: "1996-04-22", status: "ACTIVE" },
    { symbol: "BANKNIFTY", name: "NIFTY Bank Index", exchange: "NSE", segment: "INDEX", tickSize: "₹0.05", lotSize: 15, listed: "2003-06-09", status: "ACTIVE" },
    { symbol: "RELIANCE", name: "Reliance Industries Ltd", exchange: "NSE", segment: "EQUITY", tickSize: "₹0.05", lotSize: 1, listed: "1995-11-29", status: "ACTIVE" },
    { symbol: "TCS", name: "Tata Consultancy Services", exchange: "NSE", segment: "EQUITY", tickSize: "₹0.05", lotSize: 1, listed: "2004-08-25", status: "ACTIVE" },
    { symbol: "HDFCBANK", name: "HDFC Bank Ltd", exchange: "NSE", segment: "EQUITY", tickSize: "₹0.05", lotSize: 1, listed: "1995-05-19", status: "ACTIVE" },
    { symbol: "INFY", name: "Infosys Ltd", exchange: "NSE", segment: "EQUITY", tickSize: "₹0.05", lotSize: 1, listed: "1993-06-14", status: "ACTIVE" },
    { symbol: "ICICIBANK", name: "ICICI Bank Ltd", exchange: "NSE", segment: "EQUITY", tickSize: "₹0.05", lotSize: 1, listed: "1997-09-17", status: "ACTIVE" },
    { symbol: "RCOM", name: "Reliance Communications (Delisted)", exchange: "NSE", segment: "EQUITY", tickSize: "₹0.05", lotSize: 1, listed: "2006-03-06", status: "DELISTED (2021)" },
  ];

  const qualityDimensions = [
    { id: 1, name: "Missing Data Detection", desc: "Calendar-aware session gap detection (375 min/day)", status: "ENFORCED" },
    { id: 2, name: "Duplicate Detection", desc: "Prevents duplicate market timestamps and conflicting bars", status: "ENFORCED" },
    { id: 3, name: "Timestamp Validation", desc: "Strictly monotonically ascending order (Look-ahead protection)", status: "ENFORCED" },
    { id: 4, name: "Invalid OHLC Detection", desc: "Enforces High >= max(Open, Close) and Low <= min(Open, Close)", status: "ENFORCED" },
    { id: 5, name: "Zero/Negative Prices", desc: "Rejects any price <= 0 immediately", status: "ENFORCED" },
    { id: 6, name: "Volume Anomaly Detection", desc: "Rejects negative volumes; flags extreme volume spikes (>25x)", status: "ENFORCED" },
    { id: 7, name: "Stale Data Detection", desc: "Flags flat O=H=L=C streaks exceeding 5 bars as SUSPECT", status: "ENFORCED" },
    { id: 8, name: "Trading-Session Validation", desc: "Rejects bars outside 09:15-15:30 IST or on NSE exchange holidays", status: "ENFORCED" },
    { id: 9, name: "Symbol Validation", desc: "Validates against Instrument Master and listing time bounds", status: "ENFORCED" },
    { id: 10, name: "Corporate-Action Validation", desc: "Verifies splits, bonus 1:1, cash dividends point-in-time", status: "ENFORCED" },
    { id: 11, name: "Point-in-Time Validation", desc: "Rejects future timestamps and ingestion violations", status: "ENFORCED" },
  ];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-white">Market Data & Data Quality Engine</h2>
        <p className="text-slate-400 text-xs mt-1">
          Stage 2: Authoritative Indian Market Calendar, Instrument Master, Point-in-Time Corporate Actions, and 11-Dimensional Quality Gate.
        </p>
      </div>

      {/* Indian Market Session Diagnostic */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">EXCHANGE TIMEZONE</div>
          <div className="text-lg font-bold text-white mt-1">IST (UTC +05:30)</div>
          <div className="text-[11px] text-slate-400 mt-1">Asia/Kolkata Canonical Reference</div>
        </div>

        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">REGULAR SESSION HOURS</div>
          <div className="text-lg font-bold text-white mt-1">09:15 – 15:30 IST</div>
          <div className="text-[11px] text-slate-400 mt-1">375 Trading Minutes / Session</div>
        </div>

        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="text-xs text-slate-400 font-mono">SURVIVORSHIP BIAS GUARD</div>
          <div className="text-lg font-bold text-emerald-400 mt-1">Active (Principle 6)</div>
          <div className="text-[11px] text-slate-400 mt-1">Delisted Symbols Preserved in Registry</div>
        </div>
      </div>

      {/* 11-Dimensional Quality Engine Matrix */}
      <div className="rounded-lg bg-surface border border-surface-border overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">11-Dimensional Data Quality Gate (Principle 3)</h3>
          <span className="text-xs font-mono text-emerald-400 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
            ALL DIMENSIONS ACTIVE
          </span>
        </div>
        <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {qualityDimensions.map((dim) => (
            <div key={dim.id} className="p-3 rounded bg-black/40 border border-surface-border flex items-start justify-between">
              <div>
                <div className="text-xs font-semibold text-white flex items-center space-x-2">
                  <span className="text-accent font-mono">{dim.id}.</span>
                  <span>{dim.name}</span>
                </div>
                <div className="text-[11px] text-slate-400 mt-1">{dim.desc}</div>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 shrink-0">
                {dim.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Instrument Master Directory */}
      <div className="rounded-lg bg-surface border border-surface-border overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border">
          <h3 className="text-sm font-semibold text-white">Instrument Master & Symbol Mapping</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-black/30 text-slate-400 border-b border-surface-border">
              <tr>
                <th className="p-3">Symbol</th>
                <th className="p-3">Name</th>
                <th className="p-3">Exchange</th>
                <th className="p-3">Segment</th>
                <th className="p-3">Tick Size</th>
                <th className="p-3">Lot Size</th>
                <th className="p-3">Listed Date</th>
                <th className="p-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-slate-300">
              {instruments.map((i) => (
                <tr key={i.symbol} className="hover:bg-slate-800/30">
                  <td className="p-3 text-accent font-bold">{i.symbol}</td>
                  <td className="p-3 font-sans font-medium text-white">{i.name}</td>
                  <td className="p-3">{i.exchange}</td>
                  <td className="p-3">{i.segment}</td>
                  <td className="p-3">{i.tickSize}</td>
                  <td className="p-3">{i.lotSize}</td>
                  <td className="p-3 text-slate-400">{i.listed}</td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded ${
                      i.status === "ACTIVE"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                    }`}>
                      {i.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
