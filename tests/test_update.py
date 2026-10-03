#!/usr/bin/env python3
"""更新层单测（离线，零出网）：版本比较 / staging 校验 / 备份→应用→回滚闭环 / 记录。"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.dont_write_bytecode = True      # 包内零运行态：不落 __pycache__
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "update"))

from _harness import check, finish  # noqa: E402
import update as u  # noqa: E402


def _mkzip(zpath: Path, top: str, files: dict):
    with zipfile.ZipFile(zpath, "w") as zf:
        for rel, content in files.items():
            zf.writestr("%s/%s" % (top, rel), content)


def main() -> int:
    # 1) 版本比较：含位数不齐、非数字段容错
    check("2.0.1 < 2.1.0 → 有更新", u.compare("2.0.1", "2.1.0") == 1)
    check("相等 → 已是最新", u.compare("2.1.0", "2.1.0") == 0)
    check("远端 < 本地 → 开发副本判定", u.compare("2.10.0", "2.9.9") == -1)
    check("位数不齐按补零比较", u.compare("2.0", "2.0.0") == 0)
    check("非数字段不抛异常", u.compare("2.0.1", "v2.1") in (1, 0, -1))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # 2) staging 校验
        z_ok = tmp / "ok.zip"
        _mkzip(z_ok, "github-web-skill-main", {
            "manifest.json": json.dumps({"name": "github-web-skill", "version": "2.1.0"}),
            "a.txt": "new", "b.txt": "b"})
        root = u.stage_zip(z_ok, tmp)
        check("归档解压并定位包根（单顶层目录）", (root / "manifest.json").is_file())
        check("暂存版本读取", u.local_version(root) == "2.1.0")

        z_nomani = tmp / "no_manifest.zip"
        _mkzip(z_nomani, "github-web-skill-main", {"README.md": "x"})
        try:
            u.stage_zip(z_nomani, tmp)
            bad = False
        except ValueError:
            bad = True
        check("缺 manifest.json 拒绝应用", bad)

        z_wrong = tmp / "wrong.zip"
        _mkzip(z_wrong, "other-main",
               {"manifest.json": json.dumps({"name": "other", "version": "9.9.9"})})
        try:
            u.stage_zip(z_wrong, tmp)
            bad = False
        except ValueError:
            bad = True
        check("非本技能包拒绝（防错包）", bad)

        # 3) 备份 → 应用 → 回滚闭环
        pkg = tmp / "pkg"
        pkg.mkdir()
        (pkg / "manifest.json").write_text(
            json.dumps({"name": "github-web-skill", "version": "2.0.1"}), encoding="utf-8")
        (pkg / "a.txt").write_text("old", encoding="utf-8")
        (pkg / "extra").mkdir()
        (pkg / "extra" / "x.txt").write_text("e", encoding="utf-8")
        home = tmp / "home"
        home.mkdir()
        bk = u.backup(pkg, home)
        check("备份生成且含原文件", (bk / "a.txt").is_file() and (bk / "manifest.json").is_file())

        r = u.apply_staged(u.stage_zip(z_ok, tmp), pkg)
        check("应用：版本更新", u.local_version(pkg) == "2.1.0")
        check("应用：旧文件被覆盖", (pkg / "a.txt").read_text(encoding="utf-8") == "new")
        check("应用：新增文件落位", (pkg / "b.txt").is_file())
        check("应用：包内多余文件删除", not (pkg / "extra").exists())
        check("应用：变更统计（added/updated/removed）",
              r == {"added": 1, "updated": 2, "removed": 1}, r)

        u.record(home, {"ref": "main", "from": "2.0.1", "to": "2.1.0", "backup": str(bk)})
        rr = u.restore_from_backup(pkg, home)
        check("回滚 ok 且指向备份", rr.get("ok") is True and rr.get("backup") == str(bk), rr)
        check("回滚：版本复原", u.local_version(pkg) == "2.0.1")
        check("回滚：被删目录复原", (pkg / "extra" / "x.txt").is_file())
        check("回滚：新增文件清除", not (pkg / "b.txt").exists())
        check("last.json 记录可读", (u.last_record(home) or {}).get("from") == "2.0.1")

        # 4) 无备份时回滚如实失败
        empty = tmp / "empty_home"
        empty.mkdir()
        check("无备份 → 回滚如实失败", u.restore_from_backup(pkg, empty).get("ok") is False)

    # 5) 本包 manifest 可读且更新地址 URL 生成正确
    check("本包版本可读", bool(u.local_version(TESTS.parent)))
    check("raw manifest URL", u.raw_manifest_url("main") ==
          "https://raw.githubusercontent.com/18875216268/github-web-skill/main/manifest.json")
    check("codeload zip URL", u.zip_url() ==
          "https://codeload.github.com/18875216268/github-web-skill/zip/refs/heads/main")
    return finish("test_update")


if __name__ == "__main__":
    raise SystemExit(main())
