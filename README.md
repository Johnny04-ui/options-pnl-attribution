# Options P&L Attribution — Black-76 & Multi-Strike Put–Call Parity

> **Derivatives analytics · Black-76 · Greeks decomposition · Robust forward estimation · Tested Python engineering**

An end-to-end options analytics engine that decomposes daily portfolio P&L into
Delta, Gamma, Vega, Theta, and Residual components. The system combines Black-76
pricing with a robust multi-strike put–call-parity estimator for the forward
price, providing a transparent bridge between derivatives theory and production-
style quantitative implementation.

The project demonstrates strong command of option pricing, implied-volatility
inversion, Greek-based attribution, contract-life-cycle handling, robust
statistics, and test-driven Python development. The public version contains a
fully synthetic demo and **33 automated unit tests**.

> This repository is a sanitized portfolio edition. Real trades, positions,
> account identifiers, database configuration, production SQL, vendor credentials,
> and organization-specific paths are intentionally excluded.

## Quantitative capabilities demonstrated

- Implemented Black-76 prices and analytical Greeks for European options.
- Recovered forward prices from matched calls and puts across multiple strikes.
- Prevented mechanical self-reference by excluding the target option's own pair.
- Applied median absolute deviation (MAD) filtering to reject unstable parity estimates.
- Solved implied volatility with bounded bisection and explicit boundary diagnostics.
- Attributed P&L across long/short positions, intraday trades, expiries, ETFs, and multiplier changes.
- Built data-independent tests for pricing identities, sign conventions, edge cases, and daily aggregation.

## Attribution framework

Let `Q` be the opening position, `M` the contract multiplier, `ΔF` the forward-
price change, and `ΔIV` the implied-volatility change:

```text
Delta P&L = Q × M × Delta × ΔF
Gamma P&L = Q × M × 0.5 × Gamma × (ΔF)²
Vega P&L  = Q × M × Vega × ΔIV
Theta P&L = Q × M × Theta × elapsed_days / 365
Residual  = Actual P&L - Delta - Gamma - Vega - Theta
```

Residual is treated as a reconciliation term. It may contain higher-order effects,
volatility-surface dynamics, discrete-time approximation error, and model error;
it is not used as a substitute for input-data validation.

## System design

```text
market quotes + positions
          |
          v
multi-strike put-call parity -> robust forward estimate
          |
          v
Black-76 implied volatility and Greeks
          |
          v
Delta / Gamma / Vega / Theta attribution
          |
          v
daily reconciliation and history utilities
```

## Repository structure

```text
trade_attribution/
├── black76.py          # Black-76 pricing, Greeks, and IV inversion
├── parity_forward.py   # Single- and multi-strike parity forward estimates
├── option_terms.py     # Historical strike and multiplier adjustments
├── calculation.py      # Position and intraday-trade attribution
├── daily_history.py    # Daily aggregation and incremental history tools
└── models.py           # Typed domain data structures
examples/
└── demo_synthetic.py   # Fully synthetic, directly runnable example
tests/                  # 33 synthetic unit tests
```

## Quick start

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python examples/demo_synthetic.py
python -m unittest discover -s tests -v
```

The demo data are generated at runtime and do not correspond to any real account,
client, security, or transaction.

## Sanitization boundary

The public repository excludes:

- real orders, executions, positions, and realized P&L files;
- API tokens, `.env` files, database hosts, users, and passwords;
- internal table names, field mappings, and production queries;
- company names, local personal paths, account numbers, and portfolio identifiers;
- virtual environments, caches, logs, and vendor datasets.

Real-data integration should be implemented privately through adapters that map
approved market and position data into the domain objects in `models.py`.

## 中文简介

本项目实现了一个经过脱敏的期权收益归因引擎，使用 Black-76 模型与多行权价
Put–Call Parity，将每日损益拆分为 Delta、Gamma、Vega、Theta 与 Residual。
代码包含完全合成的演示数据和 33 个自动化测试，重点展示衍生品建模、稳健估计、
边界条件处理和可复现的软件工程能力。

## Disclaimer

This project is intended for research and technical demonstration. It is not
investment advice or a deployable trading or risk system. Results depend on model
assumptions, data quality, transaction costs, and market liquidity.
