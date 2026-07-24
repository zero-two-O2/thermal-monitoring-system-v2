from __future__ import annotations

from enum import Enum, auto


class AlarmState(Enum):
    NORMAL = auto()
    PENDING = auto()
    ACTIVE = auto()
    ACKNOWLEDGED = auto()
    CLEARED = auto()


_TRANSITIONS: dict[AlarmState, set[AlarmState]] = {
    AlarmState.NORMAL: {AlarmState.PENDING},
    AlarmState.PENDING: {AlarmState.NORMAL, AlarmState.ACTIVE},
    AlarmState.ACTIVE: {AlarmState.ACKNOWLEDGED, AlarmState.CLEARED},
    AlarmState.ACKNOWLEDGED: {AlarmState.CLEARED},
    AlarmState.CLEARED: {AlarmState.NORMAL},
}


def is_valid_transition(from_state: AlarmState, to_state: AlarmState) -> bool:
    return to_state in _TRANSITIONS.get(from_state, set())


class AlarmStateMachine:
    def __init__(self, delay_ms: int = 0) -> None:
        self._state: AlarmState = AlarmState.NORMAL
        self._delay_ms: int = delay_ms
        self._pending_start_frame: int | None = None

    @property
    def state(self) -> AlarmState:
        return self._state

    @property
    def delay_ms(self) -> int:
        return self._delay_ms

    @delay_ms.setter
    def delay_ms(self, value: int) -> None:
        self._delay_ms = value

    def reset(self) -> None:
        self._state = AlarmState.NORMAL
        self._pending_start_frame = None

    def evaluate(
        self,
        is_triggered: bool,
        should_clear: bool,
        frame_timestamp_ms: int,
    ) -> tuple[AlarmState, AlarmState | None]:
        old_state = self._state

        if self._state == AlarmState.NORMAL:
            if is_triggered:
                if self._delay_ms > 0:
                    self._state = AlarmState.PENDING
                    self._pending_start_frame = frame_timestamp_ms
                else:
                    self._state = AlarmState.ACTIVE

        elif self._state == AlarmState.PENDING:
            if not is_triggered:
                self._state = AlarmState.NORMAL
                self._pending_start_frame = None
            elif self._elapsed_ms(frame_timestamp_ms) >= self._delay_ms:
                self._state = AlarmState.ACTIVE
                self._pending_start_frame = None

        elif self._state == AlarmState.ACTIVE:
            if should_clear:
                self._state = AlarmState.CLEARED

        elif self._state == AlarmState.ACKNOWLEDGED:
            if should_clear:
                self._state = AlarmState.CLEARED

        elif self._state == AlarmState.CLEARED:
            self._state = AlarmState.NORMAL

        new_state = self._state
        transition = old_state if old_state != new_state else None
        return new_state, transition

    def acknowledge(self) -> AlarmState | None:
        if self._state != AlarmState.ACTIVE:
            return None
        old = self._state
        self._state = AlarmState.ACKNOWLEDGED
        return old

    def force_clear(self) -> AlarmState | None:
        old = self._state
        self._state = AlarmState.CLEARED
        self._pending_start_frame = None
        return old

    def _elapsed_ms(self, frame_timestamp_ms: int) -> int:
        if self._pending_start_frame is None:
            return 0
        return frame_timestamp_ms - self._pending_start_frame
