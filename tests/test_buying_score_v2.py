"""Synthetic v2 arithmetic/provenance tests; no market or account queries."""
import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "scripts/buying_score_v2.py"
SPEC = importlib.util.spec_from_file_location("buying_score_v2_unit", PATH)
scorer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorer)


def checks(passes=8, fails=8):
    return [{"id": ident, "status": "pass" if i < passes else "fail" if i < passes + fails else "unknown",
             "evidence": "Synthetic test evidence only.", "source_url": None, "observed_at": None}
            for i, ident in enumerate(scorer.CHECK_IDS)]


class EvidenceArithmeticTests(unittest.TestCase):
    def test_missing_evidence_never_normalizes_score(self):
        actual = scorer.summarize(checks())
        self.assertEqual(actual["score"], 40)
        self.assertEqual(actual["coverage"], 80)
        self.assertEqual(actual["unresolved"], 20)
        self.assertEqual(actual["completion_range"], [40, 60])
        self.assertEqual(actual["counts"], {"pass": 8, "fail": 8, "unknown": 4})

    def test_all_unknown_is_not_an_all_failed_business_assessment(self):
        unknown = scorer.summarize(checks(0, 0))
        self.assertIsNone(unknown["score"])
        self.assertIsNone(unknown["completion_range"])
        self.assertEqual(unknown["coverage"], 0)
        failed = scorer.summarize(checks(0, 20))
        self.assertEqual(failed["score"], 0)
        self.assertEqual(failed["coverage"], 100)
        self.assertEqual(failed["completion_range"], [0, 0])

    def test_all_pass_reproduces_weights(self):
        actual = scorer.summarize(checks(20, 0))
        self.assertEqual(actual["score"], 100)
        self.assertEqual(actual["component_scores"], scorer.WEIGHTS)

    def test_every_state_count_combination_preserves_full_denominator(self):
        for passed in range(21):
            for failed in range(21 - passed):
                actual = scorer.summarize(checks(passed, failed))
                self.assertEqual(sum(actual["component_scores"].values()), passed * 5)
                self.assertEqual(actual["coverage"] + actual["unresolved"], 100)
                self.assertEqual(sum(actual["counts"].values()), 20)

    def test_strict_ids_states_fields_and_unknown_reasons(self):
        samples = []
        for mutation in (
            lambda c: c.pop(),
            lambda c: c.append(copy.deepcopy(c[0])),
            lambda c: c[0].update(id=c[1]["id"]),
            lambda c: c[0].update(id="X1"),
            lambda c: c[0].update(status=True),
            lambda c: c[0].update(status=None),
            lambda c: c[0].update(status="PASS"),
            lambda c: c[0].update(evidence=" "),
            lambda c: c[0].update(private_note="not allowed"),
            lambda c: c[0].pop("source_url"),
        ):
            candidate = checks()
            mutation(candidate)
            samples.append(candidate)
        for candidate in samples:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    scorer.summarize(candidate)

    def test_null_provenance_allowed_but_fabricated_or_private_urls_rejected(self):
        self.assertEqual(scorer.summarize(checks())["score"], 40)
        for source in ("javascript:alert(1)", "https://name:secret@example.com", "https://example.com/?token=private"):
            candidate = checks()
            candidate[0]["source_url"] = source
            with self.assertRaises(ValueError):
                scorer.summarize(candidate)
        for observed in ("2026-10-26", "2026-10-26T13:00:00", True):
            candidate = checks()
            candidate[0]["observed_at"] = observed
            with self.assertRaises((ValueError, TypeError)):
                scorer.summarize(candidate)


if __name__ == "__main__":
    unittest.main()
