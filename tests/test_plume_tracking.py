"""Spherical tracking regressions; run with python -m unittest discover -s tests."""
import unittest

import numpy as np
from pyproj import Geod

from app.visualization.plume_tracking import (
    boundary_center, estimate_motion, great_circle_path, measure_adjacent,
    spherical_displacement,
)


class SphericalTrackingTests(unittest.TestCase):
    def motion(self, start=(0, 60), end=(10, 60), time2="2026-01-20 09:00:00"):
        def line(center):
            lon, lat = center
            return [[(lon - 0.5 + 180) % 360 - 180, lat],
                    [(lon + 0.5 + 180) % 360 - 180, lat]]
        return estimate_motion("2026-01-20 08:00:00", line(start), time2, line(end))

    def test_equator_distance_and_bearing(self):
        distance, bearing = spherical_displacement((0, 0), (10, 0))
        self.assertAlmostEqual(distance, 10)
        self.assertAlmostEqual(bearing, 90)

    def test_meridian_distance_and_bearing(self):
        distance, bearing = spherical_displacement((20, 60), (20, 70))
        self.assertAlmostEqual(distance, 10)
        self.assertAlmostEqual(bearing, 0)

    def test_high_latitude_speed_and_components(self):
        motion = self.motion()
        self.assertAlmostEqual(motion.speed_deg_h, 4.995238089839798)
        self.assertAlmostEqual(motion.direction_deg, 85.66712604792848)
        record = motion.as_record()
        self.assertAlmostEqual(np.hypot(record["v_east_deg_h"], record["v_north_deg_h"]), motion.speed_deg_h)
        self.assertEqual(record["coordinate_lon_rate_deg_h"], 10)
        self.assertEqual(record["coordinate_lat_rate_deg_h"], 0)
        self.assertEqual(record["metric"], "spherical_great_circle")

    def test_actual_elapsed_time_and_timezone(self):
        motion = self.motion(time2="2026-01-20 16:30:00+08:00")
        self.assertEqual(motion.hours, 0.5)
        self.assertAlmostEqual(motion.speed_deg_h, 2 * motion.distance_deg)

    def test_speed_does_not_require_vertical_intersection(self):
        motion = self.motion()
        self.assertIsNone(motion.intersection)
        self.assertTrue(np.isnan(motion.as_record()["intersection_lat_deg"]))
        self.assertGreater(motion.speed_deg_h, 0)

    def test_map_intersection_and_center_convention_preserved(self):
        motion = estimate_motion("2026-01-20 08:00:00", [(-10, 0), (10, 0)],
                                 "2026-01-20 09:00:00", [(-2, 3), (4, 9)])
        np.testing.assert_allclose(motion.center2, [1, 6])
        np.testing.assert_allclose(motion.intersection, [0, 5])
        np.testing.assert_allclose(motion.corner, [0, 6])
        np.testing.assert_allclose(boundary_center([(0, 0), (1, 0), (10, 0)]), [5, 0])

    def test_zero_motion(self):
        motion = self.motion(end=(0, 60))
        self.assertEqual(motion.speed_deg_h, 0)
        self.assertIsNone(motion.direction_deg)
        self.assertEqual(motion.as_record()["v_east_deg_h"], 0)
        self.assertEqual(motion.as_record()["v_north_deg_h"], 0)

    def test_date_line(self):
        motion = self.motion(start=(179, 60), end=(-179, 60))
        self.assertAlmostEqual(motion.delta_lon, 2)
        self.assertAlmostEqual(motion.distance_deg, 0.999961922097622)

    def test_180_longitude_change_is_not_necessarily_antipodal(self):
        motion = self.motion(start=(0, 60), end=(180, 60))
        self.assertAlmostEqual(motion.distance_deg, 60)
        self.assertIsNotNone(motion.direction_deg)
        self.assertIsNotNone(great_circle_path(motion.center1, motion.center2))

    def test_antipodes_have_distance_but_no_unique_bearing(self):
        motion = self.motion(start=(0, 30), end=(180, -30))
        self.assertAlmostEqual(motion.distance_deg, 180)
        self.assertIsNone(motion.direction_deg)
        self.assertIsNone(great_circle_path(motion.center1, motion.center2))
        self.assertTrue(np.isnan(motion.as_record()["v_east_deg_h"]))

    def test_pole_bearing_and_coincident_pole(self):
        distance, bearing = spherical_displacement((0, 90), (80, 70))
        self.assertAlmostEqual(distance, 20)
        self.assertIsNone(bearing)
        self.assertEqual(spherical_displacement((0, 90), (120, 90)), (0, None))

    def test_against_independent_proj_sphere(self):
        sphere = Geod(a=1, b=1)
        rng = np.random.default_rng(42)
        pairs = [((0, 80), (20, 80)), ((0, 0), (179.999999, 0.000001)),
                 ((0, 45), (0.000001, 45.000001))]
        pairs += [(rng.uniform([-180, -89], [180, 89]), rng.uniform([-180, -89], [180, 89]))
                  for _ in range(100)]
        for start, end in pairs:
            with self.subTest(start=start, end=end):
                distance, bearing = spherical_displacement(start, end)
                expected_bearing, _, expected_distance = sphere.inv(*start, *end)
                self.assertAlmostEqual(distance, np.rad2deg(expected_distance), places=8)
                self.assertAlmostEqual((bearing - expected_bearing + 180) % 360 - 180, 0, places=5)

    def test_rendered_arc_has_measured_length(self):
        start, end = (179, 60), (-150, 65)
        path = great_circle_path(start, end)
        np.testing.assert_allclose(path[0], start)
        np.testing.assert_allclose(path[-1], end)
        length = sum(spherical_displacement(a, b)[0] for a, b in zip(path, path[1:]))
        self.assertAlmostEqual(length, spherical_displacement(start, end)[0], places=9)
        self.assertGreater(great_circle_path((0, 60), (10, 60))[90, 1], 60)

    def test_invalid_times_and_coordinates(self):
        with self.assertRaises(ValueError):
            self.motion(time2="2026-01-20 08:00:00")
        for start in [(0, 91), (np.nan, 60), (0, 1, 2)]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                spherical_displacement(start, (0, 60))

    def test_adjacent_pairs_remain_sorted_without_bridging_gaps(self):
        data = [{"time": f"2026-01-20 {hour}:00:00", "line": [[0, lat], [1, lat]]}
                for hour, lat in [("11", 64), ("08", 60), ("09", 62)]]
        result = measure_adjacent(data)
        self.assertEqual([m.hours for m in result], [1, 2])
        np.testing.assert_allclose([m.speed_deg_h for m in result], [2, 1])
        data[-1]["line"] = None
        with self.assertRaises(ValueError):
            measure_adjacent(data)


if __name__ == "__main__":
    unittest.main()
