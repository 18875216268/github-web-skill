#!/usr/bin/env python3
"""规范合规 + 三向一致性审计（离线，可复跑）。

覆盖四组：
  A 规范合规：SKILL.md frontmatter（name/description/license/compatibility/metadata）、目录同名、官方 skills-ref（套件形态：临时以 SKILL.md 校验）
  B 文档↔代码：通道文件与入口函数、子命令、环境变量、退出码、清单层级/域名、场景↔CLI 映射、ROUTES 无漂移
  C 代码↔代码：全部可编译、预算透传、运行期零写包
  D 健壮性：缓存损坏、hosts 缺失、未知通道、非 https、routes 校验
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import types
from argparse import Namespace
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
SCRIPTS = PKG / "scripts"
HOME = Path(tempfile.mkdtemp(prefix="gh_audit_home_"))
os.environ["GH_ACCESS_HOME"] = str(HOME)          # 隔离用户区，不污染真实 ~/.github-access

sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True

from _harness import check, finish        # noqa: E402
import _harness                           # noqa: E402
import channel_cdn                        # noqa: E402
import channel_direct                     # noqa: E402
import channel_hosts                      # noqa: E402
import channel_mirror                     # noqa: E402
import channel_pin                        # noqa: E402
import gh# noqa: E402
import probe                              # noqa: E402
import lines                              # noqa: E402
import env_guard                          # noqa: E402


def _load_src(name: str, rel: str):
    """按包相对路径加载资源层模块（sources/ 无包结构，路径加载）。"""
    return _harness.load_module(name, PKG / rel)

SKILL = (PKG / "SKILL.md").read_text(encoding="utf-8")
FM = SKILL.split("---")[1] if SKILL.startswith("---") else ""
GH_SRC = (SCRIPTS / "gh.py").read_text(encoding="utf-8")


def fm(key):
    m = re.search(r"(?m)^%s:\s*(.+)$" % re.escape(key), FM)
    return m.group(1).strip().strip('"') if m else None


def meta_map():
    block = FM.split("metadata:", 1)[1] if "metadata:" in FM else ""
    out = {}
    for ln in block.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def tree():
    return sorted("%s:%s" % (p.relative_to(PKG), p.stat().st_mtime_ns)
                  for p in PKG.rglob("*") if p.is_file())


def main() -> int:
    routes = gh.load_routes()
    man = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    meta = meta_map()

    # ---------------- A 规范合规 ----------------
    name, desc = fm("name"), fm("description")
    mounted = PKG.parent.name == "assets" and PKG.parent.parent.name == "library"
    if mounted:   # 挂载态：目录名由宿主分配（≠资产名）→ 规范同名校验不适用，记通过并注明
        check("A1 name 与目录同名（挂载态：目录名由宿主分配 → 跳过）", True,
              "挂载目录 = %s ｜ name = %s" % (PKG.name, name))
    else:
        check("A1 name 与目录同名", name == PKG.name, "%s / %s" % (name, PKG.name))
    check("A2 name 合规（小写+连字符、≤64、无首尾/连续连字符）",
          bool(name) and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) is not None and len(name) <= 64, name)
    check("A3 description 非空且 ≤1024 字符", bool(desc) and 0 < len(desc) <= 1024, len(desc or ""))
    check("A3b description 含关键词与「何时用」语义",
          bool(desc) and len(desc) > 40 and any(k in desc for k in ("当", "使用", "适用", "Use when")),
          (desc or "")[:40])
    check("A4 license 已声明", fm("license") == "MIT", fm("license"))
    comp = fm("compatibility")
    check("A5 compatibility 已声明且 ≤500", bool(comp) and len(comp) <= 500, len(comp or ""))
    vals = list(meta.values())
    check("A6 metadata 全为字符串值（引号包裹）",
          bool(vals) and all(v.startswith('"') and v.endswith('"') for v in vals), vals)
    check("A6b 平台 schema：version/display_name/display_name_en/description_zh/description_en 顶层齐备",
          all(fm(k) for k in ("version", "display_name", "display_name_en",
                              "description_zh", "description_en")),
          {k: fm(k) for k in ("version", "display_name", "display_name_en")})
    # 上限 200：维护者 2026-10-03 定——人类向简介要覆盖足量症状关键词（打不开/屏蔽/代理…），
    # 短到 160 会逼得砍掉真实检索词。上限只防"失控变成长文"，不卡字数。
    check("A6c 展示分工：description_zh/en 为人类向简介（≠description 路由长文，长度适中）",
          fm("description_zh") != desc and 20 < len(fm("description_zh") or "") <= 200
          and fm("description_en") != desc and 20 < len(fm("description_en") or "") <= 300,
          {"zh": len(fm("description_zh") or ""), "en": len(fm("description_en") or "")})
    check("A7 SKILL.md 正文 < 500 行（渐进披露）", len(SKILL.splitlines()) < 500, len(SKILL.splitlines()))
    lic = PKG / "LICENSE"
    check("A9 发布件齐全：LICENSE 文件存在且为 MIT（与 frontmatter 声明一致）",
          lic.exists() and "MIT License" in lic.read_text(encoding="utf-8"), fm("license"))
    _tmp = None
    PLATFORM_FIELDS = {"version", "display_name", "display_name_en",
                       "description_zh", "description_en", "triggers"}
    try:
        _tmp = Path(tempfile.mkdtemp(prefix="gh_spec_"))
        _pkg = _tmp / (name or PKG.name)          # 规范名（挂载态目录名≠资产名，校验须按规范名）
        shutil.copytree(PKG, _pkg)
        r = subprocess.run([sys.executable, "-m", "skills_ref.cli", "validate", str(_pkg)],
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        # A8 守门语义：WorkBuddy 平台要求的顶层扩展字段会被官方校验器拒绝——双规范并存的有意取舍；
        # 除这些已知平台字段外，任何其他违规仍视为失败。校验器输出可能被终端宽度折行 → 先折叠空白。
        flat = re.sub(r"\s+", " ", out)
        unexpected = set()
        for chunk in re.findall(r"Unexpected fields in frontmatter:\s*(.+?)\. Only\b", flat):
            unexpected |= {f.strip() for f in chunk.split(",") if f.strip()}
        others = re.sub(r"Unexpected fields in frontmatter:\s*.+?are allowed\.", "", flat)
        real = [s for s in (x.strip() for x in others.split("- "))
                if s and not s.startswith("Validation failed for")]
        check("A8 官方 skills-ref validate：除平台扩展字段外零违规（双规范并存取舍）",
              not (unexpected - PLATFORM_FIELDS) and not real,
              {"unexpected": sorted(unexpected - PLATFORM_FIELDS), "others": real[:5]})
    except Exception as exc:
        check("A8 官方 skills-ref validate 通过（规范形态 SKILL.md）", True,
              "未安装 skills_ref，跳过：%s" % str(exc)[:60])
    finally:
        if _tmp:
            shutil.rmtree(_tmp, ignore_errors=True)
    # A8a（本地稳定守门，不依赖外部 CLI）：frontmatter 顶层键 ⊆ 官方白名单 ∪ 平台扩展字段
    ALLOWED_KEYS = {"allowed-tools", "compatibility", "description", "license", "metadata", "name"}
    top_keys = {ln.split(":")[0].strip() for ln in FM.splitlines()
                if ln and not ln.startswith((" ", "\t", "-")) and ":" in ln}
    check("A8a frontmatter 顶层键 ⊆ 官方白名单 ∪ 平台扩展字段",
          top_keys <= ALLOWED_KEYS | PLATFORM_FIELDS,
          sorted(top_keys - ALLOWED_KEYS - PLATFORM_FIELDS))

    # ---------------- B 文档↔代码 ----------------
    expect = {"direct": ["http_get", "git_run"], "cdn": ["fetch", "build_urls"],
              "pin": ["http_get", "git_run", "verify_ips", "PinProxy"],
              "mirror": ["http_get", "git_run"], "hosts": ["status", "apply", "rollback"]}
    mods = {"direct": channel_direct, "cdn": channel_cdn, "pin": channel_pin,
            "mirror": channel_mirror, "hosts": channel_hosts}
    miss = []
    for ch, fns in expect.items():
        spec = routes["channels"].get(ch)
        if not spec or not spec.get("file"):
            miss.append("%s: 无文件声明" % ch)
            continue
        if not (PKG / spec["file"]).exists():      # file 为包相对路径（如 channels/pin/channel_pin.py）
            miss.append(spec["file"])
        miss += ["%s.%s" % (ch, fn) for fn in fns if not hasattr(mods[ch], fn)]
    check("B1/B2 通道文件存在且导出约定入口", not miss, miss)
    check("B2b offline 通道如实声明为无实现文件", routes["channels"]["offline"]["file"] is None)

    subs = set(re.findall(r"add_parser\(\"(\w+)\"", GH_SRC))
    # 只认ASCII 子命令名：子命令按argparse 约定必为 ASCII，中文散文里的"gh.py 为唯一"不该被当成子命令
    doc_subs = set(re.findall(r"gh\.py ([a-z]+)\b", SKILL))
    check("B3 SKILL.md 子命令 == argparse 子命令", subs == doc_subs and bool(subs),
          "code=%s doc=%s" % (sorted(subs), sorted(doc_subs)))

    # B4 扫描面 = 生产代码全包 .py（不只 scripts/，也不含 tests/ ——否则被测试自己的字面量自满足）
    all_py = (list(SCRIPTS.glob("*.py"))
              + list((PKG / "channels").glob("*/*.py"))
              + list((PKG / "sources").rglob("*.py"))
              + list((PKG / "update").glob("*.py")))
    used_vars = set()
    for f in all_py:
        src = f.read_text(encoding="utf-8")
        used_vars |= set(re.findall(r"""environ\.get\(["'](GH_[A-Z_]+)["']""", src))
        used_vars |= set(re.findall(r"""environ\[["'](GH_[A-Z_]+)["']\]""", src))
        used_vars |= set(re.findall(r"""getenv\(["'](GH_[A-Z_]+)["']""", src))
    check("B4 全包代码使用的 GH_* 变量都在 SKILL.md 有文档且属已知集合",
          bool(used_vars) and used_vars <= {"GH_ACCESS_HOME", "GH_HOSTS_FILE"}
          and all(v in SKILL for v in used_vars), sorted(used_vars))

    codes = set(re.findall(r"args\.quiet,\s*(\d)\)", GH_SRC))
    check("B5 退出码：实现确有显式码且 ⊆ {1,2,3}，文档列出 0/1/2/3",
          bool(codes) and codes <= {"1", "2", "3"}
          and all(x in SKILL for x in ("`0`", "`1`", "`2`", "`3`")), sorted(codes))

    check("B6 manifest.layers 路径全部存在",
          all((PKG / l["path"]).exists() for l in man["layers"]),
          [l["path"] for l in man["layers"] if not (PKG / l["path"]).exists()])
    check("B6b manifest.version == frontmatter version（顶层）",
          man["version"] == (fm("version") or ""), "%s / %s" % (man["version"], fm("version")))

    doms = set()
    for c in channel_cdn.SOURCES:
        doms.add(re.sub(r"^https?://", "", c["url"]).split("/")[0])
    for m in channel_mirror.SOURCES:
        doms.add(re.sub(r"^https?://", "", m["url"]).split("/")[0])
    # 资源层：sources.json 各节 url 域 + 全量探测域清单（hub --endpoints 同口径）
    sdata = json.loads((PKG / "sources" / "sources.json").read_text(encoding="utf-8"))
    for node in sdata["kinds"].values():
        for way in (node.get("ways") or {}).values():
            for it in (way or {}).get("sources") or []:
                u = str(it.get("url") or "")
                if u:
                    doms.add(re.sub(r"^https?://", "", u).split("/")[0])
        for it in node.get("sources") or []:
            u = str(it.get("url") or "")
            if u:
                doms.add(re.sub(r"^https?://", "", u).split("/")[0])
        doms |= set(node.get("domains") or [])
    allow = set(man["network"]["allow_domains"])
    check("B7 manifest 网络声明覆盖全部出网域（资源层三节+全量域清单）",
          doms <= allow, sorted(doms - allow))
    check("B7b manifest 声明了 --url 任意 https 能力", "--url" in man["network"].get("note", ""),
          man["network"].get("note", "")[:60])

    check("B8 每个场景都有 CLI 映射", all(s.get("cli") for s in routes["scenarios"]),
          [s["id"] for s in routes["scenarios"] if not s.get("cli")])
    check("B8b 三个可执行场景的 CLI 映射指向真实子命令",
          all(any(("gh.py " + sub) in s["cli"] for sub in subs) for s in routes["scenarios"][:3]),
          [s["cli"] for s in routes["scenarios"][:3]])
    check("B9 ROUTES.md 无漂移",
          (PKG / "routes" / "ROUTES.md").read_text(encoding="utf-8") == gh.render_routes(routes))

    # ---------------- C 代码↔代码 ----------------
    bad = []
    for f in (list(SCRIPTS.glob("*.py")) + list(TESTS.glob("*.py"))
              + list((PKG / "channels").glob("*/*.py")) + list((PKG / "channels").glob("*/*/*.py"))
              + list((PKG / "sources").rglob("*.py")) + list((PKG / "update").glob("*.py"))):
        try:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")   # 纯内存语法编译：不落字节码
        except SyntaxError as exc:
            bad.append("%s: %s" % (f.name, exc))
    check("C1 全部 .py 语法可编译（零字节码写入）", not bad, bad)
    check("C2 预算透传到统一分发处（get/git 各一处 budget=bud）",
          GH_SRC.count("budget=bud") >= 2, GH_SRC.count("budget=bud"))

    # C2b 并发原语唯一性：全包只允许 probe.race（守护线程）。非守护线程池（ThreadPoolExecutor）
    # 的 worker 会在 Python 退出时被 atexit join —— 曾导致 hub 的 deadline 形同虚设、
    # 进程退不出去（git 实测 334s vs 名义预算 180s）。此断言直接钉死根因。
    # 用 AST 判定**真实代码**（import / 属性访问），不扫注释与文档字符串——
    # 文档里写明"历史实现曾用 ThreadPoolExecutor"是合法留痕，不该被当成违规。
    import ast as _ast
    offenders = []
    for f in (list(SCRIPTS.glob("*.py")) + list((PKG / "channels").glob("*/*.py"))
              + list((PKG / "sources").rglob("*.py")) + list((PKG / "update").glob("*.py"))):
        try:
            _t = _ast.parse(f.read_text(encoding="utf-8"))   # 勿用 tree：会遮蔽模块级 tree()
        except SyntaxError:
            continue
        for node in _ast.walk(_t):
            if isinstance(node, _ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] == "concurrent":
                        offenders.append("%s: import %s" % (f.relative_to(PKG).as_posix(), a.name))
            elif isinstance(node, _ast.ImportFrom):
                if (node.module or "").split(".")[0] == "concurrent":
                    offenders.append("%s: from %s import" % (f.relative_to(PKG).as_posix(), node.module))
            elif isinstance(node, _ast.Attribute) and node.attr == "ThreadPoolExecutor":
                offenders.append("%s:%d 用 ThreadPoolExecutor"
                                 % (f.relative_to(PKG).as_posix(), node.lineno))
    check("C2b 并发原语唯一：生产代码禁用非守护线程池（只用 probe.race）",
          not offenders, offenders)
    check("C2c 资源层并发都走 probe.race（hub/collect/speedtest/fetch 全部归一）",
          all("probe.race" in (PKG / rel).read_text(encoding="utf-8")
              for rel in ("sources/hub.py", "sources/collect.py", "sources/speedtest.py",
                          "sources/ip/fetch_hosts.py", "sources/ip/fetch_doh.py")),
          [rel for rel in ("sources/hub.py", "sources/collect.py", "sources/speedtest.py",
                           "sources/ip/fetch_hosts.py", "sources/ip/fetch_doh.py")
           if "probe.race" not in (PKG / rel).read_text(encoding="utf-8")])

    before = tree()
    subprocess.run([sys.executable, str(SCRIPTS / "gh.py"), "routes", "--check"],
                   capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    after = tree()
    check("C3 运行期零写包（文件与 mtime 不变）", before == after, list(set(after) ^ set(before))[:5])

    # ---------------- D 健壮性 ----------------
    cache = HOME / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "sources.json").write_text("{ 坏 JSON", encoding="utf-8")
    (cache / "ip_good.json").write_text("[坏", encoding="utf-8")
    check("D1 账本损坏 → 排序/状态读取优雅降级（不抛异常）",
          probe.order(["a", "b"]) == ["a", "b"] and probe.state("a") == {})
    probe.record("a", True, 12.0, "post-corrupt")
    check("D1b 账本损坏后自愈（下一次记录即重建）", probe.state("a").get("ok_count") == 1,
          probe.state("a"))
    check("D1c 缓存损坏 → 好 IP 缓存优雅降级", channel_pin._load_good() == {})

    os.environ["GH_HOSTS_FILE"] = str(HOME / "no-such-hosts")
    st = channel_hosts.status()
    check("D2 hosts 文件不存在 → 返回 ok=False 不抛异常", st.get("ok") is False and "detail" in st, st)
    os.environ.pop("GH_HOSTS_FILE", None)

    def cli(*args):
        p = subprocess.run([sys.executable, str(SCRIPTS / "gh.py"), *args],
                           capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "")

    rc, out = cli("get", "a/b:c", "--force", "bogus")
    check("D3 未知通道 → 退出码 3", rc == 3, out[:140])
    rc, out = cli("get", "--url", "http://example.com/x")
    check("D4 非 https 链接 → 退出码 3 且提示 https", rc == 3 and "https" in out, out[:140])
    rc, out = cli("routes", "--check")
    check("D5 routes --check 退出码 0", rc == 0, out[:140])

    # D6/D7 回归：git 子命令的 git_args 是 argparse.REMAINDER，会把 --cwd/--force/--deadline/--exclude
    # 一并吞进 git 参数列表。2026-10-03 实测：兜底解析器漏了 --cwd，导致
    #   gh.py git ls-remote origin HEAD --cwd <dir>   ← SKILL.md 文档教的写法
    # 把 --cwd 原样透传给 git → "unknown option" → rc=128，三通道全假失败。
    check("D6 cmd_git 兜底解析器必须剥离 --cwd（REMAINDER 会吞掉它）",
          '"--cwd"' in GH_SRC and "cwd = raw_args[i + 1]" in GH_SRC,
          "cmd_git 的 REMAINDER 兜底解析未处理 --cwd")

    cwd_dir = HOME / "cwdtest"
    cwd_dir.mkdir(parents=True, exist_ok=True)
    rc, out = cli("git", "init", "--cwd", str(cwd_dir), "--force", "direct")
    check("D7 --cwd 写在 git 参数之后依然生效（工作目录落到该目录）",
          rc == 0 and (cwd_dir / ".git").exists(), "rc=%s out=%s" % (rc, out[:140]))
    check("D7b --cwd 未被忽略（未在技能包目录里误建 .git）", not (PKG / ".git").exists(),
          "技能包目录被误建 .git，说明 --cwd 被忽略")

    os.environ["GH_HOSTS_FILE"] = str(HOME / "no_dir" / "hosts")
    r = channel_hosts.apply({"github.com": ["1.2.3.4"]}, confirmed=True)
    check("D6 hosts 写入不可达 → 干净报错并给出替代出路",
          r.get("ok") is False and bool(r.get("next") or r.get("detail")), r)
    check("D6b hosts 未授权 → need_confirm（不写盘）",
          channel_hosts.apply({"github.com": ["1.2.3.4"]}).get("need_confirm") is True)
    os.environ.pop("GH_HOSTS_FILE", None)

    check("D8 hosts 写入前用严格校验（真实小文件 + 2xx，防根路径假阳性）",
          hasattr(channel_pin, "verify_for_hosts") and "verify_for_hosts" in GH_SRC
          and "raw.githubusercontent.com" in getattr(lines, "STRICT_PROBE_URLS", {}), None)

    # D7 外部清单源（资源层 hosts_file）：失败不抛出、返回空（多源容错纪律）
    hfm = _load_src("hf", "sources/ip/fetch_hosts.py")
    name, got, detail = hfm._pull({"name": "t", "url": "https://127.0.0.1:1/hosts"})
    check("D7 外部清单源：失败不抛出、返回空", got == {} and "失败" in detail, detail)
    check("D7b hosts 行解析：标准行命中、坏行忽略",
          hfm.HOSTS_LINE.match("1.2.3.4 github.com") is not None
          and hfm.HOSTS_LINE.match("坏行 应当被忽略") is None, None)

    # 2026-09-28：__pycache__/.pyc 是本机运行时产物（跑 gh.py/tests 必生成）→ 移出开发自检；
    # 「随包零字节码」改在导出发布包时检查（export_release 流程）。
    check("C4 随包代码无静态残留（.orig/.log/.tmp/_tmp；tests/ 的缓存属开发侧不计）",
          not list(SCRIPTS.rglob("*.orig")) and not list(SCRIPTS.rglob("*.log"))
          and not list(SCRIPTS.rglob("*.tmp")) and not list(SCRIPTS.rglob("_tmp*")),
          [str(p.relative_to(PKG)) for p in list(SCRIPTS.rglob("*.orig")) + list(SCRIPTS.rglob("*.tmp"))][:3])

    # ---------------- E 行为断言（全离线）----------------
    # E1 env_guard：代理清理与 curl --noproxy 规则（pin 自建代理靠它不被误关）
    _saved_env = {k: os.environ.get(k) for k in env_guard.PROXY_KEYS}
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
    os.environ["https_proxy"] = "http://127.0.0.1:9"
    clean = env_guard.clean_env()
    check("E1a clean_env 剔净代理变量、不动父进程、保留 PATH",
          not any(k in clean for k in env_guard.PROXY_KEYS)
          and os.environ.get("HTTP_PROXY") == "http://127.0.0.1:9"
          and bool(clean.get("PATH")),
          sorted(k for k in clean if k.upper() in env_guard.PROXY_KEYS))
    check("E1b curl_base 默认挡代理（--noproxy）", "--noproxy" in env_guard.curl_base(5), None)
    check("E1c curl_base(allow_proxy=True) 不挡——否则会关掉 pin 自己的代理",
          "--noproxy" not in env_guard.curl_base(5, allow_proxy=True), None)
    for _k, _v in _saved_env.items():          # 复原，别给后续步骤留污染
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    check("E1d 复原后 proxy_state 回到原状（E1 不污染后续步骤）",
          all(os.environ.get(k) == v for k, v in _saved_env.items()), None)
    check("E1e git_config_prefix 含低速中止阈值",
          "http.lowSpeedLimit=1000" in " ".join(env_guard.git_config_prefix()), None)

    # E2 PinProxy：本地 CONNECT 代理真回环（全在 127.0.0.1，不出网）
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    srv_port = srv.getsockname()[1]
    _stop = threading.Event()

    def _acc():
        while not _stop.is_set():
            try:
                c, _a = srv.accept()
                c.close()
            except Exception:
                return

    threading.Thread(target=_acc, daemon=True).start()
    _px = channel_pin.PinProxy({"test.local": ["127.0.0.1"]})
    _pport = _px.start()
    try:
        _s = socket.create_connection(("127.0.0.1", _pport), timeout=4)
        _s.settimeout(4)
        _s.sendall(("CONNECT test.local:%d HTTP/1.1\r\n\r\n" % srv_port).encode())
        _resp = _s.recv(200)
        check("E2a PinProxy 对已钉域名回 200 Connection Established",
              _resp.startswith(b"HTTP/1.1 200"), _resp[:40])
        check("E2b used 记录本次实际连通的 {domain: ip}",
              _px.used.get("test.local") == "127.0.0.1", _px.used)
        _s.close()
        _s2 = socket.create_connection(("127.0.0.1", _pport), timeout=4)
        _s2.settimeout(4)
        _s2.sendall(b"GET / HTTP/1.1\r\n\r\n")
        check("E2c 非 CONNECT 请求被直接关闭（本代理只服务 CONNECT）",
              _s2.recv(200) == b"", None)
        _s2.close()
        # E2d/E2e 真验证"未钉住→走正常解析"分支：空候选表建代理，CONNECT 127.0.0.1:<仍监听的端口>
        _px2 = channel_pin.PinProxy({})
        _p2 = _px2.start()
        try:
            _s3 = socket.create_connection(("127.0.0.1", _p2), timeout=4)
            _s3.settimeout(4)
            _s3.sendall(("CONNECT 127.0.0.1:%d HTTP/1.1\r\n\r\n" % srv_port).encode())
            _r3 = _s3.recv(200)
            check("E2d 未钉住的域名走正常解析仍能 CONNECT 成功（不被代理拦死）",
                  _r3.startswith(b"HTTP/1.1 200"), _r3[:40])
            check("E2e 未钉住的域名不进 used（只有钉住映射才记账）",
                  "127.0.0.1" not in _px2.used, list(_px2.used))
            _s3.close()
        except Exception as _exc:
            check("E2d 未钉住的域名走正常解析仍能 CONNECT 成功", False, str(_exc)[:80])
        finally:
            _px2.stop()
    except Exception as _exc2:
        check("E2a PinProxy 回环可用", False, str(_exc2)[:80])
    finally:
        _px.stop()
        _stop.set()
        srv.close()
    # E3 _rotations：多轮传输级 failover 的候选顺序（防退化成"同一坏 IP 重试 N 次"）
    _rot = list(channel_pin._rotations({"d": ["a", "b", "c"]}, rounds=3))
    check("E3a 第 k 轮把第 k 个候选提到最前",
          [r["d"][0] for r in _rot] == ["a", "b", "c"], [r["d"] for r in _rot])
    check("E3b 每轮不丢候选（每候选恰好当首一次）",
          all(sorted(r["d"]) == ["a", "b", "c"] for r in _rot), _rot)
    check("E3c rounds 超过候选数时收敛（不生成空转轮次）",
          len(list(channel_pin._rotations({"d": ["a", "b"]}, rounds=9))) == 2, None)
    check("E3d 空候选域原样透传",
          list(channel_pin._rotations({"d": []}, rounds=3)) == [{"d": []}], None)

    # E4 _probe_ips：严格/弱判据差异（写系统 hosts 前的防假阳性闸门）
    _real_run = subprocess.run
    _code = {"v": "000"}

    class _P:
        stdout = ""
        stderr = ""
        returncode = 0

    def _fake_run(args, **kw):
        _P.stdout = _code["v"]
        return _P()

    subprocess.run = _fake_run
    try:
        _code["v"] = "404"
        _weak = channel_pin._probe_ips([("d", "1.1.1.1")], 3.0, strict={})
        _strict = channel_pin._probe_ips([("d", "1.1.1.1")], 3.0, strict={"d": "https://d/f"})
        check("E4a 弱判据：有 HTTP 响应即算存活（404 也算）", "d" in _weak, _weak)
        check("E4b 严格判据：非 2xx 一律不算存活（防根路径假阳性）", "d" not in _strict, _strict)
        _code["v"] = "200"
        check("E4c 严格判据：2xx 算存活",
              "d" in channel_pin._probe_ips([("d", "1.1.1.1")], 3.0, strict={"d": "https://d/f"}), None)
        _code["v"] = "000"
        check("E4d 000（完全不通）在弱判据下也不算存活",
              not channel_pin._probe_ips([("d", "1.1.1.1")], 3.0, strict={}), None)
    finally:
        subprocess.run = _real_run
    check("E4e verify_ips 走弱判据、verify_for_hosts 走严格判据（两者分立）",
          "弱判据" in (channel_pin.verify_ips.__doc__ or "")
          and "严格" in (channel_pin.verify_for_hosts.__doc__ or ""),
          (channel_pin.verify_ips.__doc__ or "")[:60])

    # E5 cmd_hosts --apply --yes：无存活 IP 时必须拒绝，且绝不调用 apply（不碰系统）
    _applied = []
    _hosts_stub = types.SimpleNamespace(
        apply=lambda pool, confirmed=False, flush=False: (_applied.append(pool), {"ok": True})[1],
        status=lambda: {"ok": True, "installed": False})
    _pin_stub = types.SimpleNamespace(
        fetch_ip_candidates=lambda: {"github.com": ["1.2.3.4"]},
        verify_for_hosts=lambda h, limit=2, timeout=6.0: {})
    _saved = (gh._CH["pin"], gh._CH["hosts"])
    gh._CH["pin"], gh._CH["hosts"] = _pin_stub, _hosts_stub
    try:
        _rc = gh.cmd_hosts(Namespace(status=False, rollback=False, apply=True, yes=True,
                                      flush=False, quiet=True))
        check("E5a 无存活 IP → 拒绝改hosts（ok=False）", _rc == 1, _rc)
        check("E5b 无存活 IP → 绝不调用 apply（系统 hosts 未被触碰）", not _applied, _applied)
    finally:
        gh._CH["pin"], gh._CH["hosts"] = _saved

    # E7 失败措辞如实：区分"预算不足没开始"与"试了 N 轮全败"（曾把没试说成 4 轮全败= 误判）
    check("E7a 预算不足、0 轮执行 → 明确说'未开始'，不说'N 轮全败'",
          channel_pin._fail_detail(0, 4, True) == "预算不足，未开始传输级 failover",
          channel_pin._fail_detail(0, 4, True))
    check("E7b 执行 2 轮全败（非预算）→ 如实报 2/4 轮",
          channel_pin._fail_detail(2, 4, False) == "2/4 轮传输级 failover 全败",
          channel_pin._fail_detail(2, 4, False))
    check("E7c 执行 2 轮后预算耗尽 → 报 2/4 且标注收口原因",
          channel_pin._fail_detail(2, 4, True) == "2/4 轮传输级 failover 全败（预算耗尽收口）",
          channel_pin._fail_detail(2, 4, True))
    _psrc = (PKG / "channels" / "pin" / "channel_pin.py").read_text(encoding="utf-8")
    check("E7d 源码里不再有硬编码的'%d 轮传输级 failover 全败'拼接",
          "%d 轮传输级 failover 全败" % 0 not in _psrc.replace("_fail_detail", ""), None)

    # E6 改名防回退：fetch_hosts → fetch_ip_candidates（曾漏改 2 个调用点导致 NameError）
    _pin_src = (PKG / "channels" / "pin" / "channel_pin.py").read_text(encoding="utf-8")
    check("E6a pin 模块不再暴露 fetch_hosts（已更名）",
          not hasattr(channel_pin, "fetch_hosts")
          and hasattr(channel_pin, "fetch_ip_candidates"),
          [a for a in dir(channel_pin) if "fetch" in a])
    check("E6b pin 源码内无 fetch_hosts( 残留调用（防改名漏改调用点）",
          "fetch_hosts(" not in _pin_src, None)
    check("E6c gh.py 侧也无 fetch_hosts 残留调用（模块改了名、调用方没改= 运行期 AttributeError）",
          "fetch_hosts" not in GH_SRC, None)
    check("E6d gh.py 实际调用的 pin 入口齐备",
          all(hasattr(channel_pin, a) for a in
              ("fetch_ip_candidates", "verify_for_hosts", "verify_ips",
               "http_get", "git_run")),
          [a for a in ("fetch_ip_candidates", "verify_for_hosts", "verify_ips",
                       "http_get", "git_run") if not hasattr(channel_pin, a)])

    shutil.rmtree(HOME, ignore_errors=True)
    return finish("test_spec_and_docs")


if __name__ == "__main__":
    raise SystemExit(main())
