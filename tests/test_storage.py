import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import storage  # noqa: E402


class StorageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.original = storage.RECORDINGS_ROOT
        self.temp_dir = tempfile.TemporaryDirectory()
        storage.RECORDINGS_ROOT = Path(self.temp_dir.name) / "recordings"

    def tearDown(self):
        storage.RECORDINGS_ROOT = self.original
        self.temp_dir.cleanup()

    def test_relative_path_is_confined_to_recording_root(self):
        path = storage.recording_path("session/input.mp4")
        self.assertEqual(path, storage.recordings_root() / "session/input.mp4")

    def test_outside_path_is_rejected(self):
        with self.assertRaises(storage.StorageBoundaryError):
            storage.recording_path("../../outside.mp4")

    def test_required_extension_is_enforced(self):
        with self.assertRaises(storage.StorageBoundaryError):
            storage.output_path("video.mp4", suffix=".avi")

