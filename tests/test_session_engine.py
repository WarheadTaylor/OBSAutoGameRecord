from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from obs_auto_record.session_engine import DetectedMatch, SessionEngine


def _match(pid: int, exe_name: str = "eldenring.exe", folder: str = "Elden Ring") -> DetectedMatch:
    return DetectedMatch(pid=pid, exe_name=exe_name, archive_subfolder=folder)


class SessionEngineTests(unittest.TestCase):
    def test_starts_when_first_matching_process_appears(self) -> None:
        engine = SessionEngine(exit_grace_period_sec=10)
        now = datetime(2026, 3, 7, 12, 0, 0)

        decision = engine.tick([_match(101)], is_recording=False, now=now)

        self.assertTrue(decision.start_recording)
        self.assertIsNotNone(engine.session)
        self.assertEqual(engine.session.trigger_exe_name, "eldenring.exe")

    def test_stops_after_last_process_exits_and_grace_period_elapses(self) -> None:
        engine = SessionEngine(exit_grace_period_sec=10)
        start = datetime(2026, 3, 7, 12, 0, 0)

        engine.tick([_match(101)], is_recording=False, now=start)
        engine.on_recording_started(start)
        no_stop = engine.tick([], is_recording=True, now=start + timedelta(seconds=9))
        stop = engine.tick([], is_recording=True, now=start + timedelta(seconds=19))

        self.assertFalse(no_stop.stop_recording)
        self.assertTrue(stop.stop_recording)

    def test_does_not_stop_recordings_it_did_not_start(self) -> None:
        engine = SessionEngine(exit_grace_period_sec=10)
        now = datetime(2026, 3, 7, 12, 0, 0)

        decision = engine.tick([_match(101)], is_recording=True, now=now)

        self.assertFalse(decision.start_recording)
        self.assertIsNone(engine.session)

    def test_manual_stop_while_game_running_suppresses_restart_until_clear(self) -> None:
        engine = SessionEngine(exit_grace_period_sec=10)
        start = datetime(2026, 3, 7, 12, 0, 0)

        engine.tick([_match(101)], is_recording=False, now=start)
        engine.on_recording_started(start)
        copy_request = engine.on_recording_stopped(start + timedelta(seconds=5))

        self.assertIsNone(copy_request)
        restart = engine.tick([_match(101)], is_recording=False, now=start + timedelta(seconds=6))
        cleared = engine.tick([], is_recording=False, now=start + timedelta(seconds=7))
        fresh = engine.tick([_match(101)], is_recording=False, now=start + timedelta(seconds=8))

        self.assertFalse(restart.start_recording)
        self.assertFalse(cleared.start_recording)
        self.assertTrue(fresh.start_recording)

    def test_overlap_keeps_original_archive_target(self) -> None:
        engine = SessionEngine(exit_grace_period_sec=10)
        start = datetime(2026, 3, 7, 12, 0, 0)

        engine.tick([_match(101, "eldenring.exe", "Elden Ring")], is_recording=False, now=start)
        engine.on_recording_started(start)
        engine.tick(
            [
                _match(101, "eldenring.exe", "Elden Ring"),
                _match(202, "cs2.exe", "Counter-Strike 2"),
            ],
            is_recording=True,
            now=start + timedelta(seconds=2),
        )
        engine.tick([], is_recording=True, now=start + timedelta(seconds=12))
        copy_request = engine.on_recording_stopped(start + timedelta(seconds=13))

        self.assertIsNotNone(copy_request)
        self.assertEqual(copy_request.archive_subfolder, "Elden Ring")


if __name__ == "__main__":
    unittest.main()
