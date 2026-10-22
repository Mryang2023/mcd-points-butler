# MCP_INTEGRATION.md

本文档说明麦麦积分管家实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## MCP Server

| 项 | 内容 |
|---|---|
| 服务提供方 | 麦当劳中国（M-China） |
| 官方仓库 | https://github.com/M-China/mcd-mcp-server |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（JSON-RPC 2.0） |
| 认证方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| Token 领取 | open.mcd.cn/mcp ，手机号登录后控制台激活（免费） |
| 限流 | 每 Token 600 次/分钟 |
| 服务范围 | 中国大陆（不含港澳台） |

客户端实现见 `mcd_butler/mcp_client.py`：纯标准库（`urllib`）实现
`initialize` → `notifications/initialized` → `tools/call` 握手，
兼容服务端返回纯 JSON 与 SSE 事件流两种响应格式。

## 使用的 Tool 清单

本项目**只调用只读工具**，共 8 个：

| Tool | 用途 | 用在本项目的模块 |
|---|---|---|
| `query-my-account` | 查询积分账户：可用/累计/冻结/即将过期积分 | `status` / `redeem` / `report` |
| `now-time-info` | 获取服务端当前时间（临期倒计时以服务端时间为准，避免本地时钟偏差） | `status` / `report` |
| `mall-points-products` | 麦麦商城积分兑换商品列表 | `redeem` / `report` |
| `mall-product-detail` | 商城商品详情（按编码补充明细） | `redeem`（备用） |
| `query-lottery-info` | 积分抽奖活动：状态、奖品、概率、消耗规则 | `lottery` / `report` |
| `query-my-prizes` | 我的抽奖奖品记录 | `lottery`（备用） |
| `order-list` | 近期到店/外送历史订单 | `bill` / `report` |
| `mall-order-list` | 麦麦商城近一年订单 | `bill` / `report` |

**刻意不使用的工具**：`create-order`、`cancel-order`、`draw-lottery`、
`auto-bind-coupons`、`mall-create-order` 等写操作。积分管家的定位是
"分析与建议"，消耗积分的动作必须由用户在麦当劳 App 内确认，
这既是产品克制，也是对用户账户安全的负责。

## 调用流程

### `status`（积分总览 + 临期预警）

```
initialize ──► tools/call now-time-info      （拿服务端当前时间）
           └─► tools/call query-my-account   （可用/累计/冻结/即将过期 + 临期明细）
                │
                ├─ 解析 expiringPoints 与 expiringPointsList[].expireTime
                ├─ 计算剩余天数 → 紧迫度分级：>7天关注 / ≤7天临近 / ≤3天紧急
                └─ 输出总览表 + 预警文案 + 行动建议
```

### `redeem`（兑换建议）

```
query-my-account ──► 得到可用积分 A
mall-points-products（分页遍历，按 productCode 去重）
    │
    ├─ 过滤 points ≤ A 的可兑商品
    ├─ 有参考价的商品计算「每积分价值 = 参考价 / 所需积分」，降序排列
    ├─ 无参考价商品排在最后（不虚估）
    └─ 额外输出「再攒 N 分就能兑」清单（points ≤ 1.5A）
```

### `lottery`（抽奖参谋）

```
query-lottery-info
    │
    ├─ 解析 status（进行中/已结束）、单次消耗、剩余次数
    ├─ 概率与奖品价值齐全时：期望价值 EV = Σ(概率ᵢ × 价值ᵢ)
    │      EV > 消耗  → 「数学上划得来」
    │      EV < 消耗  → 「长期抽大概率亏分，建议留积分换实物」
    └─ 概率未公开时：明确告知无法计算期望值，建议保守（不瞎给结论）
```

### `bill`（月度麦麦账单）

```
order-list + mall-order-list ──► 合并订单流
    │
    ├─ 按 createTime 过滤目标月份（默认当月，--month 可指定）
    ├─ 统计：订单数、餐饮消费、商城积分消耗、按日分布、最大单
    └─ 商城订单单独聚合，回答「这个月积分花哪去了」
```

### `report`（一键报告）

按 `status → redeem → lottery → bill` 顺序编排以上全部流程；
任一模块失败只降级显示该模块错误，不阻断整体输出。

## 健壮性设计

| 场景 | 处理 |
|---|---|
| 字段名与文档不一致 | 多别名 + 大小写不敏感 + 递归兜底解析（`util.search_value`） |
| 响应带 `{"code":0,"data":{...}}` 信封 | `util.unwrap` 统一脱壳 |
| 服务端返回 SSE 而非 JSON | 客户端同时兼容两种格式 |
| 网络抖动 / 连接重置 | 只读工具有限重试（指数退避），错误信息可读化 |
| 写操作误重试导致重复扣分 | 写工具名单制，绝不重试 |
| 401 / 429 | 立即失败并给出可读原因，不做无意义重试 |
| 服务端不接受分页参数 | `call_tool_compat` 自动降级为无参调用 |
| 单模块接口异常 | `report` 模式下降级展示，不影响其他模块 |

## 业务价值

把 34 个原子工具中与"积分生命周期"相关的 8 个编排成闭环：
**积分来了（订单/活动）→ 攒着（账户查询）→ 快过期了（临期预警）→
换什么（商城性价比）→ 抽奖值不值（期望值）→ 花去哪了（月度账单）**。
用户从"打开 App 凭感觉点"变成"一条命令拿到可执行的积分决策"。
