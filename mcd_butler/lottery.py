"""积分抽奖参谋。

调用 MCP 工具：
- query-lottery-info  抽奖活动信息（活动状态、奖品列表、消耗规则、用户可用资源）
- query-my-prizes     我的奖品记录（可选，展示历史战绩）

分析逻辑：
1. 解析每次抽奖的积分消耗与可用次数；
2. 奖品若能估算积分价值（如积分券/券码），计算期望价值 = Σ(概率 × 价值)；
3. 期望价值 > 消耗 → 「值得抽」；持平或低于 → 「谨慎」；
4. 概率未公开时只做展示，明确告知无法计算期望值，不瞎给建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .mcp_client import MCPClient, MCPError
from .util import as_list, fmt_int, render_table, search_value, to_float, to_int, unwrap

PRIZE_NAME = ["prizeName", "name", "title", "prize", "rewardName"]
PRIZE_VALUE = ["pointsValue", "value", "prizeValue", "worth", "amount"]
PRIZE_PROB = ["probability", "prob", "rate", "chance", "winRate", "odds"]
PRIZE_STOCK = ["stock", "remain", "quantity", "inventory"]

STATUS_KEYS = ["status", "activityStatus", "state", "lotteryStatus"]
COST_KEYS = ["pointsCost", "cost", "consumePoints", "points", "perDrawCost",
             "drawCost", "singleCost"]
TIMES_KEYS = ["remainTimes", "remainingTimes", "drawTimes", "times",
              "availableTimes", "leftTimes", "userTimes"]
ACTIVITY_NAME = ["activityName", "name", "title", "lotteryName"]
PRIZES_KEYS = ["prizes", "prizeList", "rewards", "awards", "giftList"]


@dataclass
class Prize:
    name: str = "未知奖品"
    value: Optional[float] = None      # 可估算的积分/金额价值
    probability: Optional[float] = None  # 0~1
    stock: Optional[int] = None


@dataclass
class LotteryInfo:
    active: bool = False
    name: str = ""
    cost: int = 0                       # 单次消耗积分
    remain_times: Optional[int] = None  # 剩余可抽次数
    prizes: List[Prize] = field(default_factory=list)


STATUS_ACTIVE_WORDS = ("进行中", "active", "ongoing", "running", "open", "started", "有效")


def _is_active(raw_status) -> bool:
    if raw_status is None:
        return False
    if isinstance(raw_status, bool):
        return raw_status
    if isinstance(raw_status, (int, float)):
        return int(raw_status) == 1
    text = str(raw_status).lower()
    return any(word in text for word in STATUS_ACTIVE_WORDS)


def fetch_lottery(client: MCPClient) -> LotteryInfo:
    result = client.call_tool("query-lottery-info")
    client.check_error(result)
    raw = client.result_json(result)
    if raw is None:
        raise MCPError("query-lottery-info 返回无法解析的内容。")
    data = unwrap(raw)

    info = LotteryInfo(
        active=_is_active(search_value(data, STATUS_KEYS)),
        name=str(search_value(data, ACTIVITY_NAME) or "积分抽奖"),
        cost=to_int(search_value(data, COST_KEYS)),
    )
    times = search_value(data, TIMES_KEYS)
    if times is not None:
        info.remain_times = to_int(times, -1)

    prizes_raw = []
    for key in PRIZES_KEYS:
        prizes_raw = as_list(data.get(key)) if isinstance(data, dict) else []
        if prizes_raw:
            break
    if not prizes_raw:
        prizes_raw = as_list(search_value(data, PRIZES_KEYS))
    for item in prizes_raw:
        raw_prob = search_value(item, PRIZE_PROB)
        raw_value = search_value(item, PRIZE_VALUE)
        if raw_prob is None:
            probability = None
        else:
            prob = to_float(raw_prob, 0.0)
            probability = prob / 100.0 if prob > 1.0 else prob
        info.prizes.append(Prize(
            name=str(search_value(item, PRIZE_NAME) or "未知奖品"),
            value=to_float(raw_value) if raw_value is not None else None,
            probability=probability,
            stock=to_int(search_value(item, PRIZE_STOCK), -1) or None,
        ))
    return info


def expected_value(info: LotteryInfo) -> Optional[float]:
    """奖品概率与价值齐全时计算期望积分价值，否则返回 None。"""
    if not info.prizes:
        return None
    total_prob = 0.0
    ev = 0.0
    for p in info.prizes:
        if p.probability is None or p.value is None:
            return None
        total_prob += p.probability
        ev += p.probability * p.value
    if total_prob <= 0:
        return None
    return ev


def render_lottery(info: LotteryInfo) -> str:
    lines = []
    if not info.active:
        lines.append("当前没有进行中的积分抽奖活动，留意 App 内活动。")
        return "\n".join(lines)

    lines.append("抽奖活动：{}".format(info.name))
    rows = []
    for p in info.prizes:
        prob = "{:.2f}%".format(p.probability * 100) if p.probability is not None else "未公布"
        value = fmt_int(p.value) if p.value is not None else "-"
        stock = fmt_int(p.stock) if p.stock is not None else "-"
        rows.append([p.name, value, prob, stock])
    if rows:
        lines.append(render_table(
            ["奖品", "参考价值(分)", "中奖概率", "库存"],
            rows, aligns=["l", "r", "r", "r"],
        ))
    lines.append("")
    lines.append("单次消耗：{} 积分".format(fmt_int(info.cost)) +
                 ("，剩余次数：{}".format(fmt_int(info.remain_times))
                  if info.remain_times is not None else ""))

    ev = expected_value(info)
    if ev is not None and info.cost > 0:
        if ev > info.cost:
            verdict = "期望价值 {} 分 > 单次消耗 {} 分，数学上划得来，可以抽。".format(
                fmt_int(ev), fmt_int(info.cost))
        elif ev == info.cost:
            verdict = "期望价值与消耗持平，纯看运气，闲抽即可。"
        else:
            verdict = "期望价值 {} 分 < 单次消耗 {} 分，长期抽大概率亏分，建议留积分兑换实物。".format(
                fmt_int(ev), fmt_int(info.cost))
        lines.append("参谋结论：{}".format(verdict))
    else:
        lines.append("参谋结论：奖品概率或价值未公开，无法计算期望值；积分有限时优先兑换确定性商品。")
    return "\n".join(lines)
