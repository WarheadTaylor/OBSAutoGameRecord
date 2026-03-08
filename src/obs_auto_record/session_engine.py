from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class DetectedMatch:
    pid: int
    exe_name: str
    archive_subfolder: str


@dataclass
class RecordingSession:
    trigger_exe_name: str
    archive_subfolder: str
    owned_by_script: bool
    started_at: datetime
    matched_pids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class EngineDecision:
    start_recording: bool = False
    stop_recording: bool = False


@dataclass(frozen=True)
class CopyRequest:
    archive_subfolder: str
    trigger_exe_name: str


class SessionEngine:
    def __init__(self, exit_grace_period_sec: int) -> None:
        self.exit_grace_period = timedelta(seconds=exit_grace_period_sec)
        self.session: RecordingSession | None = None
        self.last_matches: tuple[DetectedMatch, ...] = ()
        self.empty_since: datetime | None = None
        self.awaiting_start_confirmation = False
        self.awaiting_stop_confirmation = False
        self.suppressed_until_clear = False

    def tick(
        self,
        matches: list[DetectedMatch],
        is_recording: bool,
        now: datetime,
    ) -> EngineDecision:
        normalized_matches = tuple(sorted(matches, key=lambda item: (item.pid, item.exe_name, item.archive_subfolder)))
        self.last_matches = normalized_matches

        if not normalized_matches:
            self.empty_since = self.empty_since or now
            if self.suppressed_until_clear:
                self.suppressed_until_clear = False
            return self._decide_when_empty(is_recording=is_recording, now=now)

        self.empty_since = None

        if self.session is not None:
            self.session.matched_pids = {match.pid for match in normalized_matches}
            return EngineDecision()

        if self.suppressed_until_clear:
            return EngineDecision()

        if is_recording or self.awaiting_start_confirmation:
            self.suppressed_until_clear = True
            return EngineDecision()

        trigger = normalized_matches[0]
        self.session = RecordingSession(
            trigger_exe_name=trigger.exe_name,
            archive_subfolder=trigger.archive_subfolder,
            owned_by_script=True,
            started_at=now,
            matched_pids={match.pid for match in normalized_matches},
        )
        self.awaiting_start_confirmation = True
        return EngineDecision(start_recording=True)

    def on_recording_started(self, now: datetime) -> None:
        self.awaiting_start_confirmation = False
        if self.session is not None:
            self.session.started_at = now

    def on_recording_stopped(self, now: datetime) -> CopyRequest | None:
        del now
        self.awaiting_start_confirmation = False
        copy_request: CopyRequest | None = None

        if self.session is not None and self.session.owned_by_script:
            if self.last_matches and not self.awaiting_stop_confirmation:
                self.suppressed_until_clear = True
            else:
                copy_request = CopyRequest(
                    archive_subfolder=self.session.archive_subfolder,
                    trigger_exe_name=self.session.trigger_exe_name,
                )

        self.awaiting_stop_confirmation = False
        self.session = None
        self.empty_since = None
        return copy_request

    def _decide_when_empty(self, is_recording: bool, now: datetime) -> EngineDecision:
        if self.session is None:
            self.awaiting_start_confirmation = False
            return EngineDecision()

        self.session.matched_pids.clear()

        if not is_recording:
            return EngineDecision()

        if self.awaiting_stop_confirmation:
            return EngineDecision()

        if self.empty_since is None:
            self.empty_since = now
            return EngineDecision()

        if now - self.empty_since < self.exit_grace_period:
            return EngineDecision()

        self.awaiting_stop_confirmation = True
        return EngineDecision(stop_recording=True)
