"""
database.py — SQLite wrapper
"""

import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "tuition.db"):
        self.db_path = db_path
        self._init_tables()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tutors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    tutor_type TEXT NOT NULL,
                    subjects TEXT NOT NULL,
                    levels TEXT NOT NULL,
                    rate_min INTEGER NOT NULL,
                    rate_max INTEGER NOT NULL,
                    zones TEXT NOT NULL,
                    qualifications TEXT,
                    phone TEXT NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    level TEXT NOT NULL,
                    zone TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    budget INTEGER NOT NULL,
                    tutor_type_pref TEXT,
                    contact TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS interests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tutor_id, job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tutors_active ON tutors(active);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            """)
        logger.info("Database initialised.")

    def save_tutor(self, telegram_id, name, tutor_type, subjects, levels,
                   rate_min, rate_max, zones, qualifications, phone):
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tutors
                    (telegram_id, name, tutor_type, subjects, levels,
                     rate_min, rate_max, zones, qualifications, phone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def get_tutor_by_telegram_id(self, telegram_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tutors WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return dict(row) if row else None

    def find_matching_tutors(self, subject, level, zone, budget) -> list:
        budget_flex = int(budget * 1.3)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tutors
                WHERE active = 1
                  AND subjects LIKE ?
                  AND levels LIKE ?
                  AND (zones LIKE ? OR zones LIKE '%Anywhere%')
                  AND rate_min <= ?
                """,
                (f"%{subject}%", f"%{level}%", f"%{zone}%", budget_flex),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_job(self, telegram_id, subject, level, zone, schedule,
                 budget, tutor_type_pref, contact) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs
                    (telegram_id, subject, level, zone, schedule,
                     budget, tutor_type_pref, contact)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, subject, level, zone, schedule,
                 budget, tutor_type_pref, contact),
            )
            return cursor.lastrowid

    def get_job_by_id(self, job_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_open_jobs(self, limit=10) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'open' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_jobs_by_poster(self, telegram_id) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE telegram_id = ? ORDER BY created_at DESC",
                (telegram_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_interest(self, tutor_id, job_id) -> bool:
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT id FROM interests WHERE tutor_id = ? AND job_id = ?",
                (tutor_id, job_id)
            ).fetchone()
            if exists:
                return True
            conn.execute(
                "INSERT INTO interests (tutor_id, job_id) VALUES (?, ?)",
                (tutor_id, job_id)
            )
            return False
