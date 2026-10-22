---
name: mcd-points-butler
description: 麦麦积分管家——麦当劳积分管理 Skill。查询麦当劳积分账户（可用/累计/冻结/即将过期）、临期积分预警与倒计时、积分商城可兑商品性价比推荐、积分抽奖期望值分析、月度麦麦账单。当用户提到麦当劳积分、麦麦积分、积分过期、积分兑换、积分商城、积分抽奖、麦当劳账单、麦门消费时使用。依赖麦当劳中国官方 MCP（mcd-mcp），全程只读，不代下单、不代抽奖。
---

# 麦麦积分管家（mcd-points-butler）

基于麦当劳中国官方 MCP（`https://mcp.mcd.cn`，工具见
https://github.com/M-China/mcd-mcp-server ）的积分管理 Skill。
**全程只读**：只做查询、分析、建议；任何消耗积分/下单/抽奖的动作
必须由用户本人在麦当劳 App 内确认，不得代为执行写操作工具。

## 前置条件

1. 用户已在 https://open.mcd.cn/mcp 用手机号登录并激活，拿到 MCP Token；
2. WorkBuddy 已配置麦当劳 MCP 连接器（streamablehttp，url=https://mcp.mcd.cn，
   headers Authorization=Bearer <token>）；
3. 本机 Python 3.9+（零第三方依赖）。

若未配置连接器，引导用户按官方 README 配置；不要尝试猜测或代填 Token。

## 执行方式

优先直接运行本仓库脚本（比逐工具编排更稳，输出已经是分析结论）：

```bash
# Token 通过环境变量注入，切勿把 Token 写进任何文件或输出
export MCD_MCP_TOKEN="<用户Token>"

python <skill目录>/mcd-butler.py status     # 积分总览 + 临期预警
python <skill目录>/mcd-butler.py redeem     # 兑换建议（性价比榜）
python <skill目录>/mcd-butler.py lottery    # 抽奖参谋（期望值）
python <skill目录>/mcd-butler.py bill [--month YYYY-MM]   # 月度账单
python <skill目录>/mcd-butler.py report     # 一键全量报告
```

Windows 下用 `$env:MCD_MCP_TOKEN="<用户Token>"`（PowerShell）。
`--url` 可指向本地 mock server（`mock/mock_mcp_server.py`）做离线演示。

也可以直接用 MCP 工具现场编排（query-my-account / now-time-info /
mall-points-products / query-lottery-info / order-list / mall-order-list），
但结论必须与脚本输出一致：临期分级、每积分价值、期望值计算规则见
`MCP_INTEGRATION.md`。

## 用户意图 → 命令映射

| 用户说 | 执行 |
|---|---|
| "我的麦当劳积分多少" / "积分快过期了吗" | `status` |
| "积分能换什么" / "兑换什么划算" | `redeem` |
| "抽奖值不值" / "现在抽奖划得来吗" | `lottery` |
| "这个月在麦当劳花了多少" / "麦门账单" | `bill` |
| "看看我的积分情况" / 泛泛的积分问题 | `report` |

## 输出要求

- 原样呈现脚本的分析结论（表格 + 预警文案），不要复述成流水账；
- 涉及"建议立即兑换/紧急"等预警时，保留紧迫度措辞并给出下一步动作；
- 用户追问细节（某件商品详情、某笔订单）时，可补调
  `mall-product-detail` / `mall-order-detail` / `query-my-prizes` 等只读工具；
- 任何情况下不调用写操作工具（create-order / draw-lottery /
  auto-bind-coupons / mall-create-order 等）；用户要求代为操作时，
  明确拒绝并引导其在麦当劳 App 内完成。

## 异常处理

- 401：Token 无效/过期 → 引导用户去 open.mcd.cn/mcp 重新领取；
- 429：触发限流 → 告知稍后再试（脚本已做退避重试）；
- 字段解析异常：先跑 `python mcd-butler.py status --debug` 看原始响应，
  按真实字段名修正 `mcd_butler/*.py` 中的别名表，再重新运行。
