from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
import ctypes
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "obs_scripts" / "auto_record_games.py"


def _load_script_module():
    logs: list[tuple[int, str]] = []
    obs_module = types.ModuleType("obspython")
    obs_module.OBS_FRONTEND_EVENT_RECORDING_STARTED = 1
    obs_module.OBS_FRONTEND_EVENT_RECORDING_STOPPED = 2
    obs_module.OBS_TEXT_MULTILINE = 0
    obs_module.OBS_PATH_DIRECTORY = 0
    obs_module.LOG_INFO = 10
    obs_module.LOG_WARNING = 20

    def obs_data_get_string(settings, key: str) -> str:
        return str(settings.get(key, ""))

    def obs_data_get_bool(settings, key: str) -> bool:
        return bool(settings.get(key, False))

    def obs_data_get_int(settings, key: str) -> int:
        return int(settings.get(key, 0))

    def script_log(level: int, message: str) -> None:
        logs.append((level, message))

    obs_module.obs_data_get_string = obs_data_get_string
    obs_module.obs_data_get_bool = obs_data_get_bool
    obs_module.obs_data_get_int = obs_data_get_int
    obs_module.script_log = script_log
    obs_module.logs = logs

    class _FakeWinFunc:
        def __init__(self, return_value: int) -> None:
            self.return_value = return_value
            self.argtypes = None
            self.restype = None

        def __call__(self, *args, **kwargs) -> int:
            return self.return_value

    class _FakeKernel32:
        def __init__(self) -> None:
            self.CreateToolhelp32Snapshot = _FakeWinFunc(0)
            self.Process32FirstW = _FakeWinFunc(0)
            self.Process32NextW = _FakeWinFunc(0)
            self.CloseHandle = _FakeWinFunc(1)

    module_name = "test_auto_record_games_module"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load auto_record_games.py")

    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"obspython": obs_module}, clear=False), patch.object(
        ctypes,
        "WinDLL",
        return_value=_FakeKernel32(),
        create=True,
    ):
        sys.modules.pop(module_name, None)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module, obs_module


class AutoRecordGamesTests(unittest.TestCase):
    def test_load_settings_reads_disable_archive_without_warning_for_empty_archive_root(self) -> None:
        module, obs_module = _load_script_module()

        settings = module._load_settings(
            {
                "enabled": True,
                "watch_list": "eldenring.exe|Elden Ring",
                "archive_root": "   ",
                "disable_archive": True,
                "auto_delete_recordings": True,
                "poll_interval_ms": 1000,
                "exit_grace_period_sec": 10,
                "copy_timeout_sec": 120,
                "verbose_logging": False,
            }
        )

        self.assertTrue(settings.disable_archive)
        self.assertEqual(obs_module.logs, [])

    def test_recording_stop_skips_archive_submission_when_disabled(self) -> None:
        module, _obs_module = _load_script_module()
        copy_request = module.CopyRequest(trigger_exe_name="eldenring.exe", archive_subfolder="Elden Ring")
        engine = Mock()
        engine.on_recording_stopped.return_value = copy_request
        module.STATE = types.SimpleNamespace(
            settings=module.ScriptSettings(disable_archive=True),
            engine=engine,
        )

        with patch.object(module, "_submit_copy") as submit_copy:
            module._on_frontend_event(module.obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED)

        submit_copy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
