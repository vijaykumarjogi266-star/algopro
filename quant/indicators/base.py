"""Algo Lab Indicator Interface & Contract.

Adheres to Non-Negotiable Principles:
- Principle 11: Indicators are evidence, not automatic trading decisions.
- Principle 12: RSI must never independently generate BUY/SELL decisions.
- Principle 13: Multiple correlated indicators must not be treated as independent evidence.
- Principle 4: No look-ahead bias (strict point-in-time causality).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
import numpy as np
import polars as pl
from pydantic import BaseModel, Field, ConfigDict


class IndicatorResult(BaseModel):
    """Encapsulates indicator calculation output with metadata and column schema."""

    indicator_name: str
    version: str
    parameters: Dict[str, Any]
    required_columns: List[str]
    output_columns: List[str]
    warm_up_period: int
    data: Dict[str, List[Optional[float]]]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_polars(self) -> pl.DataFrame:
        """Converts output arrays to a Polars DataFrame."""
        return pl.DataFrame(self.data)

    def to_numpy(self, column: Optional[str] = None) -> Union[np.ndarray, Dict[str, np.ndarray]]:
        """Converts output data to numpy array(s)."""
        if column:
            return np.array(self.data[column], dtype=float)
        return {col: np.array(vals, dtype=float) for col, vals in self.data.items()}


class IndicatorContract(ABC):
    """Abstract base class for all deterministic quantitative indicators.
    
    Guarantees:
    1. Deterministic numerical computation.
    2. Zero look-ahead bias: row T uses only rows <= T.
    3. Proper warm-up periods (NaN before warm-up, never zero-filled).
    4. Causal evidence output (never autonomous BUY/SELL execution).
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        params: Optional[Dict[str, Any]] = None,
        required_columns: Optional[List[str]] = None,
        output_columns: Optional[List[str]] = None,
        warm_up_period: int = 1,
    ):
        self.name = name
        self.version = version
        self.params = params or {}
        self.required_columns = required_columns or ["close"]
        self.output_columns = output_columns or [name.lower()]
        self.warm_up_period = warm_up_period

    @abstractmethod
    def calculate(self, closes: np.ndarray, **kwargs) -> Union[np.ndarray, Dict[str, np.ndarray]]:
        """Core mathematical calculation.
        
        Args:
            closes: Primary price series (typically close prices).
            kwargs: Auxiliary series like highs, lows, volumes, timestamps.
        Returns:
            Computed 1D numpy array or dictionary of arrays aligned with input length.
        """
        pass

    def compute(self, data: Union[pl.DataFrame, Dict[str, np.ndarray]]) -> IndicatorResult:
        """Standard vectorized interface accepting Polars DataFrame or NumPy dictionary."""
        if isinstance(data, pl.DataFrame):
            # Check required columns
            for col in self.required_columns:
                if col not in data.columns:
                    raise ValueError(f"Indicator '{self.name}' requires missing column '{col}'. Available: {data.columns}")
            closes = data["close"].to_numpy() if "close" in data.columns else np.array([])
            aux_kwargs = {}
            for col in data.columns:
                if col != "close":
                    aux_kwargs[f"{col}s" if not col.endswith("s") else col] = data[col].to_numpy()
                    aux_kwargs[col] = data[col].to_numpy()
        else:
            for col in self.required_columns:
                if col not in data:
                    raise ValueError(f"Indicator '{self.name}' requires missing column '{col}'. Available: {list(data.keys())}")
            closes = data.get("close", np.array([]))
            aux_kwargs = {k: v for k, v in data.items() if k != "close"}
            # Alias plurals for compatibility
            for k, v in data.items():
                aux_kwargs[f"{k}s" if not k.endswith("s") else k] = v

        output = self.calculate(closes, **aux_kwargs)

        if isinstance(output, np.ndarray):
            out_dict = {self.output_columns[0]: [None if np.isnan(x) else float(x) for x in output]}
        else:
            out_dict = {k: [None if np.isnan(x) else float(x) for x in v] for k, v in output.items()}

        return IndicatorResult(
            indicator_name=self.name,
            version=self.version,
            parameters=self.params,
            required_columns=self.required_columns,
            output_columns=self.output_columns,
            warm_up_period=self.warm_up_period,
            data=out_dict,
        )

    def get_evidence(
        self,
        values: Union[np.ndarray, Dict[str, np.ndarray]],
        index: int = -1,
    ) -> Dict[str, Any]:
        """Formats the computed indicator into explainable evidence.
        
        Indicators provide evidentiary context (trend, volatility, exhaustion),
        NEVER automatic trade execution commands.
        """
        if isinstance(values, np.ndarray):
            val = float(values[index]) if len(values) > 0 and not np.isnan(values[index]) else None
            metric_val = val
        else:
            metric_val = {}
            for k, v in values.items():
                metric_val[k] = float(v[index]) if len(v) > 0 and not np.isnan(v[index]) else None

        return {
            "indicator": self.name,
            "version": self.version,
            "params": self.params,
            "value": metric_val,
            "is_evidence_only": True,
        }


# Re-exports for backward compatibility with Stage 1
from quant.indicators.sma import SMA
from quant.indicators.ema import EMA
from quant.indicators.rsi import RSI
from quant.indicators.atr import ATR
