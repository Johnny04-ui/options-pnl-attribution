from __future__ import annotations

import unittest
from math import inf, nan

from trade_attribution.parity_forward import (
    ParityForwardPoint,
    aggregate_robust_parity_forwards,
)


class RobustParityForwardTests(unittest.TestCase):
    """锁定“精确排除目标 pair + MAD 过滤 + 等权均值”的规则。"""

    def test_excludes_target_pair_and_mad_outlier(self) -> None:
        points = (
            ParityForwardPoint(strike=2.8, forward=3.00),
            # 这组远期故意写得很极端。因为它包含目标期权，所以应先排除，
            # 不能让目标价格间接参与解释目标价格。
            ParityForwardPoint(
                strike=3.0,
                forward=50.0,
                call_code="TARGET",
                put_code="PAIR",
                is_target_pair=True,
            ),
            ParityForwardPoint(strike=3.2, forward=3.01),
            ParityForwardPoint(strike=3.4, forward=3.02),
            # 该点不含目标期权，但明显偏离其他 K，应由 MAD 规则剔除。
            ParityForwardPoint(strike=3.6, forward=9.0),
        )

        result = aggregate_robust_parity_forwards(points=points)

        self.assertAlmostEqual(result.forward, 3.01)
        self.assertAlmostEqual(result.median, 3.015)
        self.assertAlmostEqual(result.dispersion, 0.01)
        self.assertEqual(result.pair_count, 4)
        self.assertEqual(result.used_pair_count, 3)
        self.assertEqual(result.excluded_target_k, 3.0)
        self.assertEqual(result.all_strikes, (2.8, 3.2, 3.4, 3.6))
        self.assertEqual(result.used_strikes, (2.8, 3.2, 3.4))
        self.assertEqual(
            result.method,
            "put_call_parity_multi_strike_leave_one_out_mad_mean",
        )
        self.assertIn("目标pair排除=是", result.source)

    def test_target_pair_is_identified_by_code_flag_not_same_strike(self) -> None:
        # 两组 pair 可以有相同有效 K（例如不同合约版本）。这里只排除明确
        # 标记为目标 pair 的那一组，同 K 的另一组仍可提供独立行情信息。
        points = (
            ParityForwardPoint(
                strike=3.0,
                forward=99.0,
                is_target_pair=True,
            ),
            ParityForwardPoint(strike=3.0, forward=3.00),
            ParityForwardPoint(strike=3.2, forward=3.02),
        )

        result = aggregate_robust_parity_forwards(points=points)

        self.assertAlmostEqual(result.forward, 3.01)
        self.assertEqual(result.pair_count, 2)
        self.assertEqual(result.used_pair_count, 2)
        self.assertEqual(result.excluded_target_k, 3.0)
        self.assertEqual(result.used_strikes, (3.0, 3.2))

    def test_can_estimate_when_target_pair_does_not_exist(self) -> None:
        result = aggregate_robust_parity_forwards(
            points=(
                ParityForwardPoint(strike=2.8, forward=3.00),
                ParityForwardPoint(strike=3.2, forward=3.02),
            )
        )

        self.assertAlmostEqual(result.forward, 3.01)
        self.assertIsNone(result.excluded_target_k)
        self.assertIn("目标pair排除=否", result.source)

    def test_requires_two_distinct_non_target_strikes(self) -> None:
        cases = (
            # 排除目标 pair 后只剩一个 K。
            (
                ParityForwardPoint(
                    strike=3.0,
                    forward=3.0,
                    is_target_pair=True,
                ),
                ParityForwardPoint(strike=3.2, forward=3.01),
            ),
            # 即使有两条记录，同一个 K 也不能冒充“多 K”。
            (
                ParityForwardPoint(strike=3.2, forward=3.00),
                ParityForwardPoint(strike=3.2, forward=3.01),
            ),
        )
        for points in cases:
            with self.subTest(points=points), self.assertRaisesRegex(
                ValueError,
                "两个不同的非目标K",
            ):
                aggregate_robust_parity_forwards(points=points)

    def test_zero_mad_keeps_tiny_floating_point_differences(self) -> None:
        result = aggregate_robust_parity_forwards(
            points=(
                ParityForwardPoint(strike=2.8, forward=3.0),
                ParityForwardPoint(strike=3.0, forward=3.0),
                ParityForwardPoint(strike=3.2, forward=3.0 + 5e-13),
            )
        )

        self.assertEqual(result.dispersion, 0.0)
        self.assertEqual(result.used_pair_count, 3)
        self.assertAlmostEqual(result.forward, 3.0, places=12)

    def test_rejects_multiple_target_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "多个目标期权PCP配对"):
            aggregate_robust_parity_forwards(
                points=(
                    ParityForwardPoint(
                        strike=2.8,
                        forward=3.0,
                        is_target_pair=True,
                    ),
                    ParityForwardPoint(
                        strike=3.0,
                        forward=3.0,
                        is_target_pair=True,
                    ),
                    ParityForwardPoint(strike=3.2, forward=3.0),
                )
            )

    def test_rejects_empty_non_finite_and_non_positive_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要一组"):
            aggregate_robust_parity_forwards(points=())

        for bad_value in (0.0, -1.0, nan, inf):
            with self.subTest(bad_value=bad_value), self.assertRaises(ValueError):
                aggregate_robust_parity_forwards(
                    points=(
                        ParityForwardPoint(strike=2.8, forward=bad_value),
                        ParityForwardPoint(strike=3.0, forward=3.0),
                    )
                )


if __name__ == "__main__":
    unittest.main()



