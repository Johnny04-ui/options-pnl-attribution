from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import patch

from trade_attribution.black76 import Black76Result, ImpliedVolatilityFit
from trade_attribution.calculation import (
    calculate_holding_etf,
    calculate_holding_option,
    calculate_intraday_etf,
    calculate_intraday_option,
)
from trade_attribution.daily_history import build_daily_rows
from trade_attribution.models import (
    Holding,
    OptionDescription,
    PricePoint,
    RunRecord,
    Trade,
)
from trade_attribution.parity_forward import (
    ParityForwardResult,
    RobustParityForwardResult,
)


PREVIOUS_DATE = date(2026, 7, 1)
TRADE_DATE = date(2026, 7, 2)


def option_trade(trade_type: str, *, count: float = 5.0) -> Trade:
    """Build the smallest useful option trade for direction/formula tests."""
    return Trade(
        source_id=f"option-{trade_type}",
        portfolio_code="DEMO_PORTFOLIO",
        trade_date=TRADE_DATE,
        instrument_code="OPT_DEMO_002",
        instrument_name="测试ETF期权",
        asset_type="OPT_F",
        market="XSHE",
        account_attribute="期权ETF基金",
        trade_type=trade_type,
        position="L" if trade_type in {"DK", "DP"} else "S",
        count=count,
        price=1_800.0,
        amount=count * 1_800.0,
        net_amount=0.0,
        commission=0.0,
        fee=0.0,
    )


def option_holding() -> Holding:
    return Holding(
        portfolio_code="DEMO_PORTFOLIO",
        holding_date=PREVIOUS_DATE,
        instrument_code="OPT_DEMO_002",
        market="XSHE",
        instrument_name="测试ETF期权",
        asset_type="OPT_F",
        contract_count=100.0,
        direction="S",
    )


def option_description() -> OptionDescription:
    return OptionDescription(
        wind_code="OPT_DEMO_002.XSHE",
        security_code="OPT_DEMO_002",
        name="测试ETF期权",
        underlying_wind_code="ETF_DEMO.XSHE",
        call_put="C",
        strike=3.00,
        maturity_date=date(2026, 8, 26),
        multiplier=10_000.0,
    )


def option_price(trade_date: date, close: float) -> PricePoint:
    return PricePoint("OPT_DEMO_002.XSHE", trade_date, close)


def underlying_price(trade_date: date, close: float) -> PricePoint:
    return PricePoint("ETF_DEMO.XSHE", trade_date, close)


class TradeDirectionTests(unittest.TestCase):
    def test_option_trade_types_are_reduced_to_buy_sell_signs(self) -> None:
        expected_quantities = {
            "DK": 5.0,   # 买入开多
            "DP": -5.0,  # 卖出平多
            "KK": -5.0,  # 卖出开空
            "KP": 5.0,   # 买入平空
        }

        for trade_type, expected in expected_quantities.items():
            with self.subTest(trade_type=trade_type):
                self.assertEqual(
                    option_trade(trade_type).signed_quantity,
                    expected,
                )


class OptionAttributionTests(unittest.TestCase):
    def calculate_holding(self):
        start_forward = RobustParityForwardResult(
            forward=3.00,
            median=3.00,
            dispersion=0.002,
            pair_count=4,
            used_pair_count=3,
            excluded_target_k=3.00,
            all_strikes=(2.80, 2.90, 3.10, 3.20),
            used_strikes=(2.90, 3.10, 3.20),
            method="put_call_parity_multi_strike_leave_one_out_mad_mean",
            source="测试期初远期",
        )
        end_forward = RobustParityForwardResult(
            forward=3.10,
            median=3.10,
            dispersion=0.003,
            pair_count=5,
            used_pair_count=4,
            excluded_target_k=3.00,
            all_strikes=(2.80, 2.90, 3.10, 3.20, 3.30),
            used_strikes=(2.90, 3.10, 3.20, 3.30),
            method="put_call_parity_multi_strike_leave_one_out_mad_mean",
            source="测试期末远期",
        )
        return calculate_holding_option(
            option_holding(),
            TRADE_DATE,
            option_description(),
            option_description(),
            option_price(PREVIOUS_DATE, 0.20),
            option_price(TRADE_DATE, 0.15),
            underlying_start=underlying_price(PREVIOUS_DATE, 3.00),
            underlying_end=underlying_price(TRADE_DATE, 3.10),
            forward_start=start_forward,
            forward_end=end_forward,
            risk_free_rate=0.01,
        )

    def test_short_100_holding_plus_kp_40_intraday_trade(self) -> None:
        """The -100 carry and +40 close trade are two additive PnL legs."""
        holding_row = self.calculate_holding()
        kp_trade = option_trade("KP", count=40.0)
        # Raw option trade price is per contract: 1,800 / 10,000 = 0.18.
        kp_trade_row = calculate_intraday_option(
            kp_trade,
            option_description(),
            option_price(TRADE_DATE, 0.15),
        )

        # Carry: -100 * 10,000 * (0.15 - 0.20) = +50,000.
        self.assertAlmostEqual(holding_row.signed_quantity, -100.0)
        self.assertAlmostEqual(holding_row.pnl_holding, 50_000.0)
        self.assertEqual(holding_row.forward_pair_count_start, 4)
        self.assertEqual(holding_row.forward_used_pair_count_start, 3)
        self.assertAlmostEqual(holding_row.forward_mad_start, 0.002)
        # KP is a buy: +40 * 10,000 * (0.15 - 0.18) = -12,000.
        self.assertAlmostEqual(kp_trade_row.signed_quantity, 40.0)
        self.assertAlmostEqual(kp_trade_row.trade_price_per_unit, 0.18)
        self.assertAlmostEqual(kp_trade_row.pnl_gross, -12_000.0)
        self.assertAlmostEqual(
            holding_row.pnl_holding + kp_trade_row.pnl_gross,
            38_000.0,
        )

    def test_end_greeks_do_not_change_current_day_attribution(self) -> None:
        start = (
            ImpliedVolatilityFit(0.20, 0.20, 0.0, "EXACT"),
            Black76Result(0.20, 0.45, 0.10, 0.08, -0.02),
            0.20,
        )
        normal_end = (
            ImpliedVolatilityFit(0.20, 0.15, 0.0, "EXACT"),
            Black76Result(0.15, 0.50, 0.12, 0.07, -0.01),
            0.19,
        )
        changed_end = (
            ImpliedVolatilityFit(0.20, 0.15, 0.0, "EXACT"),
            Black76Result(0.15, -0.90, 9.00, 8.00, 7.00),
            0.19,
        )
        with patch(
            "trade_attribution.calculation._self_calculated_valuation",
            side_effect=[start, normal_end],
        ):
            baseline = self.calculate_holding()
        with patch(
            "trade_attribution.calculation._self_calculated_valuation",
            side_effect=[start, changed_end],
        ):
            changed_end_greeks = self.calculate_holding()

        # End Greeks are reported, but today's Taylor attribution uses start Greeks.
        # Keeping end IV equal also keeps Vega PnL equal to zero.
        for field in (
            "pnl_holding",
            "pnl_delta",
            "pnl_gamma",
            "pnl_vega",
            "pnl_theta",
            "pnl_residual",
            "reconciliation",
        ):
            with self.subTest(field=field):
                self.assertAlmostEqual(
                    getattr(changed_end_greeks, field),
                    getattr(baseline, field),
                )

        self.assertNotEqual(changed_end_greeks.delta_end, baseline.delta_end)
        self.assertAlmostEqual(baseline.pnl_vega, 0.0)

    def test_missing_proxy_keeps_actual_pnl_as_residual(self) -> None:
        row = calculate_holding_option(
            option_holding(),
            TRADE_DATE,
            option_description(),
            option_description(),
            option_price(PREVIOUS_DATE, 0.20),
            option_price(TRADE_DATE, 0.15),
            underlying_start=underlying_price(PREVIOUS_DATE, 3.00),
            underlying_end=underlying_price(TRADE_DATE, 3.10),
            forward_start=None,
            forward_end=None,
            risk_free_rate=0.02,
            greeks_unavailable_reason="没有同指数期货",
        )

        self.assertAlmostEqual(row.pnl_holding, 50_000.0)
        self.assertAlmostEqual(row.pnl_residual, row.pnl_holding)
        self.assertIsNone(row.implied_vol_start)
        self.assertEqual(row.iv_fit_status_start, "UNAVAILABLE")
        self.assertAlmostEqual(row.reconciliation, 0.0)

    def test_contract_adjustment_uses_start_and_end_multipliers(self) -> None:
        start_description = option_description()
        end_description = OptionDescription(
            wind_code=start_description.wind_code,
            security_code=start_description.security_code,
            name=start_description.name,
            underlying_wind_code=start_description.underlying_wind_code,
            call_put=start_description.call_put,
            strike=2.934,
            maturity_date=start_description.maturity_date,
            multiplier=10_226.0,
        )
        row = calculate_holding_option(
            option_holding(),
            TRADE_DATE,
            start_description,
            end_description,
            option_price(PREVIOUS_DATE, 0.20),
            option_price(TRADE_DATE, 0.20),
            underlying_start=None,
            underlying_end=None,
            forward_start=None,
            forward_end=None,
            risk_free_rate=0.02,
            greeks_unavailable_reason="测试",
        )

        expected = -100.0 * (10_226.0 * 0.20 - 10_000.0 * 0.20)
        self.assertAlmostEqual(row.pnl_holding, expected)
        self.assertEqual(row.multiplier, 10_000.0)
        self.assertEqual(row.multiplier_end, 10_226.0)

    def test_contract_adjustment_normalizes_end_forward_for_delta_gamma(self) -> None:
        """除权日不能把合约计量单位变化误当成标的价格大跌。"""

        start_description = OptionDescription(
            wind_code="OPT_DEMO_001.XSHG",
            security_code="OPT_DEMO_001",
            name="300ETF购6月4000",
            underlying_wind_code="ETF_DEMO.XSHG",
            call_put="C",
            strike=4.0,
            maturity_date=date(2026, 8, 26),
            multiplier=10_000.0,
        )
        end_description = OptionDescription(
            wind_code="OPT_DEMO_001.XSHG",
            security_code="OPT_DEMO_001",
            name="300ETF购6月3912A",
            underlying_wind_code="ETF_DEMO.XSHG",
            call_put="C",
            strike=3.912,
            maturity_date=date(2026, 8, 26),
            multiplier=10_226.0,
        )
        start_forward = ParityForwardResult(
            forward=3.989795527786984,
            strike=4.0,
            call_price=0.0241,
            put_price=0.0343,
            risk_free_rate=0.02,
            time_to_maturity=8.0 / 365.0,
            discount_factor=1.0,
            call_code="OPT_DEMO_001.XSHG",
            put_code="OPT_DEMO_PUT.XSHG",
            method="put_call_parity_same_strike",
            source="测试期初PCP远期",
        )
        end_forward = ParityForwardResult(
            forward=3.903396700737168,
            strike=3.912,
            call_price=0.0227,
            put_price=0.0313,
            risk_free_rate=0.02,
            time_to_maturity=7.0 / 365.0,
            discount_factor=1.0,
            call_code="OPT_DEMO_001.XSHG",
            put_code="OPT_DEMO_PUT.XSHG",
            method="put_call_parity_same_strike",
            source="测试期末PCP远期",
        )
        start_valuation = (
            ImpliedVolatilityFit(0.20, 0.0241, 0.0, "EXACT"),
            Black76Result(0.0241, 0.50, 0.10, 0.08, -0.02),
            8.0 / 365.0,
        )
        end_valuation = (
            ImpliedVolatilityFit(0.21, 0.0227, 0.0, "EXACT"),
            Black76Result(0.0227, 0.52, 0.11, 0.07, -0.01),
            7.0 / 365.0,
        )

        with patch(
            "trade_attribution.calculation._self_calculated_valuation",
            side_effect=[start_valuation, end_valuation],
        ):
            row = calculate_holding_option(
                option_holding(),
                TRADE_DATE,
                start_description,
                end_description,
                PricePoint("OPT_DEMO_001.XSHG", PREVIOUS_DATE, 0.0241),
                PricePoint("OPT_DEMO_001.XSHG", TRADE_DATE, 0.0227),
                underlying_start=None,
                underlying_end=None,
                forward_start=start_forward,
                forward_end=end_forward,
                risk_free_rate=0.02,
            )

        expected_end = end_forward.forward * 10_226.0 / 10_000.0
        expected_change = expected_end - start_forward.forward
        self.assertAlmostEqual(row.forward_end_on_start_terms, expected_end)
        self.assertAlmostEqual(row.forward_change, expected_change)
        # 昨日是100张空仓，因此 position_units = -100 * 10000。
        self.assertAlmostEqual(
            row.pnl_delta,
            -100.0 * 10_000.0 * 0.50 * expected_change,
        )


class EtfPnlTests(unittest.TestCase):
    def test_etf_holding_and_sell_trade(self) -> None:
        holding = Holding(
            portfolio_code="DEMO_PORTFOLIO",
            holding_date=PREVIOUS_DATE,
            instrument_code="ETF_DEMO",
            market="XSHE",
            instrument_name="测试ETF基金",
            asset_type="SPT_ETF",
            contract_count=1_000.0,
            direction="L",
        )
        holding_row = calculate_holding_etf(
            holding,
            TRADE_DATE,
            "ETF_DEMO.XSHE",
            PricePoint("ETF_DEMO.XSHE", PREVIOUS_DATE, 2.00),
            PricePoint("ETF_DEMO.XSHE", TRADE_DATE, 2.10),
        )
        sell_trade = Trade(
            source_id="etf-sell",
            portfolio_code="DEMO_PORTFOLIO",
            trade_date=TRADE_DATE,
            instrument_code="ETF_DEMO",
            instrument_name="测试ETF基金",
            asset_type="SPT_S",
            market="XSHE",
            account_attribute="ETF基金",
            trade_type="",
            position="S",
            count=400.0,
            price=2.08,
            amount=-832.0,
            net_amount=831.0,
            commission=0.5,
            fee=0.5,
        )
        trade_row = calculate_intraday_etf(
            sell_trade,
            "ETF_DEMO.XSHE",
            PricePoint("ETF_DEMO.XSHE", TRADE_DATE, 2.10),
        )

        self.assertAlmostEqual(holding_row.pnl_holding, 100.0)
        # An ETF is linear in its own price, so all holding PnL is Delta PnL.
        self.assertAlmostEqual(holding_row.pnl_delta, 100.0)
        self.assertAlmostEqual(holding_row.pnl_residual, 0.0)
        self.assertAlmostEqual(trade_row.signed_quantity, -400.0)
        self.assertAlmostEqual(trade_row.pnl_gross, -8.0)
        self.assertAlmostEqual(trade_row.pnl_delta, trade_row.pnl_gross)
        self.assertAlmostEqual(trade_row.fee, 1.0)
        self.assertAlmostEqual(trade_row.pnl_net, -9.0)
        self.assertAlmostEqual(trade_row.gross_return, -8.0 / 832.0)
        self.assertAlmostEqual(trade_row.net_return, -9.0 / 832.0)
        self.assertAlmostEqual(
            holding_row.pnl_holding + trade_row.pnl_gross,
            92.0,
        )
        self.assertAlmostEqual(
            holding_row.pnl_holding + trade_row.pnl_net,
            91.0,
        )

    def test_etf_delta_is_not_counted_twice_in_daily_reconciliation(self) -> None:
        holding = Holding(
            portfolio_code="DEMO_PORTFOLIO",
            holding_date=PREVIOUS_DATE,
            instrument_code="ETF_DEMO",
            market="XSHE",
            instrument_name="测试ETF基金",
            asset_type="SPT_ETF",
            contract_count=1_000.0,
            direction="L",
        )
        holding_row = calculate_holding_etf(
            holding,
            TRADE_DATE,
            "ETF_DEMO.XSHE",
            PricePoint("ETF_DEMO.XSHE", PREVIOUS_DATE, 2.00),
            PricePoint("ETF_DEMO.XSHE", TRADE_DATE, 2.10),
        )
        sell_trade = Trade(
            source_id="etf-sell-daily",
            portfolio_code="DEMO_PORTFOLIO",
            trade_date=TRADE_DATE,
            instrument_code="ETF_DEMO",
            instrument_name="测试ETF基金",
            asset_type="SPT_S",
            market="XSHE",
            account_attribute="ETF基金",
            trade_type="",
            position="S",
            count=400.0,
            price=2.08,
            amount=-832.0,
            net_amount=831.0,
            commission=0.5,
            fee=0.5,
        )
        trade_row = calculate_intraday_etf(
            sell_trade,
            "ETF_DEMO.XSHE",
            PricePoint("ETF_DEMO.XSHE", TRADE_DATE, 2.10),
        )
        record = RunRecord(
            portfolio_code="DEMO_PORTFOLIO",
            trade_date=TRADE_DATE,
            previous_trade_date=PREVIOUS_DATE,
            status="SUCCESS",
            holding_count=1,
            trade_count=1,
            issue_count=0,
            message="完成",
            updated_at=datetime.now(),
        )

        daily = build_daily_rows([holding_row], [trade_row], [], [record])[0]

        self.assertAlmostEqual(daily.holding_etf_pnl, 100.0)
        self.assertAlmostEqual(daily.intraday_gross, -8.0)
        self.assertAlmostEqual(daily.pnl_delta, 92.0)
        self.assertAlmostEqual(daily.daily_gross, 92.0)
        self.assertAlmostEqual(daily.daily_net, 91.0)
        # ETF holding/trade subtotals are classification views, not extra legs.
        self.assertAlmostEqual(daily.reconciliation, 0.0)


if __name__ == "__main__":
    unittest.main()



