from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from obs_auto_record.archive import build_destination_path, copy_recording, wait_for_ready_file


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

            with patch("pathlib.Path.open", new=flaky_open), patch(
                "obs_auto_record.archive.FILE_STABLE_WINDOW_SEC", 0.0
            ):
                result = copy_recording(source, archive_root, "Game", timeout_sec=2)

            self.assertTrue(result.destination.exists())
            self.assertEqual(result.destination.read_text(), "recording-data")
            self.assertFalse(source.exists())

    def test_copy_recording_can_keep_source_when_auto_delete_is_disabled(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mkv"
            source.write_text("recording-data")
            archive_root = tmp_path / "archive"

            with patch("obs_auto_record.archive.FILE_STABLE_WINDOW_SEC", 0.0):
                result = copy_recording(
                    source,
                    archive_root,
                    "Game",
                    timeout_sec=2,
                    delete_source=False,
                )

            self.assertTrue(result.destination.exists())
            self.assertEqual(result.destination.read_text(), "recording-data")
            self.assertTrue(source.exists())

    def test_copy_recording_keeps_source_when_verification_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mkv"
            source.write_text("recording-data")
            archive_root = tmp_path / "archive"

            with patch("obs_auto_record.archive.FILE_STABLE_WINDOW_SEC", 0.0), patch(
                "obs_auto_record.archive.verify_recording_copy",
                side_effect=ValueError("verification failed"),
            ):
                with self.assertRaisesRegex(ValueError, "verification failed"):
                    copy_recording(source, archive_root, "Game", timeout_sec=2)

            destination = archive_root / "Game" / source.name
            self.assertTrue(destination.exists())
            self.assertTrue(source.exists())

    def test_copy_recording_retries_delete_until_source_is_released(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mkv"
            source.write_text("recording-data")
            archive_root = tmp_path / "archive"
            real_unlink = Path.unlink
            attempts = {"count": 0}

            def flaky_unlink(self: Path, *args, **kwargs):
                if self == source and attempts["count"] == 0:
                    attempts["count"] += 1
                    raise PermissionError("file is still locked for delete")
                return real_unlink(self, *args, **kwargs)

            with patch("pathlib.Path.unlink", new=flaky_unlink), patch(
                "obs_auto_record.archive.FILE_STABLE_WINDOW_SEC", 0.0
            ), patch(
                "obs_auto_record.archive.DELETE_STABLE_WINDOW_SEC", 0.0
            ):
                result = copy_recording(source, archive_root, "Game", timeout_sec=2)

            self.assertTrue(result.destination.exists())
            self.assertFalse(source.exists())

    def test_copy_recording_retries_if_source_reappears_after_delete(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mkv"
            source.write_text("recording-data")
            archive_root = tmp_path / "archive"
            real_unlink = Path.unlink
            attempts = {"count": 0}

            def flaky_unlink(self: Path, *args, **kwargs):
                if self == source and attempts["count"] == 0:
                    attempts["count"] += 1
                    real_unlink(self, *args, **kwargs)
                    self.write_text("recreated-by-finalizer")
                    return None
                return real_unlink(self, *args, **kwargs)

            with patch("pathlib.Path.unlink", new=flaky_unlink), patch(
                "obs_auto_record.archive.FILE_STABLE_WINDOW_SEC", 0.0
            ), patch(
                "obs_auto_record.archive.DELETE_STABLE_WINDOW_SEC", 0.0
            ):
                result = copy_recording(source, archive_root, "Game", timeout_sec=2)

            self.assertTrue(result.destination.exists())
            self.assertFalse(source.exists())

    def test_wait_for_ready_file_waits_for_source_to_stop_changing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "clip.mp4"
            source.write_text("part-1")

            def finish_write() -> None:
                time.sleep(0.15)
                with source.open("a", encoding="utf-8") as handle:
                    handle.write("-part-2")

            writer = threading.Thread(target=finish_write)
            writer.start()
            try:
                ready = wait_for_ready_file(
                    source,
                    timeout_sec=2,
                    poll_interval_sec=0.05,
                    stable_window_sec=0.2,
                )
            finally:
                writer.join()

            self.assertEqual(ready.read_text(), "part-1-part-2")


if __name__ == "__main__":
    unittest.main()
