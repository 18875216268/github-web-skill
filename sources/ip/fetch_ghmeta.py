"""获取方式③：GitHub 官方 IP 段（安全闸数据源）——拉官方 CIDR 段，供候选 ∈ 段校验。

一视同仁（D17）：普通获取方式，实例清单由 collect 注入、失败跳过（tried 留痕）——
官方端点不可达时本方式产出为空，hub 跳过段过滤（不阻塞主流程）。
产出特殊：{"cidrs": ["x.x.x.x/y", …]}（非 entries——消费方是 collect 的官方段旁路 meta）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parents[1]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_guard  # noqa: E402

WAY = "gh_meta"
TIMEOUT = 8.0


def collect(insts: list, domains: list | None = None) -> dict:
    """拉官方 meta → 合并全部 CIDR 段。返回 {ok, cidrs:[…], tried:[…]}。"""
    tried = []
    cidrs: list = []
    for inst in insts:
        args = env_guard.curl_base(TIMEOUT) + ["-fsSL", inst["url"]]
        try:
            p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=env_guard.clean_env(), timeout=TIMEOUT + 4)
            data = json.loads(p.stdout or "{}")
        except Exception as exc:
            tried.append({"source": inst["name"], "ok": False, "detail": str(exc)[:80]})
            continue
        n = 0
        for v in (data or {}).values():
            for seg in (v if isinstance(v, list) else []):
                if isinstance(seg, str) and "/" in seg:
                    cidrs.append(seg)
                    n += 1
        tried.append({"source": inst["name"], "ok": n > 0, "count": n, "detail": "官方段 %d 条" % n})
    return {"ok": bool(cidrs), "cidrs": sorted(set(cidrs)), "tried": tried}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    node = json.loads((_PKG / "sources" / "sources.json").read_text(encoding="utf-8"))["kinds"]["ip"]
    insts = [s for s in ((node["ways"][WAY] or {}).get("sources") or []) if s.get("enabled", True)]
    print(json.dumps(collect(insts), ensure_ascii=False, indent=2))
