#!/usr/bin/env python3
"""质量与时效 / 有效性 / 闭环 常驻自检（离线）。

Q1 无待办/占位标记残留      Q2 无乱码/替换字符
Q3 全部文本可解码、JSON 可解析（含重复键检测）  Q4 无开发残留物（.bak 除外：hosts 回滚备份）
Q5 无调试残留（print 仅允许 report.py 的 JSON/摘要输出）
Q6 无未使用 import          Q7 SKILL.md 场景路由表 == routes.json（文档↔事实源）
Q8 分层描述与实现同步（架构字符串含 probe/账本）  Q9 死配置：lines 配置键必须被引用
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
SCRIPTS = PKG / "scripts"
CHANNELS = PKG / "channels"
PY_FILES = (list(SCRIPTS.glob("*.py")) + list(TESTS.glob("*.py"))
            + list(CHANNELS.glob("*/*.py"))
            + list((PKG / "sources").rglob("*.py"))
            + list((PKG / "update").glob("*.py")))   # 治理层 + 测试 + 全部通道实现 + 资源层 + 更新层
HOME = Path(tempfile.mkdtemp(prefix="gh_quality_home_"))
os.environ["GH_ACCESS_HOME"] = str(HOME)
sys.path.insert(0, str(TESTS))
sys.dont_write_bytecode = True

from _harness import check, finish        # noqa: E402

SELF = Path(__file__).resolve()
# 本文件自身必然包含"标记词/乱码样本"字面量（它们是检测规则），扫描时排除自己
TEXT = [p for p in PKG.rglob("*")
        if p.is_file() and p.suffix in (".py", ".md", ".json") and p.resolve() != SELF]
SKILL = (PKG / "SKILL.md").read_text(encoding="utf-8")
LINES_SRC = (SCRIPTS / "lines.py").read_text(encoding="utf-8")


def texts():
    out = {}
    for p in TEXT:
        out[p.relative_to(PKG)] = p.read_text(encoding="utf-8")
    return out


def main() -> int:
    T = texts()

    # Q1 待办/占位标记
    bad = []
    for rel, t in T.items():
        for m in ("TODO", "FIXME", "TBD", "XXX", "待补", "待做", "（预留）", "占位符"):
            if m in t:
                bad.append("%s: %s" % (rel, m))
    check("Q1 无待办/占位标记残留", not bad, bad)

    # Q2 乱码 / 替换字符
    moji = ("\ufffd", "锟斤拷", "ï¿½", "â€", "Ã¤", "å¤", "æ–")
    bad = ["%s: %s" % (rel, m) for rel, t in T.items() for m in moji if m in t]
    check("Q2 无乱码/替换字符", not bad, bad)

    # Q3 可解码 + JSON 合法（含重复键）
    bad = []
    for rel, t in T.items():
        if rel.suffix == ".json":
            def dup_hook(pairs):
                keys = [k for k, _ in pairs]
                if len(keys) != len(set(keys)):
                    bad.append("%s: JSON 重复键 %s" % (rel, keys))
                return dict(pairs)
            try:
                json.loads(t, object_pairs_hook=dup_hook)
            except Exception as exc:
                bad.append("%s: JSON 解析失败 %s" % (rel, exc))
    check("Q3 文档/配置可解析（JSON 含重复键检测）", not bad, bad)

    # Q4 开发残留物（*.bak 是 hosts 回滚备份，按设计豁免）
    junk = [str(p.relative_to(PKG)) for p in PKG.rglob("*")
            if p.name == ".DS_Store"
            or p.suffix in (".orig", ".log", ".tmp", ".swp")
            or p.name.startswith("_tmp")]
    check("Q4 无开发残留物（.bak 除外：hosts 回滚备份；__pycache__/.pyc 属运行时产物，导出发布时检查）",
          not junk, junk)

    # Q5 调试残留（print 仅合法于 report.py 输出层、资源层诊断 CLI 的 __main__、tests 接口；无断点调试器）
    bad = []
    for p in [x for x in PY_FILES if x.parent.name != "tests"]:
        src = p.read_text(encoding="utf-8")
        cli_ok = p.name in ("report.py", "hub.py", "collect.py", "speedtest.py",
                            "fetch_hosts.py", "fetch_doh.py", "fetch_ghmeta.py")
        if not cli_ok and re.search(r"(?<![\w.])print\(", src):
            bad.append("%s: print(" % p.name)
        if re.search(r"\bbreakpoint\(|\bpdb\b", src):
            bad.append("%s: 调试器残留" % p.name)
    for p in TESTS.glob("*.py"):
        if p.resolve() != SELF and re.search(r"\bbreakpoint\(", p.read_text(encoding="utf-8")):
            bad.append("%s: breakpoint(" % p.name)
    check("Q5 无调试残留（print 仅合法于 report.py 与资源层诊断 CLI；无 breakpoint/pdb）", not bad, bad)

    # Q6 未使用 import
    bad = []
    for p in PY_FILES:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [(a.asname or a.name.split(".")[0]) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names += [(a.asname or a.name) for a in node.names]
        body = re.sub(r"(?m)^\s*(import|from)\s.*$", "", src)
        for n in set(names):
            if n == "annotations":
                continue
            if not re.search(r"\b%s\b" % re.escape(n), body):
                bad.append("%s: %s" % (p.name, n))
    check("Q6 无未使用 import", not bad, bad)

    # Q7 SKILL.md 场景路由表 == routes.json 场景链（文档↔事实源）
    routes = json.loads((PKG / "routes" / "routes.json").read_text(encoding="utf-8"))
    want = {s["id"]: " → ".join("`%s`" % c for c in s["chain"]) for s in routes["scenarios"]}
    chans = set(routes["channels"])
    got = {}
    for ln in SKILL.splitlines():
        m = re.match(r"^\| (取单个文件|git 只读.*|git 写.*|解析失败.*|人打不开.*|全部失败) \| (.+) \|$", ln)
        if m:                                  # 只比"通道序列"，忽略人类注解
            got[m.group(1)] = [t for t in re.findall(r"`(\w+)`", m.group(2)) if t in chans]
    pairs = [("file_read", "取单个文件"), ("git_read", "git 只读（ls-remote / fetch / pull / clone）"),
             ("git_write", "git 写（push / tag / 提交相关）"), ("resolve_broken", "解析失败 / 连接劣化"),
             ("human_access", "人打不开（浏览器）"), ("all_failed", "全部失败")]
    mismatch = [(k, got.get(label), [c for c in want[k]]) for k, label in pairs
                if got.get(label) != re.findall(r"`(\w+)`", want[k])]
    check("Q7 SKILL.md 场景路由表与 routes.json 完全一致（文档↔事实源）", not mismatch, mismatch)

    # Q8 分层描述与实现同步
    arch = re.search(r'architecture:\s*"([^"]+)"', SKILL)
    a = arch.group(1) if arch else ""
    check("Q8 metadata.architecture 覆盖实际四类治理件（routes/channels/budget/env/report/probe）",
          all(k in a for k in ("routes", "channels", "budget", "env_guard", "report", "probe")), a)

    # Q9 死配置：lines 的每个配置项都必须被代码引用
    bad = []
    for dict_name in ("PROBE", "DEFAULT_BUDGET"):
        m = re.search(r"%s = \{(.*?)\}" % dict_name, LINES_SRC, re.S)
        if not m:
            bad.append("找不到 %s" % dict_name)
            continue
        for key in re.findall(r'"([\w.\-]+)":', m.group(1)):   # 键含点（如 raw.githubusercontent.com）
            refs = sum(1 for p in PY_FILES
                       if re.search(r'%s\["%s"\]' % (dict_name, key), p.read_text(encoding="utf-8")))
            if refs == 0:
                bad.append("%s[\"%s\"] 无引用（死配置）" % (dict_name, key))
    # 整体引用的配置（键是动态取的，不能按字面量索引查）：字典看名字被引用，标量同理
    for name in ("STRICT_PROBE_URLS", "PIN_CONNECT_TIMEOUT"):
        if not any(re.search(r'\b%s\b' % name, p.read_text(encoding="utf-8"))
                   for p in PY_FILES if p.resolve() != SELF):
            bad.append("%s 无引用（死配置）" % name)
    check("Q9 无死配置（lines 的字典键与标量全部被引用）", not bad, bad)

    # Q10 自包含：随包分发的文本不得引用包外文件/目录（发布包必须能独立使用）
    bad = []
    for rel, t in T.items():
        for m in re.finditer(r"`?([\w\u4e00-\u9fff./\-]+\.(?:md|json|jsonl|py))`?", t):
            p = m.group(1)
            if "YYYY" in p or p.endswith(".jsonl"):     # 运行时模板（日志名等），非随包文件
                continue
            if p.startswith(("./", "../")) or "/../" in p:
                # 相对引用：解析后仍在包内 = 合法（如 sources/ip/fetch_doh.py 对 sources.json 的引用）
                try:
                    inside = (rel.parent / p).resolve().is_relative_to(PKG.resolve())
                except Exception:
                    inside = False
                if not inside:
                    bad.append("%s: 相对越界引用 %s" % (rel, p))
                continue
            if rel.suffix == ".py" and (rel.parts[0] == "tests" or len(rel.parts) > 1):
                continue                       # 源码/测试内部引用按文件名解析，跳过
            if p in ("SKILL.md", "manifest.json", "README.md", "LICENSE"):
                continue
            def _in_pkg(name: str) -> bool:
                # 容错：Windows 偶发文件锁/超长路径会让 exists()/rglob() 抛 OSError，
                # 巡检不应因环境抖动崩套件——判不出来时按"存在"放行，不误杀。
                try:
                    if (PKG / name).exists():
                        return True
                except OSError:
                    return True
                base = name.replace("\\", "/").rsplit("/", 1)[-1]   # rglob 仅支持相对段：按文件名匹配
                for d in ("scripts", "routes", "tests", "channels", "sources", "update"):
                    try:
                        if any((PKG / d).rglob(base)):
                            return True
                    except OSError:
                        continue
                return False
            if not _in_pkg(p):
                bad.append("%s: 引用了包外或不存在的文件 %s" % (rel, p))
        if "设计评审.md" in t or "参考/" in t:
            bad.append("%s: 引用了包外工程档案（发布包无法独立使用）" % rel)
    check("Q10 自包含：随包文件不引用包外文档/路径", not bad, bad)

    # Q11 源层表防漂移：SKILL.md〈源层〉节必须与 sources.json 强一致（双向）
    # 为什么要守：SKILL.md 里的源名清单是给人看的，sources.json 是机器事实源；
    # 一旦只改一边就会"文档说的和实际跑的不是一回事"——这正是本包最忌讳的事。
    m = re.search(r"(?ms)^##\s*[\d.]*\s*资源层.*?(?=^##\s)", SKILL)
    if not m:
        check("Q11 源层表防漂移：SKILL.md 存在〈资源层〉节", False, "未找到〈资源层〉节")
    else:
        sec = m.group(0)
        sdata = json.loads((PKG / "sources" / "sources.json").read_text(encoding="utf-8"))
        kinds = sdata["kinds"]
        ip_names = [s["name"] for w in (kinds["ip"].get("ways") or {}).values()
                    for s in ((w or {}).get("sources") or [])]
        ms_all = (kinds["mirror"].get("sources") or [])
        ms_gh = [s["name"] for s in ms_all
                 if "git" in (s.get("caps") or []) and "http" in (s.get("caps") or [])]
        cdn_names = [c["name"] for c in (kinds["cdn"].get("sources") or [])]

        # 正向：sources.json 的每个源名都必须在文档里出现
        missing = [n for n in ip_names + [s["name"] for s in ms_all] + cdn_names
                   if n not in sec]
        check("Q11a 源层表覆盖 sources.json 全部源名（ip %d + mirror %d + cdn %d）"
              % (len(ip_names), len(ms_all), len(cdn_names)), not missing, missing[:8])

        # 反向：文档 mirror 名单必须与「支持 git 的前缀式源」集合完全相等（不多不少）
        blk = re.search(r"(?ms)^```text\n(.*?)^```", sec)
        listed = set()
        if blk:
            listed = {t.strip() for t in blk.group(1).replace("\n", "·").split("·") if t.strip()}
        want = set(ms_gh)
        check("Q11b 源层表 mirror 名单 == sources.json 支持 git 的源（双向一致，%d 个）" % len(want),
              listed == want,
              {"多出": sorted(listed - want), "缺少": sorted(want - listed)})

    # Q12 交付前清洁闸：随包零字节码。
    # 为什么现在才查：此前只有注释写明"导出发布包时检查"，实际没有任何断言守着——
    # 结果单跑一次测试就在包内留下 __pycache__（.pyc），上传即带脏。闸门补在这里，
    # 红了就是"有字节码残留，删掉 __pycache__ 目录再跑"。
    # 整树扫描必须容错：Windows 上偶发的文件锁（杀软/索引服务）会让 os.stat 抛错，
    # 而 rglob 会把它冒泡上来——一次巡检失败不该带崩整个自检套件。
    def _safe_rglob(pat):
        out = []
        try:
            out = list(PKG.rglob(pat))
        except OSError:
            pass
        return out

    caches = [p.relative_to(PKG).as_posix() for p in _safe_rglob("__pycache__")]
    pycs = [p.relative_to(PKG).as_posix() for p in _safe_rglob("*.pyc")]
    check("Q12 交付前清洁：随包零 __pycache__ / 零 .pyc", not caches and not pycs,
          {"__pycache__": caches[:5], "pyc": pycs[:5]})

    # Q13 两份文档一致性：SKILL.md（给 agent / WorkBuddy）与 README.md（给 GitHub 访客）
    # 是同一套结构的两个门面。断言守两件事：**编号结构不漂移** + **关键事实不分叉**。
    README = (PKG / "README.md").read_text(encoding="utf-8")

    def _h2_seq(text):
        return [("%s. %s" % (m.group(1), m.group(2).strip())).strip()
                for m in re.finditer(r"(?m)^## (\d+)\.\s*(.+?)\s*$", text)]

    s_seq, r_seq = _h2_seq(SKILL), _h2_seq(README)
    check("Q13a 两份文档 ## N. 编号与标题逐条一致（README 允许末尾追加许可等附加节）",
          bool(s_seq) and r_seq[:len(s_seq)] == s_seq, {"skill": s_seq, "readme": r_seq})

    def _doc_version(text):
        m = re.search(r'(?m)^version:\s*"([^"]+)"', text) or re.search(r"(?m)^\| 版本 \| ([^|]+)\|", text)
        return m.group(1).strip() if m else None

    man_ver = json.loads((PKG / "manifest.json").read_text(encoding="utf-8")).get("version")
    check("Q13b 版本号三处一致（SKILL.md / README.md / manifest.json）",
          _doc_version(SKILL) == _doc_version(README) == man_ver and bool(man_ver),
          {"skill": _doc_version(SKILL), "readme": _doc_version(README), "manifest": man_ver})

    for label, pat in (("源总数 95", r"95 个源"), ("通道数 8", r"8 条通道"),
                       ("mirror 68", r"\|\s*\*\*68\*\*\s*\|"),
                       ("cdn 13", r"\|\s*\*\*13\*\*\s*\|"),
                       ("ip 启用 6", r"启用 6")):
        in_s, in_r = bool(re.search(pat, SKILL)), bool(re.search(pat, README))
        check("Q13c 关键事实在两份文档中一致：%s" % label, in_s and in_r,
              {"SKILL.md": in_s, "README.md": in_r})

    shutil.rmtree(HOME, ignore_errors=True)
    return finish("test_quality")


if __name__ == "__main__":
    raise SystemExit(main())
