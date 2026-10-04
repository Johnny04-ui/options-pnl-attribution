from __future__ import annotations

from dataclasses import replace
from datetime import date

from .models import OptionDescription, OptionTermsChange


def description_as_of(
    current: OptionDescription,
    changes: list[OptionTermsChange],
    valuation_date: date,
) -> OptionDescription:
    """把 Wind 的“当前合约参数”倒推成指定日期的参数。

    ``ChinaOptionDescription`` 保存的是当前行权价和合约单位。发生除权
    调整后，历史日期不能直接使用这组当前值。这里从当前值开始，按调整日
    从新到旧倒着走：如果估值日在某次调整之前，就退回该次调整的旧参数。
    """

    result = current
    # reverse=True 表示先处理最近一次调整，再逐步往历史倒推。
    for change in sorted(changes, key=lambda item: item.change_date, reverse=True):
        if change.wind_code != current.wind_code:
            continue
        if valuation_date < change.change_date:
            result = replace(
                result,
                strike=change.old_strike,
                multiplier=change.old_multiplier,
            )
    return result



