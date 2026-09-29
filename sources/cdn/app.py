"""CDN 源大类聚合器（D16）：读获取方式文件夹（static 登记）→ 统一候选格式。

与 mirror 大类同构；候选 url 为**模板**（{owner}/{repo}@{ref}/{path}）——渲染由消费方/speedtest 进行。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KIND = "cdn"


def collect() -> dict:
    """glob 读全部获取方式文件夹的 json → 扁平候选（enabled 过滤）。"""
    t0 = time.perf_counter()
    candidates: list = []
    tried: list = []
    for way_dir in sorted(p for p in _HERE.iterdir() if p.is_dir()):
        for jf in sorted(way_dir.glob("*.json")):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as exc:
                tried.append({"source": "%s/%s" % (way_dir.name, jf.name), "ok": False,
                              "detail": str(exc)[:60]})
                continue
            items = data.get("sources") if isinstance(data, dict) else data
            n = 0
            for it in (items or []):
                if not it.get("enabled", True) or not it.get("url"):
                    continue
                candidates.append({"kind": _KIND, "name": it["name"], "url": it["url"],
                                   "note": it.get("note", "")})
                n += 1
            tried.append({"source": "%s/%s" % (way_dir.name, jf.name), "ok": n > 0, "count": n,
                          "detail": "登记 %d 源" % n})
    return {"ok": bool(candidates), "candidates": candidates, "tried": tried,
            "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
