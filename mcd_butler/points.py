"""积分总览与临期预警。

调用 MCP 工具：
- query-my-account  我的积分查询（可用/累计/冻结/即将过期积分）
- now-time-info     获取服务端当前时间（用于临期倒计时，避免本地时钟偏差）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .mcp_client import MCPClient, MCPError
from .util import as_list, fmt_int, parse_dt, render_table, search_value, to_int

#: query-my-account 字段别名（真实字段名未公开，按多别名兜底）
ALIASES = {
    "available": ["availablePoints", "available_points", "available", "currentPoints",
                  "usablePoints", "canUsePoints", "points", "balance", "point"],
    "accumulated": ["accumulatedPoints", "accumulated_points", "accumulated",
                    "totalPoints", "totalEarnedPoints", "cumulativePoints", "sumPoints"],
    "frozen": ["frozenPoints", "frozen_points", "frozen", "freezePoints",
               "freezingPoints", "lockedPoints"],
    "expiring": ["expiringPoints", "expiring_points", "expiring", "willExpirePoints",
                 "nearExpirePoints", "expirePoints", "toExpirePoints",
                 "expiringSoonPoints", "overduePoints"],
    "expiring_list": ["expiringPointsList", "expiringList", "expireList",
                      "willExpireList", "expireDetailList", "expiringPointsDetail"],
    "nickname": ["nickname", "userName", "name", "mobile", "phone"],
}

#: 临期单项字段别名
ITEM_POINTS = ["points", "expiringPoints", "point", "amount", "num", "count"]
ITEM_EXPIRE = ["expireTime", "expirationTime", "expiredTime", "invalidTime",
               "expireDate", "endTime", "deadline", "expiryTime"]


@dataclass
class PointsSnapshot:
    """一次积分账户快照。"""

    available: int = 0
    accumulated: int = 0
    frozen: int = 0
    expiring: int = 0
    expiring_date: Optional[str] = None       # 最近一笔临期积分的过期时间（原始字符串）
    nickname: Optional[str] = None
    server_now: Optional[datetime] = None
    raw: dict = field(default_factory=dict)

    @property
    def expiring_dt(self) -> Optional[datetime]:
        return parse_dt(self.expiring_date)

    def urgency(self) -> str:
        """临期紧迫度：无 / 关注 / 临近 / 紧急 / 未知时间尽快处理。"""
        if self.expiring <= 0:
            return "none"
        dt = self.expiring_dt
        if dt is None:
            return "unknown"
        now = self.server_now or datetime.now()
        days = (dt - now).days
        if days < 0:
            return "expired"
        if days <= 3:
            return "critical"
        if days <= 7:
            return "soon"
        return "watch"


URGENCY_LABEL = {
    "none": "无临期积分，安心",
    "watch": "有临期积分，持续关注",
    "soon": "积分临近过期，建议本周内兑换",
    "critical": "积分告急，建议立即兑换",
    "unknown": "有临期积分但未拿到过期时间，建议尽快兑换",
    "expired": "临期积分可能已过期，请到 App 确认",
}


def fetch_server_now(client: MCPClient) -> Optional[datetime]:
    """拉取服务端当前时间；失败时返回 None（调用方回退本地时间）。"""
    try:
        result = client.call_tool("now-time-info")
        data = client.result_json(result) or {}
        raw = (search_value(data, ["currentTime", "now", "time", "dateTime", "serverTime"])
               or client.result_text(result))
        return parse_dt(raw)
    except MCPError:
        return None


def fetch_points(client: MCPClient, with_server_now: bool = True) -> PointsSnapshot:
    """拉取积分账户快照。"""
    result = client.call_tool("query-my-account")
    client.check_error(result)
    data = client.result_json(result)
    if data is None:
        # 极端情况：返回的不是 JSON，只能给出原始文本提示
        raise MCPError("query-my-account 返回了无法解析的内容：" + client.result_text(result)[:200])

    snap = PointsSnapshot(
        available=to_int(search_value(data, ALIASES["available"])),
        accumulated=to_int(search_value(data, ALIASES["accumulated"])),
        frozen=to_int(search_value(data, ALIASES["frozen"])),
        expiring=to_int(search_value(data, ALIASES["expiring"])),
        nickname=search_value(data, ALIASES["nickname"]),
        raw=data,
    )

    # 临期明细：取最近一笔过期时间做倒计时
    items = as_list(search_value(data, ALIASES["expiring_list"]))
    nearest = None
    for item in items:
        dt = parse_dt(search_value(item, ITEM_EXPIRE))
        if dt and (nearest is None or dt < nearest):
            nearest = dt
            snap.expiring_date = search_value(item, ITEM_EXPIRE)
    if snap.expiring > 0 and snap.expiring_date is None:
        # 没有明细时，也可能有聚合层面的最近过期时间字段
        snap.expiring_date = search_value(
            data, ["nearestExpireTime", "expireTime", "expiringTime", "firstExpireTime"]
        )

    if with_server_now:
        snap.server_now = fetch_server_now(client)
    return snap


def render_status(snap: PointsSnapshot) -> str:
    """渲染积分总览 + 临期预警文本。"""
    lines = []
    who = "（{}）".format(snap.nickname) if snap.nickname else ""
    lines.append("麦麦积分总览 {}".format(who))
    lines.append(render_table(
        ["项目", "数值"],
        [
            ["可用积分", fmt_int(snap.available)],
            ["累计积分", fmt_int(snap.accumulated)],
            ["冻结积分", fmt_int(snap.frozen)],
            ["即将过期", fmt_int(snap.expiring)],
        ],
        aligns=["l", "r"],
    ))

    level = snap.urgency()
    lines.append("")
    lines.append("临期预警：{}".format(URGENCY_LABEL[level]))
    dt = snap.expiring_dt
    if snap.expiring > 0 and dt:
        now = snap.server_now or datetime.now()
        days = (dt - now).days
        lines.append("最近一笔 {} 积分将于 {} 过期（约 {} 天）。".format(
            fmt_int(snap.expiring), snap.expiring_date, max(days, 0)))
    if snap.frozen > 0:
        lines.append("提示：有 {} 积分处于冻结状态，暂不可用。".format(fmt_int(snap.frozen)))
    if snap.available > 0:
        lines.append("下一步：运行 redeem 查看可用积分能换什么，lottery 看看抽奖值不值。")
    return "\n".join(lines)
