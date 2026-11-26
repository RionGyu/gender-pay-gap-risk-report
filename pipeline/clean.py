"""2단계: 정제. data/raw 의 API 원본을 분석용 표준 테이블로 바꾸고 품질 리포트를 남깁니다.

처리하는 문제들
1) 결측·비공개 기호:  '-', 'x', '...', '…', 빈칸 → NaN (기호별 건수 기록)
2) 분류 순서 불일치:   통계표마다 C1~C4 의 의미가 달라 C*_OBJ_NM(분류명)으로 차원을 식별
3) 코드·명칭 불일치:   연도별 직종·산업 명칭 표기 차이(띄어쓰기, 가운뎃점, 코드 접두어)를
                      표준분류(KSCO 대분류, KSIC 대분류) 코드로 통일
4) 분류체계 불일치:    산재보험 업종(대·중업종) → KSIC 대분류 교차표(config/crosswalk_injury_industry.csv)
5) 단위 불일치:        천원/원, 시간 → 원·시간으로 통일
6) 정합성 검사:        월임금총액 ≈ 정액+초과+특별/12, 남+여 ≈ 전체 근로자수
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
META = ROOT / "data" / "meta"

MISSING_SYMBOLS = {"-", "x", "X", "...", "…", "", "nan", "None", "e", "p", "▽"}

# ---------------------------------------------------------------- 표준 코드표
KSCO = {  # 한국표준직업분류 대분류
    "1": "관리자", "2": "전문가 및 관련 종사자", "3": "사무 종사자", "4": "서비스 종사자",
    "5": "판매 종사자", "6": "농림어업 숙련 종사자", "7": "기능원 및 관련 기능 종사자",
    "8": "장치·기계 조작 및 조립 종사자", "9": "단순노무 종사자",
}
KSIC = {  # 한국표준산업분류 대분류
    "A": "농업·임업·어업", "B": "광업", "C": "제조업", "D": "전기·가스·증기·공기조절 공급업",
    "E": "수도·하수·폐기물처리·원료재생업", "F": "건설업", "G": "도매 및 소매업", "H": "운수 및 창고업",
    "I": "숙박 및 음식점업", "J": "정보통신업", "K": "금융 및 보험업", "L": "부동산업",
    "M": "전문·과학 및 기술서비스업", "N": "사업시설관리·사업지원 및 임대서비스업",
    "O": "공공행정·국방 및 사회보장행정", "P": "교육서비스업", "Q": "보건업 및 사회복지서비스업",
    "R": "예술·스포츠 및 여가관련서비스업", "S": "협회·단체·수리 및 기타 개인서비스업",
}
TOTAL_LABELS = {"전체", "계", "합계", "전직종", "전산업", "전학력", "전연령", "전규모", "총계", "소계", "전경력"}

ITEM_RULES = [  # (정규식, 표준키) — 위에서부터 먼저 일치하는 규칙 적용
    (r"근로자\s*수", "workers"),
    (r"평균\s*연령", "age_mean"),
    (r"평균\s*근속", "tenure"),
    (r"근로\s*일수", "days"),
    (r"총\s*근로\s*시간", "hours_total"),
    (r"소정\s*실?\s*근로\s*시간", "hours_regular"),
    (r"초과\s*근로\s*시간", "hours_overtime"),
    (r"휴일\s*근로\s*시간", "hours_holiday"),
    (r"월?\s*임금\s*총액", "wage_total"),
    (r"월\s*급여\s*액", "wage_monthly"),
    (r"정액\s*급여", "wage_fixed"),
    (r"초과\s*급여", "wage_overtime"),
    (r"특별\s*급여.*12|12\s*개월", "wage_special_m"),
    (r"특별\s*급여", "wage_special_y"),
]

DIM_RULES = [(r"직종|직업", "occ"), (r"산업|업종", "ind"), (r"학력", "edu"), (r"성별|^성$|성\b", "sex"),
             (r"연령", "age"), (r"경력", "career"), (r"규모", "size"), (r"근속", "tenure_band")]


def norm_text(s: str) -> str:
    s = re.sub(r"^\s*(?:[\(\[][0-9A-Z]{1,3}[\)\]][\.\s]*|[0-9A-Z]{1,3}[\.\s]+)", "", str(s))  # 'C. 제조업', '(1)관리자' 등 코드 접두어
    s = re.sub(r"\(\s*[0-9A-Z~]+\s*\)\s*$", "", s)                 # '관리자(1)' 같은 코드 접미어
    return re.sub(r"[\s·ㆍ,\.・‧∙]", "", s)


_KSCO_KEYS = {norm_text(v): k for k, v in KSCO.items()}
_KSCO_KEYS.update({"농림어업숙련종사자": "6", "농림·어업숙련종사자": "6", "장치기계조작및조립종사자": "8",
                   "전문가및관련종사자": "2", "기능원및관련기능종사자": "7"})
_KSIC_KEYS = {norm_text(v): k for k, v in KSIC.items()}
_KSIC_ALIASES = {  # 연도·통계표별 표기 차이
    "농업임업및어업": "A", "전기가스증기및공기조절공급업": "D", "전기가스증기및수도사업": "D",
    "하수폐기물처리원료재생및환경복원업": "E", "수도하수및폐기물처리원료재생업": "E",
    "도매및소매업": "G", "숙박및음식점업": "I", "출판영상방송통신및정보서비스업": "J",
    "부동산업및임대업": "L", "전문과학및기술서비스업": "M", "사업시설관리및사업지원서비스업": "N",
    "사업시설관리사업지원및임대서비스업": "N", "공공행정국방및사회보장행정": "O",
    "보건업및사회복지서비스업": "Q", "예술스포츠및여가관련서비스업": "R",
    "협회및단체수리및기타개인서비스업": "S",
}
_KSIC_KEYS.update(_KSIC_ALIASES)


def map_occ(label: str) -> str | None:
    if str(label).strip() in TOTAL_LABELS:
        return "T"
    m = re.match(r"^\s*(?:\(([1-9])\)|([1-9])[\.\s])", str(label))
    key = norm_text(label)
    if key in _KSCO_KEYS:
        return _KSCO_KEYS[key]
    if m:
        return m.group(1) or m.group(2)
    for k, code in _KSCO_KEYS.items():  # 부분 일치(신·구 분류 명칭 차이)
        if k[:4] and key.startswith(k[:4]):
            return code
    return None


def map_ind(label: str) -> str | None:
    if str(label).strip() in TOTAL_LABELS:
        return "T"
    key = norm_text(label)
    if key in _KSIC_KEYS:
        return _KSIC_KEYS[key]
    m = re.match(r"^\s*\(?([A-U])\)?[\.\s]", str(label))
    if m:
        return m.group(1)
    for k, code in _KSIC_KEYS.items():
        if len(key) >= 4 and (k.startswith(key[:4]) or key.startswith(k[:4])):
            return code
    return None


def map_sex(label: str) -> str | None:
    s = str(label).strip()
    if s in TOTAL_LABELS or s in {"성별", "남녀"}:
        return "T"
    if s.startswith("남") or s.lower().startswith("m"):
        return "M"
    if s.startswith("여") or s.lower().startswith("f"):
        return "F"
    return None


def map_item(label: str) -> str | None:
    for pat, key in ITEM_RULES:
        if re.search(pat, str(label)):
            return key
    return None


def parse_value(v, unit: str, qa: Counter) -> float:
    s = str(v).strip() if v is not None else ""
    if s in MISSING_SYMBOLS:
        qa[f"missing_symbol[{s or '빈칸'}]"] += 1
        return np.nan
    s = s.replace(",", "")
    try:
        x = float(s)
    except ValueError:
        qa[f"unparsable[{s[:10]}]"] += 1
        return np.nan
    if unit and "천원" in unit:
        x *= 1000
    elif unit and "만원" in unit:
        x *= 10000
    return x


# ---------------------------------------------------------------- KOSIS 표
def kosis_to_long(rows: list[dict], qa: Counter) -> pd.DataFrame:
    recs = []
    for r in rows:
        dims = {}
        for i in range(1, 9):
            obj = r.get(f"C{i}_OBJ_NM") or r.get(f"C{i}_OBJ_NM_ENG")
            if obj is None and r.get(f"C{i}") is None:
                break
            dim = next((d for pat, d in DIM_RULES if re.search(pat, str(obj or ""))), f"c{i}")
            if dim.startswith("c"):
                qa[f"unknown_dimension[{obj}]"] += 1
            dims[dim] = r.get(f"C{i}_NM")
            dims[f"{dim}_code_raw"] = r.get(f"C{i}")
        item = map_item(r.get("ITM_NM", ""))
        if item is None:
            qa[f"unknown_item[{r.get('ITM_NM')}]"] += 1
            continue
        recs.append({"year": int(str(r.get("PRD_DE"))[:4]), **dims, "item": item,
                     "value": parse_value(r.get("DT"), r.get("UNIT_NM", ""), qa)})
    df = pd.DataFrame(recs)
    qa["rows_in"] += len(rows)
    qa["rows_out"] += len(df)
    return df


def standardize(df: pd.DataFrame, qa: Counter) -> pd.DataFrame:
    df = df.copy()
    for dim, fn in (("occ", map_occ), ("ind", map_ind), ("sex", map_sex)):
        if dim in df:
            codes = df[dim].map(fn)
            for lab in sorted(df.loc[codes.isna(), dim].unique()):
                qa[f"unmapped_{dim}[{lab}]"] += 1
            df[f"{dim}_label"] = df[dim]
            df[dim] = codes
            df = df[df[dim].notna()]
    for dim in ("edu", "age", "career"):
        if dim in df:
            df[dim] = df[dim].astype(str).str.strip().where(~df[dim].astype(str).str.strip().isin(TOTAL_LABELS), "T")
    keys = [c for c in ("year", "occ", "ind", "edu", "age", "career", "sex") if c in df]
    dup = df.duplicated(keys + ["item"]).sum()
    if dup:
        qa["duplicates_dropped"] += int(dup)
        df = df.drop_duplicates(keys + ["item"], keep="last")
    wide = df.pivot_table(index=keys, columns="item", values="value", aggfunc="first").reset_index()
    wide.columns.name = None
    return wide


def consistency_checks(wide: pd.DataFrame, qa: Counter, keys: list[str]) -> None:
    need = {"wage_total", "wage_fixed", "wage_overtime", "wage_special_m"}
    if need <= set(wide.columns):
        recon = wide["wage_fixed"] + wide["wage_overtime"] + wide["wage_special_m"]
        rel = (wide["wage_total"] - recon).abs() / wide["wage_total"]
        qa["check_wage_components_fail(>1%)"] += int((rel > 0.01).sum())
        qa["check_wage_components_tested"] += int(rel.notna().sum())
    if {"workers", "sex"} <= set(wide.columns):
        other = [k for k in keys if k != "sex"]
        p = wide.pivot_table(index=other, columns="sex", values="workers", aggfunc="first")
        if {"M", "F", "T"} <= set(p.columns):
            rel = ((p["M"] + p["F"]) - p["T"]).abs() / p["T"]
            qa["check_sex_sum_fail(>1%)"] += int((rel > 0.01).sum())
            qa["check_sex_sum_tested"] += int(rel.notna().sum())


def clean_kosis_table(name: str) -> tuple[pd.DataFrame | None, dict]:
    qa: Counter = Counter()
    files = sorted((RAW / name).glob("*.json"))
    if not files:
        return None, {"status": "no_raw_files"}
    long = pd.concat([kosis_to_long(json.loads(f.read_text(encoding="utf-8")), qa) for f in files], ignore_index=True)
    wide = standardize(long, qa)
    keys = [c for c in ("year", "occ", "ind", "edu", "age", "career", "sex") if c in wide]
    consistency_checks(wide, qa, keys)
    # 근로자수가 0/결측인 셀은 가중 분석에서 제외
    if "workers" in wide:
        bad = wide["workers"].isna() | (wide["workers"] <= 0)
        qa["cells_without_workers"] += int(bad.sum())
    # 시간당 임금(원) = 월임금총액 / 총근로시간
    if {"wage_total", "hours_total"} <= set(wide.columns):
        wide["hourly_wage"] = wide["wage_total"] / wide["hours_total"].replace(0, np.nan)
    if {"wage_fixed", "hours_regular"} <= set(wide.columns):
        wide["hourly_fixed"] = wide["wage_fixed"] / wide["hours_regular"].replace(0, np.nan)
    return wide, {"status": "ok", "years": sorted(wide["year"].unique().tolist()), "cells": len(wide), **dict(qa)}


# ---------------------------------------------------------------- 산업재해(산재보험 업종 → KSIC)
def load_crosswalk() -> list[tuple[str, str, str]]:
    cw = pd.read_csv(ROOT / "config" / "crosswalk_injury_industry.csv", dtype=str).fillna("")
    return [(r.level, norm_text(r.keyword), r.ksic) for r in cw.itertuples()]


def injury_to_ksic(big: str, mid: str, cw) -> str | None:
    b, m = norm_text(big), norm_text(mid)
    for level, kw, code in cw:  # 중업종 규칙 우선, 다음 대업종
        if level == "mid" and kw and kw in m:
            return code
    for level, kw, code in cw:
        if level == "big" and kw and kw in b:
            return code
    return None


def clean_injury_micro(manifest: dict) -> tuple[pd.DataFrame | None, dict]:
    qa: Counter = Counter()
    src = manifest.get("sources", {}).get("injury_micro", {}).get("files", {})
    frames = []
    for key, info in src.items():
        p = RAW / "injury_micro" / f"{key}.json"
        if not p.exists():
            continue
        df = pd.DataFrame(json.loads(p.read_text(encoding="utf-8")))
        ycol = next((c for c in df.columns if re.search(r"연도|년도|발생년", c)), None)
        if ycol:
            df["year"] = pd.to_numeric(df[ycol].astype(str).str[:4], errors="coerce")
        else:
            m = re.search(r"(20\d\d)", info.get("summary", ""))
            df["year"] = int(m.group(1)) if m else np.nan
        frames.append(df)
    if not frames:
        return None, {"status": "no_raw_files"}
    df = pd.concat(frames, ignore_index=True)
    qa["rows_in"] = len(df)
    col = lambda pat: next((c for c in df.columns if re.search(pat, c)), None)  # noqa: E731
    c_big, c_mid, c_sex, c_sev, c_kind = col("대업종"), col("중업종"), col("성별"), col("재해정도"), col("재해자구분")
    c_cnt = col(r"재해자\s*수|인원|건수")
    cw = load_crosswalk()
    df["ind"] = [injury_to_ksic(b, m, cw) for b, m in zip(df[c_big].fillna(""), df[c_mid].fillna("") if c_mid else [""] * len(df))]
    unm = df[df["ind"].isna()]
    for lab, n in (unm[c_mid] if c_mid else unm[c_big]).value_counts().items():
        qa[f"unmapped_industry[{lab}]"] += int(n)
    df["sex"] = df[c_sex].map(map_sex) if c_sex else "T"
    qa["unmapped_sex"] += int(df["sex"].isna().sum())
    df["n"] = pd.to_numeric(df[c_cnt], errors="coerce").fillna(1) if c_cnt else 1
    df["fatal"] = df[c_sev].astype(str).str.contains("사망") if c_sev else False
    df["disease"] = df[c_kind].astype(str).str.contains("질병") if c_kind else False
    df = df.dropna(subset=["ind", "sex", "year"])
    g = df.groupby(["year", "ind", "sex"])
    out = pd.DataFrame({
        "injured": g["n"].sum(),
        "fatal": g.apply(lambda x: x.loc[x["fatal"], "n"].sum()),
        "disease": g.apply(lambda x: x.loc[x["disease"], "n"].sum()),
    }).reset_index()
    qa["rows_out"] = len(out)
    return out, {"status": "ok", "years": sorted(out["year"].astype(int).unique().tolist()), **dict(qa)}


def load_manual(rel: str, required_cols: set[str]) -> tuple[pd.DataFrame | None, dict]:
    p = ROOT / rel
    if not p.exists():
        return None, {"status": "not_provided"}
    df = pd.read_csv(p)
    miss = required_cols - set(df.columns)
    if miss:
        return None, {"status": f"missing_columns {sorted(miss)}"}
    if "occ" in df:
        df["occ"] = df["occ"].astype(str).map(lambda s: s if s in KSCO else map_occ(s))
    if "ind" in df:
        df["ind"] = df["ind"].astype(str).map(lambda s: s if s in KSIC else map_ind(s))
    df["sex"] = df["sex"].map(map_sex)
    return df.dropna(subset=["sex"]), {"status": "ok", "rows": len(df)}


def run(log=print) -> dict:
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    manifest_p = META / "manifest.json"
    manifest = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.exists() else {}
    INTERIM.mkdir(parents=True, exist_ok=True)
    report = {}
    for name in cfg["kosis"]["tables"]:
        wide, qa = clean_kosis_table(name)
        report[name] = qa
        if wide is not None:
            wide.to_csv(INTERIM / f"{name}.csv", index=False, encoding="utf-8-sig")
        log(f"[clean] {name}: {qa.get('status')} cells={qa.get('cells')}")
    inj, qa = clean_injury_micro(manifest)
    report["injury_micro"] = qa
    if inj is not None:
        inj.to_csv(INTERIM / "injury_ind_sex.csv", index=False, encoding="utf-8-sig")
    else:  # API 미사용 시 수동 집계표
        inj, qa2 = load_manual(cfg["manual"]["injury_ind_sex"], {"year", "ind", "sex", "injured"})
        report["injury_manual"] = qa2
        if inj is not None:
            inj.to_csv(INTERIM / "injury_ind_sex.csv", index=False, encoding="utf-8-sig")
    kw, qa = load_manual(cfg["manual"]["kwcs_occ_sex"], {"year", "occ", "sex", "shift_rate", "night_rate"})
    report["kwcs"] = qa
    if kw is not None:
        kw.to_csv(INTERIM / "kwcs_occ_sex.csv", index=False, encoding="utf-8-sig")
    (META / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
