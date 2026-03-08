from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable


INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class WatchEntry:
    exe_name: str
    archive_subfolder: str


@dataclass(frozen=True)
class ScriptSettings:
    enabled: bool = True
    watch_entries: tuple[WatchEntry, ...] = ()
    archive_root: str = ""
    auto_delete_recordings: bool = True
    poll_interval_ms: int = 1000
    exit_grace_period_sec: int = 10
    copy_timeout_sec: int = 120
    verbose_logging: bool = False


def normalize_exe_name(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Executable name cannot be empty.")
    if Path(normalized).name != normalized:
        raise ValueError("Executable name must be a file name, not a path.")
    if not normalized.endswith(".exe"):
        raise ValueError("Executable name must end with .exe.")
    if INVALID_WINDOWS_CHARS.search(normalized):
        raise ValueError("Executable name contains invalid Windows path characters.")
    return normalized


def sanitize_archive_subfolder(value: str) -> str:
    sanitized = INVALID_WINDOWS_CHARS.sub("_", value.strip())
    sanitized = sanitized.rstrip(" .")
    sanitized = re.sub(r"\s+", " ", sanitized)
    if not sanitized:
        raise ValueError("Archive subfolder cannot be empty.")
    if sanitized.lower() in RESERVED_WINDOWS_NAMES:
        sanitized = f"_{sanitized}"
    return sanitized


def parse_watch_list(raw_watch_list: str, warn: Callable[[str], None] | None = None) -> tuple[WatchEntry, ...]:
    entries: list[WatchEntry] = []
    seen_exes: set[str] = set()
    logger = warn or (lambda _message: None)

    for line_number, raw_line in enumerate(raw_watch_list.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        exe_name, separator, subfolder = line.partition("|")
        if not separator:
            logger(f"Watch list line {line_number} ignored: expected 'exe_name|archive_subfolder'.")
            continue

        try:
            normalized_exe = normalize_exe_name(exe_name)
            sanitized_subfolder = sanitize_archive_subfolder(subfolder)
        except ValueError as exc:
            logger(f"Watch list line {line_number} ignored: {exc}")
            continue

        if normalized_exe in seen_exes:
            logger(f"Watch list line {line_number} ignored: duplicate executable '{normalized_exe}'.")
            continue

        entries.append(WatchEntry(exe_name=normalized_exe, archive_subfolder=sanitized_subfolder))
        seen_exes.add(normalized_exe)

    return tuple(entries)
