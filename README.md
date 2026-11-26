# 같은 일, 다른 임금? 성별 임금격차의 위험·근무부담 구조 분석

> 단순 평균 임금격차(‘몇 대 몇’)를 넘어, **직종 선택의 차이**와 **동일 직무 내 초과근로·산업재해 위험 노출**을 통제했을 때
> 성별 임금격차가 얼마나 설명되고 얼마나 남는지를 공공데이터로 분해한 정책 브리핑 리포트입니다.

- 📄 **리포트**: [`docs/index.html`](docs/index.html) (GitHub Pages로 공개, 단일 HTML · 오프라인·인쇄 가능)
- 🎯 **관련 부처**: 고용노동부, 성평등가족부, 국가데이터처
- 🔄 **원클릭 재수집**: 새 연도 통계가 공표되면 GitHub Actions에서 「Run workflow」 한 번으로 API 수집 → 정제 → 분석 → 리포트(수치·문장·차트)를 다시 생성

## 리포트 구성

1. **정책 요약(Executive Summary)** — 현황(문제) → 데이터 분석 결과 → 정책 제언, 1페이지
2. 현황: 성별 시간당 임금격차의 크기와 추이
3. 직종 분리 효과 — 직종별 여성 비중·임금, 던컨 분리지수, shift-share 분해
4. 동일 직무 내 초과근로·위험 보상 — 급여 항목별(정액/초과/특별) 격차, 초과근로시간
5. **임금 vs 산업재해율 버블 차트** — 산업×성별
6. **격차 요인 분해 폭포수 차트** — 풀드 Oaxaca-Blinder
7. 정책 제언(원인 → 근거지표 → 정책수단 → 소관부처)
8. 데이터 수집·정제 파이프라인, 품질 리포트, 방법론과 한계

## 데이터 수집·정제 자동화 파이프라인

```
config/sources.yaml ─▶ ① collect ─▶ data/raw (API 원본, 연도별 JSON + manifest)
                       ② clean   ─▶ data/interim (표준 코드 테이블) + data/meta/quality_report.json
                       ③ analyze ─▶ data/processed/results.json
                       ④ report  ─▶ docs/index.html
```

| 단계 | 처리 내용 |
|---|---|
| 수집 | KOSIS 공유서비스 OpenAPI(4만 셀 제한 대응 연도 분할 호출, 최신 수록연도 자동 탐지, 증분 수집), 공공데이터포털 파일데이터 자동변환 API(odcloud), 재시도·오류코드 해석·키 마스킹 |
| 정제 | 결측·비공개 기호(`-`, `x`, `…`) 처리 및 건수 기록 · 통계표마다 다른 분류 순서(C1~C4)를 분류명으로 자동 식별 · 연도별 직종·산업 명칭 흔들림(띄어쓰기, 가운뎃점, 코드 접두어) → KSCO/KSIC 표준코드 · **산재보험 업종 → KSIC 대분류 교차표**(`config/crosswalk_injury_industry.csv`) · 천원→원 단위 통일 |
| 검증 | 월임금총액 = 정액+초과+특별/12 대조, 남+여 = 전체 근로자수 대조, 미매핑 라벨·중복 집계 리포트 |
| 분석 | 시간가중 shift-share 분해, 던컨 분리지수, 셀 가중 회귀 + 풀드 Oaxaca-Blinder, 산업×성별 재해율 결합 |
| 리포트 | 결과 수치로 본문 문장·차트를 자동 생성하는 단일 HTML (외부 CDN 없음, 다크모드·인쇄 대응, 차트별 표 보기) |

## 사용 데이터

| 자료 | 출처 | 수집 방식 |
|---|---|---|
| 고용형태별근로실태조사: 직종·학력·연령·성별 임금 및 근로조건 (`DT_118N_PAYM42`) | 고용노동부 / KOSIS | KOSIS OpenAPI |
| 고용형태별근로실태조사: 산업·학력·연령·성별 임금 및 근로조건 (`DT_118N_PAYN42`) | 고용노동부 / KOSIS | KOSIS OpenAPI |
| 산업재해통계 마이크로데이터 (업종·성별·재해정도) | 한국산업안전보건공단 / 공공데이터포털 15127634 | odcloud API |
| 근로환경조사 직종×성별 교대·야간 비율 | 안전보건공단 | `data/manual/` 수동 입력(선택) |

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env            # 키 입력 (커밋 금지, .gitignore 처리됨)
export $(cat .env | xargs)
python -m pipeline.run all --discover   # 수집→정제→분석→리포트
python -m pipeline.run offline          # 수집 없이 기존 원본으로 재생성
python -m unittest discover -s tests    # 테스트 (네트워크 불필요)
```

GitHub Actions에서 돌리려면 저장소 **Settings → Secrets and variables → Actions**에 `KOSIS_API_KEY`(필수), `DATA_GO_KR_KEY`(선택)를 등록하고,
**Settings → Pages → Source**를 `GitHub Actions`로 설정합니다. API 키는 코드·로그 어디에도 남지 않습니다.

## 방법론 요약과 한계

- 시간당 임금 = 월 임금총액 ÷ 월 총근로시간. 집계는 근로자 수×근로시간 가중
- 요인분해: `ln(시간당임금) = 직종(산업)·학력·연령·연도 더미 + 평균근속 + 초과근로 비중 + 재해율(산업×성별) + 여성 더미`, 근로자 수 가중 WLS, HC1 표준오차, 풀드 계수 Oaxaca-Blinder (Fortin 2008; Jann 2008)
- 한계: 개인 원자료가 아닌 공표 집계 셀 분석 · 재해율의 분자·분모 출처가 달라 교차표 기반 추정 · 재해율은 산업×성별 수준 변수라 상관 추정치
