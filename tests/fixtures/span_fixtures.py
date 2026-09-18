"""
Algo Lab — Stage 12 Research & Test SPAN Fixtures
Exclusively for offline research replay and test fixture generation.
NOT imported or callable by production code.
"""

from typing import List


def generate_synthetic_16_scenarios(spot: float, psr: float, vsr: float) -> List[float]:
    """Generates standard NSE SPAN 16 price/volatility scenario loss multipliers for offline testing."""
    return [
        0.0,                        # Scenario 1: Price 0, Vol +VSR
        0.0,                        # Scenario 2: Price 0, Vol -VSR
        (1 / 3) * psr + vsr * spot, # Scenario 3: +1/3 PSR, +VSR
        (1 / 3) * psr - vsr * spot, # Scenario 4: +1/3 PSR, -VSR
        -(1 / 3) * psr + vsr * spot,# Scenario 5: -1/3 PSR, +VSR
        -(1 / 3) * psr - vsr * spot,# Scenario 6: -1/3 PSR, -VSR
        (2 / 3) * psr + vsr * spot, # Scenario 7: +2/3 PSR, +VSR
        (2 / 3) * psr - vsr * spot, # Scenario 8: +2/3 PSR, -VSR
        -(2 / 3) * psr + vsr * spot,# Scenario 9: -2/3 PSR, +VSR
        -(2 / 3) * psr - vsr * spot,# Scenario 10: -2/3 PSR, -VSR
        1.0 * psr + vsr * spot,     # Scenario 11: +1 PSR, +VSR
        1.0 * psr - vsr * spot,     # Scenario 12: +1 PSR, -VSR
        -1.0 * psr + vsr * spot,    # Scenario 13: -1 PSR, +VSR
        -1.0 * psr - vsr * spot,    # Scenario 14: -1 PSR, -VSR
        0.35 * (2.0 * psr),         # Scenario 15: +2 PSR Extreme
        0.35 * (-2.0 * psr),        # Scenario 16: -2 PSR Extreme
    ]
