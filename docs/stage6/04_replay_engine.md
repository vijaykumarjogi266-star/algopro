# Algo Lab Stage 6 — Deterministic Historical Replay Engine

## 1. Overview
The `HistoricalReplayEngine` simulates realistic market conditions by stepping through historical canonical market data bar by bar. It guarantees:
- **Principle 4:** Strict look-ahead bias prevention.
- **Principle 7:** Full mathematical determinism and reproducibility.
- **Principle 13:** Fail-closed validation on scrambled or corrupt data feeds.

---

## 2. Strict Look-Ahead Guard Architecture

```
Timeline:  t0 --------▶ t1 --------▶ t2 (current_time) --------▶ t3 --------▶ t4
History:  [========== Visible ==========]                [==== Invisible ====]
Query:    get_history("TCS") ──▶ [t0, t1, t2]
Peeking:  peek_future(t3)   ──▶ LookAheadBiasError (FAIL CLOSED)
```

At any simulation step:
1. `engine.current_time` marks the simulated present.
2. `engine.get_history(symbol)` returns only bars where $\text{timestamp} \le \text{current\_time}$.
3. Any attempt by an indicator, alpha model, or portfolio component to access data where $\text{timestamp} > \text{current\_time}$ immediately raises a `LookAheadBiasError`.

---

## 3. Multi-Symbol Synchronization

When replaying a multi-symbol universe (e.g., `["TCS", "INFY", "RELIANCE"]`):
- All bars from all symbols are merged into a unified event queue.
- Events are sorted strictly by `(timestamp, symbol)`.
- Replay steps advance monotonically in time. At timestamp $T$, all symbols with bars at $T$ are processed before time advances to $T+1$.
- No symbol can receive future bars ahead of other symbols in the universe.

---

## 4. Indian Financial Market Calendar & Session Hours

Replay integrates with `IndianMarketCalendar`:
- **Regular Trading Hours:** 09:15 to 15:30 IST.
- **Session Enforcement:** When `enforce_session_hours=True`, off-market and post-closing events are excluded.
- **Holiday Filtering:** When `filter_holidays=True`, weekends and official NSE holidays (Republic Day, Independence Day, Diwali, etc.) are filtered out automatically.
