"""通道 pin：不改源，只绕 DNS/线路——取可达 IP，再在**单次调用**内钉住。

IP 来源（动态优先）：
  1) 用户自建云函数（可达 IP，按延迟排序）
  2) DoH（阿里 / DNSPod，绕过本地 DNS 污染）
  3) 内置硬编码池（lines.IP_POOLS，实测可用清单）
应用方式：本地 CONNECT 代理（127.0.0.1 随机端口），只钉 GitHub 相关域；
  不写系统 hosts、无需管理员、进程结束即失效；代理内单 IP 连接超时收紧（实测 12s 会吃掉预算）。
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import env_guard
import lines
import report

CACHE_F = report.HOME / "cache" / "ip.json"
GOOD_F = report.HOME / "cache" / "ip_good.json"
IP_RE = re.compile(r'"data":"(\d+\.\d+\.\d+\.\d+)"')


def _load_good() -> dict:
    """上次实测连通的 IP（30 分钟 TTL）——下次优先试，避免首个候选恰是坏 IP 白等。"""
    try:
        d = json.loads(GOOD_F.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if time.time() - v.get("ts", 0) < 1800}
    except Exception:
        return {}


def _save_good(used: dict) -> None:
    if not used:
        return
    try:
        report.ensure_home()
        d = _load_good()
        for domain, ip in used.items():
            d[domain] = {"ip": ip, "ts": time.time()}
        GOOD_F.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


ALIVE_F = report.HOME / "cache" / "ip_alive.json"
ALIVE_TTL = 300.0


def _load_alive() -> dict:
    try:
        d = json.loads(ALIVE_F.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if time.time() - v.get("ts", 0) < ALIVE_TTL}
    except Exception:
        return {}


def _save_alive(dom_alive: dict) -> None:
    if not dom_alive:
        return
    try:
        report.ensure_home()
        d = _load_alive()
        for dom, ips in dom_alive.items():
            d[dom] = {"ips": ips, "ts": time.time()}
        ALIVE_F.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def _verify_first(hosts: dict, domains: list, timeout: float = 3.0, limit: int = 3) -> dict:
    """把「实测有响应」的 IP 提到最前（5 分钟缓存）。

    为什么必须做：TCP 连得上但 TLS 被掐的 IP 会白等满一轮（实测每轮 30~45s）；
    先花 3 秒逐 IP 探一下，能把这一轮直接省掉。历史好 IP（_apply_good）排在存活 IP 之后。
    """
    want = [d for d in domains if hosts.get(d)]
    if not want:
        return hosts
    cache = _load_alive()
    fresh, alive = {}, {}
    for d in want:
        if d in cache:
            alive[d] = list(cache[d].get("ips") or [])
        else:
            fresh[d] = (verify_ips({d: hosts[d]}, limit=limit, timeout=timeout)).get(d, [])
            alive[d] = fresh[d]
    _save_alive(fresh)
    out = {}
    for d, ips in hosts.items():
        lead = [ip for ip in alive.get(d, []) if ip in ips]
        out[d] = lead + [ip for ip in ips if ip not in lead]
    return out


def _apply_good(hosts: dict) -> dict:
    good = _load_good()
    out = {}
    for domain, ips in hosts.items():
        g = (good.get(domain) or {}).get("ip")
        out[domain] = ([g] + [ip for ip in ips if ip != g]) if g else list(ips)
    return out


def _parse_cloud_fn(text: str) -> dict:
    """解析云函数输出：每行 `IP<空白>域名`。

    `alive.<域>` 是函数自己的「实测存活」标记（2026-09-11 取原始输出核对：145 行中 1 行），
    必须归一化到 `<域>` 并**排在候选最前**——否则函数的存活 IP 永远进不了候选（历史 bug）。
    """
    alive, other = {}, {}
    for ln in (text or "").splitlines():
        parts = ln.split()
        if len(parts) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", parts[0]):
            continue
        ip, dom = parts[0], parts[1]
        bucket = other
        if dom.startswith("alive."):
            dom, bucket = dom[len("alive."):], alive
        if ip not in bucket.setdefault(dom, []):
            bucket[dom].append(ip)
    out = {}
    for dom in set(alive) | set(other):
        head = alive.get(dom, [])
        out[dom] = head + [ip for ip in other.get(dom, []) if ip not in head]
    return out


def _fetch_cloud_fn() -> dict:
    url = (lines.CLOUD_FN_DEFAULT.rstrip("/") + "/?source=" + lines.CLOUD_FN_SOURCE)
    args = env_guard.curl_base(lines.CLOUD_FN_TIMEOUT) + [url]
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=env_guard.clean_env(),
                           timeout=lines.CLOUD_FN_TIMEOUT + 6)
    except Exception:
        return {}
    return _parse_cloud_fn(p.stdout or "")


def _fetch_doh(domain: str) -> list:
    got = []
    for srv in lines.DOH_SERVERS:
        url = "%s?name=%s&type=A" % (srv, domain)
        args = env_guard.curl_base(lines.DOH_TIMEOUT) + [url]
        try:
            p = subprocess.run(args, capture_output=True, text=True, env=env_guard.clean_env(),
                               timeout=lines.DOH_TIMEOUT + 4)
        except Exception:
            continue
        got += IP_RE.findall(p.stdout or "")
    seen, out = set(), []
    for ip in got:
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def fetch_hosts() -> dict:
    """域名 → 候选 IP 列表（动态源优先，硬编码兜底）；结果写用户区缓存。"""
    hosts = _fetch_cloud_fn()
    for d in lines.PIN_DOMAINS:
        for ip in _fetch_doh(d):
            if ip not in hosts.setdefault(d, []):
                hosts[d].append(ip)
    for d, pool in lines.IP_POOLS.items():
        for ip in pool:
            if ip not in hosts.setdefault(d, []):
                hosts[d].append(ip)
    hosts = {d: v[:lines.PIN_CANDIDATES_PER_DOMAIN] for d, v in hosts.items() if v}
    try:
        report.ensure_home()
        CACHE_F.write_text(json.dumps({"ts": time.time(), "hosts": hosts}), encoding="utf-8")
    except Exception:
        pass
    return hosts


def cached_hosts() -> dict:
    try:
        d = json.loads(CACHE_F.read_text(encoding="utf-8"))
        if time.time() - d.get("ts", 0) < lines.CACHE_TTL["ip"]:
            return d.get("hosts") or {}
    except Exception:
        pass
    return {}


class PinProxy:
    """单次调用作用域的 CONNECT 代理：把 GitHub 域钉到候选 IP，其余域走正常 DNS。"""

    def __init__(self, hosts: dict, connect_timeout: float = lines.PIN_CONNECT_TIMEOUT):
        self.hosts = hosts
        self.connect_timeout = connect_timeout
        self.port = 0
        self._srv = None
        self.used: dict = {}          # 本次实际连通的 {domain: ip}，供"上次可用优先"缓存

    def _resolve(self, host: str) -> list:
        for domain, ips in self.hosts.items():
            if host == domain or host.endswith("." + domain):
                return list(ips)
        return []

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(self.connect_timeout + 2)
            head = conn.recv(65536)
            if not head.startswith(b"CONNECT"):
                conn.close()
                return
            target = head.split(b"\r\n", 1)[0].decode().split()[1]
            host, port = target.rsplit(":", 1)
            port = int(port)
            dest = None
            for ip in self._resolve(host):
                try:
                    dest = socket.create_connection((ip, port), timeout=self.connect_timeout)
                    self.used[host] = ip
                    break
                except Exception:
                    continue
            if dest is None:
                try:
                    dest = socket.create_connection((host, port), timeout=self.connect_timeout)
                except Exception:
                    conn.close()
                    return
            # 关键：进入转发前必须清掉两端超时——否则 4~6s 静默就会掐断转发线程，
            # 表现为 TLS 握手半途失败（schannel: failed to receive handshake），且随网络抖动间歇复现。
            conn.settimeout(None)
            dest.settimeout(None)
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

            def pipe(a, b):
                try:
                    while True:
                        data = a.recv(65536)
                        if not data:
                            break
                        b.sendall(data)
                except Exception:
                    pass
                finally:
                    for s in (a, b):
                        try:
                            s.close()
                        except Exception:
                            pass

            threading.Thread(target=pipe, args=(conn, dest), daemon=True).start()
            threading.Thread(target=pipe, args=(dest, conn), daemon=True).start()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    def start(self) -> int:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(64)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()
        return self.port

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except Exception:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def stop(self) -> None:
        try:
            self._srv.close()
        except Exception:
            pass


def verify_ips(hosts: dict, limit: int = 2, timeout: float = 4.0) -> dict:
    """逐 IP 实测可达性（判据：服务器有 HTTP 响应即视为可达；不做性能结论）。

    **并发探测**（完成即收集，按探测延迟升序返回全部存活者）；
    用途：改 hosts 之前必须过这一关——不把"没验证过的 IP"写进系统解析。
    """
    import os as _os
    import subprocess as _sp

    import probe as _probe
    devnull = "NUL" if _os.name == "nt" else "/dev/null"

    def one(domain: str, ip: str) -> dict:
        args = env_guard.curl_base(timeout) + [
            "-o", devnull, "-w", "%{http_code}",
            "--resolve", "%s:443:%s" % (domain, ip), "https://%s/" % domain]
        try:
            p = _sp.run(args, capture_output=True, text=True, env=env_guard.clean_env(),
                        timeout=timeout + 4)
        except Exception as exc:
            return {"ok": False, "detail": str(exc)[:60]}
        code = ((p.stdout or "000").strip().splitlines() or ["000"])[-1]
        return {"ok": code != "000", "code": code}

    pairs = [(d, ip) for d, ips in hosts.items() for ip in (ips or [])[:limit]]
    alive = {}
    for key, ok, _val, ms in _probe.race([("%s|%s" % (d, ip), (lambda d=d, ip=ip: one(d, ip)))
                                          for d, ip in pairs]):
        if ok:
            d, ip = key.split("|")
            alive.setdefault(d, []).append((ip, ms))
    return {d: [ip for ip, _ in sorted(v, key=lambda x: x[1])] for d, v in alive.items()}


def verify_for_hosts(hosts: dict, limit: int = 2, timeout: float = 6.0) -> dict:
    """hosts 写入前的**严格**校验：对有已知小文件的域，真实取 1 字节内容（`-r 0-0`）且要 2xx。

    为什么单独一条：根路径响应是弱判据（实测 raw 的 111.133 根路径 200、真实取文件 000/10s）。
    写进系统解析的 IP 必须"能真正取到内容"，否则只是把浏览器钉在一个假通的 IP 上。
    无稳定小文件可依的域保持 `verify_ips` 的"有响应即视为可达"判据（并如实标注在报告里）。
    """
    out = {}
    strict = getattr(lines, "STRICT_PROBE_URLS", {})
    rest = {d: ips for d, ips in hosts.items() if d not in strict}
    if rest:
        out.update(verify_ips(rest, limit=limit, timeout=timeout))
    pairs = [(d, ip) for d, ips in hosts.items() if d in strict for ip in (ips or [])[:limit]]
    if not pairs:
        return out

    import os as _os
    import subprocess as _sp

    import probe as _probe
    devnull = "NUL" if _os.name == "nt" else "/dev/null"

    def one(domain: str, ip: str) -> dict:
        args = env_guard.curl_base(timeout) + [
            "-r", "0-0", "-o", devnull, "-w", "%{http_code}",
            "--resolve", "%s:443:%s" % (domain, ip), strict[domain]]
        try:
            p = _sp.run(args, capture_output=True, text=True, env=env_guard.clean_env(),
                        timeout=timeout + 4)
        except Exception as exc:
            return {"ok": False, "detail": str(exc)[:60]}
        code = ((p.stdout or "000").strip().splitlines() or ["000"])[-1]
        return {"ok": code.startswith("2"), "code": code}

    alive = {}
    for key, ok, _val, ms in _probe.race([("%s|%s" % (d, ip), (lambda d=d, ip=ip: one(d, ip)))
                                          for d, ip in pairs]):
        if ok:
            d, ip = key.split("|")
            alive.setdefault(d, []).append((ip, ms))
    for d, v in alive.items():
        out[d] = [ip for ip, _ in sorted(v, key=lambda x: x[1])]
    return out


def _rotations(hosts: dict, rounds: int = 3):
    """生成多轮候选顺序：第 k 轮把每域的第 k 个候选提到最前。

    为什么需要它：实测存在"TCP 连得上、TLS 却被掐"的 IP（线路被针对性阻断），
    只在 CONNECT 失败时换 IP 会白等到超时——必须按"能否真正传完"来换。
    """
    maxlen = max((len(v) for v in hosts.values()), default=1)
    for k in range(max(1, min(rounds, maxlen))):
        out = {}
        for d, ips in hosts.items():
            if not ips:
                out[d] = ips
                continue
            i = k % len(ips)
            out[d] = ips[i:] + ips[:i]
        yield out


def http_get(url: str, dest: Path, timeout: float, hosts: dict | None = None,
             rounds: int = 4, budget=None) -> dict:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    hosts = _verify_first(_apply_good(hosts or cached_hosts() or fetch_hosts()), [host])
    last = {"ok": False, "detail": "无候选可试"}
    for k, rot in enumerate(_rotations(hosts, rounds)):
        if budget is not None and not budget.can_attempt():
            last["detail"] = "预算不足，停止 pin failover"
            break
        # 轮次覆盖全部候选（每域 4 个）；每轮超时按"剩余预算 ÷ 剩余轮次"收敛，末轮仍留足传输时间
        cap = 15.0
        if budget is not None:
            cap = max(8.0, min(15.0, budget.remaining() / max(1, rounds - k)))
        rt = budget.timeout_for(cap) if budget is not None else max(6.0, min(float(timeout), 15.0))
        proxy = PinProxy(rot)
        port = proxy.start()
        try:
            from channel_direct import http_get as _curl_get
            r = _curl_get(url, dest, rt, extra=["-x", "http://127.0.0.1:%d" % port])
        finally:
            proxy.stop()
        r.update({"channel": "pin", "third_party": None,
                  "detail": "钉 IP(%d 域·第%d轮) -> %s" % (len(hosts), k + 1, r.get("detail"))})
        if r["ok"]:
            # 只有"整次请求成功"才把该 IP 记为好用（TCP 级成功不算——实测会害下一轮白等）
            ip = proxy.used.get(host)
            if ip:
                _save_good({host: ip})
            return r
        last = r
    last["detail"] = str(last.get("detail")) + "；%d 轮传输级 failover 全败" % rounds
    return last


def git_run(args: list, cwd: str | None, timeout: float, hosts: dict | None = None,
            rounds: int = 3, budget=None) -> dict:
    host = ""
    for a in args:
        m = re.match(r"https?://([^/]+)/", a)
        if m:
            host = m.group(1)
            break
    hosts = _verify_first(_apply_good(hosts or cached_hosts() or fetch_hosts()), [host] if host else [])
    last = {"ok": False, "detail": "无候选可试", "rc": 1, "out": "", "err": ""}
    for k, rot in enumerate(_rotations(hosts, rounds)):
        if budget is not None and not budget.can_attempt():
            last["detail"] = "预算不足，停止 pin failover"
            break
        # 单轮 45s：实测同一条线 ls-remote 需 9~26s，偶尔更慢——30s 会误杀"健康但慢"的一轮
        rt = budget.timeout_for(45.0) if budget is not None else max(10.0, min(float(timeout), 45.0))
        proxy = PinProxy(rot)
        port = proxy.start()
        try:
            from channel_direct import git_run as _git
            r = _git(["-c", "http.proxy=http://127.0.0.1:%d" % port, *args], cwd, rt)
        finally:
            proxy.stop()
        r.update({"channel": "pin", "third_party": None,
                  "detail": "钉 IP(%d 域·第%d轮) -> %s" % (len(hosts), k + 1, r.get("detail"))})
        if r["ok"]:
            ip = proxy.used.get(host) if host else None
            if ip:
                _save_good({host: ip})
            return r
        last = r
    last["detail"] = str(last.get("detail")) + "；%d 轮传输级 failover 全败" % rounds
    return last
