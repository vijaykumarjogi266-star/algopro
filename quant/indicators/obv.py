"""On-Balance Volume (OBV) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class OBV(IndicatorContract):
    """On-Balance Volume (OBV).
    
    Cumulative momentum indicator relating volume flow to price changes.
    When Close > Close_prev -> OBV = OBV_prev + Volume
    When Close < Close_prev -> OBV = OBV_prev - Volume
    When Close == Close_prev -> OBV = OBV_prev
    
    Evidence role: Institutional accumulation/distribution, volume divergence vs price.
    """

    def __init__(self):
        super().__init__(
            name="OBV",
            version="1.0.0",
            params={},
            required_columns=["close", "volume"],
            output_columns=["obv"],
            warm_up_period=1,
        )

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        volumes = kwargs.get("volumes", kwargs.get("volume"))
        if volumes is None:
            raise ValueError("OBV calculation requires 'volumes' array.")

        n = len(closes)
        if n == 0:
            return np.array([], dtype=float)

        obv = np.zeros(n, dtype=float)
        obv[0] = volumes[0]

        for i in range(1, n):
            if closes[i] > closes[i - 1]:
                obv[i] = obv[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                obv[i] = obv[i - 1] - volumes[i]
            else:
                obv[i] = obv[i - 1]

        return obv
