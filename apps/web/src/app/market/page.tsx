export default function MarketPage() {
  return (
    <div className="space-y-4 max-w-4xl">
      <h2 className="text-xl font-bold text-white">Market Intelligence & Data Feeds</h2>
      <div className="p-6 rounded-lg bg-surface border border-surface-border text-xs text-slate-300">
        <span className="font-semibold text-accent font-mono">PLANNED FOR STAGE 2 (Data & Data Quality) & STAGE 8 (Market Intelligence):</span>
        <p className="mt-2 text-slate-400">
          This view will display historical OHLCV feeds, NSE/BSE symbol catalogs, corporate actions, and live tick streams after Stage 2 data quality pipeline certification.
        </p>
      </div>
    </div>
  );
}
