"""4단계: 리포트. results.json 을 읽어 단일 HTML(docs/index.html)을 만듭니다.

본문 문장은 분석 결과 수치로 자동 작성되며, 매년 데이터가 갱신되면 문장도 함께 바뀝니다.
외부 CDN·폰트에 의존하지 않는 자체 완결형 파일이라 오프라인·인쇄(PDF)로도 그대로 쓸 수 있습니다.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = Path(__file__).with_name("templates") / "report.html"
OUT = ROOT / "docs" / "index.html"

TITLE = "같은 일, 다른 임금? 성별 임금격차의 위험·근무부담 구조 분석"


def f0(v):
    return "–" if v is None else f"{v:,.0f}"


def f1(v):
    return "–" if v is None else f"{v:,.1f}"


def e(s) -> str:
    return html.escape(str(s))


def sig(c: dict | None) -> bool:
    return bool(c and c.get("se") and c.get("b") is not None and abs(c["b"] / c["se"]) >= 1.96)


def li(items, cls=""):
    return "<ul>" + "".join(f'<li class="{cls}">{x}</li>' if cls else f"<li>{x}</li>" for x in items) + "</ul>"


def build(res: dict) -> str:
    H, S = res["headline"], res["seg_occ"]
    SI = res.get("seg_ind")
    O = res["oaxaca_occ"]                      # 주 모형: 직종(전 산업 포괄)
    OI = res.get("oaxaca_ind")                 # 보조 모형: 산업 + 산업×성별 재해율
    if OI and (OI.get("coverage_pct") or 0) < 80:
        OI = None                              # 재해 자료가 일부 업종뿐이면 요약 수치에 쓰지 않음
    cs = O["contrib_share"]
    seg_sh, hc_sh, ten_sh, wt_sh = cs.get("segregation"), cs.get("human_capital"), cs.get("tenure"), cs.get("working_time")
    sn_sh, un_sh = cs.get("shift_night"), O["unexplained_share"]
    risk_sh = OI["contrib_share"].get("risk") if OI else None
    risk_c = OI["coef"].get("injury_rate") if OI else None
    prem = OI.get("risk_premium_pct_per_1permille") if OI else None
    year = H["year"]
    ot_m, ot_f = H["hours_overtime"]["M"], H["hours_overtime"]["F"]
    ten_m, ten_f = H["tenure"]["M"], H["tenure"]["F"]
    trend = H["trend"]
    first = trend[0] if trend else None
    sample = res["meta"].get("sample_data")
    burden = (wt_sh or 0) + (risk_sh or 0) + (sn_sh or 0)
    seg_small = (S["between_pct"] or 0) < 15
    worst_ind = min(SI["rows"], key=lambda r: r["ratio"]) if SI else None
    worst_occ = min(S["rows"], key=lambda r: r["ratio"])
    blocks = {"근속 차이(경력단절)": ten_sh or 0, "직종 분리": max(seg_sh or 0, 0),
              "초과근로·위험 등 근무부담": burden, "설명되지 않는 동일 조건 내 격차": un_sh or 0}
    order = sorted(blocks, key=lambda k: -blocks[k])

    tiles = f"""<div class="tiles">
  <div class="tile"><div class="lab">여성 시간당 임금 (남성=100)</div><div class="val">{f1(H['hourly_ratio'])}</div><div class="note">{year}년 · 월임금총액 기준 {f1(H['monthly_ratio'])}</div></div>
  <div class="tile"><div class="lab">근속 차이로 설명되는 몫</div><div class="val">{f0(ten_sh)}%</div><div class="note">평균 근속 남 {f1(ten_m)}년 · 여 {f1(ten_f)}년</div></div>
  <div class="tile"><div class="lab">초과근로·위험 노출로 설명되는 몫</div><div class="val">{f0(burden)}%</div><div class="note">초과근로 {f1(wt_sh)}%{f' · 재해위험 {f1(risk_sh)}%' if risk_sh is not None else ''}</div></div>
  <div class="tile"><div class="lab">설명되지 않는 격차</div><div class="val">{f0(un_sh)}%</div><div class="note">같은 직종·학력·연령·근속·초과근로 조건</div></div>
</div>"""

    trend_sent = ""
    if first and first["year"] != year:
        d = H["hourly_ratio"] - first["ratio"]
        trend_sent = f" {first['year']}년({f1(first['ratio'])}%) 대비 {abs(d):.1f}%p {'좁혀졌으나 여전히 큰 격차' if d > 0 else '벌어진 상태'}"

    if seg_small:
        seg_txt = (f"<b>(직종 분리)</b> 남녀 직종 분포는 다르지만(던컨 분리지수 {f1(S['duncan_index'])}), 여성 비중이 높은 사무·전문가 직종의 임금이 평균 이상이어서 "
                   f"직종 대분류 간 분포 차이로 설명되는 몫은 <b>{f0(S['between_pct'])}%</b>에 불과. 격차는 대부분 <b>같은 직종 안에서</b> 발생"
                   + (f"(예: {e(worst_ind['name'])}업 여성 시급은 남성의 {f0(worst_ind['ratio'])}%)" if worst_ind else ""))
    else:
        seg_txt = (f"<b>(직종 분리)</b> 남녀의 직종 분포 차이(던컨 분리지수 {f1(S['duncan_index'])})가 시간당 임금격차의 <b>{f0(S['between_pct'])}%</b>를 설명. "
                   f"여성 비중이 10%p 높은 직종일수록 평균 시간당 임금이 {f1(abs(S['female_share_wage_slope_pct_per10pp']))}% 낮음")
    risk_txt = ""
    if risk_sh is not None:
        risk_txt = (f", 같은 산업 안 남녀의 재해위험 차이는 <b>{f1(risk_sh)}%</b>"
                    f"(재해율 1‰p당 임금 {'+' if (prem or 0) >= 0 else ''}{f1(prem)}%, {'통계적으로 유의' if sig(risk_c) else '통계적으로 유의하지 않음'})")
    exec_body = f"""
<div class="box-title">□ 현황(문제)</div>
{li([
    f"{year}년 여성 근로자의 시간당 임금총액은 <b>{f0(H['hourly']['F'])}원</b>으로 남성({f0(H['hourly']['M'])}원)의 <b>{f1(H['hourly_ratio'])}%</b>이며,{trend_sent}임",
    f"남성은 월 초과근로 {f1(ot_m)}시간으로 여성({f1(ot_f)}시간)의 약 {ot_m / ot_f:.1f}배이고 고위험 업종 비중도 높아, ‘남성 임금이 높은 것은 장시간·위험 노동의 대가’라는 해석과 ‘같은 일을 해도 덜 받는다’는 해석이 맞서 있음",
    "두 해석은 처방이 다르므로(안전보건·근로시간 정책 vs 직무가치 재평가·동일임금 점검), 격차를 원인별로 분리해 정책 자원을 배분할 필요",
])}
<div class="box-title">□ 데이터 분석 결과</div>
{li([
    seg_txt,
    f"<b>(근속·경력)</b> 같은 직종·학력·연령대 안에서도 여성의 평균 근속이 짧아({f1(ten_f)}년 vs {f1(ten_m)}년) 격차의 <b>{f0(ten_sh)}%</b>를 설명 → 출산·육아기 경력단절이 근속 연동 임금체계를 통해 임금격차로 이어짐",
    f"<b>(근무부담 보상)</b> 초과근로 비중 차이는 격차의 <b>{f1(wt_sh)}%</b>{risk_txt}만 설명 → ‘위험·장시간 노동 보상’ 가설로 설명되는 부분은 작음" + (f", 교대·야간근무 차이는 {f1(sn_sh)}%" if sn_sh is not None else ""),
    f"<b>(동일 조건 내 격차)</b> 같은 직종·학력·연령대·근속·초과근로 조건을 맞춰도 격차의 <b>{f0(un_sh)}%</b>가 남음 → 동일노동 동일임금 점검이 필요한 영역",
])}
<div class="box-title">□ 정책 제언</div>
{li([
    f"<b>(경력단절 예방·근속 격차 완화)</b> 육아휴직·근로시간 단축 기간의 근속·호봉 인정 의무화 점검, 남성 육아휴직 확대로 경력단절의 성별 편중 완화 <span class='kicker'>고용노동부·성평등가족부</span>",
    "<b>(동일노동 동일임금 점검)</b> 동일 조건 내 잔여 격차를 매년 같은 방식으로 산출해 성별임금 공시·적극적고용개선조치(AA) 사업장 점검 지표로 활용 <span class='kicker'>고용노동부</span>",
    "<b>(직무가치 재평가)</b> 같은 직종 안에서 여성이 몰린 하위 직무(예: 보건·복지의 돌봄·간호 보조)의 가치를 숙련·책임·노력·작업조건 기준으로 재평가, 사회서비스 임금 가이드라인부터 적용 <span class='kicker'>성평등가족부·고용노동부</span>",
    "<b>(안전보건·근로시간)</b> 위험·장시간 노동에 대한 임금 보상은 격차의 작은 부분 → 위험수당보다 고위험 업종의 재해 자체를 줄이는 투자, 초과근로 의존 임금구조 개선이 우선 <span class='kicker'>고용노동부·한국산업안전보건공단</span>",
    "<b>(통계 인프라)</b> 임금 통계의 직종 중·소분류×성별 공표, 산재통계의 직종×성별 공표로 같은 직무 단위 비교 가능하게 <span class='kicker'>국가데이터처</span>",
])}
<p class="kicker" style="margin-top:10px">요인별 비중 순위: {' > '.join(order)}</p>"""

    s1_text = f"""<p>고용형태별근로실태조사({year}년 6월 기준)에서 여성의 시간당 임금총액은 남성의 <b>{f1(H['hourly_ratio'])}%</b>, 월 임금총액은 <b>{f1(H['monthly_ratio'])}%</b>입니다. 월 기준 격차가 더 큰 것은 여성의 근로시간이 짧기 때문이므로, 이 리포트는 근로시간 차이를 걸러낸 <b>시간당 임금</b>을 기본 지표로 씁니다.</p>"""
    rows = [("시간당 임금총액(원)", "hourly", f0), ("월 임금총액(원)", "monthly", f0), ("월 총근로시간", "hours_total", f1),
            ("월 초과근로시간", "hours_overtime", f1), ("월 초과급여(원)", "wage_overtime", f0), ("평균 근속(년)", "tenure", f1)]
    s1_table = ('<div class="card tbl-wrap"><table><tr><th>' + f"{year}년" + "</th><th>남성</th><th>여성</th><th>여성/남성</th></tr>" +
                "".join(f"<tr><td>{lab}</td><td>{fn(H[k]['M'])}</td><td>{fn(H[k]['F'])}</td><td>"
                        f"{f1(100 * H[k]['F'] / H[k]['M']) + '%' if H[k]['M'] and H[k]['F'] is not None else '–'}</td></tr>" for lab, k, fn in rows) +
                "</table></div>")

    top_f = [r for r in S["rows"] if r["female_share"] >= 45]
    s2_text = f"""<p>남녀 직종 분포가 얼마나 다른지 보여주는 <b>던컨 분리지수는 {f1(S['duncan_index'])}</b>입니다(여성 또는 남성의 {f1(S['duncan_index'])}%가 직종을 옮겨야 분포가 같아진다는 뜻). 여성 비중이 높은 직종은 {', '.join(e(r['name']) for r in top_f[:4]) or '–'}입니다.</p>
<p>시간당 임금격차 {f0(S['gap_won'])}원을 <b>직종 간 분포 차이</b>와 <b>같은 직종 안의 임금 차이</b>로 나누면 각각 <b>{f0(S['between_pct'])}%</b>와 <b>{f0(S['within_pct'])}%</b>입니다{f" (산업 기준 {f0(SI['between_pct'])}%와 {f0(SI['within_pct'])}%)" if SI else ''}. """ + (
        f"여성이 저임금 서비스·단순노무에도 많지만 상대적으로 임금이 높은 사무·전문가 직종에도 많아, 직종 대분류 수준의 ‘분포 차이’는 서로 상쇄됩니다. 격차는 직종을 고르는 단계보다 <b>같은 직종 안의 직무·직급·근속 차이</b>에서 생깁니다. 직종 내 여성/남성 임금 비율이 가장 낮은 곳은 {e(worst_occ['name'])}({f0(worst_occ['ratio'])}%){f', 산업 중에서는 {e(worst_ind["name"])}({f0(worst_ind["ratio"])}%)' if worst_ind else ''}입니다.</p>"
        if seg_small else "직종 선택의 차이가 격차의 상당 부분을 차지합니다.</p>") + """
<div class="callout">직종 대분류(9개)는 의사와 요양보호사를 같은 ‘전문가·서비스’로 묶을 만큼 넓습니다. 따라서 이 결과는 ‘직종 분리 효과가 없다’가 아니라 <b>대분류 수준에서는 보이지 않고 그 안의 세부 직무 위계로 숨어 있다</b>로 읽어야 하며, 직종 중·소분류×성별 임금 통계 공표가 필요한 이유입니다.</div>"""

    comp = S["monthly_gap_components"]
    tot_comp = sum(v for v in comp.values() if v is not None) or 1
    s3_text = f"""<p>같은 직종 안의 월 임금 차이를 급여 항목별로 나누면, 정액급여(기본급·고정수당) 차이가 평균 {f0(comp.get('wage_fixed'))}원(<b>{f0(100 * (comp.get('wage_fixed') or 0) / tot_comp)}%</b>), 초과근로의 대가인 초과급여 차이가 {f0(comp.get('wage_overtime'))}원({f0(100 * (comp.get('wage_overtime') or 0) / tot_comp)}%), 상여금 등 특별급여 차이가 {f0(comp.get('wage_special_m'))}원({f0(100 * (comp.get('wage_special_m') or 0) / tot_comp)}%)입니다. 초과근로에 대한 직접 보상은 격차의 일부이고, 대부분은 기본급에서 생깁니다.</p>
<div class="callout">교대·야간근무 비율은 근로환경조사 직종×성별 집계가 입력되면(<code>data/manual/kwcs_occ_sex.csv</code>) 같은 모형에 자동 투입됩니다. {'현재 입력되어 분석에 포함되었습니다.' if sn_sh is not None else '현재는 입력되지 않아 초과근로·재해율만 근무부담 지표로 사용했습니다.'}</div>"""

    if res.get("bubble"):
        B = res["bubble"]
        bm = {(b["ind"], b["sex"]): b for b in B}
        pairs = [(bm[(i, "M")], bm[(i, "F")]) for i in {b["ind"] for b in B} if (i, "M") in bm and (i, "F") in bm]
        hi_risk = sorted(pairs, key=lambda p: -p[0]["injury_rate"])[:3]
        m_higher = sum(1 for m, f in pairs if m["injury_rate"] > f["injury_rate"])
        s4_text = f"""<p>재해율이 높은 산업({', '.join(e(p[0]['name']) for p in hi_risk)})의 시간당 임금은 오히려 평균보다 낮거나 비슷합니다. 위험한 산업일수록 임금이 높다는 ‘위험 프리미엄’이 산업 간에는 뚜렷하지 않습니다. 같은 산업 안에서는 {len(pairs)}개 중 {m_higher}개 산업에서 남성의 재해율이 여성보다 높아, 위험 노출이 남성에 치우쳐 있습니다.</p>
<p class="kicker">재해율은 업무상 질병(진폐 등 퇴직 후 청구 포함)을 뺀 사고재해 기준입니다. 분자(산재보험 업종 체계)와 분모(임금조사 근로자 수, 표준산업분류)는 출처가 달라 교차표로 맞춘 추정치입니다. 농림어업·운수업은 임금조사가 포괄하지 않는 영세·특수형태 종사자가 분자에 포함돼 과대 추정될 수 있습니다.</p>"""
    else:
        s4_text = "<p>산업재해 자료가 아직 수집되지 않았습니다.</p>"

    s5_text = f"""<p>직종×학력×연령×성별 셀(최근 3개년)을 근로자 수로 가중한 회귀모형으로 로그 시간당 임금을 설명하고, 남녀 평균 특성 차이에 계수를 곱해 격차를 요인별로 나눴습니다(풀드 Oaxaca-Blinder). 빨간 막대는 격차를 키우는 요인, 파란 막대는 줄이는 요인이고, 마지막 회색 막대가 같은 조건에서도 설명되지 않는 격차입니다.</p>
<p>직종 모형에서 격차의 <b>{f0(ten_sh)}%는 근속 차이</b>, {f1(wt_sh)}%는 초과근로 비중, {f1(hc_sh)}%는 학력·연령, {f1(seg_sh)}%는 직종 분포로 설명되고, <b>{f0(un_sh)}%는 설명되지 않습니다.</b>""" + (
        f" 산업 모형(산업×성별 재해율 포함)에서 재해위험 노출의 기여는 {f1(risk_sh)}%입니다." if risk_sh is not None else "") + """ 설명되지 않는 부분은 곧 차별을 뜻하지는 않습니다(세부 직무·직급, 측정되지 않은 요인 포함). 다만 정책적으로는 동일노동 동일임금 점검이 필요한 영역의 상한으로 읽을 수 있습니다.</p>"""

    s6_text = f"""<div class="card tbl-wrap"><table class="policy">
<tr><th>격차 원인</th><th>근거 지표</th><th>정책 수단</th><th>소관</th></tr>
<tr><td><b>근속 차이(경력단절)</b></td><td>근속 기여 {f0(ten_sh)}%, 평균 근속 남 {f1(ten_m)}년 / 여 {f1(ten_f)}년</td><td>육아휴직·단축근무 기간 근속·호봉 인정 점검, 남성 육아휴직 확대, 경력 인정형 재취업 지원</td><td>고용노동부, 성평등가족부</td></tr>
<tr><td><b>설명되지 않는 격차</b></td><td>동일 조건 잔여 {f0(un_sh)}%</td><td>성별임금 공시 확대, AA 사업장 점검지표화, 임금 결정 투명성 강화</td><td>고용노동부, 성평등가족부</td></tr>
<tr><td><b>직종 내 직무 위계·저평가</b></td><td>직종 간 분포 차이 {f0(S['between_pct'])}% / 직종 내 {f0(S['within_pct'])}%{f", {e(worst_ind['name'])} 여성 시급 {f0(worst_ind['ratio'])}%" if worst_ind else ''}</td><td>직무가치 평가도구 보급, 사회서비스 임금 가이드라인, 돌봄·보조 직무 숙련 인정</td><td>성평등가족부, 고용노동부</td></tr>
<tr><td><b>근무부담(초과근로)</b></td><td>초과근로 기여 {f1(wt_sh)}%, 남 {f1(ot_m)}h / 여 {f1(ot_f)}h</td><td>기본급 중심 임금체계 개편, 장시간 근로 의존 해소</td><td>고용노동부</td></tr>
<tr><td><b>위험 노출</b></td><td>{f"재해위험 기여 {f1(risk_sh)}%, 재해율 1‰p당 임금 {f1(prem)}%" if risk_sh is not None else '산재 자료 수집 후 산출'}</td><td>위험수당보다 위험 자체 감소: 고위험 업종 안전보건 투자, 여성 진입 시 작업환경·보호구 개선</td><td>고용노동부, 한국산업안전보건공단</td></tr>
<tr><td><b>통계 공백</b></td><td>임금 직종 대분류만 성별 공표, 산재 직종×성별 미공표</td><td>직종 중·소분류×성별 임금, 직종×성별 재해 통계 공표, 근로환경조사-임금 연계</td><td>국가데이터처</td></tr>
</table></div>"""

    man = res["meta"].get("manifest", {})
    qual = res["meta"].get("quality", {})
    src_rows = "".join(
        f"<tr><td>{e(v.get('title', k))}</td><td>{e(v.get('tbl_id') or v.get('dataset_id') or '')}</td>"
        f"<td>{len(v.get('files', {}))}</td><td>{f0(sum((f.get('rows') or 0) for f in v.get('files', {}).values()))}</td></tr>"
        for k, v in man.get("sources", {}).items())
    q_rows = ""
    for name, q in qual.items():
        miss = sum(v for k, v in q.items() if k.startswith("missing_symbol"))
        unm = sum(1 for k in q if k.startswith("unmapped"))
        chk = f"{q.get('check_wage_components_fail(>1%)', 0)}/{q.get('check_wage_components_tested', 0)}" if "check_wage_components_tested" in q else "–"
        q_rows += f"<tr><td>{e(name)}</td><td>{e(q.get('status'))}</td><td>{f0(q.get('rows_in'))}</td><td>{f0(miss)}</td><td>{unm}</td><td>{chk}</td></tr>"
    s7_text = f"""<p>매년(고용형태별근로실태조사) 또는 매월 갱신되는 공공통계를 <b>API로 자동 수집하고, 결측·코드 불일치를 정제해 분석·리포트까지 재생성하는 파이프라인</b>을 구축했습니다. GitHub Actions가 정해진 일정에 파이프라인을 실행하고, 새 연도가 공표되면 이 리포트의 수치와 문장이 자동으로 바뀝니다.</p>
<div class="pipe">
<div><b>① 수집 collect</b>KOSIS 공유서비스 API(4만 셀 제한 대응 연도 분할), 공공데이터포털 파일데이터 API. 최신 연도 자동 탐지, 증분 수집</div>
<div><b>② 정제 clean</b>결측·비공개 기호('-','x','…') 처리, 분류 순서 자동 식별, 직종·산업 명칭→표준코드, 산재보험 업종→KSIC 교차표, 단위 통일</div>
<div><b>③ 검증 QA</b>임금 구성 합계(정액+초과+특별) 대조, 남+여=전체 대조, 미매핑 코드·중복 집계 → 품질 리포트</div>
<div><b>④ 분석 analyze</b>shift-share 분해, 던컨 지수, 가중 회귀·Oaxaca-Blinder, 재해율 결합</div>
<div><b>⑤ 리포트 report</b>결과 수치로 문장·차트를 생성한 단일 HTML(오프라인·인쇄 가능)</div>
</div>
<h3>수집 원천과 수집 현황</h3>
<div class="card tbl-wrap"><table><tr><th>자료</th><th>통계표/데이터셋 ID</th><th>파일 수</th><th>행 수</th></tr>{src_rows}</table></div>
<h3>정제 품질 리포트</h3>
<div class="card tbl-wrap"><table><tr><th>테이블</th><th>상태</th><th>원본 행</th><th>결측·비공개 기호</th><th>미매핑 라벨 종류</th><th>임금구성 불일치/검사</th></tr>{q_rows}</table></div>
<h3>분석 방법</h3>
{li([
    "시간당 임금 = 월 임금총액 ÷ 월 총근로시간. 집계는 근로자 수×근로시간 가중으로 해 공표 총계와 일치하도록 함",
    "직종 분리 효과: Δ = Σ(s<sub>m</sub>−s<sub>f</sub>)·(w<sub>m</sub>+w<sub>f</sub>)/2 [분포 차이] + Σ(s<sub>m</sub>+s<sub>f</sub>)/2·(w<sub>m</sub>−w<sub>f</sub>) [직종 내 차이], 정확 분해",
    "요인분해: ln(시간당임금) = 직종(산업)·학력·연령·연도 더미 + 평균근속 + 초과근로 비중 + 재해율(산업×성별) + 여성 더미, 근로자 수 가중 WLS. 풀드 계수로 Oaxaca-Blinder 분해(Fortin 2008; Jann 2008)",
    "재해율 = 산업×성별 재해자 수 ÷ 같은 산업×성별 근로자 수 × 10,000",
])}
<h3>한계</h3>
{li([
    "개인 단위 원자료가 아닌 공표 집계 셀을 사용한 분석으로, 셀 안의 개인 차이(세부 직무, 경력단절 등)는 통제되지 않음",
    "재해율의 분자(산재 승인)와 분모(임금조사 근로자 수)는 출처·분류체계가 달라 교차표로 맞춘 추정치. 여성의 산재 신청률이 낮을 가능성(과소보고)도 있음",
    "재해율은 산업×성별 수준 변수이므로 ‘같은 산업 안 남녀 위험 차이’로만 식별되며, 인과효과가 아닌 상관 추정치임",
    "교대·야간근무는 근로환경조사 집계 입력 시에만 반영됨",
])}"""

    meta_row = (f"<span>기준연도 {year}년</span><span>분석: 직종·산업×학력×연령×성별 셀 요인분해</span>"
                f"<span>생성 {dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d')} (자동 갱신)</span>")
    banner = ('<div class="banner"><b>가상 데이터 미리보기</b> · 이 화면은 레이아웃 확인용 가상 데이터로 만든 것으로 실제 통계가 아닙니다. '
              '실제 수집 데이터로 다시 생성하면 이 배너는 사라집니다.</div>') if sample else ""
    footer = ("자료: 고용노동부 「고용형태별근로실태조사」, 한국산업안전보건공단 「산업재해통계」, 안전보건공단 「근로환경조사」(입력 시). "
              "KOSIS·공공데이터포털 API로 수집. 코드·파이프라인은 저장소 README 참고.")

    data_json = json.dumps({k: v for k, v in res.items() if k != "meta"}, ensure_ascii=False).replace("</", "<\\/")
    rep = {
        "{{TITLE}}": e(TITLE),
        "{{SUBTITLE}}": "직종 선택의 차이, 동일 직무 내 초과근로·산업재해 위험을 통제하면 격차는 얼마나 남는가",
        "{{META_ROW}}": meta_row, "{{BANNER}}": banner,
        "{{EXEC_KICKER}}": "현황(문제) → 데이터 분석 결과 → 정책 제언",
        "{{TILES}}": tiles, "{{EXEC_BODY}}": exec_body,
        "{{S1_TEXT}}": s1_text, "{{S1_TABLE}}": s1_table, "{{S2_TEXT}}": s2_text, "{{S3_TEXT}}": s3_text,
        "{{S4_TEXT}}": s4_text, "{{S5_TEXT}}": s5_text, "{{S6_TEXT}}": s6_text, "{{S7_TEXT}}": s7_text,
        "{{YEAR}}": str(year), "{{FOOTER}}": footer, "{{DATA_JSON}}": data_json,
    }
    out = TPL.read_text(encoding="utf-8")
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def run(log=print) -> None:
    res = json.loads((ROOT / "data" / "processed" / "results.json").read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(res), encoding="utf-8")
    log(f"[report] {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
