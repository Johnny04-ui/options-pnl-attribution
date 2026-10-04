from __future__ import annotations

import unittest

from trade_attribution.black76 import (
    black76_price_greeks,
    implied_volatility_best_fit,
)


class Black76Tests(unittest.TestCase):
    """用公开公式的数值结果锁定 Black-76 核心行为。"""

    def test_call_price_and_forward_greeks_match_reference_values(
        self,
    ) -> None:
        result = black76_price_greeks(
            forward=100.0,
            strike=100.0,
            time_to_maturity=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            call_put="C",
        )

        self.assertAlmostEqual(result.price, 7.5770821464, places=8)
        self.assertAlmostEqual(result.delta, 0.5135001230, places=8)
        self.assertAlmostEqual(result.gamma, 0.0188796472, places=8)
        # Vega 是波动率变化 1.00 的影响；Theta 是一年口径。
        self.assertAlmostEqual(result.vega, 37.7592943291, places=8)
        self.assertAlmostEqual(result.theta, -3.3970753256, places=8)

    def test_put_price_and_forward_greeks_match_reference_values(
        self,
    ) -> None:
        result = black76_price_greeks(
            forward=100.0,
            strike=100.0,
            time_to_maturity=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            call_put="P",
        )

        self.assertAlmostEqual(result.price, 7.5770821464, places=8)
        self.assertAlmostEqual(result.delta, -0.4377293015, places=8)
        self.assertAlmostEqual(result.gamma, 0.0188796472, places=8)
        self.assertAlmostEqual(result.vega, 37.7592943291, places=8)
        self.assertAlmostEqual(result.theta, -3.3970753256, places=8)

    def test_implied_volatility_round_trip_for_call_and_put(self) -> None:
        for call_put in ("C", "P"):
            with self.subTest(call_put=call_put):
                market_price = black76_price_greeks(
                    forward=3.18,
                    strike=3.10,
                    time_to_maturity=47.0 / 365.0,
                    risk_free_rate=0.02,
                    volatility=0.2875,
                    call_put=call_put,
                ).price
                fit = implied_volatility_best_fit(
                    market_price=market_price,
                    forward=3.18,
                    strike=3.10,
                    time_to_maturity=47.0 / 365.0,
                    risk_free_rate=0.02,
                    call_put=call_put,
                )

                self.assertEqual(fit.status, "EXACT")
                self.assertAlmostEqual(fit.volatility, 0.2875, places=7)
                self.assertAlmostEqual(fit.fitted_price, market_price, places=8)
                self.assertAlmostEqual(fit.price_error, 0.0, places=8)

    def test_price_below_model_range_returns_minimum_fit(self) -> None:
        # 深度实值看涨期权的 Black-76 最低价格大于零。
        fit = implied_volatility_best_fit(
            market_price=5.0,
            forward=110.0,
            strike=100.0,
            time_to_maturity=1.0,
            risk_free_rate=0.02,
            call_put="C",
        )

        self.assertEqual(fit.status, "BELOW_MODEL_RANGE")
        self.assertEqual(fit.volatility, 1e-8)
        self.assertGreater(fit.fitted_price, 5.0)
        self.assertGreater(fit.price_error, 0.0)

    def test_price_above_model_range_returns_maximum_fit(self) -> None:
        fit = implied_volatility_best_fit(
            market_price=101.0,
            forward=100.0,
            strike=100.0,
            time_to_maturity=1.0,
            risk_free_rate=0.02,
            call_put="C",
        )

        self.assertEqual(fit.status, "ABOVE_MODEL_RANGE")
        self.assertEqual(fit.volatility, 16.0)
        self.assertLess(fit.fitted_price, 101.0)
        self.assertLess(fit.price_error, 0.0)

    def test_zero_time_to_maturity_is_an_expiry_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "到期"):
            black76_price_greeks(
                forward=100.0,
                strike=100.0,
                time_to_maturity=0.0,
                risk_free_rate=0.02,
                volatility=0.20,
                call_put="C",
            )


if __name__ == "__main__":
    unittest.main()



