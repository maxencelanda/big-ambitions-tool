import sqlite3
import unittest
from pathlib import Path

import numpy as np

from bigambitions import segmentation as seg

DB = Path(__file__).resolve().parents[1] / "out" / "bigambitions.sqlite"


class ModelTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.keys = ["payrollRatio", "idleShare", "marketingRatio", "margin", "trafficIndex"]
        self.models = ["office"] * 4 + ["shop"] * 4
        x = rng.normal(size=(8, 5))
        x[:4] += 10  # les bureaux sont décalés sur toutes les variables : c'est leur modèle économique
        x[:, 4] = 3.0  # constante
        self.x = x

    def test_centering_removes_the_business_model_and_drops_constants(self):
        m = seg.Model(self.x, self.keys, self.models)
        self.assertEqual(m.dropped, ["trafficIndex"])
        for model in ("office", "shop"):
            rows = np.array(self.models) == model
            np.testing.assert_allclose(m.z[rows].mean(axis=0), 0, atol=1e-12)

    def test_outcomes_do_not_shape_the_axes(self):
        m = seg.Model(self.x, self.keys, self.models)
        self.assertNotIn("margin", m.active_keys)
        self.assertEqual(m.axes.shape[1], len(m.active_keys))
        moved = m.z.copy()
        moved[:, m.keys.index("margin")] += 5
        np.testing.assert_allclose(m.project(moved), m.scores)

    def test_projection_of_a_training_row_matches_its_scores(self):
        m = seg.Model(self.x, self.keys, self.models)
        z = m.standardize(self.x[:1], self.keys, self.models[:1])
        np.testing.assert_allclose(m.project(z), m.scores[:1])


class ChooseKTest(unittest.TestCase):
    def test_single_business_groups_are_avoided(self):
        from scipy.cluster.hierarchy import linkage

        # Deux nuages et un point isolé près du second : à 3 groupes, la silhouette est meilleure mais le point est seul.
        points = np.array([[0, 0], [0.3, 0], [0, 0.3], [10, 0], [10.3, 0], [10, 0.3], [10, 10]], dtype=float)
        k, candidates = seg._choose_k(points, linkage(points, method="ward"))
        by_k = {c["k"]: c for c in candidates}
        self.assertEqual(by_k[3]["smallestGroup"], 1)
        self.assertGreater(by_k[3]["silhouette"], by_k[2]["silhouette"])
        self.assertEqual(k, 2)


class PeersTest(unittest.TestCase):
    def test_peers_are_better_businesses_of_the_same_model(self):
        sample = [{"address": str(i), "model": m} for i, m in enumerate(["shop", "shop", "shop", "shop", "office"])]
        perf = np.array([1.0, 0.5, -0.2, -1.0, 3.0])
        self.assertEqual(seg._peers(sample, perf, sample[3], -1.0), [0, 1])
        self.assertEqual(seg._peers(sample, perf, sample[0], 1.0), [])


@unittest.skipUnless(DB.exists(), "base locale absente")
class RealSaveTest(unittest.TestCase):
    def test_analysis_runs_on_the_current_save(self):
        db = sqlite3.connect(DB)
        result = seg.analyse(db, 14)
        if result.get("empty"):
            self.skipTest(result["reason"])
        self.assertGreaterEqual(result["groupsCount"], 1)
        self.assertGreaterEqual(result["varianceKept"], seg.VARIANCE_TARGET)
        self.assertEqual(sum(g["size"] for g in result["groups"]), result["sampleSize"])
        for b in result["businesses"]:
            for gap in b["gaps"]:
                self.assertTrue(seg.VAR[gap["key"]][4], "seuls les leviers pilotables donnent une action")


if __name__ == "__main__":
    unittest.main()
