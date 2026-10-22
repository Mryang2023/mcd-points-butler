"""麦麦积分管家测试套件（零第三方依赖，python -m unittest 直接跑）。

覆盖：
- util 别名提取 / 脏数据转换 / 日期解析 / 表格渲染
- MCP 客户端：JSON 与 SSE 两种响应、session 头、安全重试、写操作不重试、401/429
- points/redeem/lottery/bill 各业务分支（基于本地 mock server）
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd_butler import util  # noqa: E402
from mcd_butler.mcp_client import MCPClient, MCPError  # noqa: E402
from mcd_butler.bill import fetch_orders, filter_month, render_bill  # noqa: E402
from mcd_butler.lottery import expected_value, fetch_lottery, render_lottery  # noqa: E402
from mcd_butler.points import fetch_points, render_status  # noqa: E402
from mcd_butler.redeem import fetch_products, render_redeem  # noqa: E402
from mcd_butler.report import run_report  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mock import mock_mcp_server  # noqa: E402


class UtilTest(unittest.TestCase):
    def test_pick_exact_and_normalized(self):
        d = {"availablePoints": 100, "some-key": "v", "Nested": {"totalPoints": 9}}
        self.assertEqual(util.pick(d, ["availablePoints"]), 100)
        self.assertEqual(util.pick(d, ["available_points"]), 100)  # 归一化命中
        self.assertEqual(util.pick(d, ["missing"], default=7), 7)

    def test_search_value_recursive(self):
        d = {"data": {"list": [{"a": 1}, {"b": {"expireTime": "2026-10-30 12:00:00"}}]}}
        self.assertEqual(util.search_value(d, ["expireTime"]), "2026-10-30 12:00:00")

    def test_to_int_dirty(self):
        self.assertEqual(util.to_int("1,234"), 1234)
        self.assertEqual(util.to_int("560积分"), 560)
        self.assertEqual(util.to_int(12.9), 12)
        self.assertEqual(util.to_int(None, default=-1), -1)
        self.assertEqual(util.to_int("abc", default=5), 5)
        self.assertEqual(util.to_int(True, default=9), 9)  # bool 不当作数字

    def test_parse_dt_formats(self):
        self.assertEqual(util.parse_dt("2026-10-25 23:59:59"),
                         datetime(2026, 10, 25, 23, 59, 59))
        self.assertEqual(util.parse_dt("2026-10-25T08:30:00"),
                         datetime(2026, 10, 25, 8, 30))
        self.assertEqual(util.parse_dt("2026/10/25"), datetime(2026, 10, 25))
        self.assertEqual(util.parse_dt(1761000000).year, 2025)  # 秒级时间戳
        self.assertEqual(util.parse_dt(1761000000000).year, 2025)  # 毫秒级
        self.assertIsNone(util.parse_dt("not-a-date"))
        self.assertIsNone(util.parse_dt(None))

    def test_render_table_aligns(self):
        table = util.render_table(["商品", "积分"], [["可乐", "300"], ["巨无霸汉堡兑换券", "2200"]],
                                  aligns=["l", "r"])
        lines = table.splitlines()
        self.assertEqual(len(lines), 4)
        # 每行显示宽度一致（中文按 2 字符宽计）
        widths = {sum(2 if ord(ch) > 127 else 1 for ch in line) for line in lines}
        self.assertEqual(len(widths), 1, "表格各行显示宽度应一致：{}".format(lines))
        # 右列数字右对齐：数据行以数字结尾
        self.assertTrue(lines[2].rstrip().endswith("300"))


class ClientTransportTest(unittest.TestCase):
    """客户端传输层行为：用桩替换 _post，不依赖网络。"""

    def _client(self):
        return MCPClient(token="mock-token", url="http://127.0.0.1:1/unused")

    def test_safe_retries_then_succeeds(self):
        client = self._client()
        calls = {"n": 0}

        def fake_post(payload):
            calls["n"] += 1
            if calls["n"] < 3:
                raise MCPError("MCP 服务返回 HTTP 500：boom")
            import json
            return json.dumps({"jsonrpc": "2.0", "id": payload["id"],
                               "result": {"content": [{"type": "text", "text": "ok"}]}})

        client._post = fake_post
        result = client._rpc("tools/call", {"name": "query-my-account"}, safe=True)
        self.assertEqual(client.result_text(result), "ok")
        self.assertEqual(calls["n"], 3)

    def test_unsafe_never_retries(self):
        client = self._client()
        calls = {"n": 0}

        def fake_post(payload):
            calls["n"] += 1
            raise MCPError("MCP 服务返回 HTTP 500：boom")

        client._post = fake_post
        with self.assertRaises(MCPError):
            client._rpc("tools/call", {"name": "draw-lottery"}, safe=False)
        self.assertEqual(calls["n"], 1)  # 写操作绝不重试

    def test_401_raises_immediately(self):
        client = self._client()
        calls = {"n": 0}

        def fake_post(payload):
            calls["n"] += 1
            raise MCPError("MCP Token 无效或已过期（HTTP 401）")

        client._post = fake_post
        with self.assertRaises(MCPError):
            client._rpc("tools/call", {"name": "query-my-account"}, safe=True)
        self.assertEqual(calls["n"], 1)

    def test_sse_and_json_parse(self):
        import json
        payload = {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}
        sse = "event: message\ndata: " + json.dumps(payload) + "\n\n"
        messages = MCPClient._parse_messages(sse)
        self.assertEqual(messages[0]["id"], 7)
        messages = MCPClient._parse_messages(json.dumps(payload))
        self.assertEqual(messages[0]["id"], 7)
        self.assertEqual(MCPClient._parse_messages(""), [])

    def test_missing_token(self):
        with self.assertRaises(MCPError):
            MCPClient(token=None)


class MockServerTest(unittest.TestCase):
    """端到端：客户端 ↔ 本地 mock server。"""

    @classmethod
    def setUpClass(cls):
        cls.server = mock_mcp_server.serve(port=18924)
        cls.base = "http://127.0.0.1:18924"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _client(self, scenario="normal", transport=None, flaky=None):
        url = self.base + "/?scenario=" + scenario
        if transport:
            url += "&transport=" + transport
        if flaky:
            url += "&flaky=" + flaky
        return MCPClient(token="mock-token", url=url)

    def test_full_flow_json(self):
        client = self._client()
        snap = fetch_points(client)
        self.assertEqual(snap.available, 2380)
        self.assertEqual(snap.expiring, 560)
        self.assertEqual(snap.frozen, 200)
        self.assertIsNotNone(snap.expiring_dt)
        text = render_status(snap)
        self.assertIn("可用积分", text)
        self.assertIn("2,380", text)

    def test_full_flow_sse(self):
        client = self._client(transport="sse")
        snap = fetch_points(client)
        self.assertEqual(snap.available, 2380)

    def test_urgency_branches(self):
        # critical：2 天后过期
        snap = fetch_points(self._client(scenario="critical"))
        self.assertEqual(snap.urgency(), "critical")
        # empty：零积分空账户
        snap = fetch_points(self._client(scenario="empty"))
        self.assertEqual(snap.urgency(), "none")
        self.assertEqual(snap.available, 0)
        self.assertIn("安心", render_status(snap))

    def test_safe_retry_against_mock(self):
        client = self._client(flaky="query-my-account:2")
        snap = fetch_points(client)  # 前两次 500，第三次成功
        self.assertEqual(snap.available, 2380)

    def test_unknown_tool_error(self):
        client = self._client()
        with self.assertRaises(MCPError):
            client.call_tool("no-such-tool")

    def test_redeem_ranking(self):
        client = self._client()
        snap = fetch_points(client)
        products = fetch_products(client)
        names = [p.name for p in products]
        self.assertEqual(len(products), 7)  # 全部解析出来（脱信封后）
        self.assertIn("巨无霸汉堡兑换券", names)
        self.assertIn("程序员节限定徽章", names)  # 无参考价商品不丢
        text = render_redeem(snap, products)
        # 可兑商品：300/800/1200/1500（2200/2600/5000 超预算）
        self.assertIn("薯条（小）兑换券", text)
        # 性价比第一：可乐 8.0/300 ≈ 0.0267 元/分，排在数据行首位
        first_row = [l for l in text.splitlines() if "可口可乐" in l]
        self.assertTrue(first_row)
        # 缺货商品仍在榜但标注
        self.assertIn("缺货", text)
        # 差一点够兑：2600 在 2380*1.5 内
        self.assertIn("再攒一点就能兑", text)
        self.assertIn("燕麦拿铁（中）兑换券", text)

    def test_lottery_expected_value(self):
        client = self._client()
        info = fetch_lottery(client)
        self.assertTrue(info.active)
        self.assertEqual(info.cost, 50)
        # EV = 0.5*1000 + 0.1*2300 + 0.4*0 = 730
        self.assertAlmostEqual(expected_value(info), 730.0)
        text = render_lottery(info)
        self.assertIn("划得来", text)  # 730 > 50

    def test_lottery_inactive(self):
        info = fetch_lottery(self._client(scenario="no-lottery"))
        self.assertFalse(info.active)
        self.assertIn("没有进行中", render_lottery(info))

    def test_bill_month_filter(self):
        client = self._client()
        orders = fetch_orders(client)
        month = datetime.now().strftime("%Y-%m")
        current = filter_month(orders, month)
        self.assertEqual(len(current), 4)  # 3 餐饮 + 1 商城（mock 数据都在最近 12 天内）
        text = render_bill(current, month)
        self.assertIn("月度麦麦账单", text)
        self.assertIn("按日分布", text)
        # 上个月订单被排除：总消费只含本月 47.5+13.5+36.0=97.00
        self.assertIn("¥97.00", text)

    def test_report_end_to_end(self):
        client = self._client()
        text = run_report(client)
        for section in ("麦麦积分总览", "可兑商品", "抽奖活动", "月度麦麦账单"):
            self.assertIn(section, text)

    def test_report_survives_module_failure(self):
        """单模块失败不阻断整体报告（指向一个确定无人监听的端口）。"""
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
        sock.close()
        client = MCPClient(token="t", url="http://127.0.0.1:{}/x".format(closed_port))
        text = run_report(client)
        self.assertIn("获取失败", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
