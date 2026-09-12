#!/usr/bin/env python3
"""真机只读冒烟：路由校验 + 各通道各跑一次（只读、不打系统改动）。

判据：命令返回 JSON 且字段自洽；**不做性能结论**（只记可用性事实与命中通道）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
GH = PKG / "scripts" / "gh.py"
sys.path.insert(0, str(TESTS))
from _harness import check, finish  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="gh_smoke_"))
REPO = "github/gitignore"


def run(args, timeout=180, env=None):
    p = subprocess.run([sys.executable, str(GH), *args], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace", env=env)
    try:
        data = json.loads(p.stdout)
    except Exception:
        data = None
    return p.returncode, data, (p.stdout or "")[-300:] + (p.stderr or "")[-300:]


def main() -> int:
    rc, data, raw = run(["routes", "--check"], timeout=60)
    check("routes --check 通过", rc == 0 and data and data.get("ok") is True, raw)

    rc, data, raw = run(["get", "%s:README.md" % REPO, "--dest", str(tmp / "a.md")], timeout=120)
    check("get（默认路由）成功且落盘",
          rc == 0 and data and data.get("ok") and (tmp / "a.md").exists()
          and (tmp / "a.md").stat().st_size > 0, raw)
    if data and data.get("ok"):
        check("get 报告了命中通道与是否第三方",
              bool(data.get("channel")) and "third_party" in data, data)

    rc, data, raw = run(["get", "%s:README.md" % REPO, "--dest", str(tmp / "b.md"), "--force", "cdn"],
                        timeout=90)
    check("get --force cdn 可用", rc == 0 and data and data.get("ok"), raw)

    # 判据与 git pin 一致：优先"成功"；线路全断时要求"干净失败 + tried 明细 + 下一步"（并显式告警）
    rc, data, raw = run(["get", "%s:README.md" % REPO, "--dest", str(tmp / "c.md"), "--force", "pin"],
                        timeout=120)
    note = ""
    if not (rc == 0 and data and data.get("ok")):
        note = "（第 1 次线路劣化，自动重试）"
        rc, data, raw = run(["get", "%s:README.md" % REPO, "--dest", str(tmp / "c.md"),
                             "--force", "pin"], timeout=120)
    ok = rc == 0 and data and data.get("ok")
    clean_fail = bool(data) and data.get("ok") is False and data.get("tried") and data.get("next")
    check("get --force pin：成功，或（线路全断时）干净失败 + tried 明细 + 下一步" + note,
          ok or clean_fail, raw)
    if not ok:
        print("  [告警] 本次未验到 pin 成功路径（线路瞬时劣化；机制已由 tried 明细验证）")

    rc, data, raw = run(["get", "%s:README.md" % REPO, "--dest", str(tmp / "d.md"), "--force", "mirror"],
                        timeout=120)
    check("get --force mirror 可用（第三方镜像，报告须标注）",
          rc == 0 and data and data.get("ok") and data.get("third_party"), raw)

    # git 类用例：进程超时必须 > 工具内部预算（git_read 180s），否则工具来不及输出 JSON 就被测试掐死
    rc, data, raw = run(["git", "ls-remote", "https://github.com/%s.git" % REPO, "HEAD"], timeout=240)
    check("git ls-remote（默认 direct）成功", rc == 0 and data and data.get("ok")
          and "HEAD" in (data.get("out") or ""), raw)

    # pin 的真机断言：优先"成功"；线路瞬时全断时，要求"干净失败 + tried 明细 + 下一步建议"
    #（本用例验证的是通道机制——取候选/存活校验/换线/报告，而不是某一次线路状态）
    rc, data, raw = run(["git", "ls-remote", "https://github.com/%s.git" % REPO, "HEAD",
                         "--force", "pin"], timeout=240)
    note = "第 1 次即成功"
    if not (rc == 0 and data and data.get("ok")):
        note = "第 1 次线路劣化，自动重试"
        rc, data, raw = run(["git", "ls-remote", "https://github.com/%s.git" % REPO, "HEAD",
                             "--force", "pin"], timeout=240)
    ok = rc == 0 and data and data.get("ok")
    clean_fail = bool(data) and data.get("ok") is False and data.get("tried") and data.get("next")
    check("git --force pin：成功，或（线路全断时）干净失败 + tried 明细 + 下一步",
          ok or clean_fail, "%s | %s" % (note, raw))

    rc, data, raw = run(["git", "push", "--help", "--force", "mirror"], timeout=60)
    check("红线：写操作强制 mirror 被拒（退出码 3）", rc == 3 and data and data.get("ok") is False, raw)

    rc, data, raw = run(["get", "no-such-user/no-such-repo-xyz:README.md",
                         "--dest", str(tmp / "e.md"), "--deadline", "20"], timeout=90)
    check("不存在的仓库 → 干净失败（退出码 1 + tried 明细）",
          rc == 1 and data and data.get("ok") is False and data.get("tried"), raw)

    rc, data, raw = run(["hosts", "--apply"], timeout=60)
    check("hosts --apply 无 --yes → 退出码 2（需要授权）",
          rc == 2 and data and data.get("need_confirm"), raw)

    rc, data, raw = run(["hosts", "--status"], timeout=30)
    check("hosts --status 可用", rc == 0 and data and data.get("ok") is True, raw)

    rc, data, raw = run(["diag"], timeout=180)
    check("diag 只读诊断可用（给出各通道事实）",
          rc == 0 and data and isinstance(data.get("checks"), dict)
          and data["checks"].get("cdn") is not None and data["checks"].get("pin") is not None, raw)

    rc, data, raw = run(["get", "--url",
                         "https://raw.githubusercontent.com/%s/main/README.md" % REPO,
                         "--dest", str(tmp / "f.md")], timeout=90)
    check("get --url（raw 链接）可用", rc == 0 and data and data.get("ok"), raw)

    rc, data, raw = run(["get", "%s:README.md" % REPO, "--force", "no-such-channel"], timeout=30)
    check("--force 未知通道 → 退出码 3", rc == 3 and data and data.get("ok") is False, raw)

    rc, data, raw = run(["get", "--url", "https://codeload.github.com/%s/zip/refs/heads/main" % REPO,
                         "--dest", str(tmp / "repo.zip")], timeout=180)
    check("get --url（codeload 压缩包：非 raw 的 https 路径）可用",
          rc == 0 and data and data.get("ok") and (tmp / "repo.zip").stat().st_size > 0, raw)

    clone_dir = tmp / "clone"
    rc, data, raw = run(["git", "clone", "https://github.com/%s.git" % REPO, str(clone_dir)],
                        timeout=240)
    check("git clone（自动 --depth 1）成功且落盘",
          rc == 0 and data and data.get("ok") and (clone_dir / "README.md").exists(), raw)

    # 代理污染场景：注入坏代理变量，env_guard 清代理后仍应可用（沙箱陷阱回归）
    env = dict(os.environ)
    env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"})
    rc, data, raw = run(["get", "%s:README.md" % REPO, "--dest", str(tmp / "g.md"),
                         "--force", "cdn"], timeout=90, env=env)
    check("注入坏代理变量后仍可用（env_guard 清代理生效）",
          rc == 0 and data and data.get("ok"), raw)

    return finish("test_readonly_smoke")


if __name__ == "__main__":
    raise SystemExit(main())
