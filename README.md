# 麦麦积分管家 mcd-points-butler

> 麦当劳积分管理 Skill：临期积分预警、积分商城兑换参谋、抽奖期望值分析、月度麦麦账单。
> 一句话——**别让积分烂在账户里**。

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

麦当劳程序员创意开发大赛（WorkBuddy「1024 造物挑战」程序员节应用创作大赛）参赛作品。
基于麦当劳中国官方 MCP（[M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)）开发。

## 解决什么问题

麦当劳 App 里躺着几万积分的人不少，但三个问题没人管：

1. **积分悄悄过期**——账户里有"即将过期积分"，但没人在到期前提醒你；
2. **不知道能换什么**——积分商城商品一大堆，哪个值得换、手头的分够换哪件，全靠翻；
3. **抽奖像赌博**——积分抽奖划不划算，从来没算过期望值。

麦麦积分管家把官方 MCP 的原子能力编排成一条"查询 → 分析 → 建议"的日常闭环，一条命令给出答案。

## 功能特性

| 命令 | 能力 | 用到的 MCP 工具 |
|---|---|---|
| `status` | 积分总览 + 临期紧迫度分级（紧急/临近/关注）+ 过期倒计时 | `query-my-account`、`now-time-info` |
| `redeem` | 可兑商品性价比榜（每积分价值）、临期兑换策略、"再攒一点"清单 | `mall-points-products`、`mall-product-detail` |
| `lottery` | 抽奖活动解析 + 期望价值计算，给出"抽/不抽"结论 | `query-lottery-info`、`query-my-prizes` |
| `bill` | 月度麦麦账单：订单统计、按日分布、最大单、麦门浓度 | `order-list`、`mall-order-list` |
| `report` | 以上全部，一键输出 | 全部 |

**设计原则：全程只读。** 不创建订单、不抽奖、不领券、不碰任何写操作——积分管家只做分析和建议，
花积分的事永远由用户自己在麦当劳 App 里确认。对比其他会直接调 `draw-lottery` / `create-order`
的作品，这是刻意选择的克制。

## 快速开始

### 1. 领取 MCP Token（免费）

打开 [open.mcd.cn/mcp](https://open.mcd.cn/mcp)，手机号登录 → 控制台 → 激活，一键复制 Token。

### 2. 运行

```bash
# 零第三方依赖，Python 3.9+ 直接跑，无需 pip install
export MCD_MCP_TOKEN="你的Token"

python mcd-butler.py status                # 积分总览 + 临期预警
python mcd-butler.py redeem                # 兑换建议（性价比榜）
python mcd-butler.py lottery               # 抽奖参谋
python mcd-butler.py bill                  # 本月账单
python mcd-butler.py bill --month 2026-09  # 指定月份
python mcd-butler.py report                # 一键全量报告
```

Windows PowerShell 用 `$env:MCD_MCP_TOKEN="你的Token"`。

### 3. 实际输出（mock 数据演示）

```
$ python mcd-butler.py report

麦麦积分总览 （麦门信徒）
  项目     数值
--------  ------
可用积分   2,380
累计积分  15,600
冻结积分     200
即将过期     560

临期预警：积分告急，建议立即兑换
最近一笔 560 积分将于 2026-10-24 23:59:59 过期（约 2 天）。
提示：有 200 积分处于冻结状态，暂不可用。

可兑商品 TOP 8（可用积分 2,380）
        商品          所需积分  参考价    每积分价值   库存
--------------------  --------  -------  ------------  ----
可口可乐（中）兑换券       300   ¥8.00  0.0267 元/分  有货
薯条（小）兑换券           800  ¥11.50  0.0144 元/分  有货
巨无霸汉堡兑换券         2,200  ¥23.00  0.0105 元/分  有货
麦乐鸡 4 块兑换券        1,200  ¥12.00  0.0100 元/分  缺货
早餐猪柳蛋汉堡兑换券     1,500  ¥13.50  0.0090 元/分  有货

临期提醒：你有 560 积分即将过期，建议优先兑换低价快消品
（小食/饮料类），避开高积分长保质期商品，别让积分烂在账户里。

抽奖活动：1024 程序员节积分抽奖
    奖品      参考价值(分)  中奖概率   库存
------------  ------------  --------  ------
1000 积分券          1,000    50.00%     500
免费巨无霸券         2,300    10.00%      20
谢谢参与                 0    40.00%  99,999

单次消耗：50 积分，剩余次数：3
参谋结论：期望价值 730 分 > 单次消耗 50 分，数学上划得来，可以抽。

2026-10 月度麦麦账单
    指标       数值
------------  -------
订单总数         4 单
餐饮订单         3 单
餐饮消费      ¥97.00
商城订单         1 单
商城积分消耗   300 分
合计支出      ¥97.00
...
```

## 作为 WorkBuddy Skill 使用

本仓库同时是一个标准的 WorkBuddy Skill（`SKILL.md`）。配置好麦当劳 MCP 连接器后，
直接在对话里说人话即可：

> "看看我的麦当劳积分" / "有什么积分快过期了" / "现在抽奖划得来吗" / "我这个月在麦当劳花了多少"

Skill 会把上述命令编排进对话上下文，AI 直接调用并解读结果。
麦当劳 MCP 连接器配置方法见官方
[使用指南](https://github.com/M-China/mcd-mcp-server)。

## 项目结构

```
mcd-points-butler/
├── mcd-butler.py            # 命令行入口
├── mcd_butler/
│   ├── mcp_client.py        # MCP Streamable HTTP 客户端（零依赖，只读重试保护）
│   ├── points.py            # 积分总览 + 临期预警
│   ├── redeem.py            # 兑换建议（性价比分析）
│   ├── lottery.py           # 抽奖参谋（期望值）
│   ├── bill.py              # 月度账单
│   ├── report.py            # 一键报告
│   ├── util.py              # 防御性字段解析 / 表格渲染
│   └── cli.py               # 参数解析
├── mock/
│   └── mock_mcp_server.py   # 本地 Mock MCP Server（离线测试用）
├── tests/
│   └── test_butler.py       # 21 个测试：传输层 / 重试策略 / 各业务分支
├── SKILL.md                 # WorkBuddy Skill 定义
├── MCP_INTEGRATION.md       # MCP 工具清单与调用流程
├── CONTEST_DECLARATION.md   # 官方参赛声明（原文）
└── workbuddy.md             # 使用 WorkBuddy 开发的对话上下文
```

## 测试

```bash
python tests/test_butler.py        # 或 python -m unittest discover -s tests
```

21 个用例全绿，覆盖：JSON/SSE 两种 MCP 响应格式、只读工具安全重试、
写操作绝不重试、401/429 处理、临期紧迫度全部分支、兑换排序、期望值计算、
月度过滤、单模块失败不阻断整体报告。

## 安全与隐私

- **只读**：不调用任何写操作工具，不会花你的积分、不会下单；
- **Token 安全**：只从环境变量 `MCD_MCP_TOKEN` 或命令行 `--token` 读取，
  不落盘、不打印、不进日志（符合官方参赛声明的信息安全要求）；
- **限流友好**：单次报告约 6 次 MCP 调用，远低于官方 600 次/分钟限制；
- 网络异常（连接重置/超时）会转成可读错误并安全重试，不会把堆栈崩给用户。

## 参赛信息

- 赛事：麦当劳程序员创意开发大赛（WorkBuddy「1024 造物挑战」程序员节应用创作大赛）
- 官方活动仓库：[M-China/mcd-developer-innovation-challenge](https://github.com/M-China/mcd-developer-innovation-challenge)
- MCP 服务：[M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)
- 开发工具：腾讯 WorkBuddy（完整开发记录见 [workbuddy.md](workbuddy.md)）

## License

MIT
