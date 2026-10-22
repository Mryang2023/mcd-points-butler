"""麦当劳 MCP Server 的 Streamable HTTP 客户端（零第三方依赖）。

协议：JSON-RPC 2.0 over Streamable HTTP
接入：https://mcp.mcd.cn
认证：Authorization: Bearer <MCD_MCP_TOKEN>
限流：每 Token 每分钟 600 次请求（官方限制）

设计要点：
- 兼容服务端返回纯 JSON 或 SSE 事件流两种响应格式；
- 只对「只读工具」做失败重试，写操作（下单/抽奖/领券）绝不重试，
  避免重复扣积分、重复抽奖；
- 401/429 直接抛出可读错误，不做无意义重试。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "mcd-points-butler"
CLIENT_VERSION = "1.0.0"

#: 只读工具：调用失败可安全重试
SAFE_TOOLS = frozenset({
    "list-nutrition-foods", "delivery-query-addresses", "delivery-query-stores",
    "query-meal-assistance", "query-nearby-stores", "query-store-coupons",
    "query-meals", "query-meal-detail", "calculate-price", "query-order",
    "order-list", "campaign-calendar", "available-coupons", "query-my-coupons",
    "query-my-account", "mall-points-products", "mall-product-detail",
    "now-time-info", "query-lottery-info", "query-my-prizes", "mall-order-list",
    "mall-order-detail", "query-party-city", "query-party-store",
    "query-partystore-date", "query-partystore-session",
})

#: 写操作工具：失败不重试（重复调用会产生真实副作用）
UNSAFE_TOOLS = frozenset({
    "delivery-create-address", "create-order", "cancel-order",
    "auto-bind-coupons", "mall-create-order", "draw-lottery",
    "party-order-create",
})


class MCPError(Exception):
    """MCP 调用失败，消息面向用户可读。"""


class MCPClient:
    """麦当劳 MCP 客户端。"""

    def __init__(self, token=None, url=DEFAULT_URL, timeout=30, max_retries=3):
        if not token:
            raise MCPError(
                "缺少 MCP Token。请先到 open.mcd.cn/mcp 用手机号登录免费领取，"
                "然后设置环境变量 MCD_MCP_TOKEN，或用 --token 传入。"
            )
        self.url = url
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.session_id = None
        self._req_id = 0
        self._initialized = False

    # ------------------------------------------------------------------ 传输层

    def _post(self, payload):
        """发送一次 JSON-RPC 请求，返回响应体文本。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                return raw
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if exc.code == 401:
                raise MCPError("MCP Token 无效或已过期（HTTP 401），请重新领取 Token。")
            if exc.code == 429:
                raise MCPError("触发 MCP 限流（HTTP 429，官方限制 600 次/分钟），请稍后再试。")
            raise MCPError("MCP 服务返回 HTTP {}：{}".format(exc.code, detail or "无详情"))
        except urllib.error.URLError as exc:
            raise MCPError("无法连接 MCP 服务 {}：{}".format(self.url, exc.reason))
        except OSError as exc:
            # 响应阶段的连接重置/超时（WinError 10054 等）不会被 urllib 包装成
            # URLError，必须显式兜底，否则会把裸栈崩给用户
            raise MCPError("与 MCP 服务通信中断：{}".format(exc))

    @staticmethod
    def _parse_messages(raw):
        """解析响应：服务端可能返回纯 JSON，也可能返回 SSE 事件流。"""
        text = (raw or "").strip()
        if not text:
            return []
        if text[0] in "{[":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return []
            return data if isinstance(data, list) else [data]
        messages = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                messages.append(json.loads(chunk))
            except json.JSONDecodeError:
                continue
        return messages

    # ------------------------------------------------------------------ RPC 层

    def _rpc(self, method, params=None, safe=True):
        """发送 JSON-RPC 请求并等待匹配 id 的响应。

        safe=True 时对网络层错误做有限重试；safe=False（写操作）不重试。
        """
        self._req_id += 1
        payload = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params is not None:
            payload["params"] = params
        attempts = self.max_retries if safe else 1
        last_err = None
        for attempt in range(attempts):
            try:
                messages = self._parse_messages(self._post(payload))
                for msg in messages:
                    if msg.get("id") == payload["id"]:
                        if "error" in msg:
                            err = msg["error"] or {}
                            raise MCPError(
                                "MCP 错误 {}：{}".format(err.get("code"), err.get("message"))
                            )
                        return msg.get("result")
                raise MCPError("MCP 响应中未找到本次请求的结果。")
            except MCPError as exc:
                last_err = exc
                msg = str(exc)
                # Token 问题与限流重试无意义，直接抛出
                if "401" in msg or "429" in msg or "无效" in msg:
                    raise
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
        raise last_err

    def _ensure_initialized(self):
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        })
        # initialized 通知（无 id，不等待响应）；失败不影响后续
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except MCPError:
            pass
        self._initialized = True

    # ------------------------------------------------------------------ 工具层

    def list_tools(self):
        """返回服务端工具定义列表。"""
        self._ensure_initialized()
        result = self._rpc("tools/list", {})
        return (result or {}).get("tools", [])

    def call_tool(self, name, arguments=None):
        """调用一个 MCP 工具，返回原始 result（含 content/isError）。"""
        self._ensure_initialized()
        return self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            safe=name in SAFE_TOOLS,
        )

    def call_tool_compat(self, name, arguments=None):
        """兼容调用：带参失败时退化为无参重试一次。

        部分服务端版本不接受分页等可选参数，直接报错；此时用无参数
        形式再试一次，保证核心功能可用。仅用于只读工具。
        """
        if not arguments:
            return self.call_tool(name)
        try:
            return self.call_tool(name, arguments)
        except MCPError:
            return self.call_tool(name)

    @staticmethod
    def result_text(result):
        """从 tools/call 结果中抽取纯文本（content 为 [{type:text,text:...}]）。"""
        if not result:
            return ""
        parts = []
        for item in result.get("content") or []:
            if item.get("type") == "text" and item.get("text"):
                parts.append(item["text"])
        return "\n".join(parts)

    @classmethod
    def result_json(cls, result):
        """工具文本若是 JSON 则解析为对象，否则返回 None。"""
        text = cls.result_text(result)
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    @classmethod
    def check_error(cls, result):
        """服务端可能以 isError 标记业务失败，抛出可读异常。"""
        if result and result.get("isError"):
            raise MCPError(cls.result_text(result) or "MCP 工具返回业务错误。")
