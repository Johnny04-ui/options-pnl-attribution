"""Run a tiny P&L-attribution example built entirely from synthetic data.

This file deliberately uses simple numbers and many comments so a beginner can
follow how market inputs become an attribution result.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


# Running a file inside examples/ makes Python search that folder first.  We add
# the repository root so the local trade_attribution package can be imported.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from trade_attribution.black76 import black76_price_greeks
from trade_attribution.calculation import calculate_holding_option
from trade_attribution.models import Holding, OptionDescription, PricePoint
from trade_attribution.parity_forward import RobustParityForwardResult


def synthetic_forward(value: float) -> RobustParityForwardResult:
    """Create the audited forward-price object expected by the calculator."""

    return RobustParityForwardResult(
        forward=value,
        median=value,
        dispersion=0.001,
        pair_count=3,
        used_pair_count=3,
        excluded_target_k=3.0,
        all_strikes=(2.9, 3.1, 3.2),
        used_strikes=(2.9, 3.1, 3.2),
        method="synthetic_multi_strike_pcp",
        source="synthetic data only",
    )


def main() -> None:
    """Calculate one day's attribution for a synthetic call-option position."""

    start_date = date(2025, 7, 1)
    end_date = date(2025, 7, 2)
    maturity = date(2025, 8, 29)
    risk_free_rate = 0.02

    # We first choose synthetic market states.  Black-76 then gives internally
    # consistent option prices, so this demo needs no private market-data file.
    start_forward = 3.05
    end_forward = 3.07
    start_volatility = 0.25
    end_volatility = 0.27
    strike = 3.0

    start_option = black76_price_greeks(
        forward=start_forward,
        strike=strike,
        time_to_maturity=(maturity - start_date).days / 365,
        risk_free_rate=risk_free_rate,
        volatility=start_volatility,
        call_put="C",
    )
    end_option = black76_price_greeks(
        forward=end_forward,
        strike=strike,
        time_to_maturity=(maturity - end_date).days / 365,
        risk_free_rate=risk_free_rate,
        volatility=end_volatility,
        call_put="C",
    )

    holding = Holding(
        portfolio_code="DEMO_PORTFOLIO",
        holding_date=start_date,
        instrument_code="OPT_DEMO_001",
        market="DEMO",
        instrument_name="Synthetic 3.0 Call",
        asset_type="OPT_F",
        contract_count=10,
        direction="L",
    )
    description = OptionDescription(
        wind_code="OPT_DEMO_001.XSHG",
        security_code="OPT_DEMO_001",
        name="Synthetic 3.0 Call",
        underlying_wind_code="ETF_DEMO.XSHG",
        call_put="C",
        strike=strike,
        maturity_date=maturity,
        multiplier=10_000,
    )

    result = calculate_holding_option(
        holding=holding,
        trade_date=end_date,
        description_start=description,
        description_end=description,
        option_start=PricePoint(
            wind_code=description.wind_code,
            trade_date=start_date,
            close=start_option.price,
        ),
        option_end=PricePoint(
            wind_code=description.wind_code,
            trade_date=end_date,
            close=end_option.price,
        ),
        underlying_start=None,
        underlying_end=None,
        forward_start=synthetic_forward(start_forward),
        forward_end=synthetic_forward(end_forward),
        risk_free_rate=risk_free_rate,
    )

    # The final line should be numerically zero apart from floating-point noise.
    rows = (
        ("Actual holding P&L", result.pnl_holding),
        ("Delta P&L", result.pnl_delta),
        ("Gamma P&L", result.pnl_gamma),
        ("Vega P&L", result.pnl_vega),
        ("Theta P&L", result.pnl_theta),
        ("Residual", result.pnl_residual),
        ("Reconciliation difference", result.reconciliation),
    )
    for label, value in rows:
        print(f"{label:28s} {value:12.4f}")


if __name__ == "__main__":
    main()

