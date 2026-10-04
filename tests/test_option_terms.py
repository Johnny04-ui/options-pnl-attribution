from __future__ import annotations

import unittest
from datetime import date

from trade_attribution.models import OptionDescription, OptionTermsChange
from trade_attribution.option_terms import description_as_of


class HistoricalOptionTermsTests(unittest.TestCase):
    def test_current_terms_are_rolled_back_before_adjustment_date(self) -> None:
        current = OptionDescription(
            wind_code="OPT_DEMO_001.XSHG",
            security_code="OPT_DEMO_001",
            name="测试期权",
            underlying_wind_code="ETF_DEMO.XSHG",
            call_put="C",
            strike=3.912,
            maturity_date=date(2025, 6, 25),
            multiplier=10_226.0,
        )
        change = OptionTermsChange(
            wind_code="OPT_DEMO_001.XSHG",
            change_date=date(2025, 6, 18),
            old_strike=4.0,
            new_strike=3.912,
            old_multiplier=10_000.0,
            new_multiplier=10_226.0,
        )

        before = description_as_of(current, [change], date(2025, 6, 17))
        on_change = description_as_of(current, [change], date(2025, 6, 18))

        self.assertEqual(before.strike, 4.0)
        self.assertEqual(before.multiplier, 10_000.0)
        self.assertEqual(on_change.strike, 3.912)
        self.assertEqual(on_change.multiplier, 10_226.0)


if __name__ == "__main__":
    unittest.main()



