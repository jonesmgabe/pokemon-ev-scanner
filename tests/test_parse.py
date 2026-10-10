import unittest
from scanner.pricecharting import grade_from_label, fair_value, pop_for
from scanner.ebay import parse_grade
CFG = {"comp_max_age_days": 100000, "comp_sample": 8, "min_comps": 2, "grader_guide_haircut": {"PSA": 1.0, "CGC": 0.8, "OTHER": 0.6}}
class T(unittest.TestCase):
    def test_label(self): self.assertEqual(grade_from_label("Graded 7"), 7.0)
    def test_ebay(self): self.assertEqual(parse_grade("Charizard PSA 7 NM Base"), ("PSA", 7.0))
    def test_fv(self):
        prod = {"guide": {"7": 100.0}, "pop": {"psa": [0]*6 + [12, 0, 0, 0]}, "comps": {"cib": [
            {"date": "2026-01-01", "title": "X PSA 7", "price": 80}, {"date": "2026-01-02", "title": "X PSA 7", "price": 90},
            {"date": "2026-01-03", "title": "X CGC 7", "price": 50}]}}
        self.assertEqual(fair_value(prod, 7.0, "PSA", CFG)[0], 85)
        self.assertEqual(fair_value(prod, 7.0, "CGC", CFG)[0], 80)
        self.assertEqual(pop_for(prod, 7.0, "PSA"), 12); self.assertIsNone(pop_for(prod, 8.0, "PSA"))
