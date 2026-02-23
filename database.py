"""
database.py — SQLite wrapper with payments support
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

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    photo_file_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tutors_active ON tutors(active);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
            """)
        logger.info("Database initialised.")

    # =========================================================================
    # TUTORS
    # =========================================================================

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

    def get_tutor_by_id(self, tutor_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tutors WHERE id = ?", (tutor_id,)
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

    # =========================================================================
    # JOBS
    # =========================================================================

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

    def close_job(self, job_id):
        with self._conn() as conn:
            conn.execute("UPDATE jobs SET status = 'filled' WHERE id = ?", (job_id,))

    # =========================================================================
    # INTERESTS
    # =========================================================================

    def has_expressed_interest(self, tutor_id, job_id) -> bool:
        """Returns True if the tutor has already expressed interest OR has a pending payment."""
        with self._conn() as conn:
            # Check interests table
            interest = conn.execute(
                "SELECT id FROM interests WHERE tutor_id = ? AND job_id = ?",
                (tutor_id, job_id)
            ).fetchone()
            if interest:
                return True
            # Also check if there's already a pending/approved payment
            payment = conn.execute(
                "SELECT id FROM payments WHERE tutor_id = ? AND job_id = ? AND status != 'rejected'",
                (tutor_id, job_id)
            ).fetchone()
            return payment is not None

    def record_interest(self, tutor_id, job_id) -> bool:
        """Records a confirmed interest (called after payment approval). Returns True if duplicate."""
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

    # =========================================================================
    # PAYMENTS
    # =========================================================================

    def create_payment(self, tutor_id, job_id, amount) -> int:
        """Creates a new pending payment record. Returns the payment ID."""
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO payments (tutor_id, job_id, amount, status) VALUES (?, ?, ?, 'pending')",
                (tutor_id, job_id, amount)
            )
            return cursor.lastrowid

    def attach_screenshot(self, payment_id, photo_file_id):
        """Saves the Telegram file_id of the payment screenshot."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE payments SET photo_file_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (photo_file_id, payment_id)
            )

    def get_payment(self, payment_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE id = ?", (payment_id,)
            ).fetchone()
            return dict(row) if row else None

    def approve_payment(self, payment_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE payments SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payment_id,)
            )

    def reject_payment(self, payment_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE payments SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payment_id,)
            )

    # =========================================================================
    # ADMIN STATS
    # =========================================================================

    def get_stats(self) -> dict:
        with self._conn() as conn:
            tutors = conn.execute("SELECT COUNT(*) FROM tutors WHERE active = 1").fetchone()[0]
            open_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
            total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            pending_payments = conn.execute(
                "SELECT COUNT(*) FROM payments WHERE status = 'pending'"
            ).fetchone()[0]
            approved_payments = conn.execute(
                "SELECT COUNT(*) FROM payments WHERE status = 'approved'"
            ).fetchone()[0]
            total_earned = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved'"
            ).fetchone()[0]
        return {
            "tutors": tutors,
            "open_jobs": open_jobs,
            "total_jobs": total_jobs,
            "pending_payments": pending_payments,
            "approved_payments": approved_payments,
            "total_earned": total_earned,
        }
