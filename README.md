# Options P&L Attribution — Black-76 & Multi-Strike Put–Call Parity

一个经过脱敏的期权收益归因作品集项目。它使用 Black-76 模型，将期权持仓的每日损益拆分为 Delta、Gamma、Vega、Theta 与 Residual，并使用多行权价 Put–Call Parity（PCP）估计远期价格。

> 本仓库只包含通用计算引擎、合成示例和自动化测试。真实交易流水、持仓、账户信息、数据库配置、生产 SQL、数据供应商凭证及公司目录均未收录。

## 核心亮点

- 使用同行权价 Call/Put 根据 `C - P = exp(-rT) × (F - K)` 反推远期价格。
- 排除目标期权自身所在的配对，再用多个外部行权价估计远期，减少机械自引用。
- 使用 MAD（中位数绝对偏差）过滤异常远期点。
- 通过二分法拟合隐含波动率，并明确标记模型价格区间外的边界解。
- 支持 Delta、Gamma、Vega、Theta 与 Residual 的逐项损益勾稽。
- 处理多空方向、ETF `Delta=1`、盘中交易、到期日和合约乘数调整。
- 包含 33 个无需数据库、完全使用合成数据的单元测试。

## 归因公式

设期初持仓数量为 `Q`、合约乘数为 `M`、远期价格变化为 `ΔF`、隐含波动率变化为 `ΔIV`：

```text
Delta P&L = Q × M × Delta × ΔF
Gamma P&L = Q × M × 0.5 × Gamma × (ΔF)²
Vega P&L  = Q × M × Vega × ΔIV
Theta P&L = Q × M × Theta × elapsed_days / 365
Residual  = Actual P&L - Delta - Gamma - Vega - Theta
```

Residual 是勾稽项，可能包含高阶项、波动率曲面变化、日频离散误差与模型误差；它不能单独证明输入数据正确。

## 项目结构

```text
trade_attribution/
├── black76.py          # Black-76 定价、Greeks 与隐含波动率拟合
├── parity_forward.py   # 单 K PCP 与多 K 稳健远期
├── option_terms.py     # 历史行权价与合约乘数调整
├── calculation.py      # 持仓和盘中交易收益归因
├── daily_history.py    # 每日汇总与增量结果工具
└── models.py           # 数据结构
examples/
└── demo_synthetic.py   # 完全合成、可直接运行的演示
tests/                  # 33 个合成数据单元测试
```

## 快速开始

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python examples/demo_synthetic.py
python -m unittest discover -s tests -v
```

演示数据由代码现场生成，不对应任何真实账户、客户、证券或交易。

## 脱敏边界

公开版刻意排除了以下内容：

- 真实委托、成交、持仓及收益结果文件；
- API Token、`.env`、数据库主机名、用户名与密码；
- 内部数据库表名、字段映射和生产查询；
- 公司名称、个人路径、账户号及组合编号；
- 虚拟环境、缓存、日志和供应商数据。

如果要接入真实数据，应在私有环境中编写适配器，将行情与持仓转换为 `models.py` 中的数据对象；不要把凭证写进代码。

## 免责声明

本项目用于研究与技术展示，不构成投资建议，也不是可直接部署的交易或风险系统。结果会受到模型假设、数据质量、交易成本和流动性等因素影响。

