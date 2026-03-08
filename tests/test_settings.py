from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from obs_auto_record.settings import parse_watch_list, sanitize_archive_subfolder


class SettingsTests(unittest.TestCase):
    def test_parse_watch_list_skips_invalid_rows(self) -> None:
        warnings: list[str] = []
        entries = parse_watch_list(
            "\n".join(
                [
                    "eldenring.exe|Elden Ring",
                    "invalid row",
                    "bad.exe|",
                    "ELDENRING.exe|Duplicate",
                ]
            ),
            warn=warnings.append,
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].exe_name, "eldenring.exe")
        self.assertEqual(entries[0].archive_subfolder, "Elden Ring")
        self.assertEqual(len(warnings), 3)

    def test_archive_subfolder_is_sanitized(self) -> None:
        self.assertEqual(sanitize_archive_subfolder('  Elden:Ring?  '), "Elden_Ring_")
        self.assertEqual(sanitize_archive_subfolder("con"), "_con")


if __name__ == "__main__":
    unittest.main()
