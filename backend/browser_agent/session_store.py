import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Session:
    id: str
    goal: str
    created_at: str
    status: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, goal: str) -> Session:
        sid = str(uuid.uuid4())
        s = Session(
            id=sid,
            goal=goal,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="running",
        )
        self._sessions[sid] = s
        return s

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def all_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        s = self._sessions.get(session_id)
        if s is None:
            return
        s.messages.append(message)

    def set_status(self, session_id: str, status: str, error: str | None = None) -> None:
        s = self._sessions.get(session_id)
        if s is None:
            return
        s.status = status
        s.error = error
