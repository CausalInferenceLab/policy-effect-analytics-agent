"""python -m core.causal cases/<케이스> [--data 분석용표.csv] [--no-write]"""

from __future__ import annotations

import argparse
import json
import sys

from .pywhy import check_case, write


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PyWhy(DoWhy)·CausalML 두 번째 의견")
    ap.add_argument("case")
    ap.add_argument("--data", default=None)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    r = check_case(a.case, a.data)
    if r["status"] != "ok":
        print(r.get("message", r["status"]), file=sys.stderr)
        return 1
    dw, ml = r["dowhy"], r["causalml"]
    print(
        f"[{r['case']}] {r['outcome']['name']} · 처치 {r['units']['treated']} / 비교 {r['units']['control']}"
    )
    print(f"  2×2 이중차분 {r['did_2x2']:+.4g} · 기본 추정 {r['baseline_estimate']}")
    if dw["status"] == "ok":
        print(
            f"  DoWhy 추정 {dw['estimate']:+.4g} (보정: {', '.join(dw['identification']['adjust_for'])})"
        )
        for x in dw["refutations"]:
            print(f"   - {x['label']}: {x.get('status')} (새 추정 {x.get('new_effect')})")
    else:
        print("  DoWhy:", dw.get("message"))
    print(
        "  CausalML:",
        ml.get("message") or f"ATE {ml['ate']:+.4g}, 단위별 효과 p10~p90 {ml['cate_quantiles']}",
    )
    if not a.no_write:
        print("  저장:", write(a.case, r))
    else:
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
