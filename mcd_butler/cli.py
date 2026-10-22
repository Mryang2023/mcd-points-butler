"""命令行入口。

用法：
    python mcd-butler.py status                积分总览 + 临期预警
    python mcd-butler.py redeem [--top N]      兑换建议（性价比榜）
    python mcd-butler.py lottery               抽奖参谋（期望值分析）
    python mcd-butler.py bill [--month 2026-10] 月度麦麦账单
    python mcd-butler.py report [--month ...]  一键全量报告
    python mcd-butler.py tools                 列出 MCP 服务端全部工具（联调排查用）

Token 获取：open.mcd.cn/mcp 手机号登录免费领取；
通过环境变量 MCD_MCP_TOKEN 或 --token 传入。
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .mcp_client import DEFAULT_URL, MCPClient, MCPError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcd-butler",
        description="麦麦积分管家：麦当劳积分管理 Skill（1024 造物挑战参赛作品）",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN"),
                        help="MCP Token（默认读环境变量 MCD_MCP_TOKEN）")
    parser.add_argument("--url", default=os.environ.get("MCD_MCP_URL", DEFAULT_URL),
                        help="MCP 服务地址（默认 https://mcp.mcd.cn）")
    parser.add_argument("--debug", action="store_true", help="打印原始 MCP 响应（联调排查）")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="积分总览 + 临期预警")

    p_redeem = sub.add_parser("redeem", help="兑换建议")
    p_redeem.add_argument("--top", type=int, default=8, help="展示前 N 个可兑商品")

    sub.add_parser("lottery", help="抽奖参谋")

    for name in ("bill", "report"):
        p = sub.add_parser(name, help="月度麦麦账单" if name == "bill" else "一键全量报告")
        p.add_argument("--month", default=None, help="指定月份，如 2026-10（默认当月）")

    sub.add_parser("tools", help="列出 MCP 服务端工具（联调排查）")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        client = MCPClient(token=args.token, url=args.url)

        if args.command == "tools":
            tools = client.list_tools()
            if not tools:
                print("未获取到工具列表。")
                return 1
            for t in tools:
                print("- {}：{}".format(t.get("name"), (t.get("description") or "").split("\n")[0]))
            return 0

        if args.command == "status":
            from .points import fetch_points, render_status
            snap = fetch_points(client)
            print(render_status(snap))
            if args.debug:
                import json
                print("\n[debug] query-my-account 原始响应：")
                print(json.dumps(snap.raw, ensure_ascii=False, indent=2))
            return 0

        if args.command == "redeem":
            from .points import fetch_points
            from .redeem import fetch_products, render_redeem
            snap = fetch_points(client)
            products = fetch_products(client)
            print(render_redeem(snap, products, top=args.top))
            return 0

        if args.command == "lottery":
            from .lottery import fetch_lottery, render_lottery
            print(render_lottery(fetch_lottery(client)))
            return 0

        if args.command == "bill":
            from .bill import fetch_orders, filter_month, render_bill
            orders = filter_month(fetch_orders(client), args.month)
            print(render_bill(orders, args.month))
            return 0

        if args.command == "report":
            from .report import run_report
            print(run_report(client, month=args.month))
            return 0

    except MCPError as exc:
        print("出错：{}".format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
