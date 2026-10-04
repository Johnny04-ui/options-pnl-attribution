from __future__ import annotations

"""用同行权价的认购、认沽收盘价反推出 Black-76 远期价格。

本模块只负责 Put-Call Parity（认购认沽平价）这一件事，不负责寻找配对
合约，也不负责计算隐含波动率和 Greeks。这样可以让公式容易测试，也方便
在 Excel 结果里复核每一个输入值。
"""

from dataclasses import dataclass
from math import exp, fsum, isclose, isfinite
from statistics import median
from typing import Iterable


# 原始 MAD（median absolute deviation）的 3 倍以外视为异常值。
# 这里故意使用一个固定、容易解释的规则，不引入额外参数拟合。
_MAD_MULTIPLIER = 3.0
_STRIKE_TOLERANCE = 1e-9
_FLOAT_TOLERANCE = 1e-12


@dataclass(frozen=True)
class ParityForwardResult:
    """一组同行权价 Call/Put 推导出的远期价格及审计信息。

    ``discount_factor`` 是连续复利贴现因子 ``exp(-rT)``。保留 Call、Put
    的代码和价格，是为了让使用者可以从归因报表追溯到原始行情。
    """

    forward: float
    strike: float
    call_price: float
    put_price: float
    risk_free_rate: float
    time_to_maturity: float
    discount_factor: float
    call_code: str
    put_code: str
    method: str
    source: str


@dataclass(frozen=True)
class ParityForwardPoint:
    """一个合法 Call/Put 配对推导出的 PCP 远期。

    上层应先确保一组 Call/Put 的历史有效 K 和有效合约乘数相同，再用
    单 K 平价公式计算 ``forward``。这样得到的 F 已经是每份 ETF 口径，
    不需要在不同 K 之间按目标合约乘数换算，直接聚合即可。跨日期的
    ``M1 / M0`` 归一属于 PnL 计算，不属于本模块。

    ``is_target_pair`` 必须由上层根据 Wind 代码精确判断：只要这个 C/P
    配对包含当前目标期权，就标记为 ``True``。不能仅凭 K 判断，因为
    历史上可能存在相同 K、但属于不同合约版本的合法配对。

    ``call_code`` 和 ``put_code`` 不是计算必需字段，只用于追溯原行情。
    """

    strike: float
    forward: float
    call_code: str = ""
    put_code: str = ""
    is_target_pair: bool = False


@dataclass(frozen=True)
class RobustParityForwardResult:
    """排除目标 C/P 配对后，由多个行权价共同估计出的远期及诊断信息。

    ``pair_count`` 是精确排除目标 pair 后、MAD 过滤前的候选 pair 数；
    ``used_pair_count`` 是过滤后真正进入均值的 pair 数。

    ``dispersion`` 是候选远期的原始 MAD。它越大，说明不同 K 通过
    Put-Call Parity 得到的远期越不一致。``all_strikes`` 也只记录候选 K，
    被排除的目标 K 单独记录在 ``excluded_target_k`` 中。
    """

    forward: float
    median: float
    dispersion: float
    pair_count: int
    used_pair_count: int
    excluded_target_k: float | None
    all_strikes: tuple[float, ...]
    used_strikes: tuple[float, ...]
    method: str
    source: str


def infer_forward_from_put_call_parity(
    *,
    call_price: float,
    put_price: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    call_code: str = "",
    put_code: str = "",
) -> ParityForwardResult:
    """根据单个行权价的 Call/Put 价格反推出远期价格。

    Black-76 口径的 Put-Call Parity 是：

    ``C - P = exp(-rT) * (F - K)``

    移项后得到：

    ``F = K + exp(rT) * (C - P)``

    参数 ``T`` 以年为单位，例如剩余 30 个自然日应传入 ``30 / 365``；
    ``risk_free_rate`` 是连续复利年利率，例如 2% 应传入 ``0.02``。
    """

    _validate_inputs(
        call_price=call_price,
        put_price=put_price,
        strike=strike,
        time_to_maturity=time_to_maturity,
        risk_free_rate=risk_free_rate,
    )

    # D = exp(-rT)。使用 (C-P)/D 与 exp(rT)*(C-P) 完全等价；前一种写法
    # 更直接地对应老板给出的公式 C-P = D(F-K)。
    try:
        discount_factor = exp(-risk_free_rate * time_to_maturity)
    except OverflowError as exc:
        raise ValueError("无风险利率和剩余期限生成了无法表示的贴现因子") from exc
    if not isfinite(discount_factor) or discount_factor <= 0.0:
        raise ValueError("无风险利率和剩余期限生成了无效贴现因子")
    forward = strike + (call_price - put_price) / discount_factor
    if not isfinite(forward) or forward <= 0.0:
        raise ValueError(
            "Put-Call Parity 推导出的远期价格必须为正数；"
            f"当前结果为 {forward!r}"
        )

    normalized_call_code = call_code.strip()
    normalized_put_code = put_code.strip()
    method = "put_call_parity_same_strike"
    source = _source_text(
        call_code=normalized_call_code,
        put_code=normalized_put_code,
        strike=strike,
    )
    return ParityForwardResult(
        forward=forward,
        strike=strike,
        call_price=call_price,
        put_price=put_price,
        risk_free_rate=risk_free_rate,
        time_to_maturity=time_to_maturity,
        discount_factor=discount_factor,
        call_code=normalized_call_code,
        put_code=normalized_put_code,
        method=method,
        source=source,
    )


def aggregate_robust_parity_forwards(
    *,
    points: Iterable[ParityForwardPoint],
) -> RobustParityForwardResult:
    """排除目标 C/P 配对，并稳健聚合其余 K 的 PCP 远期。

    计算顺序如下：

    1. 上层先对每个 K 调用 :func:`infer_forward_from_put_call_parity`；
    2. 上层确认每组 C/P 的历史有效 K、有效乘数匹配，再把每份 ETF
       口径的 F 传入 ``ParityForwardPoint``；
    3. 本函数排除 ``is_target_pair=True`` 的精确配对，避免目标期权
       价格参与构造用于解释它自己的远期；
    4. 以中位数为中心计算 MAD，剔除距离超过 ``3 * MAD`` 的异常点；
    5. 对保留点做等权均值，得到最终远期。

    至少必须保留两个不同的非目标 K。否则这个方法会退化为另一个单 K
    估计，不能达到降低自我引用和单点噪声的目的，因此直接报不可用。
    """

    # 转成 tuple 后才能安全地重复遍历。按 K 排序让测试、日志和 Excel
    # 输出的顺序保持稳定，不受字典插入顺序影响。
    all_points = tuple(points)
    if not all_points:
        raise ValueError("多K远期聚合至少需要一组PCP远期")

    for point in all_points:
        _validate_number("PCP行权价", point.strike, positive=True)
        _validate_number("PCP远期", point.forward, positive=True)
        if not isinstance(point.is_target_pair, bool):
            raise ValueError("is_target_pair必须是bool值")

    all_points = tuple(
        sorted(
            all_points,
            key=lambda item: (item.strike, item.call_code, item.put_code),
        )
    )

    # 是否包含目标合约只能由代码判断，不能把同 K 的其他历史版本误删。
    excluded = tuple(point for point in all_points if point.is_target_pair)
    if len(excluded) > 1:
        raise ValueError("检测到多个目标期权PCP配对，无法确定应排除哪一组")
    candidates = tuple(point for point in all_points if not point.is_target_pair)
    if len(_unique_strikes(candidates)) < 2:
        raise ValueError("排除目标K后，至少需要两个不同的非目标K来估计远期")

    candidate_forwards = tuple(point.forward for point in candidates)
    center = float(median(candidate_forwards))
    absolute_deviations = tuple(
        abs(value - center) for value in candidate_forwards
    )
    mad = float(median(absolute_deviations))

    # 当多个 F_K 完全相同，MAD 会等于 0。给阈值设置一个只用于浮点
    # 误差的小下限，避免 3.000000000000001 被误判成异常值。
    cutoff = max(
        _MAD_MULTIPLIER * mad,
        _FLOAT_TOLERANCE * max(1.0, abs(center)),
    )
    used_points = tuple(
        point
        for point in candidates
        if abs(point.forward - center) <= cutoff
    )
    if len(_unique_strikes(used_points)) < 2:
        raise ValueError("MAD异常值过滤后少于两个非目标K，多K远期不可用")

    # fsum 比普通 sum 在很多小数相加时更稳定；除以数量就是等权均值。
    robust_forward = fsum(point.forward for point in used_points) / len(
        used_points
    )
    excluded_target_k = excluded[0].strike if excluded else None
    method = "put_call_parity_multi_strike_leave_one_out_mad_mean"
    source = (
        "多K Put-Call Parity稳健远期；"
        f"总pair={len(all_points)}；候选pair={len(candidates)}；"
        f"采用pair={len(used_points)}；"
        f"目标pair排除={'是' if excluded else '否'}；"
        f"中位数={center:g}；MAD={mad:g}"
    )
    return RobustParityForwardResult(
        forward=robust_forward,
        median=center,
        dispersion=mad,
        pair_count=len(candidates),
        used_pair_count=len(used_points),
        excluded_target_k=excluded_target_k,
        all_strikes=_unique_strikes(candidates),
        used_strikes=_unique_strikes(used_points),
        method=method,
        source=source,
    )


def _validate_inputs(
    *,
    call_price: float,
    put_price: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
) -> None:
    """集中检查公式输入，避免生成一个表面正常但实际上无效的远期价格。"""

    named_values = {
        "认购价格": call_price,
        "认沽价格": put_price,
        "行权价": strike,
        "剩余期限": time_to_maturity,
        "无风险利率": risk_free_rate,
    }
    for name, value in named_values.items():
        if not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"{name}必须是有限数值，实际为 {value!r}")

    if call_price < 0.0:
        raise ValueError("认购期权价格不能为负数")
    if put_price < 0.0:
        raise ValueError("认沽期权价格不能为负数")
    if strike <= 0.0:
        raise ValueError("行权价必须为正数")
    # Put-Call Parity 在到期日仍然成立，此时 D=1，因此 T=0 是合法输入。
    # 只有估值日在到期日之后（T<0）才属于错误数据。
    if time_to_maturity < 0.0:
        raise ValueError("剩余期限不能为负数；估值日不能晚于到期日")


def _validate_number(name: str, value: float, *, positive: bool) -> None:
    """检查多 K 聚合器的数值输入，错误信息保持为中文。"""

    if not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name}必须是有限数值，实际为 {value!r}")
    if positive and value <= 0.0:
        raise ValueError(f"{name}必须为正数，实际为 {value!r}")


def _unique_strikes(
    points: Iterable[ParityForwardPoint],
) -> tuple[float, ...]:
    """按容差去重 K；相同 K 的不同合约版本仍可作为不同 pair 聚合。"""

    result: list[float] = []
    for point in sorted(points, key=lambda item: item.strike):
        if not result or not isclose(
            point.strike,
            result[-1],
            rel_tol=0.0,
            abs_tol=_STRIKE_TOLERANCE,
        ):
            result.append(point.strike)
    return tuple(result)


def _source_text(*, call_code: str, put_code: str, strike: float) -> str:
    """生成可直接写进归因明细表的简短数据来源说明。"""

    call_label = call_code or "未提供Call代码"
    put_label = put_code or "未提供Put代码"
    return (
        "同行权价Put-Call Parity；"
        f"K={strike:g}；Call={call_label}；Put={put_label}"
    )



