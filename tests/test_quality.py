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
            if p.name in ("__pycache__", ".DS_Store")
            or p.suffix in (".pyc", ".orig", ".log", ".tmp", ".swp")
            or p.name.startswith("_tmp")]
    check("Q4 无开发残留物（.pyc/__pycache__/_tmp/日志/编辑器垃圾）", not junk, junk)

    # Q5 调试残留（print 仅合法于 report.py 的输出层；tests 的 PASS/FAIL 打印是其接口）
    bad = []
    for p in SCRIPTS.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        if p.name != "report.py" and re.search(r"(?<![\w.])print\(", src):
            bad.append("%s: print(" % p.name)
        if re.search(r"\bbreakpoint\(|\bpdb\b", src):
            bad.append("%s: 调试器残留" % p.name)
    for p in TESTS.glob("*.py"):
        if p.resolve() != SELF and re.search(r"\bbreakpoint\(", p.read_text(encoding="utf-8")):
            bad.append("%s: breakpoint(" % p.name)
    check("Q5 无调试残留（scripts 内仅 report.py 可 print；无 breakpoint/pdb）", not bad, bad)

    # Q6 未使用 import
    bad = []
    for p in list(SCRIPTS.glob("*.py")) + list(TESTS.glob("*.py")):
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

    # Q9 死配置：lines 配置字典的每个键都必须被代码引用
    bad = []
    for dict_name in ("CACHE_TTL", "PROBE", "DEFAULT_BUDGET"):
        m = re.search(r"%s = \{(.*?)\}" % dict_name, LINES_SRC, re.S)
        if not m:
            bad.append("找不到 %s" % dict_name)
            continue
        for key in re.findall(r'"(\w+)":', m.group(1)):
            refs = sum(1 for p in list(SCRIPTS.glob("*.py")) + list(TESTS.glob("*.py"))
                       if re.search(r'%s\["%s"\]' % (dict_name, key), p.read_text(encoding="utf-8")))
            if refs == 0:
                bad.append("%s[\"%s\"] 无引用（死配置）" % (dict_name, key))
    check("Q9 无死配置（lines 配置键全部被引用）", not bad, bad)

    # Q10 自包含：随包分发的文本不得引用包外文件/目录（发布包必须能独立使用）
    bad = []
    for rel, t in T.items():
        for m in re.finditer(r"`?([\w\u4e00-\u9fff./\-]+\.(?:md|json|jsonl|py))`?", t):
            p = m.group(1)
            if "YYYY" in p or p.endswith(".jsonl"):     # 运行时模板（日志名等），非随包文件
                continue
            if p.startswith(("./", "../")) or "/../" in p:
                bad.append("%s: 相对越界引用 %s" % (rel, p))
                continue
            if rel.suffix == ".py" and (rel.parts[0] == "tests" or len(rel.parts) > 1):
                continue                       # 源码/测试内部引用按文件名解析，跳过
            if p in ("SKILL.md", "manifest.json", "README.md", "LICENSE"):
                continue
            if not (PKG / p).exists() and not any((PKG / d / p).exists() for d in ("scripts", "routes", "tests")):
                bad.append("%s: 引用了包外或不存在的文件 %s" % (rel, p))
        if "设计评审.md" in t or "参考/" in t:
            bad.append("%s: 引用了包外工程档案（发布包无法独立使用）" % rel)
    check("Q10 自包含：随包文件不引用包外文档/路径", not bad, bad)

    shutil.rmtree(HOME, ignore_errors=True)
    return finish("test_quality")


if __name__ == "__main__":
    raise SystemExit(main())
