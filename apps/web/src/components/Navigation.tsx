"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  LineChart,
  FlaskConical,
  Briefcase,
  ShieldAlert,
  Layers,
  Bot,
  Activity,
  CheckCircle2,
  Lock,
} from "lucide-react";

export function Navigation() {
  const pathname = usePathname();

  const navItems = [
    { label: "Home", href: "/", icon: LayoutDashboard },
    { label: "Market", href: "/market", icon: LineChart },
    { label: "Research", href: "/research", icon: FlaskConical },
    { label: "Backtests", href: "/backtests", icon: LineChart },
    { label: "Strategies", href: "/strategies", icon: Layers },
    { label: "Paper Trading", href: "/paper-trading", icon: Briefcase },
    { label: "Portfolio", href: "/portfolio", icon: Briefcase },
    { label: "Risk", href: "/risk", icon: ShieldAlert },
    { label: "Options", href: "/options", icon: Layers },
    { label: "AI Analyst", href: "/ai-analyst", icon: Bot },
    { label: "System", href: "/system", icon: Activity },
  ];

  return (
    <aside className="w-64 border-r border-surface-border bg-surface flex flex-col justify-between shrink-0 h-screen sticky top-0">
      <div>
        <div className="p-5 border-b border-surface-border">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded bg-gradient-to-tr from-accent-muted to-accent flex items-center justify-center font-bold text-black text-sm">
              AL
            </div>
            <div>
              <h1 className="font-bold text-sm tracking-wide text-white">ALGO LAB</h1>
              <p className="text-[10px] text-slate-400 font-mono">QUANT OS • STAGE 1</p>
            </div>
          </div>
        </div>

        <div className="px-3 py-4">
          <div className="px-3 pb-2 text-[10px] font-semibold text-slate-400 uppercase tracking-wider font-mono">
            Navigation
          </div>
          <nav className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-3 px-3 py-2 rounded-md text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-accent/10 text-accent border border-accent/20"
                      : "text-slate-300 hover:text-white hover:bg-slate-800/60"
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? "text-accent" : "text-slate-400"}`} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>

      <div className="p-4 border-t border-surface-border bg-black/20">
        <div className="rounded border border-amber-500/20 bg-amber-500/5 p-2.5">
          <div className="flex items-center space-x-1.5 text-amber-400 text-xs font-semibold">
            <Lock className="w-3.5 h-3.5" />
            <span>Safety Guard Active</span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            Stage 1: Real broker execution & live trading strictly disabled.
          </p>
        </div>
      </div>
    </aside>
  );
}
