# Algo Lab Stage 6 — Order Execution Lifecycle & Slippage Model

## 1. Overview
Stage 6 introduces a full lifecycle state machine for simulated and paper orders. It decouples strategy alpha generation from risk gating and execution simulation, adhering to:
- **Principle 14:** Risk Engine must remain independent from Strategy/Alpha.
- **Principle 15:** AI must never override hard risk controls.
- **Principle 19:** Performance must be evaluated after realistic costs and slippage.

---

## 2. Order Lifecycle State Machine

```
   ┌──────────────────┐
   │  ORDER_PROPOSED  │
   └────────┬─────────┘
            │
            ▼
┌────────────────────────┐
│  RISK_CHECK_EVALUATED  │
└───────────┬────────────┘
            ├──────────────────────────┐
            ▼                          ▼
   ┌─────────────────┐        ┌─────────────────┐
   │ ORDER_ACCEPTED  │        │ ORDER_REJECTED  │
   └────────┬────────┘        │ (Zero Portfolio │
            │                 │   Mutation)     │
            ▼                 └─────────────────┘
   ┌─────────────────┐
   │ ORDER_SUBMITTED │
   └────────┬────────┘
            ├──────────────────────────┬──────────────────────────┐
            ▼                          ▼                          ▼
   ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
   │  ORDER_FILLED   │        │ ORDER_CANCELLED │        │  ORDER_FAILED   │
   └─────────────────┘        └─────────────────┘        └─────────────────┘
```

---

## 3. Independent Risk Engine Gate

Before any order can be submitted:
1. `ExecutionLifecycleManager.evaluate_risk()` passes the proposed order to `RiskEngine`.
2. Hard limits evaluated:
   - Max capital per trade (default 5% of portfolio equity).
   - Mandatory stop-loss presence.
   - Max portfolio drawdown breach.
   - Daily loss limit breach.
   - Open position counts.
3. If any limit is breached:
   - Order transitions to `ORDER_REJECTED`.
   - Rejection code and human-readable explanation recorded in audit trail.
   - **Zero portfolio mutation occurs.**

---

## 4. Realistic Slippage & Statutory Friction

Once submitted, the order is filled with deterministic friction:

### Slippage Model
- **Buy Orders:** Slip upwards ($P_{\text{fill}} = P_{\text{base}} + \Delta_{\text{slip}}$).
- **Sell Orders:** Slip downwards ($P_{\text{fill}} = P_{\text{base}} - \Delta_{\text{slip}}$).
- $\Delta_{\text{slip}} = \text{fixed\_tick\_points} + (P_{\text{base}} \times \text{variable\_slippage\_pct})$.

### Indian Statutory Transaction Costs (NSE/BSE)
Every fill incurs statutory charges:
1. **Brokerage:** Min(₹20, 0.03% turnover).
2. **Securities Transaction Tax (STT):** 0.025% on intraday sell; 0.1% on delivery.
3. **Exchange Turnover Fee:** 0.00345% (NSE).
4. **SEBI Regulatory Fee:** ₹10 per crore (0.0001%).
5. **GST:** 18% on (Brokerage + Exchange Fees).
6. **Stamp Duty:** 0.015% on buy side.
