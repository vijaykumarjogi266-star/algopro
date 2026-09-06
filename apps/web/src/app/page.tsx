import Link from "next/link";
import { ShieldCheck, Activity, Database, Scale, BarChart3, ArrowRight } from "lucide-react";

export default function HomePage() {
  const principles = [
    "Never force a trade.",
    "WAIT is a valid decision.",
    "Bad or uncertain data must not produce a trading decision.",
    "No look-ahead bias.",
    "No data leakage.",
    "Every backtest must be reproducible.",
    "Every strategy & dataset must be versioned.",
    "Indicators are evidence, not automatic trading decisions.",
    "RSI must never independently generate BUY/SELL decisions.",
    "Risk Engine must remain independent from Strategy/Alpha.",
    "AI must never override hard risk controls.",
    "Evaluate portfolio-level risk, not only individual trades.",
    "Simple UI; sophisticated engineering underneath.",
    "Reliability is more important than feature count.",
    "No live capital deployment during initial development stages.",
  ];

  return (
    <div className="space-y-8 max-w-6xl">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white">Algo Lab Operating System</h2>
        <p className="text-slate-400 text-sm mt-1">
          Systematic quantitative investment and trading research platform for Indian markets.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono">CORE STATUS</span>
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-lg font-bold text-white mt-2">Stage 1 Foundation</div>
          <p className="text-xs text-slate-400 mt-1">Architecture & Contracts Active</p>
        </div>

        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono">SAFETY LOCKS</span>
            <ShieldCheck className="w-4 h-4 text-sky-400" />
          </div>
          <div className="text-lg font-bold text-white mt-2">Enforced</div>
          <p className="text-xs text-slate-400 mt-1">Live Trading Hard-Disabled</p>
        </div>

        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono">DATA INTEGRITY</span>
            <Database className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-lg font-bold text-white mt-2">Strict Validation</div>
          <p className="text-xs text-slate-400 mt-1">Point-in-Time Monotonic Check</p>
        </div>

        <div className="p-4 rounded-lg bg-surface border border-surface-border">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono">RISK INDEPENDENCE</span>
            <Scale className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-lg font-bold text-white mt-2">Decoupled</div>
          <p className="text-xs text-slate-400 mt-1">Alpha Cannot Override Limits</p>
        </div>
      </div>

      {/* Useful Stage 1 Screens */}
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider font-mono text-slate-300 mb-3">
          Stage 1 Active Screens
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link
            href="/backtests"
            className="p-5 rounded-lg bg-surface border border-surface-border hover:border-accent/40 transition-colors group block"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white group-hover:text-accent flex items-center">
                Backtest Engine
              </span>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-transform group-hover:translate-x-1" />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              Inspect reproducible backtest contracts, slippage models, transaction cost models, and metrics.
            </p>
          </Link>

          <Link
            href="/strategies"
            className="p-5 rounded-lg bg-surface border border-surface-border hover:border-accent/40 transition-colors group block"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white group-hover:text-accent flex items-center">
                Strategy Framework
              </span>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-transform group-hover:translate-x-1" />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              Explore the strategy contract, evidence-based signals, and explicit WAIT decision handling.
            </p>
          </Link>

          <Link
            href="/paper-trading"
            className="p-5 rounded-lg bg-surface border border-surface-border hover:border-accent/40 transition-colors group block"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white group-hover:text-accent flex items-center">
                Paper Trading
              </span>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-transform group-hover:translate-x-1" />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              Review simulated broker interface, order simulation pipeline, and execution safety barriers.
            </p>
          </Link>

          <Link
            href="/research"
            className="p-5 rounded-lg bg-surface border border-surface-border hover:border-accent/40 transition-colors group block"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white group-hover:text-accent flex items-center">
                Research & Experiments
              </span>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-transform group-hover:translate-x-1" />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              Auditable experiments, git commit reproducibility tracking, and dataset versioning registry.
            </p>
          </Link>

          <Link
            href="/system"
            className="p-5 rounded-lg bg-surface border border-surface-border hover:border-accent/40 transition-colors group block"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white group-hover:text-accent flex items-center">
                System Health
              </span>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-transform group-hover:translate-x-1" />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              Live FastAPI connectivity probes, database health status, and safety policy enforcement.
            </p>
          </Link>

          <Link
            href="/risk"
            className="p-5 rounded-lg bg-surface border border-surface-border hover:border-accent/40 transition-colors group block"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white group-hover:text-accent flex items-center">
                Hard Risk Engine
              </span>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-transform group-hover:translate-x-1" />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              View immutable risk limits (capital allocation, max drawdown, mandatory stop loss) protecting capital.
            </p>
          </Link>
        </div>
      </div>

      {/* Non-Negotiable Quant Principles */}
      <div className="p-6 rounded-lg bg-surface border border-surface-border">
        <h3 className="text-sm font-semibold uppercase tracking-wider font-mono text-slate-300 mb-4">
          Non-Negotiable Quant Principles (15 of 25)
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {principles.map((p, idx) => (
            <div key={idx} className="flex items-start space-x-2 text-xs text-slate-300">
              <span className="text-accent font-mono shrink-0 font-bold">{idx + 1}.</span>
              <span>{p}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
