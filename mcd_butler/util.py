"""通用工具：防御性字段提取、数字解析、ASCII 表格渲染。

麦当劳 MCP 各工具返回的 JSON 字段名未完全公开，因此所有解析都按
「别名列表 + 大小写不敏感 + 递归兜底」处理，真实联调时再按实际
返回收紧。
"""

from __future__ import annotations

import re
from datetime import datetime


def _norm(key):
    """键名归一化：小写并去除非字母数字字符，便于别名匹配。"""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def dig(obj, *keys, default=None):
    """逐层安全取值：dig(d, "a", "b") 等价于 d.get("a", {}).get("b")。"""
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def pick(obj, aliases, default=None):
    """在 dict 中按别名列表找值：先精确匹配，再归一化匹配。"""
    if not isinstance(obj, dict):
        return default
    # 1) 精确键名
    for alias in aliases:
        if alias in obj and obj[alias] is not None:
            return obj[alias]
    # 2) 归一化匹配（大小写/下划线/连字符不敏感）
    norm_map = {_norm(k): v for k, v in obj.items()}
    for alias in aliases:
        hit = norm_map.get(_norm(alias))
        if hit is not None:
            return hit
    return default


def search_value(obj, aliases, default=None, _depth=0):
    """先按 pick 找一层，找不到再递归搜索嵌套 dict/list（限深 4 层）。"""
    hit = pick(obj, aliases)
    if hit is not None:
        return hit
    if _depth >= 4:
        return default
    if isinstance(obj, dict):
        for value in obj.values():
            found = search_value(value, aliases, _depth=_depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = search_value(item, aliases, _depth=_depth + 1)
            if found is not None:
                return found
    return default


def to_int(value, default=0):
    """尽力把值转成 int：支持 "1,234"、12.0、"12积分" 等脏数据。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return default
    try:
        return int(float(match.group(0)))
    except ValueError:
        return default


def to_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def as_list(value):
    """把可能是 dict / list / None 的值统一成 list。

    dict 仅在含有明确的列表包装键（list/items/records/data/result/content）时
    取其内部列表；否则返回空列表——不把任意 dict 当成单个元素，避免把
    整个响应信封误判成一条数据。
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("list", "items", "records", "data", "result", "content"):
            inner = value.get(key)
            if isinstance(inner, list):
                return inner
        return []
    return []


def unwrap(data):
    """脱掉常见响应信封：{"code":0,"data":{...}} / {"result":{...}}。"""
    if isinstance(data, dict):
        for key in ("data", "result"):
            inner = data.get(key)
            if isinstance(inner, (dict, list)):
                return inner
    return data


def parse_dt(value, default=None):
    """尽力解析日期时间，支持常见字符串与时间戳（秒/毫秒）。"""
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:  # 毫秒
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return default
    text = str(value).strip()
    if not text:
        return default
    cleaned = text.replace("T", " ").replace("Z", "").replace("/", "-")
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(cleaned[: len(fmt) + 4], fmt)
        except ValueError:
            continue
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return default
    return default


def fmt_int(value):
    """千分位整数。"""
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return str(value)


def fmt_money(value):
    """金额：保留两位。"""
    try:
        return "¥{:,.2f}".format(float(value))
    except (TypeError, ValueError):
        return str(value)


def render_table(headers, rows, aligns=None):
    """零依赖 ASCII 表格。中文按两个字符宽度计算，保证对齐。"""
    def width(text):
        return sum(2 if ord(ch) > 127 else 1 for ch in str(text))

    def pad(text, target, align):
        gap = max(0, target - width(text))
        if align == "r":
            return " " * gap + str(text)
        if align == "c":
            left = gap // 2
            return " " * left + str(text) + " " * (gap - left)
        return str(text) + " " * gap

    headers = [str(h) for h in headers]
    rows = [[str(c) for c in row] for row in rows]
    if not aligns:
        aligns = ["l"] * len(headers)
    col_width = [width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_width[i] = max(col_width[i], width(cell))

    lines = []
    lines.append("  ".join(pad(h, col_width[i], "c") for i, h in enumerate(headers)))
    lines.append("  ".join("-" * w for w in col_width))
    for row in rows:
        lines.append("  ".join(pad(c, col_width[i], aligns[i]) for i, c in enumerate(row)))
    return "\n".join(lines)
