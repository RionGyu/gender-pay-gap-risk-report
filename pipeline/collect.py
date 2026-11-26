"""1단계: 수집. 설정(config/sources.yaml)에 정의된 통계표를 API로 받아 data/raw 에 원본 그대로 저장합니다.

- 연도별로 분할 호출(KOSIS 4만 셀 제한 대응)
- end_year: latest → 통계표 메타(PRD)에서 최신 수록연도를 조회해 자동 확장
- 이미 받은 과거 연도는 건너뛰고(증분 수집), 최신 연도는 항상 재수집(잠정치 수정 반영)
- 수집 결과를 data/meta/manifest.json 에 기록(행 수, 해시, 수집시각)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import yaml

from .clients import ApiError, Kosis, Odcloud

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
META = ROOT / "data" / "meta"


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))


def _write_json(path: Path, obj) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=0)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _manifest() -> dict:
    p = META / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"sources": {}}


def collect_kosis(cfg: dict, manifest: dict, log) -> None:
    kc = cfg["kosis"]
    api = Kosis(kc["base_url"])
    for name, t in kc["tables"].items():
        try:
            _collect_table(api, name, t, manifest, log)
        except ApiError as e:
            have_raw = any((RAW / name).glob("*.json"))
            if t.get("required") and not have_raw:
                raise
            # 서버 장애·일시 차단 시: 이전에 받은 원본으로 계속 진행(다음 실행에서 재시도)
            log(f"[warn] {name}: 수집 실패, 기존 원본 사용 - {e}")


def _collect_table(api: Kosis, name: str, t: dict, manifest: dict, log) -> None:
    try:
        latest = api.latest_period(t["org_id"], t["tbl_id"], dims=t["dims"], prd_se=t["period"], log=log) if t["end_year"] == "latest" else str(t["end_year"])
    except ApiError as e:
        if t.get("required"):
            raise
        log(f"[skip] {name}: 메타 조회 실패 - {e}")
        return
    if not latest:
        log(f"[skip] {name}: 수록기간 없음")
        return
    end = int(str(latest)[:4])
    entry = manifest["sources"].setdefault(name, {"title": t["title"], "tbl_id": t["tbl_id"], "files": {}})
    entry["latest_period"] = latest
    for year in range(int(t["start_year"]), end + 1):
        out = RAW / name / f"{year}.json"
        if out.exists() and year < end:
            continue  # 확정된 과거 연도는 재수집하지 않음
        try:
            rows = api.table(t["org_id"], t["tbl_id"], dims=t["dims"], prd_se=t["period"], start=str(year), end=str(year))
        except ApiError as e:
            if t.get("required"):
                raise
            log(f"[skip] {name} {year}: {e}")
            continue
        if not rows:
            log(f"[warn] {name} {year}: 0행")
            continue
        digest = _write_json(out, rows)
        entry["files"][str(year)] = {"rows": len(rows), "sha256_16": digest,
                                     "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        log(f"[ok] {name} {year}: {len(rows):,}행")


def collect_odcloud(cfg: dict, manifest: dict, log) -> None:
    oc = cfg["data_go_kr"]
    try:
        api = Odcloud(oc["odcloud_base"], oc["swagger_url"])
    except ApiError as e:
        log(f"[skip] 공공데이터포털: {e}")
        return
    for name, d in oc["datasets"].items():
        try:
            paths = api.endpoints(d["dataset_id"])
        except Exception as e:  # noqa: BLE001
            log(f"[skip] {name}: 엔드포인트 조회 실패 - {e}")
            continue
        entry = manifest["sources"].setdefault(name, {"title": d["title"], "dataset_id": d["dataset_id"], "files": {}})
        for i, (path, summary) in enumerate(paths):
            key = path.rsplit("/", 1)[-1].replace(":", "_")
            if key in entry["files"] and i < len(paths) - 1:
                continue  # 과거 파일은 증분 수집에서 제외
            try:
                rows = api.fetch_all(path)
            except ApiError as e:
                log(f"[warn] {name} {path}: {e}")
                continue
            digest = _write_json(RAW / name / f"{key}.json", rows)
            entry["files"][key] = {"endpoint": path, "summary": summary, "rows": len(rows), "sha256_16": digest,
                                   "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            log(f"[ok] {name} [{i + 1}/{len(paths)}] {len(rows):,}행")


def discover(cfg: dict, log) -> None:  # noqa: C901
    """위치 미확정 통계표(근로환경조사, 산업재해 직종·성별) 키워드 검색 결과를 저장."""
    api = Kosis(cfg["kosis"]["base_url"])
    found = {}
    for kw in cfg["kosis"]["discovery_keywords"]:
        try:
            rows = api.search(kw)
        except ApiError as e:
            log(f"[warn] 검색 '{kw}': {e}")
            if "timed out" in str(e) or "Max retries" in str(e):
                log("[warn] KOSIS 연결 불가 → 탐색 중단")
                break
            continue
        found[kw] = [{k: r.get(k) for k in ("ORG_ID", "ORG_NM", "TBL_ID", "TBL_NM", "STAT_ID", "STRT_PRD_DE", "END_PRD_DE")}
                     for r in rows]
        log(f"[ok] 검색 '{kw}': {len(rows)}건")
    meta = {}
    for name, t in cfg["kosis"]["tables"].items():
        try:
            meta[name] = {k: api.meta(t["org_id"], t["tbl_id"], k) for k in ("ITM", "PRD")}
        except ApiError as e:
            meta[name] = {"error": str(e)}
    _write_json(META / "discovery.json", {"search": found, "table_meta": meta})


def run(log=print, do_discover: bool = False) -> None:
    cfg = load_config()
    manifest = _manifest()
    if do_discover:
        discover(cfg, log)
    collect_kosis(cfg, manifest, log)
    collect_odcloud(cfg, manifest, log)
    manifest["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _write_json(META / "manifest.json", manifest)
