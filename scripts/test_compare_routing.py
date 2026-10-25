"""Unit tests for compare-routing.py: python3 -m unittest discover scripts"""

import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "compare_routing", Path(__file__).with_name("compare-routing.py"))
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


class PolylineTest(unittest.TestCase):
    def test_google_example(self):
        # The example from the Google polyline documentation.
        pts = cr.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", 5)
        expected = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        for p, e in zip(pts, expected):
            self.assertAlmostEqual(p[0], e[0], places=5)
            self.assertAlmostEqual(p[1], e[1], places=5)

    def test_empty(self):
        self.assertEqual(cr.decode_polyline("", 6), [])


class GeometryTest(unittest.TestCase):
    def test_haversine_one_degree_lat(self):
        self.assertAlmostEqual(cr.haversine((49, 16), (50, 16)), 111_195, delta=10)

    def test_densify_step(self):
        line = [(49.0, 16.0), (49.01, 16.0)]  # about 1.1 km
        pts = cr.densify(line, 100)
        self.assertEqual(pts[0], line[0])
        self.assertEqual(pts[-1], line[-1])
        gaps = [cr.haversine(a, b) for a, b in zip(pts, pts[1:])]
        self.assertLessEqual(max(gaps), 100.01)

    def test_overlap_same_and_far(self):
        a = [(49.0, 16.0), (49.01, 16.0)]
        far = [(49.0, 16.01), (49.01, 16.01)]  # about 730 m east
        self.assertEqual(cr.overlap(a, a), 1.0)
        self.assertEqual(cr.overlap(a, far), 0.0)

    def test_overlap_half(self):
        a = [(49.0, 16.0), (49.02, 16.0)]
        half = [(49.0, 16.0), (49.01, 16.0)]
        self.assertAlmostEqual(cr.overlap(a, half), 0.5, delta=0.05)


class ElevationTest(unittest.TestCase):
    def test_climb_ignores_noise(self):
        prof = [(i * 20, h) for i, h in enumerate([100, 101, 100, 102, 110, 109, 120, 100])]
        self.assertEqual(cr.climb(prof), (20, 20))

    def test_tobler_flat_and_up(self):
        flat = [(0, 100), (1000, 100)]
        # Tobler on flat ground: 6 * exp(-0.175) km/h = 5.04 km/h.
        self.assertAlmostEqual(cr.tobler_seconds(flat), 1000 / (5.0369 / 3.6), delta=2)
        steep = [(0, 100), (1000, 300)]
        self.assertGreater(cr.tobler_seconds(steep), 2 * cr.tobler_seconds(flat))

    def test_srtm_tile(self):
        # A 3x3 tile N49E016: heights grow to the east, 0 / 50 / 100 m.
        with tempfile.TemporaryDirectory() as d:
            rows = [[0, 50, 100]] * 3
            data = b"".join(v.to_bytes(2, "big", signed=True) for r in rows for v in r)
            Path(d, "N49E016.hgt").write_bytes(data)
            srtm = cr.Srtm(d)
            self.assertAlmostEqual(srtm.height(49.5, 16.0), 0)
            self.assertAlmostEqual(srtm.height(49.5, 16.25), 25)
            self.assertAlmostEqual(srtm.height(49.5, 16.999), 99.9, delta=0.2)
            self.assertIsNone(srtm.height(48.5, 16.5))  # no tile there


if __name__ == "__main__":
    unittest.main()
