#!/usr/bin/env python3
"""github-web-skill · 唯一 CLI（Agent 面）。

用法：
  python scripts/gh.py diag [--full]                     # 只读诊断（各通道可用性事实）
  python scripts/gh.py get <owner>/<repo>:<path> [--ref R] [--dest F]   # 取单个文件（按路由降级）
  python scripts/gh.py get --url <https 链接> [--dest F]                # raw / Release 资产 / codeload 等
  python scripts/gh.py git <git 参数...> [--cwd D] [--deadline S] [--force CH]   # 包裹 git（环境守卫 + 预算 + 降级）
  python scripts/gh.py hosts --status | --apply --yes | --rollback
  python scripts/gh.py routes --check | --render

约定：stdout = 单个 JSON（Agent 解析）；stderr = 一行人类摘要；
     日志 = 用户区 ~/.github-access/logs/gh-YYYYMM.jsonl（GH_ACCESS_HOME 可覆盖）。
退出码：0 成功 ｜ 1 全通道失败 ｜ 2 需要授权 ｜ 3 用法错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# 包内零运行态：禁止写 .pyc / __pycache__（交付纪律）
sys.dont_write_bytecode = True

# 管道/重定向下也必须稳定输出 UTF-8（Windows 控制台默认 GBK 会把中文 JSON 打成乱码）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import budget as budget_mod  # noqa: E402
import env_guard  # noqa: E402
import channel_cdn  # noqa: E402
import channel_direct  # noqa: E402
import channel_hosts  # noqa: E402
import channel_mirror  # noqa: E402
import channel_pin  # noqa: E402
import lines  # noqa: E402
import probe  # noqa: E402
import report  # noqa: E402

PKG = Path(__file__).resolve().parents[1]
ROUTES_F = PKG / "routes" / "routes.json"
ROUTES_MD = PKG / "routes" / "ROUTES.md"
RAW_RE = re.compile(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)")
TARGET_RE = re.compile(r"^([\w.-]+)/([\w.-]+):(.+)$")
WRITE_TOKENS = {"push", "tag", "commit", "cherry-pick", "revert", "merge", "rebase", "reset"}


def load_routes() -> dict:
    return json.loads(ROUTES_F.read_text(encoding="utf-8"))


def chain_for(scenario: str, routes: dict | None = None) -> list:
    routes = routes or load_routes()
    for s in routes["scenarios"]:
        if s["id"] == scenario:
            return list(s["chain"])
    raise KeyError("未知场景：%s" % scenario)


def finish(result: dict, quiet: bool = False, code: int | None = None) -> int:
    report.log(result.get("action", "?"), ok=bool(result.get("ok")), channel=result.get("channel"),
               elapsed=result.get("elapsed"), detail=str(result.get("detail", ""))[:200],
               third_party=result.get("third_party"))
    report.emit(result, quiet=quiet)
    if code is not None:
        return code
    if result.get("need_confirm"):
        return 2
    return 0 if result.get("ok") else 1


def parse_target(target: str):
    m = TARGET_RE.match(target)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


# ---------------------------------------------------------------- get
def cmd_get(args) -> int:
    t0 = time.perf_counter()
    owner = repo = ref = path = None
    raw_url = None
    if args.url:
        if not args.url.startswith("https://"):
            return finish({"action": "get", "ok": False,
                           "detail": "仅接受 https 链接（收到：%s）" % args.url[:60],
                           "next": "改用 owner/repo:path 形式，或给出完整 https 链接"}, args.quiet, 3)
        raw_url = args.url
        m = RAW_RE.match(args.url)
        if m:                                    # raw 链接可走 CDN → 用 file_read 全链
            owner, repo, ref, path = m.group(1), m.group(2), m.group(3), m.group(4)
    else:
        parsed = parse_target(args.target or "")
        if not parsed:
            return finish({"action": "get", "ok": False, "detail": "目标格式应为 owner/repo:path"},
                          args.quiet, 3)
        owner, repo, path = parsed
        ref = args.ref
        raw_url = "https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner, repo, ref, path)
    if args.force and args.force not in load_routes()["channels"]:
        return finish({"action": "get", "ok": False, "detail": "未知通道：%s" % args.force},
                      args.quiet, 3)
    name = Path(path).name if path else (Path(raw_url).name or "file.bin")
    dest = Path(args.dest or (report.ensure_home() / "cache" / name))
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)   # Agent 常直接给新目录：先建父目录再取
    except Exception:
        pass
    bud = budget_mod.Budget(overall=args.deadline or lines.DEFAULT_BUDGET["get"],
                            per_call=lines.DEFAULT_BUDGET["per_call"],
                            min_effective=lines.DEFAULT_BUDGET["min_effective"],
                            circuit_threshold=lines.DEFAULT_BUDGET["circuit_threshold"])
    tried = []
    # raw 链接走 file_read 全链（含 CDN）；其他 https（Release 资产 / codeload / 任意官方端点）走 direct → pin → mirror
    chain = [args.force] if args.force else (chain_for("file_read") if owner else ["direct", "pin", "mirror"])
    for ch in chain:
        if not bud.can_attempt():
            tried.append({"channel": ch, "ok": False, "detail": "预算不足，停止降级"})
            break
        timeout = bud.timeout_for(20.0)
        if ch == "cdn":
            if not owner:
                tried.append({"channel": "cdn", "ok": False, "detail": "非 raw 链接：CDN 不适用"})
                continue
            r = channel_cdn.fetch(owner, repo, ref, path, dest, timeout)
        elif ch == "direct":
            r = channel_direct.http_get(raw_url, dest, timeout)
            r.update({"channel": "direct", "third_party": False})
        elif ch == "pin":
            r = channel_pin.http_get(raw_url, dest, timeout, budget=bud)
        elif ch == "mirror":
            r = channel_mirror.http_get(raw_url, dest, timeout, budget=bud)
        else:
            continue
        tried.append({"channel": ch, "ok": bool(r.get("ok")), "detail": str(r.get("detail", ""))[:120]})
        if r.get("ok"):
            bud.register_ok()
            return finish({"action": "get", "ok": True, "channel": ch, "via": r.get("via"),
                           "third_party": r.get("third_party"), "file": str(dest),
                           "bytes": dest.stat().st_size if dest.exists() else 0,
                           "elapsed": round(time.perf_counter() - t0, 2),
                           "detail": r.get("detail", ""), "tried": tried}, args.quiet)
    return finish({"action": "get", "ok": False, "detail": "全部通道失败",
                   "elapsed": round(time.perf_counter() - t0, 2), "tried": tried,
                   "next": "gh.py diag 看环境事实；或改用 pin / hosts 通道"}, args.quiet)


# ---------------------------------------------------------------- git
def cmd_git(args) -> int:
    t0 = time.perf_counter()
    # REMAINDER 会把 --force/--deadline 一并吞进来：这里兜底解析（两种写法都成立）
    git_args, force, deadline = [], args.force, args.deadline
    raw_args = list(args.git_args)
    i = 0
    while i < len(raw_args):
        if raw_args[i] == "--force" and i + 1 < len(raw_args):
            force = raw_args[i + 1]
            i += 2
            continue
        if raw_args[i] == "--deadline" and i + 1 < len(raw_args):
            try:
                deadline = float(raw_args[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        git_args.append(raw_args[i])
        i += 1
    if not git_args:
        return finish({"action": "git", "ok": False, "detail": "缺少 git 参数"}, args.quiet, 3)
    write = bool(set(git_args) & WRITE_TOKENS)
    scenario = "git_write" if write else "git_read"
    # shallow 乘数：clone 且未显式指定时默认 --depth 1（只读场景）
    if not write and git_args[0] == "clone" and not any(a.startswith("--depth") for a in git_args):
        git_args = [git_args[0], "--depth", "1", *git_args[1:]]
    bud = budget_mod.Budget(overall=deadline or lines.DEFAULT_BUDGET["git_read"],
                            per_call=lines.DEFAULT_BUDGET["per_call"],
                            min_effective=lines.DEFAULT_BUDGET["min_effective"],
                            circuit_threshold=lines.DEFAULT_BUDGET["circuit_threshold"])
    if force and force not in load_routes()["channels"]:
        return finish({"action": "git", "ok": False, "detail": "未知通道：%s" % force}, args.quiet, 3)
    if force == "mirror" and write:
        return finish({"action": "git", "ok": False,
                       "detail": "红线：写操作不允许强制走 mirror"}, args.quiet, 3)
    tried = []
    chain = [force] if force else chain_for(scenario)
    for ch in chain:
        if not bud.can_attempt():
            tried.append({"channel": ch, "ok": False, "detail": "预算不足，停止降级"})
            break
        timeout = bud.timeout_for(lines.DEFAULT_BUDGET["per_call"])
        if ch == "direct":
            r = channel_direct.git_run(git_args, args.cwd, timeout)
            r.update({"channel": "direct", "third_party": False})
        elif ch == "pin":
            r = channel_pin.git_run(git_args, args.cwd, timeout, budget=bud)
        elif ch == "mirror":
            if write:
                continue                      # 红线：写操作永不经 mirror
            r = channel_mirror.git_run(git_args, args.cwd, timeout, budget=bud)
        else:
            continue
        tried.append({"channel": ch, "ok": bool(r.get("ok")), "detail": str(r.get("detail", ""))[:120]})
        if r.get("ok"):
            bud.register_ok()
            out = {"action": "git", "ok": True, "channel": ch, "via": r.get("via"),
                   "third_party": r.get("third_party"), "rc": r.get("rc"),
                   "out": (r.get("out") or "")[:8000], "err": (r.get("err") or "")[-1500:],
                   "elapsed": round(time.perf_counter() - t0, 2),
                   "detail": r.get("detail", ""), "tried": tried}
            return finish(out, args.quiet)
    return finish({"action": "git", "ok": False, "rc": 1, "detail": "全部通道失败（写操作不经 mirror）" if write else "全部通道失败",
                   "elapsed": round(time.perf_counter() - t0, 2), "tried": tried,
                   "next": "gh.py diag 看环境事实；写操作可试 pin 通道"}, args.quiet)


# ---------------------------------------------------------------- diag
DIAG_PROBE = {"repo": "github/gitignore", "ref": "main", "path": "README.md"}


def cmd_diag(args) -> int:
    t0 = time.perf_counter()
    checks = {}
    # 环境事实
    checks["env"] = {"proxy_vars": env_guard.proxy_state(),
                     "git": env_guard.have_git(),
                     "user_area": str(report.ensure_home()),
                     "hosts_override": os.environ.get("GH_HOSTS_FILE")}
    # direct：官方端点
    tmp = report.HOME / "cache" / "_diag.bin"
    d = channel_direct.http_get("https://github.com/", tmp, 6)
    checks["direct_github"] = {"ok": d["ok"], "detail": d.get("detail")}
    c = channel_cdn.fetch(DIAG_PROBE["repo"].split("/")[0], DIAG_PROBE["repo"].split("/")[1],
                          DIAG_PROBE["ref"], DIAG_PROBE["path"], tmp, 8)
    checks["cdn"] = {"ok": c["ok"], "via": c.get("via"), "detail": c.get("detail")}
    hosts = channel_pin.cached_hosts()
    if not hosts or args.full:
        hosts = channel_pin.fetch_hosts()
    checks["pin"] = {"ok": bool(hosts), "domains": len(hosts),
                     "candidates": {k: len(v) for k, v in hosts.items()}, "source": "云函数+DoH+内置池"}
    if args.full:
        checks["pin_ip_alive"] = channel_pin.verify_ips(hosts)
    checks["hosts"] = channel_hosts.status()
    if args.full:
        ref_url = "https://raw.githubusercontent.com/%s/%s/%s/%s" % (
            DIAG_PROBE["repo"].split("/")[0], DIAG_PROBE["repo"].split("/")[1],
            DIAG_PROBE["ref"], DIAG_PROBE["path"])
        # 并发探活（完成即记录，一次列全）：镜像池 + CDN 域的事实与探活耗时
        # 未通过者同样列出（**失败 ≠ 失效**：只冷却，不删除）
        mres = probe.race_http([(s["name"], s["url"] + "/" + ref_url)
                                for s in lines.MIRROR_SOURCES if "http" in s["caps"]])
        checks["mirror_probe"] = {k: {"ok": ok, "ms": round(ms)} for k, ok, ms, _d in mres}
        cres = probe.race_http(channel_cdn.build_urls(
            DIAG_PROBE["repo"].split("/")[0], DIAG_PROBE["repo"].split("/")[1],
            DIAG_PROBE["ref"], DIAG_PROBE["path"]))
        checks["cdn_probe"] = {k: {"ok": ok, "ms": round(ms)} for k, ok, ms, _d in cres}
    ok = bool(checks["direct_github"]["ok"] or checks["cdn"]["ok"] or checks["pin"]["ok"])
    return finish({"action": "diag", "ok": ok, "elapsed": round(time.perf_counter() - t0, 2),
                   "checks": checks, "channel": None, "third_party": None,
                   "detail": "只读诊断完成（事实记录，不做性能结论）"}, args.quiet)


# ---------------------------------------------------------------- hosts
def cmd_hosts(args) -> int:
    if args.status:
        return finish({"action": "hosts.status", "ok": True, **channel_hosts.status()}, args.quiet)
    if args.rollback:
        r = channel_hosts.rollback()
        return finish({"action": "hosts.rollback", **r}, args.quiet)
    if args.apply:
        if not args.yes:
            # 先过授权门，再谈干活：未授权的重活一概不做
            return finish({"action": "hosts.apply", "ok": False, "need_confirm": True,
                           "detail": "改系统解析需显式授权：加 --yes 后才执行",
                           "next": "gh.py hosts --apply --yes（或由用户批准后重跑）"}, args.quiet, 2)
        hosts = channel_pin.cached_hosts() or channel_pin.fetch_hosts()
        # 严格校验：写系统解析前必须"能真正取到内容"（根路径响应会假阳性，见 lines.STRICT_PROBE_URLS）
        alive = channel_pin.verify_for_hosts(hosts, limit=2, timeout=6.0)
        pool = {d: ips for d, ips in alive.items() if ips}
        if not pool:
            return finish({"action": "hosts.apply", "ok": False,
                           "detail": "没有实测可用的 IP，拒绝改 hosts"}, args.quiet)
        r = channel_hosts.apply(pool, confirmed=True, flush=args.flush)
        return finish({"action": "hosts.apply", **r}, args.quiet)
    return finish({"action": "hosts", "ok": False,
                   "detail": "用 --status / --apply --yes / --rollback"}, args.quiet, 3)


# ---------------------------------------------------------------- routes
def render_routes(routes: dict) -> str:
    out = ["# 通道与场景路由（自动生成：改 routes/routes.json 后跑 gh.py routes --render）", "",
           "> 说明：只讲每条通道「适合什么 / 作用是什么 / 前提与副作用」；不做性能评比。", "",
           "## 通道", "", "| 通道 | 经第三方 | 需授权 | 作用 |", "| --- | --- | --- | --- |"]
    for name, c in routes["channels"].items():
        out.append("| `%s` | %s | %s | %s |" % (
            name, c["third_party"] or "否", "是" if c["needs_confirm"] else "否", c["role"]))
    out += ["", "## 场景路由", "", "| 场景 | 说明 | 降级链 | 入口命令 |", "| --- | --- | --- | --- |"]
    for s in routes["scenarios"]:
        out.append("| `%s` | %s | %s | %s |" % (
            s["id"], s["desc"], " → ".join("`%s`" % c for c in s["chain"]), s.get("cli", "")))
    out += ["", "## 红线", ""]
    out += ["- %s" % r for r in routes["rules"]]
    return "\n".join(out) + "\n"


def cmd_routes(args) -> int:
    routes = load_routes()
    problems = []
    names = set(routes["channels"])
    for s in routes["scenarios"]:
        for ch in s["chain"]:
            if ch not in names:
                problems.append("场景 %s 引用了未知通道 %s" % (s["id"], ch))
    if "mirror" in chain_for("git_write", routes):
        problems.append("红线破坏：git_write 链中出现 mirror")
    for s in routes["scenarios"]:
        if len(set(s["chain"])) != len(s["chain"]):
            problems.append("场景 %s 降级链有重复节点" % s["id"])
    rendered = render_routes(routes)
    if args.render:
        ROUTES_MD.write_text(rendered, encoding="utf-8")
        return finish({"action": "routes.render", "ok": True, "file": str(ROUTES_MD)}, args.quiet)
    drift = (not ROUTES_MD.exists()) or ROUTES_MD.read_text(encoding="utf-8") != rendered
    if drift:
        problems.append("ROUTES.md 与 routes.json 不一致（跑 gh.py routes --render 重绘）")
    return finish({"action": "routes.check", "ok": not problems,
                   "detail": "；".join(problems) if problems else "通道与场景链全部有效"},
                  args.quiet)


def main() -> int:
    ap = argparse.ArgumentParser(prog="gh.py", description="github-web-skill · GitHub 访问层 CLI")
    ap.add_argument("--quiet", action="store_true", help="关闭 stderr 人类摘要")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)      # 让 --quiet 在子命令之后也能用
    common.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS,
                        help="关闭 stderr 人类摘要")

    p = sub.add_parser("diag", help="只读诊断：各通道可用性事实", parents=[common])
    p.add_argument("--full", action="store_true", help="附带逐 IP / 镜像实测（更慢）")
    p.set_defaults(func=cmd_diag)

    p = sub.add_parser("get", help="取单个文件（按 file_read 路由降级）", parents=[common])
    p.add_argument("target", nargs="?", help="owner/repo:path")
    p.add_argument("--url", help="任意 https 链接（raw / Release 资产 / codeload 等）")
    p.add_argument("--ref", default="main", help="owner/repo:path 形式时的引用（分支/标签/commit）")
    p.add_argument("--dest")
    p.add_argument("--deadline", type=float)
    p.add_argument("--force", help="只走指定通道（排障/验收用）")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("git", help="包裹 git（环境守卫 + 预算 + 降级；写操作不经 mirror）", parents=[common])
    p.add_argument("git_args", nargs=argparse.REMAINDER)
    p.add_argument("--cwd")
    p.add_argument("--deadline", type=float, help="整体时间预算（秒）")
    p.add_argument("--force", help="只走指定通道（排障/验收用；写操作禁 mirror）")
    p.set_defaults(func=cmd_git)

    p = sub.add_parser("hosts", help="hosts 兜底（需授权；可回滚）", parents=[common])
    p.add_argument("--status", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--rollback", action="store_true")
    p.add_argument("--yes", action="store_true", help="显式授权（改系统解析必填）")
    p.add_argument("--flush", action="store_true", help="写后刷新 DNS 缓存")
    p.set_defaults(func=cmd_hosts)

    p = sub.add_parser("routes", help="路由表校验 / 渲染", parents=[common])
    p.add_argument("--check", action="store_true")
    p.add_argument("--render", action="store_true")
    p.set_defaults(func=cmd_routes)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
