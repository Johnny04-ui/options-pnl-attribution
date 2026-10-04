from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log, sqrt
from statistics import NormalDist
from typing import Literal


# 标准正态分布对象。后面用它计算累计概率 N(x) 和密度 phi(x)。
NORMAL = NormalDist()

# IV 拟合状态只有这三种，写错字符串时类型检查工具会提醒我们。
FitStatus = Literal[
    "EXACT",
    "BELOW_MODEL_RANGE",
    "ABOVE_MODEL_RANGE",
]


@dataclass(frozen=True)
class Black76Result:
    """单份期权的 Black-76 价格和 Greeks。

    delta、gamma 都是对远期价格 F 的敏感度；Vega 对应波动率变化
    1.00（例如 20% 变成 120%）；Theta 是一年口径的日历时间损耗。
    """

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float


@dataclass(frozen=True)
class ImpliedVolatilityFit:
    """“尽力拟合”隐含波动率的完整结果。

    price_error 定义为 ``拟合价格 - 市场价格``：
    正数表示模型最低价格仍然太高，负数表示模型最高价格仍然太低。
    """

    volatility: float
    fitted_price: float
    price_error: float
    status: FitStatus


def _option_type(call_put: str) -> str:
    """把 CALL/PUT 等常见写法统一成 C/P。"""

    value = call_put.strip().upper()
    aliases = {"C": "C", "CALL": "C", "P": "P", "PUT": "P"}
    if value not in aliases:
        raise ValueError(f"期权类型应为C或P，实际为{call_put!r}")
    return aliases[value]


def _validate_model_inputs(
    forward: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    volatility: float,
) -> None:
    """集中检查 Black-76 的输入，避免不同函数各写一遍。"""

    values = (
        forward,
        strike,
        time_to_maturity,
        risk_free_rate,
        volatility,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("Black-76输入包含非有限数值")
    if forward <= 0:
        raise ValueError("远期价格必须为正")
    if strike <= 0:
        raise ValueError("行权价必须为正")
    if time_to_maturity <= 0:
        raise ValueError("期权已经到期，无法计算Black-76 Greeks")
    if volatility <= 0:
        raise ValueError("波动率必须为正")


def black76_price_greeks(
    *,
    forward: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    volatility: float,
    call_put: str,
) -> Black76Result:
    """计算欧式期权的 Black-76 价格及远期 Greeks。

    这里把远期价格 ``forward`` 看成自变量。Theta 按“远期价格 F
    保持不变、日历向前走一年”的定义计算，因此可直接乘以天数/365。
    """

    _validate_model_inputs(
        forward,
        strike,
        time_to_maturity,
        risk_free_rate,
        volatility,
    )
    option_type = _option_type(call_put)

    root_time = sqrt(time_to_maturity)
    discount = exp(-risk_free_rate * time_to_maturity)
    d1 = (
        log(forward / strike)
        + 0.5 * volatility**2 * time_to_maturity
    ) / (volatility * root_time)
    d2 = d1 - volatility * root_time
    density = NORMAL.pdf(d1)

    # Gamma 和 Vega 对看涨、看跌相同，且都是针对远期价格 F。
    gamma = discount * density / (
        forward * volatility * root_time
    )
    vega = discount * forward * density * root_time

    if option_type == "C":
        price = discount * (
            forward * NORMAL.cdf(d1)
            - strike * NORMAL.cdf(d2)
        )
        delta = discount * NORMAL.cdf(d1)
    else:
        price = discount * (
            strike * NORMAL.cdf(-d2)
            - forward * NORMAL.cdf(-d1)
        )
        delta = -discount * NORMAL.cdf(-d1)

    # calendar theta = -dV/dT；这里 T 是剩余期限，且求导时固定 F。
    theta = (
        risk_free_rate * price
        - discount
        * forward
        * density
        * volatility
        / (2.0 * root_time)
    )

    return Black76Result(
        price=price,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
    )


def implied_volatility_best_fit(
    *,
    market_price: float,
    forward: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    call_put: str,
    minimum_volatility: float = 1e-8,
    maximum_volatility: float = 16.0,
    tolerance: float = 1e-10,
    max_iterations: int = 120,
) -> ImpliedVolatilityFit:
    """在给定波动率区间内反解 IV，越界时返回最接近的边界解。

    市场价格可能带有噪音，甚至落在 Black-76 的可达价格区间外。
    本函数不会因此丢掉该期权，而是返回最低或最高波动率对应的拟合，
    并通过 ``status`` 和 ``price_error`` 明确标记误差。
    """

    if not isfinite(market_price):
        raise ValueError("期权市场价格不是有限数值")
    if market_price < 0:
        raise ValueError("期权市场价格不能为负")
    if not isfinite(tolerance) or tolerance <= 0:
        raise ValueError("拟合容差必须为正")
    if max_iterations <= 0:
        raise ValueError("最大迭代次数必须为正整数")
    if (
        not isfinite(minimum_volatility)
        or not isfinite(maximum_volatility)
        or minimum_volatility <= 0
        or maximum_volatility <= minimum_volatility
    ):
        raise ValueError("波动率上下限无效")

    # 用最低波动率复用模型输入检查；call_put 则单独标准化一次。
    _validate_model_inputs(
        forward,
        strike,
        time_to_maturity,
        risk_free_rate,
        minimum_volatility,
    )
    option_type = _option_type(call_put)

    def price_at(volatility: float) -> float:
        """给二分法使用的小函数：传入 sigma，只返回模型价格。"""

        return black76_price_greeks(
            forward=forward,
            strike=strike,
            time_to_maturity=time_to_maturity,
            risk_free_rate=risk_free_rate,
            volatility=volatility,
            call_put=option_type,
        ).price

    low = minimum_volatility
    high = maximum_volatility
    low_price = price_at(low)
    high_price = price_at(high)
    price_tolerance = tolerance * max(
        1.0,
        forward,
        strike,
        market_price,
    )

    if market_price < low_price - price_tolerance:
        return ImpliedVolatilityFit(
            volatility=low,
            fitted_price=low_price,
            price_error=low_price - market_price,
            status="BELOW_MODEL_RANGE",
        )
    if market_price > high_price + price_tolerance:
        return ImpliedVolatilityFit(
            volatility=high,
            fitted_price=high_price,
            price_error=high_price - market_price,
            status="ABOVE_MODEL_RANGE",
        )

    # 价格恰好位于数值边界时，直接返回，可少做很多轮二分。
    if abs(low_price - market_price) <= price_tolerance:
        return ImpliedVolatilityFit(
            volatility=low,
            fitted_price=low_price,
            price_error=low_price - market_price,
            status="EXACT",
        )
    if abs(high_price - market_price) <= price_tolerance:
        return ImpliedVolatilityFit(
            volatility=high,
            fitted_price=high_price,
            price_error=high_price - market_price,
            status="EXACT",
        )

    # Black-76 价格随 sigma 单调上升，因此可以稳定地用二分法反解。
    fitted_volatility = (low + high) / 2.0
    fitted_price = price_at(fitted_volatility)
    for _ in range(max_iterations):
        fitted_volatility = (low + high) / 2.0
        fitted_price = price_at(fitted_volatility)
        if abs(fitted_price - market_price) <= price_tolerance:
            break
        if fitted_price < market_price:
            low = fitted_volatility
        else:
            high = fitted_volatility

    return ImpliedVolatilityFit(
        volatility=fitted_volatility,
        fitted_price=fitted_price,
        price_error=fitted_price - market_price,
        status="EXACT",
    )



