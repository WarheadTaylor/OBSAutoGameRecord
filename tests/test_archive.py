from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from obs_auto_record.archive import build_destination_path, copy_recording


class ArchiveTests(unittest.TestCase):
    def test_build_destination_path_avoids_name_collisions(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "input.mkv"
            source.write_text("recording")
            archive_root = tmp_path / "archive"
            destination = archive_root / "Game" / source.name
            destination.parent.mkdir(parents=True)
            destination.write_text("existing")

            resolved = build_destination_path(source, archive_root, "Game")

            self.assertEqual(resolved.parent, destination.parent)
            self.assertTrue(resolved.name.startswith("input-"))
            self.assertEqual(resolved.suffix, ".mkv")

    def test_copy_recording_waits_for_file_unlock(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mkv"
            source.write_text("recording-data")
            archive_root = tmp_path / "archive"
            real_open = Path.open
            attempts = {"count": 0}

            def flaky_open(self: Path, *args, **kwargs):
                if self == source and "rb" in args and attempts["count"] == 0:
                    attempts["count"] += 1
                    raise OSError("file is locked")
                return real_open(self, *args, **kwargs)

            with patch("pathlib.Path.open", new=flaky_open):
                result = copy_recording(source, archive_root, "Game", timeout_sec=2)

            self.assertTrue(result.destination.exists())
            self.assertEqual(result.destination.read_text(), "recording-data")
            self.assertFalse(source.exists())

    def test_copy_recording_keeps_source_when_verification_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mkv"
            source.write_text("recording-data")
            archive_root = tmp_path / "archive"

            with patch(
                "obs_auto_record.archive.verify_recording_copy",
                side_effect=ValueError("verification failed"),
            ):
                with self.assertRaisesRegex(ValueError, "verification failed"):
                    copy_recording(source, archive_root, "Game", timeout_sec=2)

            destination = archive_root / "Game" / source.name
            self.assertTrue(destination.exists())
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
