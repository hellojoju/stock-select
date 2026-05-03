"""Simple in-memory step logger for execution process visibility."""

import threading
import time
from datetime import datetime
from typing import Any

_step_logs: dict[str, list[dict[str, Any]]] = {}
_lock = threading.Lock()


def init_session(session_id: str) -> None:
    """Initialize a new step log session."""
    with _lock:
        _step_logs[session_id] = []


def log_step(
    session_id: str,
    message: str,
    detail: str = "",
    completed: bool = False,
    request_data: dict | None = None,
    response_data: dict | None = None,
) -> None:
    """Append a step to the session log."""
    with _lock:
        if session_id not in _step_logs:
            _step_logs[session_id] = []
        entry = {
            "message": message,
            "detail": detail,
            "completed": completed,
            "timestamp": time.time(),
            "time_display": datetime.now().strftime("%H:%M:%S"),
        }
        if request_data is not None:
            entry["request"] = request_data
        if response_data is not None:
            entry["response"] = response_data
        _step_logs[session_id].append(entry)


def get_session_steps(session_id: str) -> list[dict[str, Any]]:
    """Get all steps for a session."""
    with _lock:
        return list(_step_logs.get(session_id, []))


def clear_session(session_id: str) -> None:
    """Remove a session's step log."""
    with _lock:
        _step_logs.pop(session_id, None)


def cleanup_stale_sessions(max_age: float = 300) -> None:
    """Remove sessions older than max_age seconds."""
    now = time.time()
    with _lock:
        stale = [
            sid for sid, steps in _step_logs.items()
            if steps and now - steps[-1].get("timestamp", 0) > max_age
        ]
        for sid in stale:
            del _step_logs[sid]
