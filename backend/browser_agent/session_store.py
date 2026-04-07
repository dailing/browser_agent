import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from browser_agent.db_models import MessageRow, SessionRow


@dataclass
class SessionView:
    id: str
    name: str | None
    status: str
    error: str | None
    max_steps: int
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]


class DbSessionStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    def _iso(self, dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    async def create_empty(self, *, name: str | None, max_steps: int) -> SessionView:
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        async with self._sf() as db:
            db.add(
                SessionRow(
                    id=sid,
                    name=name,
                    status="idle",
                    error=None,
                    max_steps=max_steps,
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.commit()
        out = await self.get(sid)
        assert out is not None
        return out

    async def get(self, session_id: str) -> SessionView | None:
        async with self._sf() as db:
            srow = await db.get(SessionRow, session_id)
            if srow is None:
                return None
            mstmt = (
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.id.asc())
            )
            mres = await db.execute(mstmt)
            mrows = mres.scalars().all()
            messages = [dict(m.payload) for m in mrows]
            return SessionView(
                id=srow.id,
                name=srow.name,
                status=srow.status,
                error=srow.error,
                max_steps=srow.max_steps,
                created_at=self._iso(srow.created_at),
                updated_at=self._iso(srow.updated_at),
                messages=messages,
            )

    async def list_summaries(self) -> list[dict[str, Any]]:
        async with self._sf() as db:
            stmt = (
                select(SessionRow, func.count(MessageRow.id))
                .outerjoin(MessageRow, MessageRow.session_id == SessionRow.id)
                .group_by(SessionRow.id)
                .order_by(SessionRow.created_at.desc())
            )
            res = await db.execute(stmt)
            rows = res.all()
            return [
                {
                    "id": r[0].id,
                    "name": r[0].name,
                    "status": r[0].status,
                    "created_at": self._iso(r[0].created_at),
                    "message_count": int(r[1]),
                }
                for r in rows
            ]

    async def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        role = str(message.get("role", ""))
        async with self._sf() as db:
            db.add(
                MessageRow(session_id=session_id, role=role, payload=dict(message), created_at=now)
            )
            await db.execute(
                update(SessionRow).where(SessionRow.id == session_id).values(updated_at=now)
            )
            await db.commit()

    async def set_status(self, session_id: str, status: str, error: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        async with self._sf() as db:
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(status=status, error=error, updated_at=now)
            )
            await db.commit()

    async def delete(self, session_id: str) -> bool:
        async with self._sf() as db:
            srow = await db.get(SessionRow, session_id)
            if srow is None:
                return False
            await db.delete(srow)
            await db.commit()
        return True
