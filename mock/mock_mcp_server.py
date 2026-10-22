"""本地 Mock 麦当劳 MCP Server（仅用于离线测试，不联网、不发真实请求）。

用法：
    python mock/mock_mcp_server.py [端口]     # 默认 18923

支持通过 URL query 控制行为，便于测试不同分支：
    ?scenario=critical   临期积分 3 天内过期（紧急分支）
    ?scenario=empty      零积分空账户分支
    ?scenario=no-lottery 无进行中抽奖分支
    ?transport=sse       以 SSE 事件流格式返回响应（测试解析兼容性）
    ?flaky=query-my-account:2   该工具前 2 次调用返回 500（测试安全重试）
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOOLS = [
    {"name": "query-my-account", "description": "查询用户积分账户信息，包括可用积分、累计积分、冻结积分、即将过期积分等"},
    {"name": "now-time-info", "description": "返回当前的完整时间信息"},
    {"name": "mall-points-products", "description": "查询麦麦商城内可使用积分兑换或现金购买的商品"},
    {"name": "mall-product-detail", "description": "查询商城商品详细信息"},
    {"name": "query-lottery-info", "description": "查询当前积分抽奖活动的基本信息"},
    {"name": "draw-lottery", "description": "执行一次积分抽奖（写操作）"},
    {"name": "query-my-prizes", "description": "查询用户在积分抽奖活动中获得的全部奖品记录"},
    {"name": "order-list", "description": "查询近期的到店/外送历史订单"},
    {"name": "mall-order-list", "description": "查询麦麦商城内近一年购买或兑换的商品订单列表"},
]

_call_counts = {}
_lock = threading.Lock()


def _now():
    return datetime.now()


def _account_data(scenario):
    now = _now()
    if scenario == "empty":
        return {"code": 0, "data": {
            "availablePoints": 0, "accumulatedPoints": 320,
            "frozenPoints": 0, "expiringPoints": 0, "nickname": "白嫖用户",
        }}
    if scenario == "critical":
        expiring_list = [{"points": 560, "expireTime": (now + timedelta(days=2)).strftime("%Y-%m-%d 23:59:59")}]
    else:
        expiring_list = [{"points": 560, "expireTime": (now + timedelta(days=12)).strftime("%Y-%m-%d 23:59:59")}]
    return {"code": 0, "data": {
        "availablePoints": 2380, "accumulatedPoints": 15600, "frozenPoints": 200,
        "expiringPoints": 560, "expiringPointsList": expiring_list,
        "nickname": "麦门信徒",
    }}


def _products_data(page_num=1, page_size=50):
    all_products = [
        {"productCode": "P1001", "productName": "可口可乐（中）兑换券", "points": 300,
         "originalPrice": 8.0, "category": "饮品", "stock": 998},
        {"productCode": "P1002", "productName": "薯条（小）兑换券", "points": 800,
         "originalPrice": 11.5, "category": "小食", "stock": 120},
        {"productCode": "P1003", "productName": "巨无霸汉堡兑换券", "points": 2200,
         "originalPrice": 23.0, "category": "汉堡", "stock": 56},
        {"productCode": "P1004", "productName": "麦乐鸡 4 块兑换券", "points": 1200,
         "originalPrice": 12.0, "category": "小食", "stock": 0},
        {"productCode": "P1005", "productName": "程序员节限定徽章", "points": 5000,
         "category": "周边", "stock": 30},  # 无参考价
        {"productCode": "P1006", "productName": "燕麦拿铁（中）兑换券", "points": 2600,
         "originalPrice": 19.0, "category": "饮品", "stock": 12},
        {"productCode": "P1007", "productName": "早餐猪柳蛋汉堡兑换券", "points": 1500,
         "originalPrice": 13.5, "category": "早餐", "stock": 88},
    ]
    start = (max(page_num, 1) - 1) * page_size
    return {"code": 0, "data": {"products": all_products[start:start + page_size],
                                "total": len(all_products)}}


def _lottery_data(scenario):
    if scenario == "no-lottery":
        return {"code": 0, "data": {"activityName": "积分月月抽", "status": "已结束",
                                    "prizes": []}}
    return {"code": 0, "data": {
        "activityName": "1024 程序员节积分抽奖", "status": "进行中",
        "pointsCost": 50, "remainTimes": 3,
        "prizes": [
            {"prizeName": "1000 积分券", "pointsValue": 1000, "probability": 0.5, "stock": 500},
            {"prizeName": "免费巨无霸券", "pointsValue": 2300, "probability": 0.1, "stock": 20},
            {"prizeName": "谢谢参与", "pointsValue": 0, "probability": 0.4, "stock": 99999},
        ],
    }}


def _orders_data():
    now = _now()
    def dt(days_ago, hour=12):
        return (now - timedelta(days=days_ago)).replace(hour=hour, minute=30, second=0)
    orders = [
        {"orderId": "M20261018001", "orderType": "外送", "createTime": dt(4).strftime("%Y-%m-%d %H:%M:%S"),
         "totalAmount": 47.5, "storeName": "麦当劳(科技园餐厅)",
         "orderStatus": "已完成",
         "productList": [{"productName": "巨无霸套餐", "quantity": 1},
                         {"productName": "麦乐鸡 5 块", "quantity": 1}]},
        {"orderId": "M20261020002", "orderType": "到店", "createTime": dt(2, 8).strftime("%Y-%m-%d %H:%M:%S"),
         "totalAmount": 13.5, "storeName": "麦当劳(创业大厦餐厅)",
         "orderStatus": "已完成",
         "productList": [{"productName": "早餐猪柳蛋套餐", "quantity": 1}]},
        {"orderId": "M20261022003", "orderType": "外送", "createTime": dt(0, 19).strftime("%Y-%m-%d %H:%M:%S"),
         "totalAmount": 36.0, "storeName": "麦当劳(科技园餐厅)",
         "orderStatus": "配送中",
         "productList": [{"productName": "双层吉士汉堡套餐", "quantity": 2}]},
        # 上个月订单（应被月度过滤排除）
        {"orderId": "M20260915009", "orderType": "到店", "createTime": "2026-09-15 12:00:00",
         "totalAmount": 24.0, "storeName": "麦当劳(创业大厦餐厅)",
         "orderStatus": "已完成", "productList": [{"productName": "安格斯厚牛堡", "quantity": 1}]},
    ]
    return {"code": 0, "data": {"orders": orders}}


def _mall_orders_data():
    now = _now()
    return {"code": 0, "data": {"orders": [
        {"orderId": "G20261010001", "createTime": (now - timedelta(days=12)).strftime("%Y-%m-%d 10:00:00"),
         "payPoints": 300, "totalAmount": 0, "orderStatus": "已完成",
         "productList": [{"productName": "可口可乐（中）兑换券", "quantity": 1}]},
    ]}}


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静音
        pass

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _send(self, payload, status=200, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, payload):
        body = ("event: message\ndata: " +
                json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond(self, payload, headers=None):
        if "sse" in self._query().get("transport", []):
            self._send_sse(payload)
        else:
            self._send(payload, headers=headers)

    def do_POST(self):
        query = self._query()
        scenario = (query.get("scenario") or ["normal"])[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}})
            return

        method = request.get("method")
        req_id = request.get("id")

        if method == "initialize":
            self._respond({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mock-mcd-mcp", "version": "1.0.0"},
            }}, headers={"mcp-session-id": "mock-session-123"})
            return

        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "tools/list":
            self._respond({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
            return

        if method == "tools/call":
            name = (request.get("params") or {}).get("name")
            arguments = (request.get("params") or {}).get("arguments") or {}

            # flaky 支持：前 N 次返回 500
            flaky = (query.get("flaky") or [""])[0]
            if flaky:
                tool_name, _, times = flaky.partition(":")
                if tool_name == name:
                    with _lock:
                        _call_counts[name] = _call_counts.get(name, 0) + 1
                        count = _call_counts[name]
                    if count <= int(times or 1):
                        self.send_response(500)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return

            if name not in {t["name"] for t in TOOLS}:
                self._respond({"jsonrpc": "2.0", "id": req_id, "error": {
                    "code": -32601, "message": "Unknown tool: {}".format(name)}})
                return

            if name == "query-my-account":
                data = _account_data(scenario)
            elif name == "now-time-info":
                data = {"currentTime": _now().strftime("%Y-%m-%d %H:%M:%S"),
                        "timestamp": int(_now().timestamp())}
            elif name == "mall-points-products":
                data = _products_data(arguments.get("pageNum", 1), arguments.get("pageSize", 50))
            elif name == "mall-product-detail":
                data = {"code": 0, "data": {"productName": "巨无霸汉堡兑换券",
                                            "points": 2200, "description": "任意门店可用"}}
            elif name == "query-lottery-info":
                data = _lottery_data(scenario)
            elif name == "query-my-prizes":
                data = {"code": 0, "data": {"prizes": [
                    {"prizeName": "1000 积分券", "winTime": "2026-10-01 12:00:00"}]}}
            elif name == "order-list":
                data = _orders_data()
            elif name == "mall-order-list":
                data = _mall_orders_data()
            elif name == "draw-lottery":
                data = {"code": 0, "data": {"win": False, "prizeName": "谢谢参与"}}
            else:  # pragma: no cover
                data = {"code": 0, "data": {}}

            self._respond({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                "isError": False,
            }})
            return

        # 未知方法
        self._respond({"jsonrpc": "2.0", "id": req_id, "error": {
            "code": -32601, "message": "Method not found: {}".format(method)}})


def serve(port=18923):
    with _lock:
        _call_counts.clear()
    server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18923
    server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    print("Mock MCP server (threaded) listening on http://127.0.0.1:{}".format(port))
    server.serve_forever()
