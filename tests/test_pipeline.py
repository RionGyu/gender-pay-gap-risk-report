"""정제·분석 로직 단위 테스트 (네트워크 불필요)."""
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import analyze, clean  # noqa: E402


class TestCodeMapping(unittest.TestCase):
    def test_occupation_variants(self):
        for s in ["서비스 종사자", "서비스종사자", "4. 서비스 종사자", "(4)서비스 종사자"]:
            self.assertEqual(clean.map_occ(s), "4", s)
        self.assertEqual(clean.map_occ("장치·기계 조작 및 조립 종사자"), "8")
        self.assertEqual(clean.map_occ("장치, 기계조작 및 조립종사자"), "8")
        self.assertEqual(clean.map_occ("전직종"), "T")

    def test_industry_variants(self):
        self.assertEqual(clean.map_ind("C. 제조업"), "C")
        self.assertEqual(clean.map_ind("보건업 및 사회복지 서비스업"), "Q")
        self.assertEqual(clean.map_ind("사업시설관리, 사업지원 및 임대 서비스업"), "N")
        self.assertEqual(clean.map_ind("전산업"), "T")

    def test_sex(self):
        self.assertEqual([clean.map_sex(s) for s in ["남", "남자", "여성", "전체"]], ["M", "M", "F", "T"])

    def test_items(self):
        self.assertEqual(clean.map_item("전년도연간특별급여/12개월"), "wage_special_m")
        self.assertEqual(clean.map_item("전년도 연간특별급여"), "wage_special_y")
        self.assertEqual(clean.map_item("초과근로시간"), "hours_overtime")
        self.assertEqual(clean.map_item("초과급여"), "wage_overtime")

    def test_injury_crosswalk(self):
        cw = clean.load_crosswalk()
        self.assertEqual(clean.injury_to_ksic("기타의사업", "보건및사회복지사업", cw), "Q")
        self.assertEqual(clean.injury_to_ksic("운수·창고및통신업", "통신업", cw), "J")
        self.assertEqual(clean.injury_to_ksic("운수·창고및통신업", "육상및수상운수업", cw), "H")
        self.assertEqual(clean.injury_to_ksic("건설업", "건설업", cw), "F")


class TestValues(unittest.TestCase):
    def test_missing_and_units(self):
        qa = Counter()
        self.assertTrue(np.isnan(clean.parse_value("-", "천원", qa)))
        self.assertTrue(np.isnan(clean.parse_value("x", "", qa)))
        self.assertEqual(clean.parse_value("1,234", "천원", qa), 1234000)
        self.assertEqual(qa["missing_symbol[-]"], 1)


class TestDecomposition(unittest.TestCase):
    def test_shift_share_exact(self):
        """분포 차이 + 직종 내 차이 = 전체 격차 (정확 분해)."""
        rows = []
        for occ, w, fsh in (("1", 30000, .2), ("2", 15000, .7)):
            for sex, mult, share in (("M", 1.0, 1 - fsh), ("F", .85, fsh)):
                rows.append(dict(year=2025, occ=occ, edu="T", age="T", sex=sex, workers=1000 * share,
                                 hours_total=170, hourly_wage=w * mult, hours_overtime=5,
                                 wage_total=w * mult * 170, wage_fixed=w * mult * 150, wage_overtime=1, wage_special_m=1))
        s = analyze.segregation(pd.DataFrame(rows), "occ", 2025, {})
        self.assertAlmostEqual(s["between_won"] + s["within_won"], s["gap_won"], delta=1)

    def test_oaxaca_recovers_known_gap(self):
        rng = np.random.default_rng(0)
        n = 400
        d = pd.DataFrame({"sex": rng.choice(["M", "F"], n), "x": rng.normal(0, 1, n), "workers": rng.uniform(1, 5, n)})
        d.loc[d.sex == "M", "x"] += 1.0
        d["lnw"] = 0.2 * d["x"] - 0.1 * (d.sex == "F") + rng.normal(0, .01, n)
        o = analyze.oaxaca(d, {"g": ["x"]})
        self.assertAlmostEqual(o["coef"]["female"]["b"], -0.1, delta=0.01)
        self.assertAlmostEqual(o["contrib_log"]["g"] + o["unexplained_log"], o["total_log_gap"], delta=1e-3)


class TestEndToEndSample(unittest.TestCase):
    def test_sample_pipeline(self):
        """가상 데이터로 정제→분석→리포트가 끝까지 도는지 (임시 폴더에서)."""
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            for sub in ("pipeline", "config", "tests"):
                subprocess.run(["cp", "-r", str(repo / sub), tmp], check=True)
            subprocess.run([sys.executable, "tests/make_sample.py", tmp], cwd=tmp, check=True, capture_output=True)
            r = subprocess.run([sys.executable, "-m", "pipeline.run", "offline"], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = json.loads(Path(tmp, "data/processed/results.json").read_text(encoding="utf-8"))
            self.assertTrue(res["meta"]["sample_data"])
            html = Path(tmp, "docs/index.html").read_text(encoding="utf-8")
            self.assertIn("가상 데이터 미리보기", html)
            self.assertNotIn("{{", html)


if __name__ == "__main__":
    unittest.main()
