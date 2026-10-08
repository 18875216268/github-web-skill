#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ssh / proxy 双通道（2026-10-08 新增）的结构与行为锁。

单开铁律：一通道一文件夹一注册一源类，互不借用——
- ssh 通道只消费 kinds.ssh（2 官方端点）；ip 源类（42 域）保持纯净（无 ssh 域混入）；
- proxy 通道无源类（地址来自 --proxy 运行时参数），且只收无认证地址（凭证不经过本技能）；
- 两通道都不进自动降级链（六条场景链不变）。
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
SCRIPTS = PKG / "scripts"
_UHOME = os.path.join(os.environ["TEMP"], "gws_t_uhome")   # 测试用户区（隔离真实 ~/.github-access）
os.makedirs(_UHOME, exist_ok=True)
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PKG / "channels" / "proxy"))   # channel_proxy.validate 供进程内单测
sys.path.insert(0, str(PKG / "channels" / "ssh"))     # channel_ssh.probe 供进程内单测


def gh(*args, timeout=90):
    # 用户区隔离（不写真实 ~/.github-access）+ 代理清空（探活/offers 不受环境噪声影响）
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "GH_ACCESS_HOME": _UHOME,
           "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
           "ALL_PROXY": "", "all_proxy": ""}
    p = subprocess.run([sys.executable, str(SCRIPTS / "gh.py"), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env, cwd=str(PKG))
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


class TestSingleOpenStructure(unittest.TestCase):
    """单开铁律的结构面：注册、源类、文件夹三者一一对应。"""

    def setUp(self):
        self.routes = json.loads((PKG / "routes" / "routes.json").read_text(encoding="utf-8"))
        self.src = json.loads((PKG / "sources" / "sources.json").read_text(encoding="utf-8"))

    def test_ssh_channel_registered_with_dedicated_kind(self):
        c = self.routes["channels"].get("ssh")
        self.assertIsNotNone(c, "routes.json 缺少 ssh 通道注册")
        self.assertEqual(c.get("kinds"), ["ssh"])
        self.assertTrue((PKG / "channels" / "ssh" / "channel_ssh.py").is_file())
        self.assertTrue((PKG / "channels" / "ssh" / "README.md").is_file())

    def test_ssh_kind_exists_with_two_official_endpoints(self):
        k = self.src["kinds"].get("ssh")
        self.assertIsNotNone(k, "sources.json 缺少 kinds.ssh（单开源类）")
        eps = k["endpoints"]
        self.assertEqual(len(eps), 2)
        self.assertEqual({e["name"] for e in eps},
                         {"github-22", "ssh-over-443"})
        self.assertEqual({e["port"] for e in eps}, {22, 443})

    def test_ip_domains_stay_pure_no_ssh_mixing(self):
        """铁律锁：ssh.github.com 不得混入 ip 源类（那是 pin/hosts 的专属源层）。"""
        doms = self.src["kinds"]["ip"]["domains"]
        self.assertEqual(len(doms), 42, "ip 域表数量被改动")
        self.assertNotIn("ssh.github.com", doms)

    def test_proxy_channel_registered_without_sources(self):
        c = self.routes["channels"].get("proxy")
        self.assertIsNotNone(c, "routes.json 缺少 proxy 通道注册")
        self.assertEqual(c.get("kinds"), [], "proxy 无源类（地址来自 --proxy 运行时参数）")
        self.assertTrue((PKG / "channels" / "proxy" / "channel_proxy.py").is_file())
        self.assertTrue((PKG / "channels" / "proxy" / "README.md").is_file())

    def test_scenarios_unchanged(self):
        """六条自动降级链不动：ssh/proxy 不进链（单开 ≠ 必须进链）。"""
        chains = {s["id"]: s["chain"] for s in self.routes["scenarios"]}
        self.assertEqual(chains["git_write"], ["direct", "pin"])
        self.assertEqual(chains["git_read"], ["direct", "pin", "mirror"])
        for cid in ("ssh", "proxy"):
            for chain in chains.values():
                self.assertNotIn(cid, chain,
                                 "%s 不应出现在自动降级链中" % cid)


class TestSshStatusCli(unittest.TestCase):
    """gh.py ssh --status：零凭证探测，只验 JSON 结构（不验网络结果）。"""

    def test_status_shape(self):
        """只验结构不验网络：门可达→rc0，不可达→rc1，两者都合法。"""
        rc, out, err = gh("ssh", "--status")
        self.assertIn(rc, (0, 1), err[:120])
        d = json.loads(out)
        self.assertEqual(d.get("action"), "ssh.status")
        self.assertEqual(d.get("channel"), "ssh")
        self.assertIsInstance(d.get("ok"), bool)
        eps = d.get("endpoints") or []
        self.assertEqual(len(eps), 2)
        for e in eps:
            self.assertIn("ok", e)
            self.assertIn("ms", e)

    def test_ssh_without_args_is_usage_error(self):
        rc, _out, _err = gh("ssh")
        self.assertEqual(rc, 3)


class TestDiagSshProbe(unittest.TestCase):
    """diag --full 必须携带 ssh_probe（双端点结构）。"""

    def test_diag_full_has_ssh_probe(self):
        rc, out, _err = gh("diag", "--full", timeout=300)
        self.assertEqual(rc, 0, out[:160])
        d = json.loads(out)
        sp = (d.get("checks") or {}).get("ssh_probe") or {}
        eps = sp.get("endpoints") or []
        self.assertEqual(len(eps), 2)
        for e in eps:
            self.assertIn("ok", e)
            self.assertIn("ms", e)


class TestOffersShape(unittest.TestCase):
    """offers 契约（环境容忍：门开才有 ssh 选项；无代理环境无 proxy 选项）。"""

    def test_git_failure_offers_are_wellformed(self):
        d = os.path.join(os.environ["TEMP"], "gws_offer_dir")
        os.makedirs(d, exist_ok=True)
        rc, out, _err = gh("git", "push", "origin", "main",
                           "--cwd", d, "--deadline", "30")
        self.assertIn(rc, (1, 2))
        body = json.loads(out)
        self.assertFalse(body.get("ok"))
        offers = body.get("offers") or []
        for o in offers:
            self.assertIn(o.get("id"), ("ssh", "proxy", "chain"))
            self.assertTrue(o.get("evidence"))
            self.assertTrue(str(o.get("retry", "")).startswith("gh.py"))
        self.assertEqual(body.get("need_confirm"), bool(offers))
        self.assertEqual(rc, 2 if offers else 1)


class TestSshBudgetCap(unittest.TestCase):
    """probe 总预算封顶：多地址（双栈/污染假地址）不累加超时。"""

    def test_budget_values_lock_user_decision(self):
        """2026-10-08 用户裁决：诊断预算 180s/端点（极端场景），offers 快筛 10s。"""
        import channel_ssh
        self.assertEqual(channel_ssh.TIMEOUT, 180.0)
        self.assertEqual(channel_ssh.OFFER_TIMEOUT, 10.0)

    def test_multi_address_capped(self):
        import channel_ssh
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.255.255.1", 22)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.255.255.2", 22))]
        with unittest.mock.patch.object(channel_ssh.socket, "getaddrinfo",
                                        return_value=fake):
            t0 = time.monotonic()
            r = channel_ssh.probe(timeout=1.0)
            elapsed_ms = (time.monotonic() - t0) * 1000
        self.assertFalse(r.get("ok"))
        eps = r["endpoints"]
        self.assertEqual(len(eps), 2)                     # 两端点都按预算走完
        self.assertLess(elapsed_ms, 3000, "总预算封顶失效（>3s）")
        for e in eps:
            self.assertFalse(e["ok"])
            self.assertIn("errs", e)                      # 逐地址失败记录（带 IP:类型）


class TestProxyChannel(unittest.TestCase):
    """proxy：只收无认证地址；显式传入即已决定；失败给 offers 而非静默回退。"""

    def test_validate_credential_matrix(self):
        """宽松凭证判定（2026-10-08 用户裁决）：仅拒 user:pass@；裸用户名/path@ 放行。"""
        import channel_proxy  # noqa: E402
        v = channel_proxy.validate
        self.assertFalse(v("http://user:pass@127.0.0.1:7890")[0])       # 密码 → 拒
        self.assertIn("密码", v("http://user:pass@127.0.0.1:7890")[1])
        self.assertFalse(v("socks5://u:p@proxy:1080")[0])               # socks 凭证 → 拒
        self.assertFalse(v("http://127.0.0.1:9@x")[0])                  # 歧义 netloc → 宁拒
        self.assertTrue(v("http://127.0.0.1:7890")[0])                  # 无认证 → 放行
        self.assertTrue(v("socks5h://127.0.0.1:1080")[0])
        self.assertTrue(v("http://127.0.0.1:9/p@th")[0])                # @ 在 path → 放行
        self.assertTrue(v("http://127.0.0.1:9/?a=@b")[0])               # @ 在 query → 放行
        self.assertFalse(v("ftp://127.0.0.1:21")[0])                    # 协议白名单
        self.assertFalse(v("")[0])
        self.assertFalse(v("http://127.0.0.1:7890 x")[0])               # 空白 → 拒

    def test_cli_rejects_credential_proxy(self):
        rc, out, _err = gh("get", "--url", "https://github.com/git/git/raw/master/README.md",
                           "--proxy", "http://user:pass@127.0.0.1:7890")
        self.assertEqual(rc, 3)
        self.assertIn("密码", out)

    def test_dead_proxy_fails_with_chain_offer(self):
        """离线确定性：不可达端口 → 快速失败 + offers 含『改走自动链』。"""
        rc, out, _err = gh("get", "--url", "https://github.com/git/git/raw/master/README.md",
                           "--proxy", "http://127.0.0.1:9")
        self.assertEqual(rc, 2, out[:160])
        d = json.loads(out)
        self.assertFalse(d.get("ok"))
        offers = d.get("offers") or []
        self.assertTrue(any(o.get("id") == "chain" for o in offers),
                        "代理失败后应提供『改走自动链』选项")
        self.assertTrue(d.get("need_confirm"))

    def test_mutual_exclusion_transport_and_proxy(self):
        rc, out, _err = gh("git", "push", "--transport", "ssh",
                           "--proxy", "http://127.0.0.1:7890")
        self.assertEqual(rc, 3)
        self.assertIn("互斥", out)

    def test_bogus_transport_is_usage_error(self):
        rc, out, _err = gh("git", "push", "--transport", "carrier-pigeon")
        self.assertEqual(rc, 3)
        self.assertIn("仅支持 ssh", out)


class TestTransportSshRewrite(unittest.TestCase):
    """--transport ssh 的调用级改写：单点注入 insteadOf，不碰 remote/key。"""

    def test_rewrite_marker_in_source(self):
        src = (PKG / "scripts" / "gh.py").read_text(encoding="utf-8")
        self.assertIn("url.git@github.com:.insteadOf=https://github.com/", src,
                      "调用级 SSH 改写（insteadOf）缺失")

    def test_prefer_ssh_flag_exists(self):
        src = (PKG / "scripts" / "gh.py").read_text(encoding="utf-8")
        self.assertIn('"--prefer-ssh"', src)
        self.assertIn("--prefer-ssh", (PKG / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
