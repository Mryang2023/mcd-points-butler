"""一键报告：积分总览 + 兑换建议 + 抽奖参谋 + 月度账单。"""

from __future__ import annotations

from .bill import fetch_orders, filter_month, render_bill
from .lottery import fetch_lottery, render_lottery
from .mcp_client import MCPClient, MCPError
from .points import fetch_points, render_status
from .redeem import fetch_products, render_redeem


def run_report(client: MCPClient, month: str = None) -> str:
    """依次拉取各模块数据并渲染完整报告；单模块失败不阻断整体。"""
    sections = []

    snap = None
    try:
        snap = fetch_points(client, with_server_now=True)
        sections.append(render_status(snap))
    except MCPError as exc:
        sections.append("[积分总览获取失败] {}".format(exc))

    if snap is not None:
        try:
            products = fetch_products(client)
            sections.append("")
            sections.append(render_redeem(snap, products))
        except MCPError as exc:
            sections.append("")
            sections.append("[兑换建议获取失败] {}".format(exc))

    try:
        sections.append("")
        sections.append(render_lottery(fetch_lottery(client)))
    except MCPError as exc:
        sections.append("")
        sections.append("[抽奖信息获取失败] {}".format(exc))

    try:
        orders = filter_month(fetch_orders(client), month)
        sections.append("")
        sections.append(render_bill(orders, month))
    except MCPError as exc:
        sections.append("")
        sections.append("[账单获取失败] {}".format(exc))

    return "\n".join(sections)
