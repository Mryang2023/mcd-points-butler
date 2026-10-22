"""月度麦麦账单。

调用 MCP 工具：
- order-list        历史订单（近期的到店/外送订单）
- mall-order-list   麦麦商城订单（近一年购买/兑换记录）

统计维度：
- 本月订单数与总消费（按服务端订单时间过滤，默认当月，可用 --month 指定）；
- 按日分布，找出「麦门消费高峰日」；
- 商城订单单独汇总积分消耗，回答「这个月积分花哪去了」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .mcp_client import MCPClient, MCPError
from .util import as_list, fmt_int, fmt_money, parse_dt, render_table, search_value, to_float, to_int, unwrap

ORDER_LIST_KEYS = ["orders", "orderList", "list", "items", "records", "data"]
ORDER_ID = ["orderId", "orderNo", "id", "orderCode"]
ORDER_TIME = ["createTime", "orderTime", "createDate", "orderDate", "payTime", "submitTime"]
ORDER_AMOUNT = ["totalAmount", "finalAmount", "payAmount", "amount", "totalFee",
                "paymentAmount", "orderAmount", "actualAmount"]
ORDER_STORE = ["storeName", "shopName", "store", "restaurantName"]
ORDER_TYPE = ["orderType", "businessType", "type", "scene", "channel"]
ORDER_ITEMS = ["productList", "items", "orderItems", "details", "goodsList", "meals"]
ITEM_NAME = ["productName", "name", "title", "goodsName", "mealName"]
ITEM_QTY = ["quantity", "qty", "count", "num"]
ORDER_POINTS = ["payPoints", "pointsAmount", "deductPoints", "usePoints", "points"]
ORDER_STATUS = ["orderStatus", "status", "state"]


@dataclass
class Order:
    order_id: str = ""
    dt: Optional[datetime] = None
    amount: float = 0.0
    store: str = ""
    otype: str = ""
    points: int = 0
    status: str = ""
    items: List[str] = field(default_factory=list)


def _parse_orders(data, default_type="") -> List[Order]:
    orders = []
    data = unwrap(data)
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ORDER_LIST_KEYS:
            items = as_list(data.get(key))
            if items:
                break
    for item in items:
        if not isinstance(item, dict):
            continue
        names = []
        for sub in as_list(search_value(item, ORDER_ITEMS)):
            name = search_value(sub, ITEM_NAME)
            if name:
                qty = to_int(search_value(sub, ITEM_QTY), 1)
                names.append("{}x{}".format(name, qty) if qty > 1 else str(name))
        orders.append(Order(
            order_id=str(search_value(item, ORDER_ID) or ""),
            dt=parse_dt(search_value(item, ORDER_TIME)),
            amount=to_float(search_value(item, ORDER_AMOUNT)),
            store=str(search_value(item, ORDER_STORE) or ""),
            otype=str(search_value(item, ORDER_TYPE) or default_type),
            points=to_int(search_value(item, ORDER_POINTS)),
            status=str(search_value(item, ORDER_STATUS) or ""),
            items=names,
        ))
    return orders


def fetch_orders(client: MCPClient) -> List[Order]:
    """拉取餐饮订单 + 商城订单，合并返回（商城订单 otype 标注）。"""
    all_orders: List[Order] = []
    result = client.call_tool_compat("order-list", {"pageNum": 1, "pageSize": 20})
    client.check_error(result)
    all_orders.extend(_parse_orders(client.result_json(result) or {}, "餐饮"))
    try:
        result = client.call_tool_compat("mall-order-list", {"pageNum": 1, "pageSize": 20})
        client.check_error(result)
        mall_orders = _parse_orders(client.result_json(result) or {}, "商城")
        all_orders.extend(mall_orders)
    except MCPError:
        # 商城订单接口异常不影响餐饮账单
        pass
    return all_orders


def filter_month(orders: List[Order], month: Optional[str] = None) -> List[Order]:
    """按月过滤；month 形如 2026-10，缺省取当前月。无时间的订单不纳入统计。"""
    key = month or datetime.now().strftime("%Y-%m")
    out = []
    for o in orders:
        if o.dt and o.dt.strftime("%Y-%m") == key:
            out.append(o)
    return out


def render_bill(orders: List[Order], month: Optional[str] = None) -> str:
    key = month or datetime.now().strftime("%Y-%m")
    lines = ["{} 月度麦麦账单".format(key)]
    if not orders:
        lines.append("本月暂无订单记录。")
        return "\n".join(lines)

    total = sum(o.amount for o in orders)
    food_orders = [o for o in orders if o.otype != "商城"]
    mall_orders = [o for o in orders if o.otype == "商城"]
    lines.append(render_table(
        ["指标", "数值"],
        [
            ["订单总数", "{} 单".format(len(orders))],
            ["餐饮订单", "{} 单".format(len(food_orders))],
            ["餐饮消费", fmt_money(sum(o.amount for o in food_orders))],
            ["商城订单", "{} 单".format(len(mall_orders))],
            ["商城积分消耗", "{} 分".format(fmt_int(sum(o.points for o in mall_orders)))],
            ["合计支出", fmt_money(total)],
        ],
        aligns=["l", "r"],
    ))

    # 按日分布
    by_day = {}
    for o in orders:
        day = o.dt.strftime("%m-%d")
        agg = by_day.setdefault(day, {"count": 0, "amount": 0.0})
        agg["count"] += 1
        agg["amount"] += o.amount
    lines.append("")
    lines.append("按日分布：")
    rows = [[day, "{} 单".format(v["count"]), fmt_money(v["amount"])]
            for day, v in sorted(by_day.items())]
    lines.append(render_table(["日期", "订单", "金额"], rows, aligns=["l", "r", "r"]))

    # 最大单
    biggest = max(orders, key=lambda o: o.amount)
    if biggest.amount > 0:
        detail = "、".join(biggest.items[:3]) or biggest.store or "订单"
        lines.append("")
        lines.append("本月最大单：{}（{}，{}）".format(
            fmt_money(biggest.amount), biggest.dt.strftime("%m-%d %H:%M"), detail))

    # 麦门浓度
    active_days = len(by_day)
    lines.append("麦门浓度：本月 {} 天有消费，日均 {} 单。".format(
        active_days, "{:.1f}".format(len(orders) / max(active_days, 1))))
    return "\n".join(lines)
