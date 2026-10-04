from __future__ import annotations

from datetime import date

from .black76 import (
    Black76Result,
    ImpliedVolatilityFit,
    black76_price_greeks,
    implied_volatility_best_fit,
)
from .models import (
    Holding,
    HoldingAttributionRow,
    OptionDescription,
    PricePoint,
    Trade,
    TradePnlRow,
)
from .parity_forward import ParityForwardResult, RobustParityForwardResult


# 单 K 结果仍保留给公式单元测试使用；正式 service 会传入多 K 稳健结果。
ForwardResult = ParityForwardResult | RobustParityForwardResult


def _self_calculated_valuation(
    market_price: float,
    forward: float,
    description: OptionDescription,
    valuation_date: date,
    risk_free_rate: float,
) -> tuple[ImpliedVolatilityFit, Black76Result, float]:
    days_to_maturity = (description.maturity_date - valuation_date).days
    if days_to_maturity <= 0:
        raise ValueError(f"{valuation_date} 期权已经到期，无法反解IV")
    time_to_maturity = days_to_maturity / 365.0
    fit = implied_volatility_best_fit(
        market_price=market_price,
        forward=forward,
        strike=description.strike,
        time_to_maturity=time_to_maturity,
        risk_free_rate=risk_free_rate,
        call_put=description.call_put,
    )
    greeks = black76_price_greeks(
        forward=forward,
        strike=description.strike,
        time_to_maturity=time_to_maturity,
        risk_free_rate=risk_free_rate,
        volatility=fit.volatility,
        call_put=description.call_put,
    )
    return fit, greeks, time_to_maturity


def calculate_holding_option(
    holding: Holding,
    trade_date: date,
    description_start: OptionDescription,
    description_end: OptionDescription,
    option_start: PricePoint,
    option_end: PricePoint,
    *,
    underlying_start: PricePoint | None,
    underlying_end: PricePoint | None,
    forward_start: ForwardResult | None,
    forward_end: ForwardResult | None,
    risk_free_rate: float,
    greeks_unavailable_reason: str = "",
) -> HoldingAttributionRow:
    """用 Black-76 归因昨日持仓，同时始终保留真实市场价值变化。"""

    for label, description in (
        ("期初", description_start),
        ("期末", description_end),
    ):
        if description.multiplier <= 0:
            raise ValueError(f"{label}合约乘数非正：{description.multiplier}")
        if description.strike <= 0:
            raise ValueError(f"{label}行权价非正：{description.strike}")
    if option_start.close < 0 or option_end.close < 0:
        raise ValueError("期权收盘价为负")
    elapsed_days = (trade_date - holding.holding_date).days
    if elapsed_days <= 0:
        raise ValueError("归因日期必须晚于持仓日期")
    if trade_date > description_end.maturity_date:
        raise ValueError(
            f"归因日{trade_date}晚于到期日{description_end.maturity_date}"
        )

    quantity = holding.signed_quantity
    multiplier_start = description_start.multiplier
    multiplier_end = description_end.multiplier
    # 跨除权调整日时，期初和期末每张合约代表的份数可能不同。
    pnl_holding = quantity * (
        multiplier_end * option_end.close
        - multiplier_start * option_start.close
    )
    time_fraction = elapsed_days / 365.0

    # 没有可用的同行权价 Call/Put 配对时，真实持仓损益仍然保留；
    # 无法解释的部分全部进入 Residual。
    if forward_start is None or forward_end is None:
        start_fit = end_fit = None
        start_greeks = end_greeks = None
        time_start = (
            max((description_start.maturity_date - holding.holding_date).days, 0)
            / 365.0
        )
        time_end = (
            max((description_end.maturity_date - trade_date).days, 0) / 365.0
        )
        pnl_delta = pnl_gamma = pnl_vega = pnl_theta = 0.0
        pnl_residual = pnl_holding
        forward_end_on_start_terms = None
        forward_change = None
        greeks_source = f"Black-76不可用：{greeks_unavailable_reason}"
    else:
        start_fit, start_greeks, time_start = _self_calculated_valuation(
            option_start.close,
            forward_start.forward,
            description_start,
            holding.holding_date,
            risk_free_rate,
        )
        if trade_date == description_end.maturity_date:
            end_fit = None
            end_greeks = None
            time_end = 0.0
        else:
            end_fit, end_greeks, time_end = _self_calculated_valuation(
                option_end.close,
                forward_end.forward,
                description_end,
                trade_date,
                risk_free_rate,
            )

        position_units = quantity * multiplier_start
        # 除权调整日会同时改变 K 和合约乘数。期末 PCP 远期属于“期末每份”
        # 的价格口径，必须先乘 M1/M0 才能和期初远期比较。没有调整时比例为 1。
        forward_end_on_start_terms = (
            forward_end.forward * multiplier_end / multiplier_start
        )
        forward_change = (
            forward_end_on_start_terms - forward_start.forward
        )
        pnl_delta = position_units * start_greeks.delta * forward_change
        pnl_gamma = (
            position_units * 0.5 * start_greeks.gamma * forward_change**2
        )
        pnl_vega = (
            position_units
            * start_greeks.vega
            * (end_fit.volatility - start_fit.volatility)
            if end_fit is not None
            else 0.0
        )
        pnl_theta = position_units * start_greeks.theta * time_fraction
        pnl_residual = pnl_holding - (
            pnl_delta + pnl_gamma + pnl_vega + pnl_theta
        )
        greeks_source = (
            "Black-76（多K PCP留一法远期；到期日仅期初Greeks）"
            if end_greeks is None
            else "Black-76（多K PCP留一法远期；收盘价最佳拟合IV）"
        )
    reconciliation = pnl_holding - (
        pnl_delta + pnl_gamma + pnl_vega + pnl_theta + pnl_residual
    )

    return HoldingAttributionRow(
        portfolio_code=holding.portfolio_code,
        trade_date=trade_date,
        previous_trade_date=holding.holding_date,
        instrument_code=holding.instrument_code,
        wind_code=description_end.wind_code,
        instrument_name=holding.instrument_name,
        asset_type=holding.asset_type,
        market=holding.market,
        position=holding.direction,
        raw_count=holding.contract_count,
        signed_quantity=quantity,
        multiplier=multiplier_start,
        multiplier_end=multiplier_end,
        close_start=option_start.close,
        close_end=option_end.close,
        call_put=description_end.call_put,
        strike=description_start.strike,
        strike_end=description_end.strike,
        risk_free_rate=risk_free_rate,
        time_to_maturity_start=time_start,
        time_to_maturity_end=time_end,
        greeks_source=greeks_source,
        underlying_code=description_end.underlying_wind_code,
        underlying_close_start=(
            underlying_start.close if underlying_start is not None else None
        ),
        underlying_close_end=(
            underlying_end.close if underlying_end is not None else None
        ),
        forward_start=(forward_start.forward if forward_start else None),
        forward_end=(forward_end.forward if forward_end else None),
        forward_end_on_start_terms=forward_end_on_start_terms,
        forward_change=forward_change,
        forward_source_start=(forward_start.source if forward_start else ""),
        forward_source_end=(forward_end.source if forward_end else ""),
        forward_pair_count_start=(
            getattr(forward_start, "pair_count", None) if forward_start else None
        ),
        forward_used_pair_count_start=(
            getattr(forward_start, "used_pair_count", None)
            if forward_start
            else None
        ),
        forward_mad_start=(
            getattr(forward_start, "dispersion", None)
            if forward_start
            else None
        ),
        forward_pair_count_end=(
            getattr(forward_end, "pair_count", None) if forward_end else None
        ),
        forward_used_pair_count_end=(
            getattr(forward_end, "used_pair_count", None)
            if forward_end
            else None
        ),
        forward_mad_end=(
            getattr(forward_end, "dispersion", None) if forward_end else None
        ),
        implied_vol_start=(start_fit.volatility if start_fit else None),
        implied_vol_end=(end_fit.volatility if end_fit else None),
        iv_fit_status_start=(start_fit.status if start_fit else "UNAVAILABLE"),
        iv_fit_status_end=(
            end_fit.status
            if end_fit
            else ("EXPIRY" if start_fit else "UNAVAILABLE")
        ),
        iv_price_error_start=(start_fit.price_error if start_fit else None),
        iv_price_error_end=(end_fit.price_error if end_fit else None),
        delta_start=(start_greeks.delta if start_greeks else None),
        delta_end=(end_greeks.delta if end_greeks else None),
        gamma_start=(start_greeks.gamma if start_greeks else None),
        gamma_end=(end_greeks.gamma if end_greeks else None),
        vega_start=(start_greeks.vega if start_greeks else None),
        vega_end=(end_greeks.vega if end_greeks else None),
        theta_start=(start_greeks.theta if start_greeks else None),
        theta_end=(end_greeks.theta if end_greeks else None),
        pnl_holding=pnl_holding,
        pnl_delta=pnl_delta,
        pnl_gamma=pnl_gamma,
        pnl_vega=pnl_vega,
        pnl_theta=pnl_theta,
        pnl_residual=pnl_residual,
        reconciliation=reconciliation,
    )


def calculate_holding_etf(
    holding: Holding,
    trade_date: date,
    wind_code: str,
    price_start: PricePoint,
    price_end: PricePoint,
) -> HoldingAttributionRow:
    if price_start.close <= 0 or price_end.close <= 0:
        raise ValueError("ETF收盘价非正")
    quantity = holding.signed_quantity
    pnl_holding = quantity * (price_end.close - price_start.close)
    return HoldingAttributionRow(
        portfolio_code=holding.portfolio_code,
        trade_date=trade_date,
        previous_trade_date=holding.holding_date,
        instrument_code=holding.instrument_code,
        wind_code=wind_code,
        instrument_name=holding.instrument_name,
        asset_type=holding.asset_type,
        market=holding.market,
        position=holding.direction,
        raw_count=holding.contract_count,
        signed_quantity=quantity,
        multiplier=1.0,
        multiplier_end=1.0,
        close_start=price_start.close,
        close_end=price_end.close,
        call_put="",
        strike=None,
        strike_end=None,
        risk_free_rate=None,
        time_to_maturity_start=None,
        time_to_maturity_end=None,
        greeks_source="ETF Delta=1",
        underlying_code=wind_code,
        underlying_close_start=price_start.close,
        underlying_close_end=price_end.close,
        forward_start=None,
        forward_end=None,
        forward_end_on_start_terms=None,
        forward_change=None,
        forward_source_start="",
        forward_source_end="",
        forward_pair_count_start=None,
        forward_used_pair_count_start=None,
        forward_mad_start=None,
        forward_pair_count_end=None,
        forward_used_pair_count_end=None,
        forward_mad_end=None,
        implied_vol_start=None,
        implied_vol_end=None,
        iv_fit_status_start="NOT_APPLICABLE",
        iv_fit_status_end="NOT_APPLICABLE",
        iv_price_error_start=None,
        iv_price_error_end=None,
        delta_start=1.0,
        delta_end=1.0,
        gamma_start=0.0,
        gamma_end=0.0,
        vega_start=0.0,
        vega_end=0.0,
        theta_start=0.0,
        theta_end=0.0,
        pnl_holding=pnl_holding,
        pnl_delta=pnl_holding,
        pnl_gamma=0.0,
        pnl_vega=0.0,
        pnl_theta=0.0,
        pnl_residual=0.0,
        reconciliation=0.0,
    )


def _trade_result(
    trade: Trade,
    wind_code: str,
    multiplier: float,
    trade_price_per_unit: float,
    close_end: float,
) -> TradePnlRow:
    quantity = trade.signed_quantity
    turnover = abs(trade.amount)
    pnl_gross = quantity * multiplier * (close_end - trade_price_per_unit)
    pnl_delta = pnl_gross if trade.asset_type == "SPT_S" else 0.0
    fee = trade.total_fee
    pnl_net = pnl_gross - fee
    gross_return = pnl_gross / turnover if turnover else None
    net_return = pnl_net / turnover if turnover else None
    reconciliation = pnl_net - (pnl_gross - fee)
    return TradePnlRow(
        source_id=trade.source_id,
        portfolio_code=trade.portfolio_code,
        trade_date=trade.trade_date,
        instrument_code=trade.instrument_code,
        wind_code=wind_code,
        instrument_name=trade.instrument_name,
        asset_type=trade.asset_type,
        market=trade.market,
        trade_type=trade.trade_type,
        position=trade.position,
        action=trade.action,
        raw_count=trade.count,
        signed_quantity=quantity,
        multiplier=multiplier,
        trade_price_raw=trade.price,
        trade_price_per_unit=trade_price_per_unit,
        close_end=close_end,
        amount=trade.amount,
        net_amount=trade.net_amount,
        turnover=turnover,
        pnl_gross=pnl_gross,
        pnl_delta=pnl_delta,
        fee=fee,
        pnl_net=pnl_net,
        gross_return=gross_return,
        net_return=net_return,
        reconciliation=reconciliation,
    )


def calculate_intraday_option(
    trade: Trade,
    description: OptionDescription,
    option_end: PricePoint,
) -> TradePnlRow:
    if description.multiplier <= 0:
        raise ValueError(f"合约乘数非正：{description.multiplier}")
    if option_end.close < 0:
        raise ValueError("期权收盘价为负")
    if trade.price == 0:
        raise ValueError("期权成交价为零")
    trade_price_per_unit = abs(trade.price) / description.multiplier
    return _trade_result(
        trade,
        description.wind_code,
        description.multiplier,
        trade_price_per_unit,
        option_end.close,
    )


def calculate_intraday_etf(
    trade: Trade,
    wind_code: str,
    price_end: PricePoint,
) -> TradePnlRow:
    if price_end.close <= 0 or trade.price == 0:
        raise ValueError("ETF成交价为零或收盘价非正")
    return _trade_result(
        trade,
        wind_code,
        1.0,
        abs(trade.price),
        price_end.close,
    )



