from __future__ import annotations

import unittest
from math import exp, inf, nan

from trade_attribution.parity_forward import (
    infer_forward_from_put_call_parity,
)


class ParityForwardTests(unittest.TestCase):
    """用手工可复核的数字锁定 Put-Call Parity 核心公式。"""

    def test_infers_forward_with_continuous_discounting(self) -> None:
        result = infer_forward_from_put_call_parity(
            call_price=0.18,
            put_price=0.12,
            strike=3.0,
            time_to_maturity=90.0 / 365.0,
            risk_free_rate=0.02,
            call_code="CALL_DEMO.XSHG",
            put_code="PUT_DEMO.XSHG",
        )

        expected_discount = exp(-0.02 * 90.0 / 365.0)
        expected_forward = 3.0 + (0.18 - 0.12) / expected_discount
        self.assertAlmostEqual(result.discount_factor, expected_discount, places=14)
        self.assertAlmostEqual(result.forward, expected_forward, places=14)
        self.assertEqual(result.method, "put_call_parity_same_strike")
        self.assertEqual(result.call_code, "CALL_DEMO.XSHG")
        self.assertEqual(result.put_code, "PUT_DEMO.XSHG")
        self.assertIn("K=3", result.source)

    def test_matches_exported_science_tech_50_pair(self) -> None:
        """使用完全合成的 C/P 样本验证公式。"""

        start = infer_forward_from_put_call_parity(
            call_price=0.0769,
            put_price=0.1760,
            strike=2.0,
            time_to_maturity=30.0 / 365.0,
            risk_free_rate=0.02,
        )
        end = infer_forward_from_put_call_parity(
            call_price=0.0410,
            put_price=0.2619,
            strike=2.0,
            time_to_maturity=29.0 / 365.0,
            risk_free_rate=0.02,
        )

        self.assertAlmostEqual(start.forward, 1.9007369619232257, places=14)
        self.assertAlmostEqual(end.forward, 1.7787487017821860, places=14)

    def test_matches_exported_contract_adjustment_pair(self) -> None:
        """历史日必须使用调整前 K；调整日开始使用调整后 K。"""

        start = infer_forward_from_put_call_parity(
            call_price=0.0241,
            put_price=0.0343,
            strike=4.0,
            time_to_maturity=8.0 / 365.0,
            risk_free_rate=0.02,
        )
        end = infer_forward_from_put_call_parity(
            call_price=0.0227,
            put_price=0.0313,
            strike=3.912,
            time_to_maturity=7.0 / 365.0,
            risk_free_rate=0.02,
        )

        self.assertAlmostEqual(start.forward, 3.989795527786984, places=14)
        self.assertAlmostEqual(end.forward, 3.903396700737168, places=14)

    def test_zero_rate_reduces_to_strike_plus_call_minus_put(self) -> None:
        result = infer_forward_from_put_call_parity(
            call_price=0.25,
            put_price=0.10,
            strike=4.0,
            time_to_maturity=0.5,
            risk_free_rate=0.0,
        )

        self.assertEqual(result.discount_factor, 1.0)
        self.assertAlmostEqual(result.forward, 4.15)
        self.assertIn("未提供Call代码", result.source)

    def test_negative_interest_rate_is_valid(self) -> None:
        # 利率可能小于零，因此这里只要求它是有限数值，不错误地限制为正数。
        result = infer_forward_from_put_call_parity(
            call_price=0.12,
            put_price=0.15,
            strike=3.5,
            time_to_maturity=0.25,
            risk_free_rate=-0.01,
        )

        expected = 3.5 + exp(-0.01 * 0.25) * (0.12 - 0.15)
        self.assertAlmostEqual(result.forward, expected, places=14)

    def test_rejects_negative_option_prices(self) -> None:
        for field in ("call_price", "put_price"):
            values = {
                "call_price": 0.10,
                "put_price": 0.10,
                "strike": 3.0,
                "time_to_maturity": 0.25,
                "risk_free_rate": 0.02,
            }
            values[field] = -0.01
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError,
                "价格不能为负数",
            ):
                infer_forward_from_put_call_parity(**values)

    def test_expiry_day_uses_discount_factor_one(self) -> None:
        # T=0 时虽然不能再算通常意义上的 Greeks，但平价公式本身仍然有效。
        result = infer_forward_from_put_call_parity(
            call_price=0.20,
            put_price=0.05,
            strike=3.0,
            time_to_maturity=0.0,
            risk_free_rate=0.02,
        )

        self.assertEqual(result.discount_factor, 1.0)
        self.assertAlmostEqual(result.forward, 3.15)

    def test_rejects_non_positive_strike_and_negative_maturity(self) -> None:
        invalid_values = (
            ("strike", 0.0),
            ("time_to_maturity", -1.0 / 365.0),
        )
        for field, bad_value in invalid_values:
            values = {
                "call_price": 0.10,
                "put_price": 0.10,
                "strike": 3.0,
                "time_to_maturity": 0.25,
                "risk_free_rate": 0.02,
            }
            values[field] = bad_value
            with self.subTest(field=field), self.assertRaises(ValueError):
                infer_forward_from_put_call_parity(**values)

    def test_rejects_non_finite_numbers(self) -> None:
        for bad_value in (nan, inf, -inf):
            with self.subTest(bad_value=bad_value), self.assertRaisesRegex(
                ValueError,
                "有限数值",
            ):
                infer_forward_from_put_call_parity(
                    call_price=bad_value,
                    put_price=0.10,
                    strike=3.0,
                    time_to_maturity=0.25,
                    risk_free_rate=0.02,
                )

    def test_rejects_non_positive_inferred_forward(self) -> None:
        # 极端噪声价格可能使 K + exp(rT)(C-P) 小于零；这种值不能交给 Black-76。
        with self.assertRaisesRegex(ValueError, "远期价格必须为正数"):
            infer_forward_from_put_call_parity(
                call_price=0.0,
                put_price=5.0,
                strike=1.0,
                time_to_maturity=1.0,
                risk_free_rate=0.02,
            )

    def test_rejects_unrepresentable_discount_factor(self) -> None:
        with self.assertRaisesRegex(ValueError, "贴现因子"):
            infer_forward_from_put_call_parity(
                call_price=0.10,
                put_price=0.10,
                strike=3.0,
                time_to_maturity=1.0,
                risk_free_rate=-1e308,
            )


if __name__ == "__main__":
    unittest.main()



