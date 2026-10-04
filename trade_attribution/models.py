from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


MODEL_VERSION = "public_demo_black76_pcp_v1"


# 对计算而言只需要买卖方向；T_TYPE 用来把开平仓编码转换成买卖符号。
OPTION_DIRECTIONS = {
    "DK": 1.0,   # 多头开仓：买入
    "DP": -1.0,  # 多头平仓：卖出
    "KK": -1.0,  # 空头开仓：卖出
    "KP": 1.0,   # 空头平仓：买入
}


@dataclass(frozen=True)
class Holding:
    portfolio_code: str
    holding_date: date
    instrument_code: str
    market: str
    instrument_name: str
    asset_type: str
    contract_count: float
    direction: str

    @property
    def signed_quantity(self) -> float:
        if self.direction == "L":
            return abs(self.contract_count)
        if self.direction == "S":
            return -abs(self.contract_count)
        raise ValueError(
            f"{self.instrument_code} 的 POSITION={self.direction!r}，应为 L 或 S"
        )


@dataclass(frozen=True)
class Trade:
    source_id: str
    portfolio_code: str
    trade_date: date
    instrument_code: str
    instrument_name: str
    asset_type: str
    market: str
    account_attribute: str
    trade_type: str
    position: str
    count: float
    price: float
    amount: float
    net_amount: float
    commission: float
    fee: float

    @property
    def signed_quantity(self) -> float:
        if self.asset_type == "OPT_F":
            return OPTION_DIRECTIONS[self.trade_type] * abs(self.count)
        # ETF 沿用此前已跑通的流水字段口径：L 为买入，S 为卖出。
        if self.position == "L":
            return abs(self.count)
        if self.position == "S":
            return -abs(self.count)
        raise ValueError(
            f"{self.instrument_code} 的 POSITION={self.position!r}，应为 L 或 S"
        )

    @property
    def action(self) -> str:
        return "买入" if self.signed_quantity >= 0 else "卖出"

    @property
    def total_fee(self) -> float:
        return abs(self.commission) + abs(self.fee)

    @property
    def is_etf(self) -> bool:
        text = f"{self.instrument_name} {self.account_attribute}".upper()
        return "ETF" in text or "基金" in text


@dataclass(frozen=True)
class OptionDescription:
    wind_code: str
    security_code: str
    name: str
    underlying_wind_code: str
    call_put: str
    strike: float
    maturity_date: date
    multiplier: float


@dataclass(frozen=True)
class OptionTermsChange:
    """Wind 记录的一次行权价/合约单位调整。"""

    wind_code: str
    change_date: date
    old_strike: float
    new_strike: float
    old_multiplier: float
    new_multiplier: float


@dataclass(frozen=True)
class PricePoint:
    wind_code: str
    trade_date: date
    close: float


@dataclass(frozen=True)
class HoldingAttributionRow:
    portfolio_code: str
    trade_date: date
    previous_trade_date: date
    instrument_code: str
    wind_code: str
    instrument_name: str
    asset_type: str
    market: str
    position: str
    raw_count: float
    signed_quantity: float
    multiplier: float
    multiplier_end: float
    close_start: float
    close_end: float
    call_put: str
    strike: float | None
    strike_end: float | None
    risk_free_rate: float | None
    time_to_maturity_start: float | None
    time_to_maturity_end: float | None
    greeks_source: str
    underlying_code: str
    underlying_close_start: float | None
    underlying_close_end: float | None
    forward_start: float | None
    forward_end: float | None
    # 若跨越合约调整日，需要先把期末远期换算成期初合约单位，才能计算 Delta/Gamma。
    forward_end_on_start_terms: float | None
    forward_change: float | None
    forward_source_start: str
    forward_source_end: str
    # 多 K 诊断：候选数是排除目标配对后的数量，采用数是 MAD 过滤后
    # 真正进入等权平均的数量。MAD 越大，说明不同行权价推导的 F 越分散。
    forward_pair_count_start: int | None
    forward_used_pair_count_start: int | None
    forward_mad_start: float | None
    forward_pair_count_end: int | None
    forward_used_pair_count_end: int | None
    forward_mad_end: float | None
    implied_vol_start: float | None
    implied_vol_end: float | None
    iv_fit_status_start: str
    iv_fit_status_end: str
    iv_price_error_start: float | None
    iv_price_error_end: float | None
    delta_start: float | None
    delta_end: float | None
    gamma_start: float | None
    gamma_end: float | None
    vega_start: float | None
    vega_end: float | None
    theta_start: float | None
    theta_end: float | None
    pnl_holding: float
    pnl_delta: float
    pnl_gamma: float
    pnl_vega: float
    pnl_theta: float
    pnl_residual: float
    reconciliation: float


@dataclass(frozen=True)
class TradePnlRow:
    source_id: str
    portfolio_code: str
    trade_date: date
    instrument_code: str
    wind_code: str
    instrument_name: str
    asset_type: str
    market: str
    trade_type: str
    position: str
    action: str
    raw_count: float
    signed_quantity: float
    multiplier: float
    trade_price_raw: float
    trade_price_per_unit: float
    close_end: float
    amount: float
    net_amount: float
    turnover: float
    pnl_gross: float
    pnl_delta: float
    fee: float
    pnl_net: float
    gross_return: float | None
    net_return: float | None
    reconciliation: float


@dataclass(frozen=True)
class DataIssue:
    trade_date: date
    source_type: str
    source_id: str
    instrument_code: str
    instrument_name: str
    message: str
    created_at: datetime


@dataclass(frozen=True)
class RunRecord:
    portfolio_code: str
    trade_date: date
    previous_trade_date: date
    status: str
    holding_count: int
    trade_count: int
    issue_count: int
    message: str
    updated_at: datetime
    model_version: str = MODEL_VERSION


@dataclass(frozen=True)
class DailyHistoryRow:
    portfolio_code: str
    trade_date: date
    previous_trade_date: date
    status: str
    holding_count: int
    holding_option_count: int
    holding_etf_count: int
    trade_count: int
    trade_option_count: int
    trade_etf_count: int
    issue_count: int
    greeks_unavailable_count: int
    holding_pnl: float
    holding_option_pnl: float
    holding_etf_pnl: float
    pnl_delta: float
    pnl_gamma: float
    pnl_vega: float
    pnl_theta: float
    pnl_residual: float
    intraday_turnover: float
    intraday_gross: float
    intraday_fee: float
    intraday_net: float
    intraday_gross_return: float | None
    intraday_net_return: float | None
    daily_gross: float
    daily_net: float
    reconciliation: float
    updated_at: datetime
    model_version: str = MODEL_VERSION



