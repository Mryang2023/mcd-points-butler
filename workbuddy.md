# workbuddy.md — 使用 WorkBuddy 的开发记录

本文件记录「麦麦积分管家」使用 **腾讯 WorkBuddy** 完成开发的完整过程，
用于核验大赛 WorkBuddy 专项奖励条件（排行榜前 100 名 + 提交本文件 = 3,000 积分）。

- 开发日期：2026-10-22（大赛报名期最后 3 天）
- 开发环境：Windows 11 / Python 3.13.12（兼容 3.9+）/ 无 Docker、无第三方 Python 包
- 开发方式：全程在 WorkBuddy 对话中完成——需求分析、竞品调研、架构设计、
  编码、测试、文档，均由 WorkBuddy 协作产出；作者负责决策与验收。

## 开发过程（按时间线）

### 阶段 0 · 选题决策（2026-10-22 上午）

作者决定参加麦当劳程序员创意开发大赛后，WorkBuddy 先从公开渠道核实了
赛制（报名截止 10-25 23:59、按 GitHub Star 排名、官方仓库
M-China/mcd-developer-innovation-challenge），并给出竞争格局分析：

- 红海：省钱/优惠券组合（前三名 611/512/491 stars 全集中在此）、
  卡路里/营养估算（一大批同质作品）；
- 蓝海打法：把 MCP 原子能力编排成"每天愿意用"的闭环，而非单点调接口
  （参考全场唯一的碳账本作品）。

在 WorkBuddy 给出的三个候选方向（拼单助手 / 积分管家 / 麦门盲盒）中，
作者选定**麦麦积分管家**：开发最稳、能力现成、临期预警是真实痛点。

### 阶段 1 · 接口调研

WorkBuddy 拉取官方两个仓库，摸清关键事实：

- MCP 接入：`https://mcp.mcd.cn`，Streamable HTTP，`Authorization: Bearer <token>`，
  限流 600 次/分钟；
- 34 个工具中与积分相关的 8 个只读工具：`query-my-account`、
  `now-time-info`、`mall-points-products`、`mall-product-detail`、
  `query-lottery-info`、`query-my-prizes`、`order-list`、`mall-order-list`；
- 仓库必备文件：README.md / CONTEST_DECLARATION.md（原文不可改）/
  MCP_INTEGRATION.md / 源代码 / workbuddy.md。

### 阶段 2 · 架构与编码

作者定下的产品原则：**零第三方依赖、Python 3.9+、一行命令、全程只读**。
WorkBuddy 据此产出全部代码（`mcd_butler/` 包 + `mcd-butler.py` 入口）：

1. `mcp_client.py`：标准库实现的 MCP Streamable HTTP 客户端。
   关键设计——**只读工具有限重试，写操作绝不重试**（防止重复抽奖/重复扣分）；
   401/429 快速失败；兼容 JSON 与 SSE 两种响应；
2. `points.py`：积分总览 + 临期紧迫度分级（以服务端时间 `now-time-info`
   为基准做倒计时）；
3. `redeem.py`：可兑商品按「每积分价值 = 参考价 / 所需积分」排序，
   附"再攒一点就能兑"清单；
4. `lottery.py`：期望价值 EV = Σ(概率 × 价值)，与单次消耗对比给出
   抽/不抽结论；概率未公开时明确拒绝瞎猜；
5. `bill.py`：月度账单（订单统计/按日分布/最大单/麦门浓度）；
6. `util.py`：防御性字段解析（多别名 + 递归兜底，应对字段名未公开）+ 中文对齐表格。

### 阶段 3 · 测试与调试（同日晚）

WorkBuddy 编写了本地 mock MCP server（`mock/mock_mcp_server.py`，支持
critical/empty/no-lottery 场景、SSE 模式、flaky 故障注入）和 21 个测试。
调试中实际抓到并修复的问题：

1. **响应信封未脱壳**：接口返回 `{"code":0,"data":{...}}`，解析器直接找
   顶层字段导致订单/商品全部解析为空 → 增加 `util.unwrap` 统一脱壳；
2. **零值被误杀**：`value or None` 把"谢谢参与（0 分）"变成 None，
   导致期望值算不出来 → 区分"字段缺失"与"值为 0"；
3. **裸 OSError 逃逸**：Windows 下连接重置（WinError 10054）不被 urllib
   包装成 URLError，会把堆栈崩给用户 → `_post` 增加 OSError 兜底转可读错误；
4. **单线程 mock server 偶发挂起** → 改 ThreadingHTTPServer；
5. **参数兼容**：真实服务端可能不接受 `pageNum/pageSize` →
   `call_tool_compat` 失败自动降级无参重试。

最终 21/21 测试通过（连跑 5 次全绿），并用 mock server 跑通了
`report` 全链路真实输出（样例见 README）。

### 阶段 4 · 文档与参赛准备

README.md、MCP_INTEGRATION.md、SKILL.md、CONTEST_DECLARATION.md（官方原文）、
本文件，均由 WorkBuddy 按大赛文件要求生成，作者审校。

## 结论

本项目从选题、调研、编码、测试到文档，全程在 WorkBuddy 中协作完成，
符合大赛"使用 WorkBuddy 开发"的联动奖励条件。开发过程遵守官方
《信息安全声明》：未在任何文件、输出、日志中写入真实 MCP Token，
Token 仅通过环境变量 `MCD_MCP_TOKEN` 注入。
