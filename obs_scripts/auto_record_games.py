from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sys
from typing import Iterable

import obspython as obs


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# OBS can keep imported project modules cached across script reloads.
# Force fresh imports so local code changes are picked up reliably.
for module_name in (
    "obs_auto_record.archive",
    "obs_auto_record.process_scan",
    "obs_auto_record.session_engine",
    "obs_auto_record.settings",
    "obs_auto_record",
):
    sys.modules.pop(module_name, None)

from obs_auto_record.archive import copy_recording
from obs_auto_record.process_scan import iter_processes
from obs_auto_record.session_engine import CopyRequest, DetectedMatch, SessionEngine
from obs_auto_record.settings import ScriptSettings, parse_watch_list


STATE: "ScriptState | None" = None


class ScriptState:
    def __init__(self) -> None:
        self.settings = ScriptSettings()
        self.engine = SessionEngine(exit_grace_period_sec=self.settings.exit_grace_period_sec)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obs-auto-record")
        self.timer_registered = False

    def reconfigure(self, settings: ScriptSettings) -> None:
        self.settings = settings
        self.engine = SessionEngine(exit_grace_period_sec=settings.exit_grace_period_sec)


def script_description() -> str:
    return (
        "Automatically starts OBS recording when configured game executables are detected, "
        "stops after they exit, verifies the archived copy, and can optionally delete the original recording."
    )


def script_defaults(settings) -> None:
    obs.obs_data_set_default_bool(settings, "enabled", True)
    obs.obs_data_set_default_string(settings, "watch_list", "")
    obs.obs_data_set_default_string(settings, "archive_root", "")
    obs.obs_data_set_default_bool(settings, "disable_archive", False)
    obs.obs_data_set_default_bool(settings, "auto_delete_recordings", True)
    obs.obs_data_set_default_int(settings, "poll_interval_ms", 1000)
    obs.obs_data_set_default_int(settings, "exit_grace_period_sec", 10)
    obs.obs_data_set_default_int(settings, "copy_timeout_sec", 120)
    obs.obs_data_set_default_bool(settings, "verbose_logging", False)


def script_properties():
    properties = obs.obs_properties_create()
    obs.obs_properties_add_bool(properties, "enabled", "Enabled")
    obs.obs_properties_add_text(properties, "watch_list", "Watch List", obs.OBS_TEXT_MULTILINE)
    obs.obs_properties_add_path(
        properties,
        "archive_root",
        "Archive Root",
        obs.OBS_PATH_DIRECTORY,
        "",
        None,
    )
    disable_archive = obs.obs_properties_add_bool(properties, "disable_archive", "Disable Auto Archive")
    obs.obs_property_set_modified_callback(disable_archive, _on_disable_archive_modified)
    obs.obs_properties_add_bool(properties, "auto_delete_recordings", "Auto Delete Original Recording")
    obs.obs_properties_add_int(properties, "poll_interval_ms", "Poll Interval Ms", 250, 60_000, 250)
    obs.obs_properties_add_int(properties, "exit_grace_period_sec", "Exit Grace Period Sec", 0, 600, 1)
    obs.obs_properties_add_int(properties, "copy_timeout_sec", "Copy Timeout Sec", 1, 3600, 1)
    obs.obs_properties_add_bool(properties, "verbose_logging", "Verbose Logging")
    return properties


def script_load(settings) -> None:
    global STATE
    STATE = ScriptState()
    script_update(settings)
    obs.obs_frontend_add_event_callback(_on_frontend_event)


def script_unload() -> None:
    if STATE is None:
        return
    _unregister_timer()
    obs.obs_frontend_remove_event_callback(_on_frontend_event)
    STATE.executor.shutdown(wait=False, cancel_futures=False)


def script_update(settings) -> None:
    if STATE is None:
        return

    script_settings = _load_settings(settings)
    STATE.reconfigure(script_settings)
    _register_timer(script_settings.poll_interval_ms if script_settings.enabled else 0)
    _log("Configuration reloaded.", verbose_only=True)


def _load_settings(obs_settings) -> ScriptSettings:
    warnings: list[str] = []
    watch_entries = parse_watch_list(
        obs.obs_data_get_string(obs_settings, "watch_list"),
        warn=warnings.append,
    )
    for message in warnings:
        _warn(message)

    archive_root = obs.obs_data_get_string(obs_settings, "archive_root").strip()
    disable_archive = obs.obs_data_get_bool(obs_settings, "disable_archive")
    if not archive_root and not disable_archive:
        _warn("Archive Root is empty; completed recordings will not be copied until it is configured.")

    return ScriptSettings(
        enabled=obs.obs_data_get_bool(obs_settings, "enabled"),
        watch_entries=watch_entries,
        archive_root=archive_root,
        disable_archive=disable_archive,
        auto_delete_recordings=obs.obs_data_get_bool(obs_settings, "auto_delete_recordings") and not disable_archive,
        poll_interval_ms=max(250, obs.obs_data_get_int(obs_settings, "poll_interval_ms")),
        exit_grace_period_sec=max(0, obs.obs_data_get_int(obs_settings, "exit_grace_period_sec")),
        copy_timeout_sec=max(1, obs.obs_data_get_int(obs_settings, "copy_timeout_sec")),
        verbose_logging=obs.obs_data_get_bool(obs_settings, "verbose_logging"),
    )


def _on_disable_archive_modified(props, _property, settings) -> bool:
    disable_archive = obs.obs_data_get_bool(settings, "disable_archive")
    auto_delete = obs.obs_properties_get(props, "auto_delete_recordings")
    if auto_delete is not None:
        obs.obs_property_set_enabled(auto_delete, not disable_archive)
    if disable_archive:
        obs.obs_data_set_bool(settings, "auto_delete_recordings", False)
    return True


def _register_timer(interval_ms: int) -> None:
    if STATE is None:
        return
    if STATE.timer_registered:
        obs.timer_remove(_poll)
        STATE.timer_registered = False
    if interval_ms > 0:
        obs.timer_add(_poll, interval_ms)
        STATE.timer_registered = True


def _unregister_timer() -> None:
    if STATE is None or not STATE.timer_registered:
        return
    obs.timer_remove(_poll)
    STATE.timer_registered = False


def _poll() -> None:
    if STATE is None:
        return

    settings = STATE.settings
    if not settings.enabled:
        return
    if not settings.watch_entries:
        _log("No watch list entries configured.", verbose_only=True)
        return

    watch_map = {entry.exe_name: entry.archive_subfolder for entry in settings.watch_entries}
    matches = _detect_matches(watch_map)
    is_recording = bool(obs.obs_frontend_recording_active())
    decision = STATE.engine.tick(matches=matches, is_recording=is_recording, now=datetime.now())

    if matches:
        summary = ", ".join(f"{match.exe_name} (pid {match.pid})" for match in matches)
        _log(f"Detected watched games: {summary}", verbose_only=True)

    if decision.start_recording:
        _log(f"Starting recording for {STATE.engine.session.trigger_exe_name}.")
        obs.obs_frontend_recording_start()
    elif decision.stop_recording:
        _log("All watched games exited; stopping recording.")
        obs.obs_frontend_recording_stop()


def _detect_matches(watch_map: dict[str, str]) -> list[DetectedMatch]:
    matches: list[DetectedMatch] = []
    try:
        for process in iter_processes():
            archive_subfolder = watch_map.get(process.exe_name)
            if archive_subfolder is None:
                continue
            matches.append(
                DetectedMatch(
                    pid=process.pid,
                    exe_name=process.exe_name,
                    archive_subfolder=archive_subfolder,
                )
            )
    except OSError as exc:
        _warn(f"Process scan failed: {exc}")
        return []

    return sorted(matches, key=lambda match: (match.pid, match.exe_name))


def _on_frontend_event(event: int) -> None:
    if STATE is None:
        return

    now = datetime.now()
    if event == obs.OBS_FRONTEND_EVENT_RECORDING_STARTED:
        STATE.engine.on_recording_started(now)
        _log("OBS recording started.", verbose_only=True)
        return

    if event == obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED:
        copy_request = STATE.engine.on_recording_stopped(now)
        _log("OBS recording stopped.")
        if copy_request is not None and not STATE.settings.disable_archive:
            _submit_copy(copy_request)


def _submit_copy(copy_request: CopyRequest) -> None:
    if STATE is None:
        return

    archive_root = STATE.settings.archive_root
    if not archive_root:
        _warn(
            f"Skipping archive copy for {copy_request.trigger_exe_name}: Archive Root is not configured."
        )
        return

    last_recording = _get_last_recording_path()
    if not last_recording:
        _warn(f"Skipping archive copy for {copy_request.trigger_exe_name}: OBS returned no recording path.")
        return

    timeout_sec = STATE.settings.copy_timeout_sec
    _log(f"Queueing archive copy for {last_recording} -> {copy_request.archive_subfolder}.")
    STATE.executor.submit(
        _copy_worker,
        last_recording,
        archive_root,
        copy_request.archive_subfolder,
        timeout_sec,
        STATE.settings.auto_delete_recordings,
    )


def _copy_worker(
    source_path: str,
    archive_root: str,
    archive_subfolder: str,
    timeout_sec: int,
    auto_delete_recordings: bool,
) -> None:
    try:
        result = copy_recording(
            source_file=source_path,
            archive_root=archive_root,
            archive_subfolder=archive_subfolder,
            timeout_sec=timeout_sec,
            delete_source=auto_delete_recordings,
        )
    except Exception as exc:  # pragma: no cover - exercised manually in OBS
        _warn(f"Archive operation failed for '{source_path}': {exc}")
        return

    if auto_delete_recordings:
        _log(f"Archived recording to {result.destination} and deleted the source file.")
    else:
        _log(f"Archived recording to {result.destination}; the source file was kept.")


def _get_last_recording_path() -> str:
    getter = getattr(obs, "obs_frontend_get_last_recording", None)
    if getter is None:
        return ""
    try:
        path = getter()
    except Exception as exc:  # pragma: no cover - OBS-specific failure path
        _warn(f"Failed to query last recording path: {exc}")
        return ""
    return path or ""


def _log(message: str, verbose_only: bool = False) -> None:
    if STATE is None:
        return
    if verbose_only and not STATE.settings.verbose_logging:
        return
    obs.script_log(obs.LOG_INFO, message)


def _warn(message: str) -> None:
    obs.script_log(obs.LOG_WARNING, message)
