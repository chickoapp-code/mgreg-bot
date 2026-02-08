"""Database models and initialization."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import aiosqlite


class Database:
    """SQLite database wrapper."""

    def __init__(self, db_path: str = "bot.db") -> None:
        self.db_path = db_path

    async def init(self) -> None:
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            # Tasks table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id INTEGER PRIMARY KEY,
                    nomber TEXT,
                    restaurant_name TEXT NOT NULL,
                    restaurant_address TEXT,
                    visit_date TEXT,
                    deadline TEXT NOT NULL,
                    status TEXT,
                    assigned_guest_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Add nomber column if it doesn't exist (migration for existing databases)
            try:
                await db.execute("ALTER TABLE tasks ADD COLUMN nomber TEXT")
            except Exception:
                pass
            # Add assignment message columns for "Начать прохождение" message (to delete after form submit)
            for col in ("assignment_chat_id", "assignment_message_id"):
                try:
                    await db.execute(f"ALTER TABLE tasks ADD COLUMN {col} INTEGER")
                except Exception:
                    pass

            # Invitations table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    guest_planfix_id INTEGER NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    withdrawn_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)

            # Guest telegram mapping
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guest_telegram_map (
                    planfix_contact_id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Form sessions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS form_sessions (
                    session_id TEXT PRIMARY KEY,
                    task_id INTEGER NOT NULL,
                    guest_planfix_id INTEGER NOT NULL,
                    form TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    score INTEGER,
                    summary TEXT,
                    payload TEXT,
                    file_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)

            # Indexes
            await db.execute("CREATE INDEX IF NOT EXISTS idx_invitations_task_id ON invitations(task_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_invitations_guest_id ON invitations(guest_planfix_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_form_sessions_task_id ON form_sessions(task_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_form_sessions_completed ON form_sessions(completed_at)")

            await db.commit()

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get database connection."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute query."""
        async with self.connection() as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor

    async def fetch_one(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        """Fetch one row."""
        async with self.connection() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchone()

    async def fetch_all(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """Fetch all rows."""
        async with self.connection() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchall()


# Global database instance
_db: Optional[Database] = None


def get_database(db_path: str = "bot.db") -> Database:
    """Get database instance."""
    global _db
    if _db is None:
        _db = Database(db_path)
    return _db








