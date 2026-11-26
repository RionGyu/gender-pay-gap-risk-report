"""파이프라인 실행기.

    python -m pipeline.run all          # 수집 → 정제 → 분석 → 리포트
    python -m pipeline.run collect --discover
    python -m pipeline.run clean | analyze | report
"""
from __future__ import annotations

import argparse
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="성별 임금격차·위험부담 분석 파이프라인")
    ap.add_argument("step", choices=["collect", "clean", "analyze", "report", "all", "offline"],
                    help="offline = 수집 없이 기존 raw 로 정제→분석→리포트")
    ap.add_argument("--discover", action="store_true", help="KOSIS 키워드 검색으로 후보 통계표 목록 저장")
    a = ap.parse_args(argv)

    def log(msg):
        print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

    steps = {"all": ["collect", "clean", "analyze", "report"], "offline": ["clean", "analyze", "report"]}.get(a.step, [a.step])
    for s in steps:
        log(f"=== {s} ===")
        if s == "collect":
            from . import collect
            collect.run(log, do_discover=a.discover)
        elif s == "clean":
            from . import clean
            clean.run(log)
        elif s == "analyze":
            from . import analyze
            analyze.run(log)
        elif s == "report":
            from . import build_report
            build_report.run(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
