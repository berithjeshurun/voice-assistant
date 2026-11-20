"""Re-run only the E2E section and merge into capability_bench.json."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amy.env import apply_env  # noqa: E402
from scripts.bench_capabilities import (  # noqa: E402
    AMY_PORT,
    REPORT_PATH,
    Result,
    _port_open,
    _scorecard,
    section_e2e,
)


def main() -> int:
    apply_env()
    results: list[Result] = []
    prev: dict = {}
    if REPORT_PATH.is_file():
        prev = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        for r in prev.get("results", []):
            if r.get("section") == "e2e":
                continue
            fields = {k: v for k, v in r.items() if k in Result.__dataclass_fields__}
            results.append(Result(**fields))

    print("amy port open", _port_open("127.0.0.1", AMY_PORT))
    section_e2e(results, leave_running=False)
    score = _scorecard(results)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_ms": prev.get("elapsed_ms"),
        "score": score,
        "results": [r.__dict__ for r in results],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== E2E RESCORE ===")
    for sec, info in score["sections"].items():
        print(f"  {sec:<10} {info['pass']}/{info['total']}")
    print(f"  overall   {score['pass']}/{score['total']}  ({'PASS' if score['ok'] else 'FAIL'})")
    if score["top_gaps"]:
        print("  top gaps:")
        for g in score["top_gaps"]:
            print("   -", g)
    for r in results:
        if r.section != "e2e":
            continue
        mark = "OK" if r.ok else "FAIL"
        print(f"[{mark}] {r.name} {r.ms:.0f}ms {r.detail[:140]}")
    return 0 if score["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
