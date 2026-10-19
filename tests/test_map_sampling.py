"""Custom map sampling preserves storage order and remains bounded."""

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np
from pydantic import ValidationError

from app.backend.config import Settings
from app.backend.errors import BackendError
from app.backend.maps import MapService
from app.backend.models import MapParameters, MapRenderSpec


class MapSamplingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(root=Path(temporary.name), max_points=4)
        self.maps = MapService(self.settings)
        with h5py.File(self.maps.directory("roti-map") / "sample.h5", "w") as file:
            rows = np.array(
                [(float(i), float(i + 20), float(i * 10)) for i in range(9)],
                dtype=[("lat", "f4"), ("lon", "f4"), ("value", "f4")],
            )
            file.create_group("data").create_dataset("2026-01-01T00:00:00Z", data=rows)

    def test_presets_and_custom_stride(self):
        for resolution, custom, expected in [
            ("medium", None, [0, 40, 80]),
            ("low", None, [0]),
            ("low", 2, [0, 20, 40, 60, 80]),
            ("full", 3, [0, 30, 60]),
        ]:
            params = MapParameters(
                timestamp="2026-01-01T00:00:00Z",
                resolution=resolution,
                samplingStride=custom,
            )
            if custom == 2:
                with self.assertRaises(BackendError) as raised:
                    self.maps.read("roti-map", params, acquire=False)
                self.assertEqual(raised.exception.status, 413)
            else:
                arrays, metadata = self.maps.read("roti-map", params, acquire=False)
                self.assertEqual(arrays["value"].tolist(), expected)
                self.assertEqual(metadata["samplingStride"], custom or {"medium": 4, "low": 16, "full": 1}[resolution])

    def test_invalid_strides_are_rejected(self):
        for value in (0, -1, 1.5, 2.0, 1025, "2", "2.5", True):
            with self.assertRaises(ValidationError):
                MapParameters(timestamp="2026-01-01T00:00:00Z", samplingStride=value)
        self.assertIsNone(MapParameters(timestamp="2026-01-01T00:00:00Z").samplingStride)
        self.assertIn("samplingStride", MapRenderSpec.model_fields)


if __name__ == "__main__":
    unittest.main()
