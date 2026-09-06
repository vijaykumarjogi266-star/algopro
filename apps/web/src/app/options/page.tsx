export default function OptionsPage() {
  return (
    <div className="space-y-4 max-w-4xl">
      <h2 className="text-xl font-bold text-white">Options Lab & Derivatives Research</h2>
      <div className="p-6 rounded-lg bg-surface border border-surface-border text-xs text-slate-300">
        <span className="font-semibold text-accent font-mono">PLANNED FOR STAGE 11 & 12 (Options Lab & Intraday Expiry):</span>
        <p className="mt-2 text-slate-400">
          This view will provide options Greeks modeling, volatility surfaces, options hedging payoff matrices, and expiry-day pin risk analysis for NIFTY/BANKNIFTY contracts.
        </p>
      </div>
    </div>
  );
}
