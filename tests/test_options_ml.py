import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import options_ml as m  # noqa: E402
from test_options_scorer import series  # noqa: E402


class MLTests(unittest.TestCase):
    def test_model_file_and_multiplier(self):
        model = m.load_model()
        self.assertIsNotNone(model)
        self.assertEqual(len(model["features"]), len(model["coef"]))
        self.assertEqual(m.size_multiplier(model["q33"] - 0.01, model)[0], 0.5)
        self.assertEqual(m.size_multiplier(model["q67"] + 0.01, model)[0], 1.5)
        self.assertEqual(m.size_multiplier((model["q33"] + model["q67"]) / 2, model)[0], 1.0)

    def test_features_and_score_on_a_dip(self):
        bars = series(300, 50, 0.2, 0.3)
        for k, drop in zip((-4, -3, -2, -1), (1.5, 3.0, 4.5, 6.0)):
            b = bars[k]
            bars[k] = {**b, "c": b["c"] - drop, "l": min(b["l"], b["c"] - drop)}
        spy = series(300, 100, 0.05, 0.2)
        f = m.features(bars, None, spy, 1, True, 1.0)
        self.assertGreaterEqual(f["streak"], 4)
        self.assertIsNone(f["vs_sector"])
        p = m.score(f, m.load_model())
        self.assertTrue(0 < p < 1)
        self.assertIsNone(m.features(bars[:100], None, spy, 1, True, 1.0))  # not enough history


if __name__ == "__main__":
    unittest.main()
