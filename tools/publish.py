"""一键发布：创建 GitHub 公开仓库、推送代码、提交大赛报名 Issue。

用法（在项目根目录）：
    # PowerShell：
    $env:GITHUB_TOKEN="ghp_你的PAT"
    python tools/publish.py            # 建公开仓库 + 推送代码
    python tools/publish.py --issue    # 追加：提交大赛报名 Issue
    python tools/publish.py --all      # 以上全部

安全设计：
- Token 只从环境变量 GITHUB_TOKEN（或 --token）读取，不写入任何文件；
- git 推送通过 http.extraHeader 传递 Bearer 认证，不落进 .git/config；
  仅在 bearer 失败时降级用 URL 嵌入，推送后立即重置为干净 URL；
- 本脚本不打印 Token 本身。

PAT 领取（30 秒）：github.com → Settings → Developer settings →
Personal access tokens → Tokens (classic) → Generate new token (classic)
→ 勾选 public_repo（或 repo）→ 生成后复制（ghp_ 开头）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO_NAME = "mcd-points-butler"
REPO_DESC = ("麦麦积分管家：麦当劳积分管理 Skill——临期积分预警、积分商城兑换性价比推荐、"
             "抽奖期望值分析、月度麦麦账单。基于麦当劳中国官方 MCP，全程只读，零依赖。"
             "WorkBuddy「1024 造物挑战」参赛作品")
CHALLENGE_REPO = "M-China/mcd-developer-innovation-challenge"
PLACEHOLDER_USER = "mryang"  # 代码/文档中使用的占位 GitHub 用户名
API = "https://api.github.com"


def api(method, path, token, payload=None):
    """调用 GitHub REST API，返回 (status, parsed_json)。"""
    url = API + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "mcd-points-butler-publish",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"message": raw[:300]}
    except urllib.error.URLError as exc:
        print("网络错误：无法连接 GitHub API（{}）".format(exc.reason))
        sys.exit(1)


def git(*args, token=None, check=True):
    """执行 git 命令；token 存在时以 extraHeader 传递（不落盘）。"""
    cmd = ["git"]
    if token:
        cmd += ["-c", "http.extraHeader=Authorization: Bearer " + token]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        print("git {} 失败：\n{}\n{}".format(" ".join(args), result.stdout, result.stderr))
        sys.exit(1)
    return result


def resolve_login(token):
    status, data = api("GET", "/user", token)
    if status != 200:
        print("PAT 校验失败（HTTP {}）：{}".format(status, data.get("message", "未知错误")))
        print("请确认 Token 未过期，且勾选了 public_repo（或 repo）权限。")
        sys.exit(1)
    return data["login"]


def ensure_repo(token, login):
    """创建公开仓库；已存在则复用。返回 (repo_url, created)。"""
    status, data = api("POST", "/user/repos", token, {
        "name": REPO_NAME,
        "description": REPO_DESC,
        "private": False,
        "has_issues": True,
        "has_wiki": False,
        "has_projects": False,
        "auto_init": False,
    })
    if status == 201:
        return data["html_url"], True
    if status == 422 and "already exists" in str(data.get("errors", "")):
        status, data = api("GET", "/repos/{}/{}".format(login, REPO_NAME), token)
        if status == 200:
            if data.get("private"):
                print("仓库已存在但是私有的，正在设为公开……")
                api("PATCH", "/repos/{}/{}".format(login, REPO_NAME), token, {"private": False})
            print("仓库已存在，复用：{}".format(data["html_url"]))
            return data["html_url"], False
    print("创建仓库失败（HTTP {}）：{}".format(status, data.get("message", data)))
    sys.exit(1)


def fix_placeholder(login):
    """把代码/文档里的占位用户名替换为真实 GitHub 登录名。"""
    if login.lower() == PLACEHOLDER_USER:
        return False
    files = ["README.md", "mcd_butler/__init__.py", "SKILL.md", "MCP_INTEGRATION.md"]
    changed = False
    for path in files:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        new = text.replace("github.com/{}/".format(PLACEHOLDER_USER),
                           "github.com/{}/".format(login))
        if new != text:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
            changed = True
    if changed:
        git("add", "-A")
        git("commit", "--amend", "--no-edit")
        print("已将文档中的仓库地址更新为 github.com/{}/{}".format(login, REPO_NAME))
    return changed


def push(token, login):
    """推送 main 分支；bearer 失败时降级 URL 嵌入并事后清理。"""
    clean_url = "https://github.com/{}/{}.git".format(login, REPO_NAME)
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", clean_url)
    git("branch", "-M", "main", check=False)

    result = git("push", "-u", "origin", "main", token=token, check=False)
    if result.returncode == 0:
        print(result.stderr.strip())
        return True

    # 降级：URL 嵌入 Token 推送，完成后立刻重置为干净 URL
    print("bearer 推送失败，降级重试……\n{}".format(result.stderr.strip()[:500]))
    embed_url = "https://x-access-token:{}@github.com/{}/{}.git".format(token, login, REPO_NAME)
    git("push", "-u", embed_url, "main")
    git("remote", "set-url", "origin", clean_url)
    return True


def verify_pushed(token, login):
    """校验关键文件已在远端可见。"""
    for path in ("README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md"):
        status, _ = api("GET", "/repos/{}/{}/contents/{}".format(login, REPO_NAME, path), token)
        if status != 200:
            print("警告：远端未找到 {}（HTTP {}），请检查推送结果。".format(path, status))
            return False
    print("校验通过：README / CONTEST_DECLARATION / MCP_INTEGRATION 均已在远端。")
    return True


def submit_issue(token, login):
    """按官方模板提交报名 Issue。

    官方警告：标题与正文间、字段名与字段值间不要加换行/空行；
    项目地址不要用 Markdown 链接格式。
    """
    repo_url = "https://github.com/{}/{}".format(login, REPO_NAME)
    title = "麦麦积分管家 mcd-points-butler 参赛申请"
    body = (
        "【参赛申请】\n"
        "项目名称：麦麦积分管家 mcd-points-butler\n"
        "项目地址：{}\n"
        "项目简介：麦当劳积分管理 Skill：临期积分预警、积分商城兑换性价比推荐、"
        "抽奖期望值分析、月度麦麦账单。基于麦当劳中国官方 MCP 开发，全程只读不代操作，"
        "零第三方依赖，Python 3.9+ 一行命令。参加 WorkBuddy「1024 造物挑战」程序员节"
        "应用创作大赛。".format(repo_url)
    )
    status, data = api("POST", "/repos/{}/issues".format(CHALLENGE_REPO), token,
                       {"title": title, "body": body})
    if status == 201:
        print("报名 Issue 提交成功：{}".format(data["html_url"]))
        print("系统稍后会在 Issue 下回复审核结果，请留意。")
        return True
    print("报名 Issue 提交失败（HTTP {}）：{}".format(status, data.get("message", data)))
    if status == 403:
        print("提示：确认 PAT 勾选了 public_repo（或 repo）权限。")
    return False


def main():
    parser = argparse.ArgumentParser(description="一键发布参赛项目到 GitHub 并报名")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub PAT（默认读环境变量 GITHUB_TOKEN）")
    parser.add_argument("--issue", action="store_true", help="推送后提交报名 Issue")
    parser.add_argument("--all", action="store_true", help="推送并提交报名 Issue")
    args = parser.parse_args()

    if not args.token:
        print("未检测到 GitHub PAT。领取方式（30 秒）：")
        print("  github.com → Settings → Developer settings → Personal access tokens")
        print("  → Tokens (classic) → Generate new token (classic)")
        print("  → 勾选 public_repo → 生成复制（ghp_ 开头）")
        print("然后：PowerShell 执行  $env:GITHUB_TOKEN=\"ghp_...\"  再跑本脚本。")
        sys.exit(2)

    if not os.path.isdir(".git"):
        print("当前目录不是 git 仓库，请在项目根目录运行。")
        sys.exit(2)

    print("== 1/4 校验 PAT ==")
    login = resolve_login(args.token)
    print("PAT 有效，GitHub 账号：{}".format(login))

    print("== 2/4 创建公开仓库 ==")
    repo_url, created = ensure_repo(args.token, login)
    print("{}：{}".format("已创建" if created else "复用", repo_url))

    print("== 3/4 推送代码 ==")
    fix_placeholder(login)
    push(args.token, login)
    verify_pushed(args.token, login)
    print("仓库地址：{}".format(repo_url))

    if args.issue or args.all:
        print("== 4/4 提交报名 Issue ==")
        submit_issue(args.token, login)
    else:
        print("（报名 Issue 未提交；确认仓库无误后运行：python tools/publish.py --issue）")
    print("完成。接下来：去仓库页面点个 Star，然后把链接甩进你的群/V2EX/掘金（文案见 PROMO.md）。")


if __name__ == "__main__":
    main()
