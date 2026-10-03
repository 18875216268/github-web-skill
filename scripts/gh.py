#!/usr/bin/env python3
"""github-web-skill · 唯一 CLI（Agent 面）。

用法：
  python scripts/gh.py diag [--full]                     # 只读诊断（各通道可用性事实）
  python scripts/gh.py get <owner>/<repo>:<path> [--ref R] [--dest F] [--force CH] [--exclude CH,CH]   # 取单个文件（按路由降级）
  python scripts/gh.py get --url <https 链接> [--dest F]                # raw / Release 资产 / codeload 等
  python scripts/gh.py git <git 参数...> [--cwd D] [--deadline S] [--force CH] [--exclude CH,CH]   # 包裹 git（环境守卫 + 预算 + 降级）
  python scripts/gh.py hosts --status | --apply --yes | --rollback
  python scripts/gh.py routes --check | --render
  python scripts/gh.py update --check | --apply --yes | --rollback    # 更新层（仅显式调用，从不自检）

约定：stdout = 单个 JSON（Agent 解析）；stderr = 一行人类摘要；
     日志 = 用户区 ~/.github-access/logs/gh-YYYYMM.jsonl（GH_ACCESS_HOME 可覆盖）。
退出码：0 成功 ｜ 1 全通道失败 ｜ 2 需要授权 ｜ 3 用法错误。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
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

# 方式目录引导：channels/*/（一方式一文件夹）注入 sys.path——通道内部平铺 import 依赖它
for _d in sorted((Path(__file__).resolve().parents[1] / "channels").glob("*")):
    if _d.is_dir():
        sys.path.insert(0, str(_d))

# 更新层引导：update/（纯逻辑模块；出网动作在本文件 cmd_update 经自有通道完成）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "update"))

import budget as budget_mod  # noqa: E402
import env_guard  # noqa: E402
import lines  # noqa: E402
import probe  # noqa: E402
import report  # noqa: E402
import update as update_mod  # noqa: E402

PKG = Path(__file__).resolve().parents[1]
ROUTES_F = PKG / "routes" / "routes.json"
ROUTES_MD = PKG / "routes" / "ROUTES.md"
RAW_RE = re.compile(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)")
TARGET_RE = re.compile(r"^([\w.-]+)/([\w.-]+):(.+)$")
WRITE_TOKENS = {"push", "tag", "commit", "cherry-pick", "revert", "merge", "rebase", "reset"}
# 非 raw https 直取（Release/codeload 等）与更新层共用的降级链——有意不含 cdn：
# CDN 只按仓库路径取（不认任意 URL），且更新检测要求新鲜度（不走有缓存的第三方 CDN）。
HTTP_FALLBACK = ["direct", "pin", "mirror"]


def load_routes() -> dict:
    return json.loads(ROUTES_F.read_text(encoding="utf-8"))


def chain_for(scenario: str, routes: dict | None = None) -> list:
    routes = routes or load_routes()
    for s in routes["scenarios"]:
        if s["id"] == scenario:
            return list(s["chain"])
    raise KeyError("未知场景：%s" % scenario)


def load_channels() -> dict:
    """按 routes.json 注册表**动态加载**通道模块（注册表驱动的分发）。

    新增/删除方式 = 放置 `channels/<name>/channel_<name>.py` + routes.json 注册/注销一行，
    **无需改本文件**。返回 {通道名: 模块}；`file: null`（约定态，如 offline）自然缺席。
    接口约定：参与 get/git 降级链的通道导出 `http_get` / `git_run`（如 cdn 的 git 占位实现）；
    不参与链的通道（如 hosts，只服务独立 CLI）可不导出——分发时如实跳过，不做强制。
    """
    mods = {}
    routes = load_routes()
    for name, spec in routes["channels"].items():
        f = spec.get("file")
        if not f:
            continue                     # 约定态通道（offline）：无实现文件
        mod_name = "channel_" + name
        if mod_name in sys.modules:      # 已被其他通道 import（如 cdn→channel_direct）：复用单例
            mods[name] = sys.modules[mod_name]
            continue
        p = PKG / f
        if not p.is_file():
            continue                     # 缺文件：--check 会报，分发时按"约定态缺席"处理
        spec_ = importlib.util.spec_from_file_location(mod_name, p)
        mod = importlib.util.module_from_spec(spec_)
        sys.modules[mod_name] = mod
        spec_.loader.exec_module(mod)
        mods[name] = mod
    return mods


_CH = load_channels()                    # 通道模块表（单一实例，全命令共享）


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


def _parse_exclude(exclude: str | None, force: str | None) -> tuple:
    """解析 --exclude：返回 (排除集, 错误信息)。

    规则：与 --force 互斥（显式优于隐式——同时给出按用法错误处理）；
    未知通道名同样是用法错误。
    """
    excl = {x.strip() for x in (exclude or "").split(",") if x.strip()}
    if not excl:
        return set(), ""
    if force:
        return set(), "--force 与 --exclude 互斥：只走单道请用 --force，裁剪链请用 --exclude"
    unknown = excl - set(load_routes()["channels"])
    if unknown:
        return set(), "未知通道：%s" % ", ".join(sorted(unknown))
    return excl, ""


def _force_err(routes: dict, force: str | None, cap: str) -> str:
    """--force 通道名校验：须为**已注册、且具备所需能力**的通道。

    两道门：① 约定态通道（`file: null`，如 offline）本就没有实现；
    ② 有实现文件但**不提供该能力**的通道（如 hosts 只有 status/apply/rollback，
    没有 http_get / git_run）。二者都早在此拦下退 3（用法错误），
    而不是放它进链后以"全通道失败"退 1 误导调用方。
    """
    if not force:
        return ""
    spec = routes["channels"].get(force)
    if not spec:
        return "未知通道：%s" % force
    if not spec.get("file"):
        return "通道 %s 是约定态（无实现文件），不能用 --force；请直接用它的命令" % force
    if getattr(_CH.get(force), cap, None) is None:
        return "通道 %s 不提供 %s 能力，不能用 --force；请直接用它的命令" % (force, cap)
    return ""


_REPO_URL_RE = re.compile(r"https?://(?:[^/]+/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def _archive_hint(git_args: list) -> str:
    """clone 全链失败后的归档替代建议（方案 A：只提示、不自动执行——选择权留给调用方）。

    归档 = codeload 的 zip 快照：无 git 历史、不能 pull/push，但"只要代码"时往往能走通
    （普通 HTTP 下载，direct/pin 渠道皆可取）。分支未知，提示语中留 <默认分支，通常 main>
    由调用方确认替换（不臆测分支名）。
    """
    if not git_args or git_args[0] != "clone":
        return ""
    url = next((a for a in git_args[1:] if a.startswith("http")), "")
    m = _REPO_URL_RE.match(url)
    if not m:
        return ""
    owner, repo = m.group(1), m.group(2)
    return ("；若只需代码、不需历史，可改取 codeload 归档（zip 快照，无 git 历史）："
            "gh.py get --url https://codeload.github.com/%s/%s/zip/refs/heads/<默认分支，通常 main> "
            "--dest %s.zip" % (owner, repo, repo))


def _http_via_chain(url: str, dest: Path, chain: list, bud, routes: dict, tried: list):
    """沿通道链取文件（get 与 update 共用）：完成即用、失败降级；返回首个成功结果或 None。"""
    for ch in chain:
        if not bud.can_attempt():
            tried.append({"channel": ch, "ok": False, "detail": "预算不足，停止降级"})
            break
        mod = _CH.get(ch)
        fn = getattr(mod, "http_get", None) if mod else None
        if fn is None:
            tried.append({"channel": ch, "ok": False,
                          "detail": "约定态通道或该通道不提供 HTTP 取文件能力，跳过"})
            continue
        r = fn(url, dest, bud.timeout_for(20.0), budget=bud)
        r.setdefault("channel", ch)
        r.setdefault("third_party", routes["channels"].get(ch, {}).get("third_party") or False)
        tried.append({"channel": ch, "ok": bool(r.get("ok")), "detail": str(r.get("detail", ""))[:120]})
        if r.get("ok"):
            bud.register_ok()
            return r
    return None


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
    excl, err = _parse_exclude(getattr(args, "exclude", None), args.force)
    if err:
        return finish({"action": "get", "ok": False, "detail": err}, args.quiet, 3)
    routes = load_routes()
    ferr = _force_err(routes, args.force, "http_get")
    if ferr:
        return finish({"action": "get", "ok": False, "detail": ferr,
                       "next": "可 --force 的通道：direct / pin / mirror / cdn"}, args.quiet, 3)
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
    base = [args.force] if args.force else (chain_for("file_read") if owner else HTTP_FALLBACK)
    chain = [c for c in base if c not in excl]
    if not chain:
        return finish({"action": "get", "ok": False,
                       "detail": "场景链被 --exclude 全部排除（base=%s, exclude=%s）" % (base, sorted(excl))},
                      args.quiet, 1)
    r = _http_via_chain(raw_url, dest, chain, bud, routes, tried)
    if r:
        return finish({"action": "get", "ok": True, "channel": r["channel"], "via": r.get("via"),
                       "third_party": r.get("third_party"), "file": str(dest),
                       "bytes": dest.stat().st_size if dest.exists() else 0,
                       "elapsed": round(time.perf_counter() - t0, 2),
                       "budget": bud.snapshot(),
                       "detail": r.get("detail", ""), "tried": tried}, args.quiet)
    return finish({"action": "get", "ok": False, "detail": "全部通道失败",
                   "elapsed": round(time.perf_counter() - t0, 2), "tried": tried,
                   "budget": bud.snapshot(),
                   "next": "gh.py diag 看环境事实；或改用 pin / hosts 通道"}, args.quiet)


# ---------------------------------------------------------------- git
def cmd_git(args) -> int:
    t0 = time.perf_counter()
    # REMAINDER 会把 --cwd/--force/--deadline/--exclude 一并吞进来：这里兜底解析（两种写法都成立）
    git_args, force, deadline, exclude = [], args.force, args.deadline, getattr(args, "exclude", None)
    cwd = args.cwd
    raw_args = list(args.git_args)
    i = 0
    while i < len(raw_args):
        # git 自身没有 --cwd 选项，这里剥离不会与 git 参数冲突；缺值时保守当作 git 参数原样透传
        if raw_args[i] == "--cwd" and i + 1 < len(raw_args):
            cwd = raw_args[i + 1]
            i += 2
            continue
        if raw_args[i] == "--force" and i + 1 < len(raw_args):
            force = raw_args[i + 1]
            i += 2
            continue
        if raw_args[i] == "--exclude" and i + 1 < len(raw_args):
            exclude = raw_args[i + 1]
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
    excl, err = _parse_exclude(exclude, force)
    if err:
        return finish({"action": "git", "ok": False, "detail": err}, args.quiet, 3)
    write = bool(set(git_args) & WRITE_TOKENS)
    scenario = "git_write" if write else "git_read"
    # shallow 乘数：clone 且未显式指定时默认 --depth 1（只读场景）
    if not write and git_args[0] == "clone" and not any(a.startswith("--depth") for a in git_args):
        git_args = [git_args[0], "--depth", "1", *git_args[1:]]
    bud = budget_mod.Budget(overall=deadline or lines.DEFAULT_BUDGET["git_read"],
                            per_call=lines.DEFAULT_BUDGET["per_call"],
                            min_effective=lines.DEFAULT_BUDGET["min_effective"],
                            circuit_threshold=lines.DEFAULT_BUDGET["circuit_threshold"])
    routes = load_routes()
    ferr = _force_err(routes, force, "git_run")
    if ferr:
        return finish({"action": "git", "ok": False, "detail": ferr,
                       "next": "可 --force 的通道：direct / pin / mirror / cdn"}, args.quiet, 3)
    if force == "mirror" and write:
        return finish({"action": "git", "ok": False,
                       "detail": "红线：写操作不允许强制走 mirror"}, args.quiet, 3)
    tried = []
    base = [force] if force else chain_for(scenario)
    chain = [c for c in base if c not in excl]
    if not chain:
        return finish({"action": "git", "ok": False,
                       "detail": "场景链被 --exclude 全部排除（base=%s, exclude=%s）" % (base, sorted(excl))},
                      args.quiet, 1)
    for ch in chain:
        if not bud.can_attempt():
            tried.append({"channel": ch, "ok": False, "detail": "预算不足，停止降级"})
            break
        if ch == "mirror" and write:
            continue                      # 红线：写操作永不经 mirror
        mod = _CH.get(ch)
        fn = getattr(mod, "git_run", None) if mod else None
        if fn is None:
            tried.append({"channel": ch, "ok": False,
                          "detail": "约定态通道或该通道不提供 git 能力，跳过"})
            continue
        timeout = bud.timeout_for(lines.DEFAULT_BUDGET["per_call"])
        r = fn(git_args, cwd, timeout, budget=bud)
        r.setdefault("channel", ch)
        r.setdefault("third_party", routes["channels"].get(ch, {}).get("third_party") or False)
        tried.append({"channel": ch, "ok": bool(r.get("ok")), "detail": str(r.get("detail", ""))[:120]})
        if r.get("ok"):
            bud.register_ok()
            out = {"action": "git", "ok": True, "channel": ch, "via": r.get("via"),
                   "third_party": r.get("third_party"), "rc": r.get("rc"),
                   "out": (r.get("out") or "")[:8000], "err": (r.get("err") or "")[-1500:],
                   "elapsed": round(time.perf_counter() - t0, 2),
                   "budget": bud.snapshot(),
                   "detail": r.get("detail", ""), "tried": tried}
            return finish(out, args.quiet)
    nxt = "gh.py diag 看环境事实；写操作可试 pin 通道" + _archive_hint(git_args)
    return finish({"action": "git", "ok": False, "rc": 1,
                   "detail": "全部通道失败（写操作不经 mirror）" if write else "全部通道失败",
                   "elapsed": round(time.perf_counter() - t0, 2), "tried": tried,
                   "budget": bud.snapshot(),
                   "next": nxt}, args.quiet)


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
    d = _CH["direct"].http_get("https://github.com/", tmp, 6)
    checks["direct_github"] = {"ok": d["ok"], "detail": d.get("detail")}
    c = _CH["cdn"].fetch(DIAG_PROBE["repo"].split("/")[0], DIAG_PROBE["repo"].split("/")[1],
                         DIAG_PROBE["ref"], DIAG_PROBE["path"], tmp, 8)
    checks["cdn"] = {"ok": c["ok"], "via": c.get("via"), "detail": c.get("detail")}
    hosts = _CH["pin"].fetch_ip_candidates()
    checks["pin"] = {"ok": bool(hosts), "domains": len(hosts),
                     "candidates": {k: len(v) for k, v in hosts.items()},
                     "source": "资源层多源聚合 + 统一测速（hub）"}
    if args.full:
        checks["pin_ip_alive"] = _CH["pin"].verify_ips(hosts)
    checks["hosts"] = _CH["hosts"].status()
    if args.full:
        ref_url = "https://raw.githubusercontent.com/%s/%s/%s/%s" % (
            DIAG_PROBE["repo"].split("/")[0], DIAG_PROBE["repo"].split("/")[1],
            DIAG_PROBE["ref"], DIAG_PROBE["path"])
        # 并发探活（完成即记录，一次列全）：镜像池 + CDN 域的事实与探活耗时
        # 未通过者同样列出（**失败 ≠ 失效**：只冷却，不删除）
        mres = probe.race_http([(s["name"], s["url"] + "/" + ref_url)
                                for s in _CH["mirror"].SOURCES
                                if s.get("enabled", True) and "http" in s["caps"]])
        checks["mirror_probe"] = {k: {"ok": ok, "ms": round(ms)} for k, ok, ms, _d in mres}
        cres = probe.race_http(_CH["cdn"].build_urls(
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
        return finish({"action": "hosts.status", "ok": True, **_CH["hosts"].status()}, args.quiet)
    if args.rollback:
        r = _CH["hosts"].rollback()
        return finish({"action": "hosts.rollback", **r}, args.quiet)
    if args.apply:
        if not args.yes:
            # 先过授权门，再谈干活：未授权的重活一概不做
            return finish({"action": "hosts.apply", "ok": False, "need_confirm": True,
                           "detail": "改系统解析需显式授权：加 --yes 后才执行",
                           "next": "gh.py hosts --apply --yes（或由用户批准后重跑）"}, args.quiet, 2)
        hosts = _CH["pin"].fetch_ip_candidates()
        # 严格校验：写系统解析前必须"能真正取到内容"（根路径响应会假阳性，见 lines.STRICT_PROBE_URLS）
        alive = _CH["pin"].verify_for_hosts(hosts, limit=2, timeout=6.0)
        pool = {d: ips for d, ips in alive.items() if ips}
        if not pool:
            return finish({"action": "hosts.apply", "ok": False,
                           "detail": "没有实测可用的 IP，拒绝改 hosts"}, args.quiet)
        r = _CH["hosts"].apply(pool, confirmed=True, flush=args.flush)
        return finish({"action": "hosts.apply", **r}, args.quiet)
    return finish({"action": "hosts", "ok": False,
                   "detail": "用 --status / --apply --yes / --rollback"}, args.quiet, 3)


# ---------------------------------------------------------------- routes
def render_routes(routes: dict) -> str:
    out = ["# 通道与场景路由（自动生成：改 routes/routes.json 后跑 gh.py routes --render）", "",
           "> 说明：只讲每条通道「适合什么 / 作用是什么 / 前提与副作用」；不做性能评比。",
           "> 每条通道的**内部降级链**（源池/择路/超时）见其通道目录 README：`channels/<通道名>/README.md`。", "",
           "## 通道", "", "| 通道 | 经第三方 | 需授权 | 消费供给 | 作用 | 实现与说明 |",
           "| --- | --- | --- | --- | --- | --- |"]
    for name, c in routes["channels"].items():
        impl = ("`%s`（README 含内部降级链）" % c["file"]) if c.get("file") else "约定态（无实现文件）"
        kinds = "、".join("`%s`" % k for k in (c.get("kinds") or [])) or "—"
        out.append("| `%s` | %s | %s | %s | %s | %s |" % (
            name, c["third_party"] or "否", "是" if c["needs_confirm"] else "否", kinds,
            c["role"], impl))
    out += ["", "## 场景路由（情况 × 通道矩阵）", "",
            "> 情况决定通道序列；通道内部还有各自的源级降级链（见各通道目录 README）。", "",
            "| 情况（场景） | 说明 | 通道降级链 | 入口命令 |", "| --- | --- | --- | --- |"]
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
    # 注册表↔方式目录双向完整性：注册的文件必须存在；目录里的实现必须已注册（防悬空/漏注册）
    for name, spec in routes["channels"].items():
        f = spec.get("file")
        if f and not (PKG / f).is_file():
            problems.append("通道 %s 的实现文件不存在：%s" % (name, f))
    registered = {str((PKG / spec["file"]).resolve()) for spec in routes["channels"].values() if spec.get("file")}
    for p in (PKG / "channels").glob("*/channel_*.py"):
        if str(p.resolve()) not in registered:   # 统一转 str 再比对（Path 对象与 str 集合不可直接比较）
            problems.append("channels/ 下存在未注册的通道实现：%s" % p.relative_to(PKG))
    # 通道↔供给对账：kinds 消费声明 ⊆ sources.json 注册表（正向硬校验）；反向未消费 = 软提示
    try:
        src_kinds = set(json.loads((PKG / "sources" / "sources.json")
                                   .read_text(encoding="utf-8"))["kinds"])
    except Exception as exc:
        problems.append("sources.json 读取失败：%s" % exc)
        src_kinds = set()
    for name, c in routes["channels"].items():
        declared = c.get("kinds")
        if declared is None:
            problems.append("通道 %s 缺 kinds 消费声明（新 schema 必填）" % name)
            continue
        unknown = set(declared) - src_kinds
        if unknown:
            problems.append("通道 %s 声明了不存在的供给大类 %s" % (name, sorted(unknown)))
    consumed = {k for c in routes["channels"].values() for k in (c.get("kinds") or [])}
    unconsumed = sorted(src_kinds - consumed)
    rendered = render_routes(routes)
    if args.render:
        ROUTES_MD.write_text(rendered, encoding="utf-8")
        return finish({"action": "routes.render", "ok": True, "file": str(ROUTES_MD)}, args.quiet)
    drift = (not ROUTES_MD.exists()) or ROUTES_MD.read_text(encoding="utf-8") != rendered
    if drift:
        problems.append("ROUTES.md 与 routes.json 不一致（跑 gh.py routes --render 重绘）")
    detail = "；".join(problems) if problems else "通道与场景链全部有效"
    if not problems and unconsumed:
        detail += "；软提示：供给大类无消费者 %s" % unconsumed
    return finish({"action": "routes.check", "ok": not problems, "detail": detail},
                  args.quiet)


# ---------------------------------------------------------------- update
def cmd_update(args) -> int:
    """更新层（仅显式调用——本技能从不自检更新，其他命令一律不碰这个层）。"""
    t0 = time.perf_counter()
    if args.rollback:
        r = update_mod.restore_from_backup(PKG, report.ensure_home())
        return finish({"action": "update.rollback", **r}, args.quiet)
    ref = args.ref or update_mod.DEFAULT_REF
    routes = load_routes()
    home = report.ensure_home()
    bud = budget_mod.Budget(overall=args.deadline or lines.DEFAULT_BUDGET["get"],
                            per_call=lines.DEFAULT_BUDGET["per_call"],
                            min_effective=lines.DEFAULT_BUDGET["min_effective"],
                            circuit_threshold=lines.DEFAULT_BUDGET["circuit_threshold"])
    chain = HTTP_FALLBACK                  # 检测/下载均不含 cdn：更新要求新鲜度，不走有缓存的第三方 CDN
    if args.check:
        url = update_mod.raw_manifest_url(ref)
        dest = home / "cache" / "_remote_manifest.json"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        local = update_mod.local_version(PKG)     # 本地版本本地可得——失败分支也如实报告
        tried = []
        r = _http_via_chain(url, dest, chain, bud, routes, tried)
        if not r:
            return finish({"action": "update.check", "ok": False, "url": url, "ref": ref,
                           "local": local, "detail": "无法获取远端版本信息", "tried": tried,
                           "next": "gh.py diag 看环境事实；稍后重试 gh.py update --check"}, args.quiet)
        try:
            remote = update_mod.manifest_bytes_version(dest.read_bytes())
        except Exception as e:
            return finish({"action": "update.check", "ok": False, "url": url, "ref": ref,
                           "local": local, "detail": "远端 manifest 解析失败：%s" % e,
                           "next": "确认仓库内 main 分支存在合法 manifest.json"}, args.quiet)
        c = update_mod.compare(local, remote)
        if c > 0:
            detail, nxt = "有新版本 %s → %s" % (local, remote), "gh.py update --apply --yes"
        elif c == 0:
            detail, nxt = "已是最新（%s）" % local, None
        else:
            detail, nxt = "本地（%s）比远端（%s）新——可能是开发副本" % (local, remote), None
        return finish({"action": "update.check", "ok": True, "update_available": c > 0,
                       "local": local, "remote": remote, "ref": ref,
                       "url": update_mod.REPO_URL, "channel": r.get("channel"),
                       "third_party": r.get("third_party"),
                       "elapsed": round(time.perf_counter() - t0, 2),
                       "detail": detail, "next": nxt, "tried": tried}, args.quiet)
    if args.apply:
        if not args.yes:
            # 先过授权门，再谈干活：替换包文件属重活，未授权一概不做
            return finish({"action": "update.apply", "ok": False, "need_confirm": True,
                           "detail": "更新会替换本技能包文件：加 --yes 后才执行（写前自动备份、可回滚）",
                           "next": "gh.py update --apply --yes（或由用户批准后重跑）"}, args.quiet, 2)
        url = update_mod.zip_url(ref)
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = home / "update" / ("dl-%s.zip" % ts)
        work = home / "update" / ("tmp-" + ts)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        tried = []
        r = _http_via_chain(url, dest, chain, bud, routes, tried)
        if not r:
            return finish({"action": "update.apply", "ok": False, "url": url, "ref": ref,
                           "detail": "归档下载失败", "tried": tried,
                           "next": "gh.py diag 看环境事实；或手动从 %s 下载替换" % update_mod.REPO_URL},
                          args.quiet)
        try:
            local = update_mod.local_version(PKG)
            staged = update_mod.stage_zip(dest, work)
            newv = update_mod.local_version(staged)
            backup_dir = update_mod.backup(PKG, home)
            changes = update_mod.apply_staged(staged, PKG)
            update_mod.record(home, {"time": ts, "ref": ref, "from": local, "to": newv,
                                     "backup": str(backup_dir), "channel": r.get("channel")})
        except Exception as e:
            return finish({"action": "update.apply", "ok": False, "ref": ref,
                           "detail": "应用失败（现有包未被改动前已尽力备份）：%s" % e,
                           "next": "gh.py update --rollback 可恢复到最近备份"}, args.quiet)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return finish({"action": "update.apply", "ok": True, "from": local, "to": newv,
                       "ref": ref, "backup": str(backup_dir), "changes": changes,
                       "channel": r.get("channel"), "third_party": r.get("third_party"),
                       "elapsed": round(time.perf_counter() - t0, 2),
                       "detail": "已更新并备份；验证：gh.py routes --check；后悔药：gh.py update --rollback",
                       "tried": tried}, args.quiet)
    return finish({"action": "update", "ok": False,
                   "detail": "用 --check / --apply --yes / --rollback（本技能从不自检更新：仅此命令出网）"},
                  args.quiet, 3)


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
    p.add_argument("--exclude", help="排除通道（逗号分隔，如 mirror,cdn；与 --force 互斥）")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("git", help="包裹 git（环境守卫 + 预算 + 降级；写操作不经 mirror）", parents=[common])
    p.add_argument("git_args", nargs=argparse.REMAINDER)
    p.add_argument("--cwd")
    p.add_argument("--deadline", type=float, help="整体时间预算（秒）")
    p.add_argument("--force", help="只走指定通道（排障/验收用；写操作禁 mirror）")
    p.add_argument("--exclude", help="排除通道（逗号分隔；与 --force 互斥）")
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

    p = sub.add_parser("update", help="更新层：检测/应用/回滚（仅显式调用，从不自检）", parents=[common])
    p.add_argument("--check", action="store_true", help="只读检测：拉远端 manifest 比版本")
    p.add_argument("--apply", action="store_true", help="下载并应用更新（需 --yes；自动备份可回滚）")
    p.add_argument("--rollback", action="store_true", help="回滚到最近一次更新前备份")
    p.add_argument("--yes", action="store_true", help="显式授权（--apply 必填）")
    p.add_argument("--ref", default=update_mod.DEFAULT_REF, help="更新的分支/标签（默认 main）")
    p.add_argument("--deadline", type=float)
    p.set_defaults(func=cmd_update)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
