# Algo Lab — Quantitative Indicator Library (Stage 3)

## 1. Overview & Architectural Philosophy

The Algo Lab Indicator Library provides a deterministic, causal, point-in-time quantitative computation layer built directly upon the validated Stage 2 data engine.

### Non-Negotiable Quantitative Principles
- **Principle 4: No Look-Ahead Bias**:
  Indicator calculations at timestamp $T$ consume ONLY information known on or before $T$. Future rows ($T+1, \dots$) never mutate past outputs.
- **Principle 11: Indicators Are Evidence, Not Automatic Trading Decisions**:
  Indicators provide quantitative features, regime context, and evidentiary support. They NEVER directly generate automatic BUY/SELL executions.
- **Principle 12: RSI Protection**:
  RSI is mathematically a momentum exhaustion oscillator. It must NEVER independently generate BUY/SELL orders.
- **Principle 13: Correlation Awareness**:
  Collinear momentum oscillators (e.g. RSI and Stochastic) must not be counted as independent evidence.

---

## 2. Standard Indicator Contract (`quant/indicators/base.py`)

Every indicator inherits from `IndicatorContract` and adheres to a strict interface:
- **`required_columns`**: Column prerequisites (e.g., `["close"]`, `["high", "low", "close", "volume"]`).
- **`output_columns`**: Schema of generated series (e.g., `["macd", "macd_signal", "macd_hist"]`).
- **`warm_up_period`**: Exact count of initial rows before producing non-NaN values.
- **`compute(data: pl.DataFrame | dict) -> IndicatorResult`**: Vectorized interface accepting Polars DataFrames and returning an immutable `IndicatorResult`.
- **`get_evidence(values, index=-1)`**: Formats numeric output into an explainable evidence dictionary for strategy evaluation.

---

## 3. Supported Indicators

### Trend Domain
1. **SMA (Simple Moving Average)** (`quant/indicators/sma.py`):
   - **Formula**: $SMA_t = \frac{1}{n}\sum_{i=0}^{n-1} Close_{t-i}$
   - **Warm-up**: `period` bars (first $period-1$ values are `NaN`).
   - **Evidence Role**: Trend direction and structural support/resistance.

2. **EMA (Exponential Moving Average)** (`quant/indicators/ema.py`):
   - **Formula**: $\alpha = \frac{2}{period + 1}$, $EMA_t = \alpha Close_t + (1 - \alpha) EMA_{t-1}$
   - **Seed**: Initial SMA of first `period` bars.
   - **Warm-up**: `period` bars.
   - **Evidence Role**: Dynamic trend trailing and momentum tracking.

3. **MACD (Moving Average Convergence Divergence)** (`quant/indicators/macd.py`):
   - **Components**:
     - MACD Line: $EMA_{fast} - EMA_{slow}$
     - Signal Line: $EMA_{signal}(MACD_{line})$
     - Histogram: $MACD_{line} - Signal_{line}$
   - **Default Parameters**: Fast = 12, Slow = 26, Signal = 9.
   - **Warm-up**: $slow\_period + signal\_period - 1$ (34 bars).
   - **Evidence Role**: Trend acceleration, deceleration, and divergence.

4. **ADX (Average Directional Index)** (`quant/indicators/adx.py`):
   - **Formulas**: Wilder's smoothing of $+DM$, $-DM$, and True Range ($TR$).
     - $+DI = 100 \times \frac{Smoothed(+DM)}{Smoothed(TR)}$, $-DI = 100 \times \frac{Smoothed(-DM)}{Smoothed(TR)}$
     - $DX = 100 \times \frac{|+DI - -DI|}{+DI + -DI}$
     - $ADX = WilderSmooth(DX, period)$
   - **Scale**: 0 to 100 (Direction-neutral trend strength).
   - **Warm-up**: $2 \times period$ (28 bars for period 14).
   - **Evidence Role**: Regime filter (Trend vs Range).

---

### Momentum Domain
5. **RSI (Relative Strength Index)** (`quant/indicators/rsi.py`):
   - **Formula**: Wilder's smoothed gains and losses:
     - $RS = \frac{SmoothedGain}{SmoothedLoss}$
     - $RSI = 100 - \frac{100}{1 + RS}$
   - **Warm-up**: $period + 1$ bars.
   - **Evidence Role**: Momentum exhaustion and mean-reversion context (Never autonomous BUY/SELL).

6. **Stochastic Oscillator** (`quant/indicators/stochastic.py`):
   - **Components**:
     - Fast $\%K = 100 \times \frac{Close - LowestLow}{HighestHigh - LowestLow}$
     - Slow $\%K = SMA(Fast \%K, slowing)$
     - $\%D = SMA(Slow \%K, d\_period)$
   - **Warm-up**: $k\_period + slowing + d\_period - 2$.
   - **Evidence Role**: Location within recent range, oscillator turns.

7. **ROC (Rate of Change)** (`quant/indicators/roc.py`):
   - **Formula**: $ROC_t = \frac{Close_t - Close_{t-period}}{Close_{t-period}} \times 100$
   - **Warm-up**: `period` bars.
   - **Evidence Role**: Momentum velocity and thrust.

---

### Volatility Domain
8. **ATR (Average True Range)** (`quant/indicators/atr.py`):
   - **Formula**: Wilder's RMA of True Range:
     - $TR_t = \max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)$
     - $ATR_t = \frac{ATR_{t-1} \times (n-1) + TR_t}{n}$
   - **Warm-up**: `period` bars.
   - **Evidence Role**: Dynamic stop-loss distances and volatility normalization.

9. **Bollinger Bands** (`quant/indicators/bollinger.py`):
   - **Components**:
     - Middle Band = $SMA(Close, period)$
     - Upper Band = $Middle + (k \times \sigma)$
     - Lower Band = $Middle - (k \times \sigma)$
     - Bandwidth = $\frac{Upper - Lower}{Middle} \times 100$
     - $\%B = \frac{Close - Lower}{Upper - Lower}$
   - **Warm-up**: `period` bars.
   - **Evidence Role**: Volatility squeeze detection and statistical boundaries.

10. **Realized Volatility** (`quant/indicators/realized_volatility.py`):
    - **Formula**: Sample standard deviation of log returns annualized:
      - $r_t = \ln(Close_t / Close_{t-1})$
      - $RealizedVol = \text{std}(r, period) \times \sqrt{annualization\_factor} \times 100$
    - **Default Annualization**: 252.0 (Trading days per year).
    - **Warm-up**: $period + 1$ bars.
    - **Evidence Role**: Historical volatility clustering and options pricing reference.

---

### Volume Domain
11. **VWAP (Volume-Weighted Average Price)** (`quant/indicators/vwap.py`):
    - **Formula**:
      - Typical Price $TP = (High + Low + Close) / 3$
      - $VWAP_t = \frac{\sum (TP \times Volume)}{\sum Volume}$
      - Includes 2-standard-deviation bands.
    - **Warm-up**: 1 bar.
    - **Evidence Role**: Intraday value reference and institutional execution benchmarking.

12. **OBV (On-Balance Volume)** (`quant/indicators/obv.py`):
    - **Formula**: Cumulative running volume signed by price direction:
      - $OBV_t = OBV_{t-1} + Volume_t$ if $Close_t > Close_{t-1}$
      - $OBV_t = OBV_{t-1} - Volume_t$ if $Close_t < Close_{t-1}$
    - **Warm-up**: 1 bar.
    - **Evidence Role**: Volume accumulation/distribution and divergence.

13. **Relative Volume (RVOL)** (`quant/indicators/relative_volume.py`):
    - **Formula**: $RVOL_t = \frac{Volume_t}{SMA(Volume, period)_t}$
    - **Warm-up**: `period` bars.
    - **Evidence Role**: Breakout participation and liquidity expansion validation.

---

## 4. Usage Example with Polars

```python
import polars as pl
from quant.indicators import BollingerBands, RSI, VWAP

# Load validated market data from Stage 2 storage
df = pl.read_parquet("data/processed/NSE/5m/RELIANCE/2024.parquet")

# 1. Bollinger Bands
bb = BollingerBands(period=20, num_std=2.0)
bb_result = bb.compute(df)
df_with_bb = pl.concat([df, bb_result.to_polars()], how="horizontal")

# 2. RSI (Evidence Only)
rsi = RSI(period=14)
rsi_result = rsi.compute(df)
df_features = pl.concat([df_with_bb, rsi_result.to_polars()], how="horizontal")
```

---

## 5. Testing & Verification Methodology

Every indicator is covered by rigorous unit tests in `tests/unit/test_indicators_stage3.py`:
- **Correctness**: Validated against analytical reference calculations.
- **Edge Cases**: Zero volume, constant prices, insufficient observations.
- **Look-Ahead Protection**: Parameterized tests verifying that appending future data points does NOT alter historical outputs at time $T$.
- **Determinism**: Verified bitwise identical results across repeated executions.
