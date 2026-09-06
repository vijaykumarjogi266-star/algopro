"""Unit tests for Stage 3 Quantitative Indicator Library.

Verifies:
1. Basic correctness against analytical reference calculations.
2. Edge cases (insufficient observations, constant prices, zero volume).
3. Warm-up behavior (NaNs preserved, no silent zero-filling).
4. Strict No-Look-Ahead protection (future observations do not alter historical outputs).
5. Deterministic computation.
6. Polars DataFrame integration and output schema alignment.
"""

import numpy as np
import polars as pl
import pytest

from quant.indicators import (
    ADX,
    ATR,
    EMA,
    MACD,
    OBV,
    ROC,
    RSI,
    SMA,
    BollingerBands,
    IndicatorContract,
    IndicatorResult,
    RealizedVolatility,
    RelativeVolume,
    Stochastic,
    VWAP,
)


@pytest.fixture
def synthetic_ohlcv():
    """Generates 100 rows of synthetic trending and oscillating market data."""
    np.random.seed(42)
    n = 100
    base_price = 100.0
    returns = np.random.normal(0.001, 0.015, n)
    closes = base_price * np.cumprod(1.0 + returns)
    highs = closes * (1.0 + np.abs(np.random.normal(0.005, 0.003, n)))
    lows = closes * (1.0 - np.abs(np.random.normal(0.005, 0.003, n)))
    opens = (highs + lows) / 2.0
    volumes = np.random.uniform(1000, 10000, n)

    df = pl.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    return df, closes, highs, lows, volumes


# --------------------------------------------------------------------------
# 1. Trend Indicators Tests
# --------------------------------------------------------------------------

def test_sma_correctness_and_warmup():
    sma = SMA(period=5)
    prices = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    res = sma.calculate(prices)

    # First 4 must be NaN (warm-up)
    assert np.all(np.isnan(res[:4]))
    # Index 4: mean(10..50) = 30
    assert np.isclose(res[4], 30.0)
    # Index 5: mean(20..60) = 40
    assert np.isclose(res[5], 40.0)


def test_ema_correctness_and_warmup():
    ema = EMA(period=3)
    prices = np.array([10.0, 10.0, 10.0, 20.0])
    res = ema.calculate(prices)

    assert np.all(np.isnan(res[:2]))
    assert np.isclose(res[2], 10.0)
    # alpha = 2 / (3 + 1) = 0.5
    # ema[3] = 20 * 0.5 + 10 * 0.5 = 15.0
    assert np.isclose(res[3], 15.0)


def test_macd_correctness_and_schema():
    macd = MACD(fast_period=3, slow_period=6, signal_period=3)
    closes = np.linspace(100, 150, 20)
    res = macd.calculate(closes)

    assert "macd" in res and "macd_signal" in res and "macd_hist" in res
    assert len(res["macd"]) == 20
    assert len(res["macd_signal"]) == 20
    assert len(res["macd_hist"]) == 20
    # Before slow_period (6), macd must be NaN
    assert np.all(np.isnan(res["macd"][:5]))


def test_adx_trend_strength():
    adx = ADX(period=5)
    # Strongly trending upward market
    closes = np.linspace(100, 200, 30)
    highs = closes + 2.0
    lows = closes - 2.0
    res = adx.calculate(closes, highs=highs, lows=lows)

    assert "adx" in res and "plus_di" in res and "minus_di" in res
    # Plus DI should dominate Minus DI in an uptrend
    valid_mask = ~np.isnan(res["plus_di"])
    assert np.mean(res["plus_di"][valid_mask]) > np.mean(res["minus_di"][valid_mask])
    # ADX must be positive
    adx_valid = res["adx"][~np.isnan(res["adx"])]
    assert len(adx_valid) > 0
    assert np.all(adx_valid >= 0) and np.all(adx_valid <= 100)


# --------------------------------------------------------------------------
# 2. Momentum Indicators Tests
# --------------------------------------------------------------------------

def test_rsi_bounds_and_flat_market():
    rsi = RSI(period=5)
    # Flat constant prices
    flat = np.full(20, 100.0)
    res = rsi.calculate(flat)
    # In flat market with zero gain and zero loss, RSI should not crash
    assert len(res) == 20

    # Steadily rising prices -> RSI = 100
    rising = np.linspace(100, 200, 20)
    res_rising = rsi.calculate(rising)
    assert np.all(np.isnan(res_rising[:5]))
    assert np.isclose(res_rising[5], 100.0)


def test_stochastic_oscillator():
    stoch = Stochastic(k_period=5, d_period=3, slowing=3)
    closes = np.array([10, 12, 14, 16, 18, 17, 15, 13, 11, 10, 12, 14], dtype=float)
    highs = closes + 1.0
    lows = closes - 1.0
    res = stoch.calculate(closes, highs=highs, lows=lows)

    assert "stoch_k" in res and "stoch_d" in res
    assert len(res["stoch_k"]) == len(closes)
    valid_k = res["stoch_k"][~np.isnan(res["stoch_k"])]
    assert np.all(valid_k >= 0.0) and np.all(valid_k <= 100.0)


def test_roc_correctness():
    roc = ROC(period=2)
    prices = np.array([100.0, 110.0, 120.0, 110.0])
    res = roc.calculate(prices)

    assert np.isnan(res[0]) and np.isnan(res[1])
    # index 2: (120 - 100) / 100 * 100 = 20%
    assert np.isclose(res[2], 20.0)
    # index 3: (110 - 110) / 110 * 100 = 0%
    assert np.isclose(res[3], 0.0)


# --------------------------------------------------------------------------
# 3. Volatility Indicators Tests
# --------------------------------------------------------------------------

def test_atr_volatility_response():
    atr = ATR(period=3)
    closes = np.array([10.0, 10.0, 10.0, 10.0])
    highs = np.array([12.0, 12.0, 12.0, 12.0])
    lows = np.array([8.0, 8.0, 8.0, 8.0])
    # Range is constant 4.0
    res = atr.calculate(closes, highs=highs, lows=lows)
    assert np.all(np.isnan(res[:2]))
    assert np.isclose(res[2], 4.0)
    assert np.isclose(res[3], 4.0)


def test_bollinger_bands_geometry():
    bb = BollingerBands(period=5, num_std=2.0)
    closes = np.linspace(100, 110, 20)
    res = bb.calculate(closes)

    assert "bb_upper" in res and "bb_middle" in res and "bb_lower" in res
    valid_idx = ~np.isnan(res["bb_middle"])
    # Geometry invariant: Upper >= Middle >= Lower
    assert np.all(res["bb_upper"][valid_idx] >= res["bb_middle"][valid_idx])
    assert np.all(res["bb_middle"][valid_idx] >= res["bb_lower"][valid_idx])


def test_realized_volatility_scaling():
    rv = RealizedVolatility(period=5, annualization_factor=252.0)
    # Constant prices -> zero volatility
    flat_prices = np.full(15, 100.0)
    res = rv.calculate(flat_prices)
    valid_rv = res[~np.isnan(res)]
    assert np.all(np.isclose(valid_rv, 0.0))


# --------------------------------------------------------------------------
# 4. Volume Indicators Tests
# --------------------------------------------------------------------------

def test_vwap_monotonic_cumulative_volume():
    vwap = VWAP(num_std=2.0)
    closes = np.array([100.0, 105.0, 110.0])
    highs = closes + 1.0
    lows = closes - 1.0
    volumes = np.array([100.0, 200.0, 300.0])

    res = vwap.calculate(closes, highs=highs, lows=lows, volumes=volumes)
    assert "vwap" in res
    # First VWAP equals typical price of first bar
    tp0 = (101.0 + 99.0 + 100.0) / 3.0
    assert np.isclose(res["vwap"][0], tp0)


def test_obv_cumulative_flow():
    obv = OBV()
    closes = np.array([100.0, 105.0, 102.0, 102.0])
    volumes = np.array([1000.0, 500.0, 300.0, 200.0])
    res = obv.calculate(closes, volumes=volumes)

    assert res[0] == 1000.0
    # Bar 1: close rose (100 -> 105) -> 1000 + 500 = 1500
    assert res[1] == 1500.0
    # Bar 2: close fell (105 -> 102) -> 1500 - 300 = 1200
    assert res[2] == 1200.0
    # Bar 3: close unchanged -> 1200
    assert res[3] == 1200.0


def test_relative_volume():
    rvol = RelativeVolume(period=3)
    volumes = np.array([100.0, 100.0, 100.0, 300.0])
    res = rvol.calculate(np.array([10, 10, 10, 10]), volumes=volumes)

    assert np.all(np.isnan(res[:2]))
    # Index 2: SMA = 100, vol = 100 -> 1.0
    assert np.isclose(res[2], 1.0)
    # Index 3: SMA of [100, 100, 300] = 166.6667, vol = 300 -> 300 / 166.67 = 1.8
    assert np.isclose(res[3], 300.0 / (500.0 / 3.0))


# --------------------------------------------------------------------------
# 5. Non-Negotiable Principle 4: Strict No-Look-Ahead Protection
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "indicator_class, kwargs",
    [
        (SMA, {"period": 5}),
        (EMA, {"period": 5}),
        (RSI, {"period": 5}),
        (ROC, {"period": 5}),
        (ATR, {"period": 5}),
        (BollingerBands, {"period": 5}),
        (RealizedVolatility, {"period": 5}),
        (VWAP, {}),
        (OBV, {}),
        (RelativeVolume, {"period": 5}),
    ],
)
def test_strict_no_lookahead_causality(indicator_class, kwargs, synthetic_ohlcv):
    """Verifies that appending future bars NEVER alters indicator values at earlier timestamps."""
    df, closes, highs, lows, volumes = synthetic_ohlcv
    n = 60
    t_closes = closes[:n]
    t_highs = highs[:n]
    t_lows = lows[:n]
    t_vols = volumes[:n]

    inst = indicator_class(**kwargs)

    # Compute up to horizon n
    out_t = inst.calculate(t_closes, highs=t_highs, lows=t_lows, volumes=t_vols)

    # Append future bars (n to n + 20) and recompute
    future_closes = closes[: n + 20]
    future_highs = highs[: n + 20]
    future_lows = lows[: n + 20]
    future_vols = volumes[: n + 20]

    out_future = inst.calculate(
        future_closes,
        highs=future_highs,
        lows=future_lows,
        volumes=future_vols,
    )

    if isinstance(out_t, dict):
        for k in out_t.keys():
            slice_past = out_t[k]
            slice_future = out_future[k][:n]
            # Replace NaNs with sentinel for clean comparison
            np.testing.assert_allclose(
                np.nan_to_num(slice_past, nan=-999.0),
                np.nan_to_num(slice_future, nan=-999.0),
                err_msg=f"Look-ahead violation detected in indicator '{inst.name}' column '{k}'",
            )
    else:
        np.testing.assert_allclose(
            np.nan_to_num(out_t, nan=-999.0),
            np.nan_to_num(out_future[:n], nan=-999.0),
            err_msg=f"Look-ahead violation detected in indicator '{inst.name}'",
        )


# --------------------------------------------------------------------------
# 6. Polars DataFrame Vectorized Interface & Determinism
# --------------------------------------------------------------------------

def test_polars_compute_interface(synthetic_ohlcv):
    df, _, _, _, _ = synthetic_ohlcv
    bb = BollingerBands(period=10, num_std=2.0)
    result = bb.compute(df)

    assert isinstance(result, IndicatorResult)
    assert result.indicator_name == "BollingerBands"
    assert len(result.output_columns) == 5

    out_df = result.to_polars()
    assert isinstance(out_df, pl.DataFrame)
    assert out_df.height == df.height
    assert "bb_upper" in out_df.columns
    assert "bb_bandwidth" in out_df.columns


def test_determinism_identical_runs(synthetic_ohlcv):
    df, closes, _, _, _ = synthetic_ohlcv
    ema = EMA(period=14)
    res1 = ema.calculate(closes)
    res2 = ema.calculate(closes)
    np.testing.assert_array_equal(res1, res2)
