"""并发探测 + 源健康账本。

核心原则（用户原则落地）：**失败 ≠ 失效** —— 源只冷却、永不删除；冷却到期自动半开重试。
- 账本：`~/.github-access/cache/sources.json`（用户区；键 = 源名）。
- 排序：不在冷却期的源按 EMA 延迟升序在前；冷却中的源排在最后但**仍在候选内**。
- 并发：`race()` 用标准库线程同时探测 N 个源，**完成即用**（最快者先拿到结果）；
  到 deadline 用已返回的最优者；单条探测自带 4s 超时（快速定位不通 → 立即换源）。
"""
from __future__ import annotations

import json
import threading
import time

import lines
import report

LEDGER_F = report.HOME / "cache" / "sources.json"
_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def _load() -> dict:
    try:
        d = json.loads(LEDGER_F.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        report.ensure_home()
        LEDGER_F.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def state(key: str) -> dict:
    with _LOCK:
        return dict(_load().get(key) or {})


def cooldown_left(key: str) -> float:
    return max(0.0, float(state(key).get("cooldown_until", 0)) - _now())


def record(key: str, ok: bool, ms: float = 0.0, detail: str = "") -> None:
    """记一次**真实结果**：成功清零连败并更新延迟 EMA；失败按指数冷却（封顶 1h）。"""
    with _LOCK:
        d = _load()
        st = d.setdefault(key, {})
        st["last_detail"] = str(detail)[:160]
        if ok:
            st["ok_count"] = int(st.get("ok_count", 0)) + 1
            st["fail_streak"] = 0
            st["last_ok"] = _now()
            if ms > 0:
                prev = float(st.get("latency_ms") or 0)
                st["latency_ms"] = round(ms if prev <= 0 else prev * 0.6 + ms * 0.4, 1)
            st.pop("cooldown_until", None)
        else:
            st["fail_count"] = int(st.get("fail_count", 0)) + 1
            streak = int(st.get("fail_streak", 0)) + 1
            st["fail_streak"] = streak
            st["last_fail"] = _now()
            cd = min(lines.PROBE["cooldown_max"], lines.PROBE["cooldown_base"] * (2 ** (streak - 1)))
            st["cooldown_until"] = _now() + cd
        _save(d)


def order(keys: list) -> list:
    """健康优先排序：健康段（EMA 延迟升序）→ 未知 → 冷却中（按到期先后）。**绝不剔除任何键**。"""
    d = _load()
    now = _now()
    healthy, unknown, cooled = [], [], []
    for k in keys:
        st = d.get(k) or {}
        last_ok = float(st.get("last_ok") or 0)
        if last_ok and now - last_ok <= lines.PROBE["fresh_ok_within"] and float(st.get("cooldown_until", 0)) <= now:
            healthy.append((k, float(st.get("latency_ms") or 99999)))
        elif float(st.get("cooldown_until", 0)) > now:
            cooled.append((k, float(st.get("cooldown_until", 0))))
        else:
            unknown.append(k)
    healthy.sort(key=lambda x: x[1])
    cooled.sort(key=lambda x: x[1])
    return [k for k, _ in healthy] + unknown + [k for k, _ in cooled]


def recent_ok(keys: list) -> list:
    """账本里"最近成功过且未冷却"的源（按延迟升序）——可直接真取，省一次探测。"""
    d = _load()
    now = _now()
    out = []
    for k in keys:
        st = d.get(k) or {}
        last_ok = float(st.get("last_ok") or 0)
        if last_ok and now - last_ok <= lines.PROBE["fresh_ok_within"] and float(st.get("cooldown_until", 0)) <= now:
            out.append((k, float(st.get("latency_ms") or 99999)))
    out.sort(key=lambda x: x[1])
    return [k for k, _ in out]


def race(tasks: list, workers: int | None = None, deadline: float | None = None) -> list:
    """并发执行 `[(key, fn)]`；返回**按完成顺序**的 `[(key, ok, value, ms)]`。

    - fn 须自带超时；本函数只负责并发与截止；异常一律视为"不通"，绝不上抛。
    - 到 deadline 仍未完成的线程被放弃（daemon，子进程自带超时）。
    """
    workers = workers or lines.PROBE["workers"]
    deadline = deadline or lines.PROBE["deadline"]
    results, lock = [], threading.Lock()
    sem = threading.Semaphore(workers)

    def run(key, fn):
        with sem:
            t0 = time.perf_counter()
            try:
                val = fn()
                ok = bool(val.get("ok")) if isinstance(val, dict) else bool(val)
            except Exception as exc:
                val, ok = {"ok": False, "detail": "probe error: %s" % str(exc)[:80]}, False
            ms = (time.perf_counter() - t0) * 1000
            with lock:
                results.append((key, ok, val, ms))

    ths = [threading.Thread(target=run, args=(k, f), daemon=True) for k, f in tasks]
    end = time.perf_counter() + deadline
    for t in ths:
        t.start()
    for t in ths:
        t.join(max(0.05, end - time.perf_counter()))
    with lock:
        done = {k for k, _ok, _v, _ms in results}
    # 未在 deadline 内返回的，补显式占位（绝不静默消失：清单完整性优先）
    for k, _f in tasks:
        if k not in done:
            results.append((k, False, {"ok": False, "detail": "探测超时（deadline 内未返回）"},
                            (time.perf_counter() - (end - deadline)) * 1000))
    return list(results)


def race_http(pairs: list, timeout: float | None = None, workers: int | None = None) -> list:
    """`[(key, url)]` → 并发 HEAD 探活；返回按完成顺序的 `[(key, ok, ms, detail)]`。"""
    from channel_direct import head_ok
    t = timeout or lines.PROBE["timeout"]
    res = race([(k, (lambda u=u: head_ok(u, t))) for k, u in pairs], workers=workers)
    return [(k, ok, ms, (v or {}).get("detail", "")) for (k, ok, v, ms) in res]


def candidates(names: list, probe_pairs: list | None = None, probe_fn=None,
               hot: int = 2, rest: int = 2):
    """**惰性**候选序列（生成器）：热源先出（零探测开销）→ 耗尽后才并发探活 → 其余按账本序。

    为什么惰性：账本已有"刚成功过"的源时，快路径不应再付一轮探测成本
    （实测教训：先探后取把 0.3s 的 CDN 取文件拖成 7s）。只有热源真的失败，才付并发探测的钱。
    不删除任何源：探活未过者仍可能出现在 rest 段；本次没轮到的，等冷却到期/账本变化后重排。
    """
    seen = set()

    def emit(seq):
        for n in seq:
            if n not in seen:
                seen.add(n)
                yield n

    hot_names = recent_ok(names)[:hot]
    yield from emit(hot_names)
    rest_names = [n for n in names if n not in seen]
    if not rest_names:
        return
    if probe_pairs:
        pairs = [(k, u) for k, u in probe_pairs if k in set(rest_names)]
        yield from emit([k for k, ok, _ms, _d in race_http(pairs) if ok])
    elif probe_fn is not None:
        yield from emit([k for k, ok, _v, _ms in
                         race([(n, (lambda n=n: probe_fn(n))) for n in rest_names]) if ok])
    yield from emit(order([n for n in rest_names if n not in seen])[:rest])


def plan(names: list, probe_pairs: list | None = None, probe_fn=None,
         hot: int = 2, rest: int = 2) -> list:
    """`candidates()` 的立即求值版本（供需要完整列表的场景/测试使用）。"""
    return list(candidates(names, probe_pairs=probe_pairs, probe_fn=probe_fn, hot=hot, rest=rest))
