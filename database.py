"""
database.py — SQLite wrapper for SG Tuition Match Bot
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "/data/tuition.db"):
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

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    photo_file_id TEXT,
                    expires_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_telegram_id INTEGER NOT NULL,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    reason TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tutors_active   ON tutors(active);
                CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_subs_status     ON subscriptions(status);
                CREATE INDEX IF NOT EXISTS idx_subs_tutor      ON subscriptions(tutor_id);
                CREATE INDEX IF NOT EXISTS idx_reports_tutor   ON reports(tutor_id);
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

    def get_all_tutors(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tutors ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_tutor_active(self, tutor_id, active: bool):
        with self._conn() as conn:
            conn.execute(
                "UPDATE tutors SET active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if active else 0, tutor_id)
            )

    def delete_tutor(self, tutor_id):
        """Hard delete — removes all child records first to satisfy FK constraints."""
        with self._conn() as conn:
            conn.execute("DELETE FROM reports WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM interests WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM subscriptions WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM tutors WHERE id = ?", (tutor_id,))

    def find_matching_subscribed_tutors(self, subject, level, zone, budget) -> list:
        """Returns active subscribed tutors matching the job. Budget has 30% flex."""
        budget_flex = int(budget * 1.3)
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT t.*
                FROM tutors t
                INNER JOIN subscriptions s ON s.tutor_id = t.id
                WHERE t.active = 1
                  AND s.status = 'active'
                  AND s.expires_at > ?
                  AND t.subjects LIKE ?
                  AND t.levels LIKE ?
                  AND (t.zones LIKE ? OR t.zones LIKE '%Anywhere%')
                  AND t.rate_min <= ?
                """,
                (now, f"%{subject}%", f"%{level}%", f"%{zone}%", budget_flex),
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

    def get_all_jobs(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_job(self, job_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM interests WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM reports WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # =========================================================================
    # INTERESTS
    # =========================================================================

    def has_expressed_interest(self, tutor_id, job_id) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM interests WHERE tutor_id = ? AND job_id = ?",
                (tutor_id, job_id)
            ).fetchone()
            return row is not None

    def record_interest(self, tutor_id, job_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO interests (tutor_id, job_id) VALUES (?, ?)",
                (tutor_id, job_id)
            )

    # =========================================================================
    # SUBSCRIPTIONS
    # =========================================================================

    def create_subscription(self, tutor_id, amount) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO subscriptions (tutor_id, amount, status) VALUES (?, ?, 'pending')",
                (tutor_id, amount)
            )
            return cursor.lastrowid

    def attach_sub_screenshot(self, sub_id, photo_file_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE subscriptions SET photo_file_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (photo_file_id, sub_id)
            )

    def get_subscription(self, sub_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_active_subscription(self, tutor_id) -> Optional[dict]:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE tutor_id = ? AND status = 'active' AND expires_at > ?
                ORDER BY expires_at DESC LIMIT 1
                """,
                (tutor_id, now)
            ).fetchone()
            return dict(row) if row else None

    def get_pending_subscription(self, tutor_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE tutor_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (tutor_id,)
            ).fetchone()
            return dict(row) if row else None

    def activate_subscription(self, sub_id) -> str:
        """Activates for 30 days. Returns the expiry datetime string."""
        expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET status = 'active', expires_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (expires_at, sub_id)
            )
        return expires_at

    def reject_subscription(self, sub_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE subscriptions SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (sub_id,)
            )

    def get_subscriptions_expiring_in_days(self, days: int) -> list:
        now = datetime.utcnow()
        window_end = (now + timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE status = 'active'
                  AND expires_at >= ?
                  AND expires_at <= ?
                """,
                (now.isoformat(), window_end)
            ).fetchall()
        return [dict(r) for r in rows]

    def expire_old_subscriptions(self) -> int:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE subscriptions
                SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'active' AND expires_at < ?
                """,
                (now,)
            )
            return cursor.rowcount

    # =========================================================================
    # REPORTS
    # =========================================================================

    def save_report(self, reporter_telegram_id, tutor_id, job_id, reason) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reports (reporter_telegram_id, tutor_id, job_id, reason)
                VALUES (?, ?, ?, ?)
                """,
                (reporter_telegram_id, tutor_id, job_id, reason)
            )
            return cursor.lastrowid

    def count_reports_for_tutor(self, tutor_id) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM reports WHERE tutor_id = ? AND status != 'dismissed'",
                (tutor_id,)
            ).fetchone()
            return row[0] if row else 0

    def dismiss_report(self, report_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE reports SET status = 'dismissed' WHERE id = ?",
                (report_id,)
            )

    def get_reports_for_tutor(self, tutor_id) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reports WHERE tutor_id = ? ORDER BY created_at DESC",
                (tutor_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # ADMIN STATS
    # =========================================================================

    def get_stats(self) -> dict:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            tutors          = conn.execute("SELECT COUNT(*) FROM tutors WHERE active = 1").fetchone()[0]
            active_subs     = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND expires_at > ?", (now,)).fetchone()[0]
            pending_subs    = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'pending'").fetchone()[0]
            open_jobs       = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
            total_jobs      = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            total_interests = conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0]
            pending_reports = conn.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'").fetchone()[0]
            total_earned    = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM subscriptions WHERE status IN ('active', 'expired')").fetchone()[0]
        return {
            "tutors":          tutors,
            "active_subs":     active_subs,
            "pending_subs":    pending_subs,
            "open_jobs":       open_jobs,
            "total_jobs":      total_jobs,
            "total_interests": total_interests,
            "pending_reports": pending_reports,
            "total_earned":    total_earned,
        }
