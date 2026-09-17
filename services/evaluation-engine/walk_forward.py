"""
Algo Lab — Stage 7 Walk-Forward Simulation Engine
Implements expanding and rolling window walk-forward validation with deterministic
step increments, minimum observation threshold gates, and leak prevention.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple, Optional, Any, Sequence


class WalkForwardMode(str, Enum):
    EXPANDING = "EXPANDING"
    ROLLING = "ROLLING"


class LookAheadBiasError(ValueError):
    """Raised when data past the current window boundary is accessed."""
    pass


@dataclass(frozen=True)
class WalkForwardWindow:
    step_index: int
    train_start_idx: int
    train_end_idx: int
    test_start_idx: int
    test_end_idx: int
    train_data: Optional[Any] = None
    test_data: Optional[Any] = None

    def validate_no_leakage(self, requested_index: int) -> None:
        """Validates that requested index does not exceed current step bounds (AT-30)."""
        if requested_index >= self.test_end_idx:
            raise LookAheadBiasError(
                f"Look-ahead access attempt: requested index {requested_index} "
                f"exceeds window boundary test_end_idx={self.test_end_idx} (Step {self.step_index})."
            )


@dataclass
class WalkForwardConfig:
    mode: WalkForwardMode = WalkForwardMode.EXPANDING
    initial_train_size: int = 252
    test_size: int = 63
    step_size: int = 63
    min_train_size: int = 100

    def __post_init__(self):
        # AT-29: Invalid step size rejection
        if self.step_size <= 0:
            raise ValueError(f"Step size must be strictly positive (> 0). Got: {self.step_size}")
        
        # AT-28: Sub-minimum window rejection
        if self.initial_train_size < self.min_train_size:
            raise ValueError(
                f"Initial train window size ({self.initial_train_size}) is below minimum "
                f"required threshold ({self.min_train_size})."
            )
        
        if self.test_size <= 0:
            raise ValueError(f"Test size must be strictly positive (> 0). Got: {self.test_size}")


class WalkForwardEngine:
    """Generates and manages walk-forward window sequences for strategy evaluation."""

    def __init__(self, config: Optional[WalkForwardConfig] = None):
        self.config = config or WalkForwardConfig()

    def generate_windows(
        self,
        data_length: int,
        dataset: Optional[Sequence[Any]] = None,
    ) -> List[WalkForwardWindow]:
        """Generates deterministic walk-forward windows for a dataset of length `data_length`."""
        if data_length < (self.config.initial_train_size + self.config.test_size):
            raise ValueError(
                f"Dataset length ({data_length}) is insufficient for initial_train_size "
                f"({self.config.initial_train_size}) + test_size ({self.config.test_size})."
            )

        windows: List[WalkForwardWindow] = []
        step = 0
        
        while True:
            if self.config.mode == WalkForwardMode.EXPANDING:
                train_start = 0
                train_end = self.config.initial_train_size + (step * self.config.step_size)
            elif self.config.mode == WalkForwardMode.ROLLING:
                train_start = step * self.config.step_size
                train_end = train_start + self.config.initial_train_size
            else:
                raise ValueError(f"Unknown walk-forward mode: {self.config.mode}")

            test_start = train_end
            test_end = test_start + self.config.test_size

            # Stop condition: if test window goes beyond available data length
            if test_end > data_length:
                break

            train_slice = dataset[train_start:train_end] if dataset is not None else None
            test_slice = dataset[test_start:test_end] if dataset is not None else None

            window = WalkForwardWindow(
                step_index=step,
                train_start_idx=train_start,
                train_end_idx=train_end,
                test_start_idx=test_start,
                test_end_idx=test_end,
                train_data=train_slice,
                test_data=test_slice,
            )
            windows.append(window)
            step += 1

        if not windows:
            raise ValueError("No valid walk-forward windows could be constructed with given config and data length.")

        return windows
