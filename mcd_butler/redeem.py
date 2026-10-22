"""积分兑换建议。

调用 MCP 工具：
- mall-points-products  麦麦商城商品列表（积分兑换或现金购买）
- mall-product-detail   商品详情（需要时按编码补齐）

分析逻辑：
1. 过滤出「积分可兑」且「可用积分够用」的商品；
2. 有原价/市场价的商品计算「每积分兑换价值」，按性价比降序；
3. 额外列出「差一点够兑」的商品（积分缺口 < 50%），给用户攒分目标；
4. 有临期积分时优先推荐低价快消品，避免过期作废。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .mcp_client import MCPClient, MCPError
from .points import PointsSnapshot
from .util import as_list, fmt_int, fmt_money, render_table, search_value, to_float, to_int, unwrap

PRODUCT_NAME = ["productName", "name", "title", "goodsName", "skuName"]
PRODUCT_POINTS = ["points", "pointsPrice", "exchangePoints", "needPoints",
                  "integral", "score", "pointsCost"]
PRODUCT_PRICE = ["originalPrice", "marketPrice", "price", "referencePrice",
                 "linePrice", "sellingPrice", "cashPrice"]
PRODUCT_CATEGORY = ["category", "categoryName", "type", "typeName", "goodsType"]
PRODUCT_CODE = ["productCode", "productId", "code", "id", "skuId", "goodsId"]
PRODUCT_STOCK = ["stock", "stockNum", "quantity", "inventory", "remain"]
PRODUCT_LIST_KEYS = ["products", "productList", "list", "items", "records",
                     "data", "mallProducts", "goodsList"]


@dataclass
class Product:
    name: str = "未知商品"
    points: int = 0
    price: Optional[float] = None      # 原价/参考价（若有）
    category: str = ""
    code: str = ""
    in_stock: Optional[bool] = None

    @property
    def value_ratio(self) -> Optional[float]:
        """每积分兑换价值（元/分）。无参考价时无法估算。"""
        if self.price and self.points > 0:
            return self.price / self.points
        return None


def fetch_products(client: MCPClient, page_size: int = 50) -> List[Product]:
    """拉取积分商城商品列表（按页遍历，直到拿不到新数据或达到安全上限）。"""
    products: List[Product] = []
    seen_codes = set()
    for page in range(1, 6):  # 最多 5 页，防止异常分页导致无限循环
        result = client.call_tool_compat("mall-points-products", {
            "pageNum": page, "pageSize": page_size,
        })
        client.check_error(result)
        raw = client.result_json(result)
        if raw is None:
            raise MCPError("mall-points-products 返回无法解析的内容。")
        data = unwrap(raw)
        items = []
        for key in PRODUCT_LIST_KEYS:
            items = as_list(data.get(key)) if isinstance(data, dict) else []
            if items:
                break
        if not items:
            items = data if isinstance(data, list) else []
        if not items:
            break
        new_count = 0
        for item in items:
            code = str(search_value(item, PRODUCT_CODE) or item.get("name") or "")
            if code in seen_codes:
                continue
            seen_codes.add(code)
            new_count += 1
            stock_raw = search_value(item, PRODUCT_STOCK)
            products.append(Product(
                name=str(search_value(item, PRODUCT_NAME) or "未知商品"),
                points=to_int(search_value(item, PRODUCT_POINTS)),
                price=to_float(search_value(item, PRODUCT_PRICE), 0.0) or None,
                category=str(search_value(item, PRODUCT_CATEGORY) or ""),
                code=code,
                in_stock=(to_int(stock_raw, 1) > 0) if stock_raw is not None else None,
            ))
        if new_count == 0:
            break  # 没有新商品，停止翻页
    return products


def render_redeem(snap: PointsSnapshot, products: List[Product], top: int = 8) -> str:
    """渲染兑换建议。"""
    lines = []
    affordable = [p for p in products if p.points > 0 and p.points <= snap.available]

    lines.append("可兑商品 TOP {}（可用积分 {}）".format(top, fmt_int(snap.available)))
    if not products:
        lines.append("积分商城暂无可兑换商品（或接口未返回商品数据）。")
    elif not affordable:
        lines.append("当前积分不足以兑换商城商品，先攒分；也可运行 lottery 看抽奖机会。")
    else:
        # 有参考价的按性价比排，没有的按积分升序（快消优先）
        ranked = sorted(
            affordable,
            key=lambda p: (p.value_ratio is None, -(p.value_ratio or 0), p.points),
        )
        rows = []
        for p in ranked[:top]:
            ratio = "{:.4f} 元/分".format(p.value_ratio) if p.value_ratio else "参考价未知"
            stock = "" if p.in_stock is None else ("有货" if p.in_stock else "缺货")
            rows.append([p.name, fmt_int(p.points),
                         fmt_money(p.price) if p.price else "-", ratio, stock])
        lines.append(render_table(
            ["商品", "所需积分", "参考价", "每积分价值", "库存"],
            rows, aligns=["l", "r", "r", "r", "c"],
        ))

    # 临期策略
    if snap.urgency() in ("critical", "soon", "unknown"):
        lines.append("")
        lines.append("临期提醒：你有 {} 积分即将过期，建议优先兑换低价快消品".format(
            fmt_int(snap.expiring)))
        lines.append("（小食/饮料类），避开高积分长保质期商品，别让积分烂在账户里。")

    # 差一点够兑
    near = [p for p in products
            if p.points > snap.available and p.points <= snap.available * 1.5]
    if near:
        near.sort(key=lambda p: p.points)
        lines.append("")
        lines.append("再攒一点就能兑：")
        for p in near[:5]:
            lines.append("  - {}（还差 {} 分）".format(p.name, fmt_int(p.points - snap.available)))
    return "\n".join(lines)
