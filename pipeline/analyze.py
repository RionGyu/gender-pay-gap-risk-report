"""3단계: 분석. 정제 테이블로 격차 분해를 계산해 data/processed/results.json 으로 내보냅니다.

A. 현황:           성별 시간당 임금·월임금·근로시간, 연도별 추이
B. 직종 분리 효과:  시간가중 shift-share 분해 (직종 간 분포 차이 vs 동일 직종 내 임금 차이), 던컨 분리지수
C. 임금 구성 분해:  동일 직종 내 월임금 격차 = 정액급여 + 초과급여 + 특별급여 차이
D. 요인 분해:       셀(직종/산업×학력×연령×성) 가중 회귀 → 풀드(pooled) Oaxaca-Blinder 분해
                   설명요인 = 직종·산업 분리 / 인적자본(학력·연령·근속) / 초과근로 / 위험노출(재해율) / 교대·야간
E. 위험 vs 임금:    산업×성별 재해율(근로자 1만명당)과 시간당 임금 (버블 차트)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .clean import KSCO, KSIC

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "data" / "processed"
META = ROOT / "data" / "meta"

SHORT_OCC = {"1": "관리자", "2": "전문가", "3": "사무", "4": "서비스", "5": "판매", "6": "농림어업",
             "7": "기능원", "8": "장치·기계조작", "9": "단순노무"}
SHORT_IND = {"A": "농림어업", "B": "광업", "C": "제조업", "D": "전기·가스", "E": "수도·폐기물", "F": "건설업",
             "G": "도소매", "H": "운수·창고", "I": "숙박·음식", "J": "정보통신", "K": "금융·보험", "L": "부동산",
             "M": "전문·과학기술", "N": "사업시설·지원", "O": "공공행정", "P": "교육", "Q": "보건·사회복지",
             "R": "예술·여가", "S": "기타개인서비스"}


def _read(name: str) -> pd.DataFrame | None:
    p = INTERIM / f"{name}.csv"
    return pd.read_csv(p, dtype={"occ": str, "ind": str, "sex": str, "edu": str, "age": str}) if p.exists() else None


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


# ------------------------------------------------------------------ A. 현황
def headline(df: pd.DataFrame, dim: str) -> dict:
    tot = df[(df[dim] == "T") & (df["edu"] == "T") & (df["age"] == "T")]
    years = sorted(tot["year"].unique())
    trend = []
    for y in years:
        t = tot[tot["year"] == y].set_index("sex")
        if not {"M", "F"} <= set(t.index):
            continue
        trend.append({"year": int(y), "hourly_m": _r(t.at["M", "hourly_wage"], 0), "hourly_f": _r(t.at["F", "hourly_wage"], 0),
                      "ratio": _r(100 * t.at["F", "hourly_wage"] / t.at["M", "hourly_wage"])})
    y = years[-1]
    t = tot[tot["year"] == y].set_index("sex")
    g = lambda s, c: _r(t.at[s, c], 1) if c in t.columns else None  # noqa: E731
    return {
        "year": int(y),
        "hourly": {"M": g("M", "hourly_wage"), "F": g("F", "hourly_wage")},
        "monthly": {"M": g("M", "wage_total"), "F": g("F", "wage_total")},
        "hours_total": {"M": g("M", "hours_total"), "F": g("F", "hours_total")},
        "hours_overtime": {"M": g("M", "hours_overtime"), "F": g("F", "hours_overtime")},
        "wage_overtime": {"M": g("M", "wage_overtime"), "F": g("F", "wage_overtime")},
        "tenure": {"M": g("M", "tenure"), "F": g("F", "tenure")},
        "workers": {"M": g("M", "workers"), "F": g("F", "workers")},
        "hourly_ratio": _r(100 * t.at["F", "hourly_wage"] / t.at["M", "hourly_wage"]),
        "monthly_ratio": _r(100 * t.at["F", "wage_total"] / t.at["M", "wage_total"]),
        "trend": trend,
    }


# ------------------------------------------------------------------ B/C. 직종(산업) 분리 효과
def segregation(df: pd.DataFrame, dim: str, year: int, labels: dict) -> dict:
    d = df[(df["year"] == year) & (df["edu"] == "T") & (df["age"] == "T") & (df[dim] != "T") & df["sex"].isin(["M", "F"])].copy()
    d = d.dropna(subset=["workers", "hourly_wage", "hours_total"])
    d["hw"] = d["workers"] * d["hours_total"]  # 시간가중 → 집계 시간당임금과 정확히 일치
    p = d.pivot_table(index=dim, columns="sex", values=["hw", "workers", "hourly_wage", "hours_overtime",
                                                        "wage_total", "wage_fixed", "wage_overtime", "wage_special_m",
                                                        "hours_total"], aggfunc="first").dropna(subset=[("hourly_wage", "M"), ("hourly_wage", "F")])
    sm = p[("hw", "M")] / p[("hw", "M")].sum()
    sf = p[("hw", "F")] / p[("hw", "F")].sum()
    wm, wf = p[("hourly_wage", "M")], p[("hourly_wage", "F")]
    Wm, Wf = (sm * wm).sum(), (sf * wf).sum()
    between = ((sm - sf) * (wm + wf) / 2)
    within = ((sm + sf) / 2 * (wm - wf))
    em = p[("workers", "M")] / p[("workers", "M")].sum()
    ef = p[("workers", "F")] / p[("workers", "F")].sum()
    duncan = 0.5 * (em - ef).abs().sum()
    rows = []
    for k in p.index:
        fshare = p.at[k, ("workers", "F")] / (p.at[k, ("workers", "F")] + p.at[k, ("workers", "M")])
        comp = {}
        for c in ("wage_fixed", "wage_overtime", "wage_special_m"):
            if (c, "M") in p.columns:
                comp[c] = _r(p.at[k, (c, "M")] - p.at[k, (c, "F")], 0)
        hw_all = (p.at[k, ("hourly_wage", "M")] * p.at[k, ("hw", "M")] + p.at[k, ("hourly_wage", "F")] * p.at[k, ("hw", "F")]) / (p.at[k, ("hw", "M")] + p.at[k, ("hw", "F")])
        rows.append({
            "code": k, "name": labels.get(k, k),
            "female_share": _r(100 * fshare),
            "emp_share_m": _r(100 * em[k]), "emp_share_f": _r(100 * ef[k]),
            "hourly_m": _r(wm[k], 0), "hourly_f": _r(wf[k], 0), "hourly_all": _r(hw_all, 0),
            "ratio": _r(100 * wf[k] / wm[k]),
            "overtime_h_m": _r(p.at[k, ("hours_overtime", "M")]), "overtime_h_f": _r(p.at[k, ("hours_overtime", "F")]),
            "monthly_gap_components": comp,
            "between_contrib": _r(between[k], 0), "within_contrib": _r(within[k], 0),
        })
    # 월임금 격차 구성(직종 평균, 여성 고용가중): 정액 vs 초과 vs 특별
    comp_tot = {}
    for c in ("wage_fixed", "wage_overtime", "wage_special_m"):
        if (c, "M") in p.columns:
            comp_tot[c] = _r(((p[(c, "M")] - p[(c, "F")]) * (em + ef) / 2).sum(), 0)
    # 여성비중 vs 시간당임금 기울기(직종·산업 간): 여성비중 10%p 높을 때 임금 변화율
    x = np.array([r["female_share"] for r in rows], dtype=float)
    yv = np.log(np.array([r["hourly_all"] for r in rows], dtype=float))
    wts = np.array([p.at[r["code"], ("workers", "M")] + p.at[r["code"], ("workers", "F")] for r in rows], dtype=float)
    slope = _wls(np.c_[np.ones_like(x), x], yv, wts)[0][1] * 10 * 100
    return {
        "year": int(year), "gap_won": _r(Wm - Wf, 0), "W_m": _r(Wm, 0), "W_f": _r(Wf, 0),
        "between_won": _r(between.sum(), 0), "within_won": _r(within.sum(), 0),
        "between_pct": _r(100 * between.sum() / (Wm - Wf)), "within_pct": _r(100 * within.sum() / (Wm - Wf)),
        "duncan_index": _r(100 * duncan), "female_share_wage_slope_pct_per10pp": _r(slope, 2),
        "monthly_gap_components": comp_tot, "rows": sorted(rows, key=lambda r: -r["female_share"]),
    }


# ------------------------------------------------------------------ D. 가중회귀 + Oaxaca-Blinder
def _wls(X, y, w):
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    resid = y - X @ beta
    # HC1 강건 표준오차
    XtWX_inv = np.linalg.pinv((X * w[:, None]).T @ X)
    meat = (X * (w * resid)[:, None]).T @ (X * (w * resid)[:, None])
    n, k = X.shape
    V = XtWX_inv @ meat @ XtWX_inv * n / max(n - k, 1)
    return beta, np.sqrt(np.diag(V))


def oaxaca(cells: pd.DataFrame, groups: dict[str, list[str]], weight: str = "workers") -> dict:
    """pooled Oaxaca-Blinder (Fortin 2008 / Jann 2008: 성별 더미 포함 풀드 회귀계수 사용)."""
    cols = [c for g in groups.values() for c in g]
    d = cells.dropna(subset=cols + ["lnw", weight])
    d = d[d[weight] > 0]
    X = np.c_[np.ones(len(d)), d[cols].to_numpy(float), (d["sex"] == "F").to_numpy(float)]
    y = d["lnw"].to_numpy(float)
    w = d[weight].to_numpy(float)
    beta, se = _wls(X, y, w)
    m, f = (d["sex"] == "M").to_numpy(), (d["sex"] == "F").to_numpy()
    xm = np.average(X[m], axis=0, weights=w[m])
    xf = np.average(X[f], axis=0, weights=w[f])
    total = np.average(y[m], weights=w[m]) - np.average(y[f], weights=w[f])
    contrib = {}
    for g, cs in groups.items():
        idx = [1 + cols.index(c) for c in cs]
        contrib[g] = float(((xm[idx] - xf[idx]) * beta[idx]).sum())
    explained = sum(contrib.values())
    coef = {c: {"b": _r(beta[1 + i], 5), "se": _r(se[1 + i], 5)} for i, c in enumerate(cols) if not c.startswith(("d_",))}
    coef["female"] = {"b": _r(beta[-1], 5), "se": _r(se[-1], 5)}
    yhat = X @ beta
    r2 = 1 - np.average((y - yhat) ** 2, weights=w) / np.average((y - np.average(y, weights=w)) ** 2, weights=w)
    return {
        "n_cells": int(len(d)), "r2": _r(r2, 3),
        "total_log_gap": _r(total, 4), "total_pct": _r(100 * (1 - np.exp(-total))),  # 남성 대비 여성 임금이 낮은 정도(%)
        "contrib_log": {k: _r(v, 4) for k, v in contrib.items()},
        "contrib_share": {k: _r(100 * v / total) for k, v in contrib.items()},
        "unexplained_log": _r(total - explained, 4), "unexplained_share": _r(100 * (total - explained) / total),
        "coef": coef,
        "means": {c: {"M": _r(xm[1 + i], 4), "F": _r(xf[1 + i], 4)} for i, c in enumerate(cols) if not c.startswith("d_")},
    }


def build_cells(df: pd.DataFrame, dim: str, extra: pd.DataFrame | None = None, extra_on: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    d = df[(df[dim] != "T") & (df["edu"] != "T") & (df["age"] != "T") & df["sex"].isin(["M", "F"])].copy()
    d = d.dropna(subset=["hourly_wage", "workers"])
    d = d[(d["hourly_wage"] > 0) & (d["workers"] > 0)]
    d["lnw"] = np.log(d["hourly_wage"])
    d["ot_share"] = d["hours_overtime"] / d["hours_total"]
    groups: dict[str, list[str]] = {}
    for col, g in ((dim, "segregation"), ("edu", "human_capital"), ("age", "human_capital"), ("year", "year")):
        dums = pd.get_dummies(d[col].astype(str), prefix=f"d_{col}", drop_first=True, dtype=float)
        d = pd.concat([d, dums], axis=1)
        groups.setdefault(g, []).extend(dums.columns.tolist())
    if "tenure" in d and d["tenure"].notna().mean() > 0.9:
        groups["human_capital"].append("tenure")
    groups["working_time"] = ["ot_share"]
    if extra is not None:
        d = d.merge(extra, on=extra_on, how="left")
    return d, groups


# ------------------------------------------------------------------ E. 산업×성 재해율
def injury_rates(wage_ind: pd.DataFrame, inj: pd.DataFrame) -> pd.DataFrame:
    w = wage_ind[(wage_ind["edu"] == "T") & (wage_ind["age"] == "T") & (wage_ind["ind"] != "T") & wage_ind["sex"].isin(["M", "F"])]
    w = w[["year", "ind", "sex", "workers", "hourly_wage", "hours_overtime", "hours_total"]]
    inj = inj.copy()
    inj["ind"] = inj["ind"].astype(str)
    m = w.merge(inj, on=["year", "ind", "sex"], how="inner")
    m["injury_rate"] = 10000 * m["injured"] / m["workers"]  # 근로자 1만명당
    if "fatal" in m:
        m["fatal_rate"] = 10000 * m["fatal"] / m["workers"]
    return m


def run(log=print) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    occ, ind = _read("wage_occ"), _read("wage_ind")
    inj, kwcs = _read("injury_ind_sex"), _read("kwcs_occ_sex")
    res: dict = {"meta": {}}
    if occ is None:
        raise SystemExit("wage_occ 정제 테이블이 없습니다. collect/clean 단계를 먼저 실행하세요.")
    res["headline"] = headline(occ, "occ")
    year = res["headline"]["year"]
    res["seg_occ"] = segregation(occ, "occ", year, SHORT_OCC)
    if ind is not None:
        res["seg_ind"] = segregation(ind, "ind", int(ind["year"].max()), SHORT_IND)

    # D-1. 직종 모형 (최근 3개년 풀링, 연도 더미)
    occ_recent = occ[occ["year"] >= year - 2]
    extra = None
    if kwcs is not None:
        extra = kwcs[["year", "occ", "sex", "shift_rate", "night_rate"]].copy()
    cells, groups = build_cells(occ_recent, "occ", extra, ["year", "occ", "sex"] if extra is not None else None)
    if extra is not None and cells[["shift_rate", "night_rate"]].notna().mean().min() > 0.8:
        groups["shift_night"] = ["shift_rate", "night_rate"]
    groups.pop("year", None)
    yd = [c for c in cells.columns if c.startswith("d_year")]
    groups_occ = {**groups, "_year": yd}
    res["oaxaca_occ"] = oaxaca(cells, groups_occ)
    res["oaxaca_occ"]["years"] = sorted(int(v) for v in occ_recent["year"].unique())

    # D-2. 산업 모형 + 산업×성 재해율 (재해 자료가 있을 때)
    if ind is not None and inj is not None:
        rates = injury_rates(ind, inj)
        res["bubble"] = [{"year": int(r.year), "ind": r.ind, "name": SHORT_IND.get(r.ind, r.ind), "sex": r.sex,
                          "workers": _r(r.workers, 0), "hourly": _r(r.hourly_wage, 0),
                          "injury_rate": _r(r.injury_rate, 2), "fatal_rate": _r(getattr(r, "fatal_rate", np.nan), 3),
                          "overtime_h": _r(r.hours_overtime, 1)}
                         for r in rates.itertuples() if r.year == rates["year"].max()]
        iy = sorted(set(rates["year"]))
        ind_recent = ind[ind["year"].isin(iy[-3:])]
        risk = rates[["year", "ind", "sex", "injury_rate"]].copy()
        risk["injury_rate"] = risk["injury_rate"] / 10  # 1,000명당으로 스케일(계수 해석 편의)
        cells_i, groups_i = build_cells(ind_recent, "ind", risk, ["year", "ind", "sex"])
        groups_i["risk"] = ["injury_rate"]
        groups_i.pop("year", None)
        groups_i["_year"] = [c for c in cells_i.columns if c.startswith("d_year")]
        res["oaxaca_ind"] = oaxaca(cells_i, groups_i)
        res["oaxaca_ind"]["years"] = [int(v) for v in iy[-3:]]
        b = res["oaxaca_ind"]["coef"]["injury_rate"]["b"]
        res["oaxaca_ind"]["risk_premium_pct_per_1permille"] = _r(100 * (np.exp(b) - 1), 2) if b is not None else None

    manifest = json.loads((META / "manifest.json").read_text(encoding="utf-8")) if (META / "manifest.json").exists() else {}
    quality = json.loads((META / "quality_report.json").read_text(encoding="utf-8")) if (META / "quality_report.json").exists() else {}
    res["meta"] = {"manifest": manifest, "quality": quality, "sample_data": bool(manifest.get("sample_data"))}
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[analyze] year={year} hourly_ratio={res['headline']['hourly_ratio']}%")
    return res
