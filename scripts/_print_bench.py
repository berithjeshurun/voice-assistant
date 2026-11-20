import json
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "logs" / "capability_bench.json"
d = json.loads(p.read_text(encoding="utf-8"))
s = d["score"]
print(json.dumps(s, indent=2))
print("--- fails ---")
for r in d["results"]:
    if not r.get("ok") and not r.get("skipped"):
        print("FAIL", f"{r['section']}/{r['name']}", round(r.get("ms") or 0), (r.get("detail") or "")[:120])
print("--- slowest ---")
for r in sorted(d["results"], key=lambda x: -float(x.get("ms") or 0))[:8]:
    print(f"{r['ms']:.0f}ms {r['section']}/{r['name']}")
