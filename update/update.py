#!/usr/bin/env python3
"""github-web-skill · 更新层（仅显式调用——本技能从不自检更新，无后台/定时检查）。

职责：版本比较 / 归档 staging 校验 / 备份 / 原地应用 / 回滚 / 记录。
出网动作（拉远端 manifest、拉 codeload 归档）由 gh.py 的 cmd_update 经自有通道链完成，
本模块保持纯逻辑、可离线单测。

更新地址：https://github.com/18875216268/github-web-skill
（远端 main 分支的 manifest.json 为版本事实源）
"""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

REPO = "18875216268/github-web-skill"
REPO_URL = "https://github.com/" + REPO
DEFAULT_REF = "main"


def raw_manifest_url(ref: str = DEFAULT_REF) -> str:
    """远端版本事实源：main 分支 manifest.json（raw 有分钟级缓存滞后）。"""
    return "https://raw.githubusercontent.com/%s/%s/manifest.json" % (REPO, ref)


def zip_url(ref: str = DEFAULT_REF) -> str:
    """整包归档：codeload zip 快照（无 git 历史，普通 HTTP 可取）。"""
    return "https://codeload.github.com/%s/zip/refs/heads/%s" % (REPO, ref)


# ---------------------------------------------------------------- 版本
def parse_version(v: str) -> tuple:
    """'2.1.0' → (2,1,0)；非数字段取其中的数字、无数字按 0——保证比较永不抛异常。"""
    out = []
    for part in str(v).strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def compare(local: str, remote: str) -> int:
    """远端>本地 → 1（有更新）；相等 → 0；远端<本地 → -1（本地是开发副本）。位数不齐补零。"""
    a, b = parse_version(local), parse_version(remote)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return (b > a) - (b < a)


def manifest_bytes_version(data: bytes) -> str:
    return str(json.loads(data.decode("utf-8")).get("version", "")).strip()


def local_version(pkg: Path) -> str:
    return manifest_bytes_version((pkg / "manifest.json").read_bytes())


# ---------------------------------------------------------------- staging
def stage_zip(zip_path: Path, work: Path) -> Path:
    """解压到 work/staged 并校验；返回暂存包根目录（含 manifest.json）。

    校验（不过一律拒绝，绝不触碰现有包）：
    ① zip 路径穿越防护（拒绝绝对路径与 ..）；② 必须存在 manifest.json；
    ③ manifest.name 必须是 github-web-skill（防错包）。
    """
    staged = Path(work) / "staged"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        for m in zf.infolist():
            name = m.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("归档含不安全路径，拒绝应用：%s" % name)
        zf.extractall(staged)
    root = staged
    if not (root / "manifest.json").is_file():
        subs = [d for d in root.iterdir() if d.is_dir()]
        if len(subs) == 1 and (subs[0] / "manifest.json").is_file():
            root = subs[0]                       # codeload 归档：单顶层目录 github-web-skill-<ref>
        else:
            raise ValueError("暂存包缺 manifest.json，拒绝应用")
    mf = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if mf.get("name") != REPO.split("/")[1]:
        raise ValueError("归档不是 github-web-skill（name=%s），拒绝应用" % mf.get("name"))
    return root


# ---------------------------------------------------------------- 备份 / 应用 / 回滚
def backup(pkg: Path, home: Path) -> Path:
    """把当前包整体备份到 用户区/update/backup/<时间戳>/，返回备份目录。"""
    dest = Path(home) / "update" / "backup" / time.strftime("%Y%m%d-%H%M%S")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(pkg, dest)
    return dest


def apply_staged(staged: Path, pkg: Path) -> dict:
    """原地应用：新文件覆盖 + 包内多余文件删除 + 空目录清理。只动 pkg 内部，返回变更统计。"""
    staged, pkg = Path(staged).resolve(), Path(pkg).resolve()
    new_files = {p.relative_to(staged) for p in staged.rglob("*") if p.is_file()}
    old_files = ({p.relative_to(pkg) for p in pkg.rglob("*") if p.is_file()}
                 if pkg.is_dir() else set())
    added = updated = removed = 0
    for rel in sorted(new_files):
        dst = pkg / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged / rel, dst)
        if rel in old_files:
            updated += 1
        else:
            added += 1
    for rel in sorted(old_files - new_files):
        (pkg / rel).unlink()
        removed += 1
    for d in sorted((p for p in pkg.rglob("*") if p.is_dir()),
                    key=lambda p: len(p.parts), reverse=True):
        if d != pkg:
            try:
                d.rmdir()                        # 仅成功删除空目录；非空自然跳过
            except OSError:
                pass
    return {"added": added, "updated": updated, "removed": removed}


def record(home: Path, data: dict) -> Path:
    f = Path(home) / "update" / "last.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f


def last_record(home: Path) -> dict | None:
    f = Path(home) / "update" / "last.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_backup(home: Path) -> Path | None:
    d = Path(home) / "update" / "backup"
    if not d.is_dir():
        return None
    subs = sorted(x for x in d.iterdir() if x.is_dir())
    return subs[-1] if subs else None


def restore_from_backup(pkg: Path, home: Path) -> dict:
    """回滚：优先按 last.json 记录的备份恢复；否则取最新时间戳备份。"""
    home = Path(home)
    rec = last_record(home) or {}
    cand = rec.get("backup")
    src = Path(cand) if cand and Path(cand).is_dir() else latest_backup(home)
    if not src:
        return {"ok": False, "detail": "没有可用备份，无法回滚"}
    r = apply_staged(src, pkg)
    return {"ok": True, "backup": str(src), **r,
            "detail": "已从备份恢复（%s）；再次更新可直接 update --apply --yes" % Path(src).name}
