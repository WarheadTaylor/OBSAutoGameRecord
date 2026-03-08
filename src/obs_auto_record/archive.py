from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import time

COPY_VERIFY_CHUNK_SIZE = 1024 * 1024
FILE_STABLE_WINDOW_SEC = 1.0
DELETE_STABLE_WINDOW_SEC = 1.0


@dataclass(frozen=True)
class ArchiveResult:
    source: Path
    destination: Path


def build_destination_path(source_file: str | Path, archive_root: str | Path, archive_subfolder: str) -> Path:
    source = Path(source_file)
    destination_dir = Path(archive_root) / archive_subfolder
    destination = destination_dir / source.name
    if not destination.exists():
        return destination

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return destination.with_name(f"{source.stem}-{timestamp}{source.suffix}")


def wait_for_ready_file(
    source_file: str | Path,
    timeout_sec: int,
    poll_interval_sec: float = 0.5,
    stable_window_sec: float | None = None,
) -> Path:
    deadline = time.monotonic() + timeout_sec
    source = Path(source_file)
    last_error: OSError | None = None
    last_signature: tuple[int, int] | None = None
    stable_since: float | None = None
    if stable_window_sec is None:
        stable_window_sec = FILE_STABLE_WINDOW_SEC

    while time.monotonic() <= deadline:
        if source.exists():
            try:
                stat = source.stat()
                with source.open("rb"):
                    pass
            except OSError as exc:
                last_error = exc
                last_signature = None
                stable_since = None
            else:
                signature = (stat.st_size, stat.st_mtime_ns)
                now = time.monotonic()
                if signature != last_signature:
                    last_signature = signature
                    stable_since = now
                elif stable_since is not None and now - stable_since >= stable_window_sec:
                    return source
        time.sleep(poll_interval_sec)

    if last_error is not None:
        raise TimeoutError(f"Timed out waiting for recording file '{source}' to become readable.") from last_error
    if source.exists():
        raise TimeoutError(f"Timed out waiting for recording file '{source}' to finish writing.")
    raise TimeoutError(f"Timed out waiting for recording file '{source}' to appear.")


def delete_recording_file(
    source_file: str | Path,
    timeout_sec: int,
    poll_interval_sec: float = 0.5,
    stable_window_sec: float | None = None,
) -> None:
    deadline = time.monotonic() + timeout_sec
    source = Path(source_file)
    last_error: OSError | None = None
    absent_since: float | None = None
    if stable_window_sec is None:
        stable_window_sec = DELETE_STABLE_WINDOW_SEC

    while time.monotonic() <= deadline:
        if not source.exists():
            now = time.monotonic()
            if absent_since is None:
                absent_since = now
            elif now - absent_since >= stable_window_sec:
                return
            time.sleep(poll_interval_sec)
            continue

        absent_since = None
        try:
            source.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            last_error = exc
        time.sleep(poll_interval_sec)

    if not source.exists():
        return
    if last_error is not None:
        raise TimeoutError(f"Timed out waiting to delete recording file '{source}'.") from last_error
    raise TimeoutError(f"Timed out waiting to delete recording file '{source}'.")


def verify_recording_copy(
    source_file: str | Path,
    destination_file: str | Path,
    chunk_size: int = COPY_VERIFY_CHUNK_SIZE,
) -> None:
    source = Path(source_file)
    destination = Path(destination_file)
    if not destination.exists():
        raise FileNotFoundError(f"Copied recording '{destination}' does not exist.")

    if source.stat().st_size != destination.stat().st_size:
        raise ValueError(
            f"Copied recording '{destination}' size does not match source '{source}'."
        )

    with source.open("rb") as source_handle, destination.open("rb") as destination_handle:
        while True:
            source_chunk = source_handle.read(chunk_size)
            destination_chunk = destination_handle.read(chunk_size)
            if source_chunk != destination_chunk:
                raise ValueError(
                    f"Copied recording '{destination}' contents do not match source '{source}'."
                )
            if not source_chunk:
                return


def copy_recording(
    source_file: str | Path,
    archive_root: str | Path,
    archive_subfolder: str,
    timeout_sec: int,
    delete_source: bool = True,
) -> ArchiveResult:
    source = wait_for_ready_file(source_file, timeout_sec=timeout_sec)
    destination = build_destination_path(source, archive_root, archive_subfolder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    verify_recording_copy(source, destination)
    if delete_source:
        delete_recording_file(source, timeout_sec=timeout_sec)
    return ArchiveResult(source=source, destination=destination)
