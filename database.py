"""
database.py — SQLite wrapper for the Tuition Matching Bot
==========================================================

Why SQLite for MVP?
  - Zero setup: no server to run, no connection strings, no cost
  - Comes built-in with Python (no install needed)
  - Handles hundreds of concurrent users fine (Telegram bots aren't that write-heavy)
  - Easy to migrate to PostgreSQL later by swapping the connection string and driver

When to upgrade to PostgreSQL:
  - When you have >1,000 active users
  - When you need full-text search on tutor profiles
  - When you want to run analytics queries on a separate read replica
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "tuition.db"):
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """
        We create a new connection per call rather than keeping one open.
        This is safe for our async bot because python-telegram-bot runs handlers
        in a thread pool, and sqlite3 connections are NOT thread-safe if shared.
        Each connection is short-lived and cheap to create for SQLite.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Allows dict-like access: row["name"]
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging: better for concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_tables(self):
        """Create tables if they don't exist. Safe to run on every startup."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tutors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    tutor_type TEXT NOT NULL,
                    subjects TEXT NOT NULL,      -- comma-separated
                    levels TEXT NOT NULL,         -- comma-separated
                    rate_min INTEGER NOT NULL,
                    rate_max INTEGER NOT NULL,
                    zones TEXT NOT NULL,          -- comma-separated
                    qualifications TEXT,
                    phone TEXT NOT NULL,
                    active INTEGER DEFAULT 1,     -- 1 = active, 0 = paused
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL, -- poster's Telegram ID
                    subject TEXT NOT NULL,
                    level TEXT NOT NULL,
                    zone TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    budget INTEGER NOT NULL,
                    tutor_type_pref TEXT,
                    contact TEXT NOT NULL,
                    status TEXT DEFAULT 'open',   -- open, filled, cancelled
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS interests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tutor_id, job_id)       -- prevent duplicate interests
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    amount INTEGER NOT NULL,       -- in SGD cents
                    status TEXT DEFAULT 'pending', -- pending, paid
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- Index for the most common query: find tutors by subject + zone
                CREATE INDEX IF NOT EXISTS idx_tutors_active ON tutors(active);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            """)
        logger.info("Database initialised.")

    # =========================================================================
    # TUTOR OPERATIONS
    # =========================================================================

    def save_tutor(
        self,
        telegram_id: int,
        name: str,
        tutor_type: str,
        subjects: str,
        levels: str,
        rate_min: int,
        rate_max: int,
        zones: str,
        qualifications: str,
        phone: str,
    ) -> int:
        """
        INSERT OR REPLACE: if the tutor already exists (same telegram_id),
        update their profile. This handles re-registration gracefully.
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tutors
                    (telegram_id, name, tutor_type, subjects, levels,
                     rate_min, rate_max, zones, qualifications, phone, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    name=excluded.name,
                    tutor_type=excluded.tutor_type,
                    subjects=excluded.subjects,
                    levels=excluded.levels,
                    rate_min=excluded.rate_min,
                    rate_max=excluded.rate_max,
                    zones=excluded.zones,
                    qualifications=excluded.qualifications,
                    phone=excluded.phone,
                    active=1,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (telegram_id, name, tutor_type, subjects, levels,
                 rate_min, rate_max, zones, qualifications, phone),
            )
            return cursor.lastrowid

    def get_tutor_by_telegram_id(self, telegram_id: int) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tutors WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return dict(row) if row else None

    def find_matching_tutors(
        self, subject: str, level: str, zone: str, budget: int
    ) -> list[dict]:
        """
        Matching logic — finds tutors whose:
          1. subjects include the requested subject
          2. levels include the requested level
          3. zones include the requested zone OR they teach island-wide
          4. minimum rate is within the parent's budget (within 30% flex)
          5. profile is active

        Why LIKE for comma-separated fields?
          Simple and sufficient for MVP. If subjects grow to 100+, switch to
          a many-to-many join table or use PostgreSQL's array type.
        """
        budget_with_flex = int(budget * 1.3)  # Allow 30% over-budget tutors to be notified too
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tutors
                WHERE active = 1
                  AND subjects LIKE ?
                  AND levels LIKE ?
                  AND (zones LIKE ? OR zones LIKE '%Anywhere%')
                  AND rate_min <= ?
                """,
                (
                    f"%{subject}%",
                    f"%{level}%",
                    f"%{zone}%",
                    budget_with_flex,
                ),
            ).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # JOB OPERATIONS
    # =========================================================================

    def save_job(
        self,
        telegram_id: int,
        subject: str,
        level: str,
        zone: str,
        schedule: str,
        budget: int,
        tutor_type_pref: str,
        contact: str,
    ) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs
                    (telegram_id, subject, level, zone, schedule, budget, tutor_type_pref, contact)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, subject, level, zone, schedule, budget, tutor_type_pref, contact),
            )
            return cursor.lastrowid

    def get_job_by_id(self, job_id: int) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_open_jobs(self, limit: int = 10) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'open' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_jobs_by_poster(self, telegram_id: int) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE telegram_id = ? ORDER BY created_at DESC",
                (telegram_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close_job(self, job_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'filled' WHERE id = ?", (job_id,)
            )

    # =========================================================================
    # INTEREST OPERATIONS
    # =========================================================================

    def record_interest(self, tutor_id: int, job_id: int) -> bool:
        """
        Returns True if the tutor had already expressed interest (duplicate).
        Uses INSERT OR IGNORE to handle the UNIQUE constraint gracefully.
        """
        with self._get_conn() as conn:
            before = conn.execute(
                "SELECT id FROM interests WHERE tutor_id = ? AND job_id = ?",
                (tutor_id, job_id)
            ).fetchone()
            if before:
                return True  # Already exists
            conn.execute(
                "INSERT INTO interests (tutor_id, job_id) VALUES (?, ?)",
                (tutor_id, job_id)
            )
            return False

    def get_interests_for_job(self, job_id: int) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT t.*, i.created_at as interest_at
                FROM interests i
                JOIN tutors t ON t.id = i.tutor_id
                WHERE i.job_id = ?
                ORDER BY i.created_at ASC
                """,
                (job_id,),
            ).fetchall()
        return [dict(r) for r in rows]
