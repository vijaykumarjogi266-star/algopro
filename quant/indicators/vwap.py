"""Volume-Weighted Average Price (VWAP) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class VWAP(IndicatorContract):
    """Volume-Weighted Average Price (VWAP).
    
    The benchmark price representing the ratio of the cumulative value traded
    to the total cumulative volume traded over a session or trading horizon.
    Typical Price (TP) = (High + Low + Close) / 3
    VWAP = sum(TP * Volume) / sum(Volume)
    
    Includes 2-standard-deviation bands for mean-reversion analysis.
    Evidence role: Institutional benchmark reference, intraday value location, mean-reversion anchor.
    """

    def __init__(self, num_std: float = 2.0):
        super().__init__(
            name="VWAP",
            version="1.0.0",
            params={"num_std": num_std},
            required_columns=["high", "low", "close", "volume"],
            output_columns=["vwap", "vwap_upper", "vwap_lower"],
            warm_up_period=1,
        )
        self.num_std = num_std

    def calculate(self, closes: np.ndarray, **kwargs) -> Dict[str, np.ndarray]:
        highs = kwargs.get("highs", kwargs.get("high"))
        lows = kwargs.get("lows", kwargs.get("low"))
        volumes = kwargs.get("volumes", kwargs.get("volume"))

        if highs is None or lows is None or volumes is None:
            raise ValueError("VWAP requires 'highs', 'lows', and 'volumes' arrays.")

        n = len(closes)
        vwap = np.full(n, np.nan, dtype=float)
        vwap_upper = np.full(n, np.nan, dtype=float)
        vwap_lower = np.full(n, np.nan, dtype=float)

        if n == 0:
            return {"vwap": vwap, "vwap_upper": vwap_upper, "vwap_lower": vwap_lower}

        # Calculate Typical Price
        tp = (highs + lows + closes) / 3.0
        tp_v = tp * volumes

        cum_tp_v = np.cumsum(tp_v)
        cum_vol = np.cumsum(volumes)

        for i in range(n):
            if cum_vol[i] > 0:
                v = cum_tp_v[i] / cum_vol[i]
                vwap[i] = v

                # Calculate cumulative variance around VWAP up to bar i
                variance = np.sum(volumes[: i + 1] * ((tp[: i + 1] - v) ** 2)) / cum_vol[i]
                std = np.sqrt(max(variance, 0.0))

                vwap_upper[i] = v + (self.num_std * std)
                vwap_lower[i] = v - (self.num_std * std)
            else:
                vwap[i] = tp[i]
                vwap_upper[i] = tp[i]
                vwap_lower[i] = tp[i]

        return {
            "vwap": vwap,
            "vwap_upper": vwap_upper,
            "vwap_lower": vwap_lower,
        }


def compute_session_vwap(df, timezone_str: str = "Asia/Kolkata"):
    """Computes session-reset cumulative VWAP across IST sessions.

    VWAP resets at the beginning of each trading day in Asia/Kolkata timezone.
    For each session:
        TP = (High + Low + Close) / 3
        VWAP_t = sum(TP * Volume) / sum(Volume)
    """
    import pandas as pd
    from zoneinfo import ZoneInfo

    high_col = next((c for c in ["High", "high"] if c in df.columns), None)
    low_col = next((c for c in ["Low", "low"] if c in df.columns), None)
    close_col = next((c for c in ["Close", "close"] if c in df.columns), None)
    vol_col = next((c for c in ["Volume", "volume"] if c in df.columns), None)

    if high_col is None or low_col is None or close_col is None:
        raise ValueError("DataFrame must contain High, Low, Close columns")

    tp = (df[high_col].astype(float) + df[low_col].astype(float) + df[close_col].astype(float)) / 3.0
    vol = df[vol_col].astype(float) if vol_col else pd.Series(0.0, index=df.index)

    # Identify session dates
    ts = None
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = pd.to_datetime(df.index)

    if ts is not None:
        tz = ZoneInfo(timezone_str)
        if ts.dt.tz is None:
            session_dates = ts.dt.tz_localize("UTC").dt.tz_convert(tz).dt.date
        else:
            session_dates = ts.dt.tz_convert(tz).dt.date
    else:
        session_dates = pd.Series(0, index=df.index)

    vwap_res = pd.Series(index=df.index, dtype=float)

    for _, idxs in df.groupby(session_dates).groups.items():
        s_tp = tp.loc[idxs]
        s_vol = vol.loc[idxs]
        s_tp_v = (s_tp * s_vol).cumsum()
        s_cum_v = s_vol.cumsum()
        s_vwap = np.where(s_cum_v > 0, s_tp_v / s_cum_v, s_tp)
        vwap_res.loc[idxs] = s_vwap

    return vwap_res
