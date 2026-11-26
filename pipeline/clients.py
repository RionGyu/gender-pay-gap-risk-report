"""공공데이터 API 클라이언트 (KOSIS 공유서비스, 공공데이터포털 odcloud).

- 인증키는 환경변수로만 받습니다: KOSIS_API_KEY, DATA_GO_KR_KEY
- 재시도(지수 백오프), 응답 오류코드 해석, 키가 로그에 찍히지 않도록 마스킹합니다.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

UA = "gender-pay-gap-risk-report/1.0 (public statistics pipeline)"


class ApiError(RuntimeError):
    pass


def _mask(text: str) -> str:
    """URL·메시지에 섞인 인증키를 가립니다."""
    for env in ("KOSIS_API_KEY", "DATA_GO_KR_KEY"):
        key = os.environ.get(env)
        if key:
            text = text.replace(key, "***")
    return re.sub(r"(apiKey|serviceKey)=[^&\s]+", r"\1=***", text)


def _get(url: str, params: dict[str, Any], *, retries: int = 4, timeout: int = 60) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA})
            if r.status_code in (429, 500, 502, 503, 504):
                raise ApiError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException, ApiError) as e:  # noqa: PERF203
            last = e
            time.sleep(2 ** attempt)
    raise ApiError(_mask(f"GET {url} 실패: {last}"))


# --------------------------------------------------------------------------- KOSIS
KOSIS_ERRORS = {
    "10": "인증키 누락",
    "11": "인증키 기간만료",
    "20": "필수요청변수 누락",
    "21": "잘못된 요청변수",
    "30": "조회결과 없음",
    "31": "조회결과 초과(4만 셀)",
    "40": "호출가능건수 제한",
    "41": "호출가능 ROW수 제한",
    "42": "사용자별 이용 제한",
    "50": "서버오류",
}


class Kosis:
    def __init__(self, base_url: str = "https://kosis.kr/openapi", api_key: str | None = None):
        self.base = base_url.rstrip("/")
        self.key = api_key or os.environ.get("KOSIS_API_KEY")
        if not self.key:
            raise ApiError("환경변수 KOSIS_API_KEY 가 없습니다 (https://kosis.kr/openapi 에서 발급).")

    def _call(self, path: str, params: dict[str, Any]) -> list[dict]:
        params = {"apiKey": self.key, "format": "json", "jsonVD": "Y", **params}
        r = _get(f"{self.base}/{path}", params)
        text = r.text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ApiError(_mask(f"KOSIS JSON 파싱 실패: {text[:200]}")) from e
        if isinstance(data, dict) and "err" in data:
            code = str(data.get("err"))
            if code == "30":
                return []
            raise ApiError(f"KOSIS 오류 {code} ({KOSIS_ERRORS.get(code, '?')}): {data.get('errMsg')}")
        return data if isinstance(data, list) else [data]

    # 통계표 데이터 (분류값·항목 전체)
    def table(self, org_id: str, tbl_id: str, *, dims: int, prd_se: str, start: str, end: str) -> list[dict]:
        """4만 셀을 넘으면(오류 31) 항목(itmId)을 나눠서 다시 호출합니다."""
        try:
            return self._table(org_id, tbl_id, dims=dims, prd_se=prd_se, start=start, end=end, itm="ALL")
        except ApiError as e:
            if "오류 31" not in str(e):
                raise
        items = self.item_ids(org_id, tbl_id)
        if len(items) < 2:
            raise ApiError(f"{tbl_id}: 4만 셀 초과인데 항목 목록을 얻지 못했습니다")
        out: list[dict] = []
        queue = [items]
        while queue:
            chunk = queue.pop(0)
            try:
                out.extend(self._table(org_id, tbl_id, dims=dims, prd_se=prd_se, start=start, end=end,
                                       itm="+".join(chunk) + "+"))
            except ApiError as e:
                if "오류 31" not in str(e) or len(chunk) == 1:
                    raise
                mid = len(chunk) // 2
                queue[:0] = [chunk[:mid], chunk[mid:]]
        return out

    def item_ids(self, org_id: str, tbl_id: str) -> list[str]:
        rows = self.meta(org_id, tbl_id, "ITM")
        ids = [str(r["ITM_ID"]) for r in rows
               if r.get("ITM_ID") and (str(r.get("OBJ_ID", "")).upper() == "ITEM" or "항목" in str(r.get("OBJ_NM", "")))]
        return list(dict.fromkeys(ids))

    def _table(self, org_id: str, tbl_id: str, *, dims: int, prd_se: str, start: str, end: str, itm: str) -> list[dict]:
        params = {
            "method": "getList",
            "orgId": org_id,
            "tblId": tbl_id,
            "itmId": itm,
            "prdSe": prd_se,
            "startPrdDe": start,
            "endPrdDe": end,
        }
        for i in range(1, dims + 1):
            params[f"objL{i}"] = "ALL"
        return self._call("Param/statisticsParameterData.do", params)

    # 통계표 메타(분류·항목, 수록기간)
    def meta(self, org_id: str, tbl_id: str, kind: str) -> list[dict]:
        return self._call("statisticsData.do", {"method": "getMeta", "type": kind, "orgId": org_id, "tblId": tbl_id})

    def latest_period(self, org_id: str, tbl_id: str, *, dims: int = 4, prd_se: str = "Y", log=print) -> str | None:
        """최신 수록시점. 메타(PRD) → 실패 시 '최근 1개 시점' 데이터 호출(newEstPrdCnt=1)로 확인."""
        try:
            rows = self.meta(org_id, tbl_id, "PRD")
        except ApiError as e:
            rows = []
            log(f"[info] {tbl_id} PRD 메타 오류: {e}")
        periods = sorted(str(r.get("PRD_DE") or r.get("END_PRD_DE") or "") for r in rows)
        periods = [p for p in periods if p[:4].isdigit()]
        if periods:
            return periods[-1]
        log(f"[info] {tbl_id} PRD 메타 응답 형식 미일치 → 최신 1개 시점 조회로 대체 (응답 예: {str(rows[:2])[:200]})")
        params = {"method": "getList", "orgId": org_id, "tblId": tbl_id, "itmId": "ALL", "prdSe": prd_se, "newEstPrdCnt": "1"}
        for i in range(1, dims + 1):
            params[f"objL{i}"] = "ALL"
        data = self._call("Param/statisticsParameterData.do", params)
        got = sorted(str(r.get("PRD_DE")) for r in data if r.get("PRD_DE"))
        return got[-1] if got else None

    # 통합검색
    def search(self, keyword: str, rows: int = 50) -> list[dict]:
        return self._call("statisticsSearch.do", {"method": "getList", "searchNm": keyword, "resultCount": rows})


# --------------------------------------------------------------------------- data.go.kr (odcloud)
class Odcloud:
    def __init__(self, base_url: str, swagger_url: str, api_key: str | None = None):
        self.base = base_url.rstrip("/")
        self.swagger = swagger_url
        self.key = api_key or os.environ.get("DATA_GO_KR_KEY")
        if not self.key:
            raise ApiError("환경변수 DATA_GO_KR_KEY 가 없습니다 (https://www.data.go.kr 에서 발급·활용신청).")

    def endpoints(self, dataset_id: str) -> list[tuple[str, str]]:
        """파일데이터 자동변환 API의 (경로, 설명) 목록. 설명에 기준연도가 들어 있습니다."""
        r = _get(self.swagger.format(dataset_id=dataset_id), {})
        spec = r.json()
        out = []
        for path, ops in spec.get("paths", {}).items():
            op = ops.get("get", {}) if isinstance(ops, dict) else {}
            out.append((path, f"{op.get('summary', '')} {op.get('description', '')}".strip()))
        return sorted(out)

    def fetch_all(self, path: str, per_page: int = 1000) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            r = _get(f"{self.base}{path}" if path.startswith("/") else f"{self.base}/{path}",
                     {"page": page, "perPage": per_page, "serviceKey": self.key, "returnType": "JSON"})
            body = r.json()
            data = body.get("data", [])
            out.extend(data)
            total = body.get("totalCount") or body.get("matchCount") or 0
            if not data or len(out) >= total:
                break
            page += 1
        return out
