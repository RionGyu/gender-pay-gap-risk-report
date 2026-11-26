"""개발·테스트용 가상 데이터 생성기 (KOSIS 응답 형식 모사).

실제 통계가 아닙니다. 생성된 manifest 에 sample_data=true 가 기록되고,
리포트에는 '가상 데이터' 경고 배너가 표시됩니다. 실제 수집 데이터가 있으면 실행하지 마세요.
일부러 결측기호('-','x'), 표기 흔들림(띄어쓰기·코드 접두어)을 섞어 정제 로직을 검증합니다.

    python tests/make_sample.py <출력 루트(기본: 저장소 루트)>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

rng = np.random.default_rng(7)
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]

OCC = [("0", "전직종"), ("1", "관리자"), ("2", "전문가 및 관련 종사자"), ("3", "사무 종사자"), ("4", "서비스 종사자"),
       ("5", "판매 종사자"), ("6", "농림·어업 숙련 종사자"), ("7", "기능원 및 관련 기능 종사자"),
       ("8", "장치·기계 조작 및 조립 종사자"), ("9", "단순노무 종사자")]
IND = [("0", "전산업"), ("C", "C. 제조업"), ("F", "F. 건설업"), ("G", "G. 도매 및 소매업"), ("H", "H. 운수 및 창고업"),
       ("I", "I. 숙박 및 음식점업"), ("J", "J. 정보통신업"), ("K", "K. 금융 및 보험업"), ("N", "N. 사업시설관리, 사업지원 및 임대 서비스업"),
       ("P", "P. 교육 서비스업"), ("Q", "Q. 보건업 및 사회복지 서비스업")]
EDU = [("0", "전학력"), ("1", "중졸이하"), ("2", "고졸"), ("3", "전문대졸"), ("4", "대졸이상")]
AGE = [("0", "전체"), ("1", "20~29세"), ("2", "30~39세"), ("3", "40~49세"), ("4", "50~59세"), ("5", "60세이상")]
SEX = [("0", "전체"), ("1", "남"), ("2", "여")]
ITEMS = [("T1", "근로자수", "명"), ("T2", "평균근속년수", "년"), ("T3", "총근로시간", "시간"), ("T4", "소정실근로시간", "시간"),
         ("T5", "초과근로시간", "시간"), ("T6", "월임금총액", "천원"), ("T7", "정액급여", "천원"), ("T8", "초과급여", "천원"),
         ("T9", "전년도연간특별급여/12개월", "천원")]
# 직종·산업별 기준 시급(천원), 여성비중, 초과근로(시간), 위험도
OCC_P = {"1": (55, .15, 3, .2), "2": (32, .52, 3, .3), "3": (26, .55, 4, .2), "4": (14, .70, 6, .6), "5": (17, .55, 3, .4),
         "6": (15, .3, 5, 1.2), "7": (21, .1, 12, 1.5), "8": (20, .2, 22, 1.4), "9": (13, .48, 8, 1.6)}
IND_P = {"C": (23, .28, 18, 1.4), "F": (24, .12, 6, 2.6), "G": (20, .45, 3, .5), "H": (19, .15, 14, 1.3), "I": (12, .62, 5, .7),
         "J": (30, .30, 3, .1), "K": (38, .55, 3, .1), "N": (14, .45, 7, .9), "P": (24, .65, 2, .2), "Q": (17, .80, 4, .6)}
EDU_M = {"1": .75, "2": .9, "3": 1.0, "4": 1.3}
AGE_M = {"1": .75, "2": .95, "3": 1.1, "4": 1.08, "5": .8}


def gen(classes, params, tbl, objnm, years):
    rows = []
    for y in years:
        cells = {}
        for code, _ in classes[1:]:
            base, fsh, ot, risk = params[code]
            for e, _ in EDU[1:]:
                for a, _ in AGE[1:]:
                    for s in ("1", "2"):
                        fem = s == "2"
                        n = rng.uniform(5e3, 8e4) * (fsh if fem else 1 - fsh) * (1.3 if e in "24" else .7)
                        hr = 160 + rng.normal(0, 4)
                        o = max(0.2, ot * (0.55 if fem else 1.15) + rng.normal(0, 1))
                        ten = 3 + int(a) * 2.2 * (0.75 if fem else 1)
                        hw = base * EDU_M[e] * AGE_M[a] * (0.86 if fem else 1) * (1 + 0.02 * (y - 2020)) * (1 + 0.004 * o) * np.exp(rng.normal(0, .03))
                        fixed = hw * hr
                        otp = hw * 1.5 * o
                        spec = fixed * (0.08 if fem else 0.13)
                        cells[(code, e, a, s)] = [n, ten, hr + o, hr, o, fixed + otp + spec, fixed, otp, spec]
        # 합계 분류 생성
        def agg(keyfn):
            out = {}
            for k, v in cells.items():
                for kk in keyfn(k):
                    out.setdefault(kk, []).append(v)
            res = {}
            for kk, vs in out.items():
                arr = np.array(vs)
                n = arr[:, 0].sum()
                res[kk] = [n] + list((arr[:, 1:] * arr[:, [0]]).sum(0) / n)
            return res
        allc = agg(lambda k: [(c, e, a, s) for c in (k[0], "0") for e in (k[1], "0") for a in (k[2], "0") for s in (k[3], "0")])
        for (c, e, a, s), v in allc.items():
            for (iid, inm, unit), val in zip(ITEMS, v):
                if unit == "천원":
                    val = val
                dt = f"{val:,.1f}" if unit != "명" else f"{val:,.0f}"
                if rng.random() < 0.003:
                    dt = rng.choice(["-", "x"])
                cl = dict(classes)
                cnm = cl[c] if rng.random() > .2 or c == "0" else cl[c].replace(" ", "")
                rows.append({"ORG_ID": "118", "TBL_ID": tbl, "C1": c, "C1_NM": cnm, "C1_OBJ_NM": objnm,
                             "C2": e, "C2_NM": dict(EDU)[e], "C2_OBJ_NM": "학력별",
                             "C3": s, "C3_NM": dict(SEX)[s], "C3_OBJ_NM": "성별",
                             "C4": a, "C4_NM": dict(AGE)[a], "C4_OBJ_NM": "연령계층별",
                             "ITM_ID": iid, "ITM_NM": inm, "UNIT_NM": unit, "PRD_SE": "A", "PRD_DE": str(y), "DT": dt})
    return rows


def main():
    raw = ROOT / "data" / "raw"
    years = [2021, 2022, 2023, 2024, 2025]
    manifest = {"sample_data": True, "sources": {}}
    for name, classes, params, tbl, obj in (("wage_occ", OCC, OCC_P, "DT_118N_PAYM42", "직종별"),
                                             ("wage_ind", IND, IND_P, "DT_118N_PAYN42", "산업별")):
        rows = gen(classes, params, tbl, obj, years)
        for y in years:
            p = raw / name / f"{y}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps([r for r in rows if r["PRD_DE"] == str(y)], ensure_ascii=False))
        manifest["sources"][name] = {"title": f"[가상] {tbl}", "files": {str(y): {"rows": 0} for y in years}}
    # 산재 마이크로데이터(산재보험 업종 체계) — 대업종/중업종 표기
    inj_ind = {"C": ("제조업", "기계기구·금속·비금속광물제품제조업"), "F": ("건설업", "건설업"),
               "G": ("기타의사업", "도소매및소비자용품수리업"), "H": ("운수·창고및통신업", "육상및수상운수업"),
               "I": ("기타의사업", "음식및숙박업"), "J": ("운수·창고및통신업", "통신업"), "K": ("금융및보험업", "금융및보험업"),
               "N": ("기타의사업", "건물등의종합관리사업"), "P": ("기타의사업", "교육서비스업"), "Q": ("기타의사업", "보건및사회복지사업")}
    recs = []
    for y in years[-3:]:
        for k, (big, mid) in inj_ind.items():
            base, fsh, ot, risk = IND_P[k]
            for sx, mult in (("남", 1.0), ("여", 0.45)):
                n = int(risk * 30 * mult * (fsh if sx == "여" else 1 - fsh) * 40 * rng.uniform(.9, 1.1))
                recs.append({"재해년도": str(y), "재해자구분": "사고", "대업종": big, "중업종": mid, "성별": sx,
                             "재해정도": "요양", "재해자수": n})
                recs.append({"재해년도": str(y), "재해자구분": "사고", "대업종": big, "중업종": mid, "성별": sx,
                             "재해정도": "사망", "재해자수": max(0, int(n * .004 * (1 + risk)))})
    p = raw / "injury_micro" / "sample.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recs, ensure_ascii=False))
    manifest["sources"]["injury_micro"] = {"title": "[가상] 산업재해통계 마이크로데이터", "files": {"sample": {"rows": len(recs), "summary": ""}}}
    (ROOT / "data" / "meta").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "meta" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print("sample written to", raw)


if __name__ == "__main__":
    main()
