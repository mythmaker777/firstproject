"""
database.py — SQLite wrapper for SG Tuition Match Bot
"You've Been Selected" model — per-match payment, no subscriptions
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

                -- Tutor applies for a job (free)
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    status TEXT DEFAULT 'applied',  -- applied | shortlisted | paid | rejected
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tutor_id, job_id)
                );

                -- Payment triggered when parent shortlists a tutor
                CREATE TABLE IF NOT EXISTS match_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',  -- pending | approved | rejected
                    paynow_reference TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- Confirmed matches (contact has been released)
                CREATE TABLE IF NOT EXISTS interests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tutor_id, job_id)
                );

                -- Parent reports of tutor misconduct
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_telegram_id INTEGER NOT NULL,
                    tutor_id INTEGER REFERENCES tutors(id),
                    job_id INTEGER REFERENCES jobs(id),
                    reason TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',  -- pending | actioned | dismissed
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tutors_active     ON tutors(active);
                CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_apps_job          ON applications(job_id);
                CREATE INDEX IF NOT EXISTS idx_apps_tutor        ON applications(tutor_id);
                CREATE INDEX IF NOT EXISTS idx_payments_status   ON match_payments(status);
                CREATE INDEX IF NOT EXISTS idx_reports_tutor     ON reports(tutor_id);
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
        """Hard delete — removes all child records first."""
        with self._conn() as conn:
            conn.execute("DELETE FROM reports       WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM interests      WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM match_payments WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM applications   WHERE tutor_id = ?", (tutor_id,))
            conn.execute("DELETE FROM tutors         WHERE id = ?",       (tutor_id,))

    def find_matching_tutors(self, subject, level, zone, budget) -> list:
        """Returns all active registered tutors matching the job. Budget has 30% flex."""
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

    def get_all_jobs(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_job(self, job_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM reports       WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM interests      WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM match_payments WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM applications   WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs           WHERE id = ?",     (job_id,))

    # =========================================================================
    # APPLICATIONS (free — tutor applies for job)
    # =========================================================================

    def save_application(self, tutor_id, job_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO applications (tutor_id, job_id) VALUES (?, ?)",
                (tutor_id, job_id)
            )

    def has_applied(self, tutor_id, job_id) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM applications WHERE tutor_id = ? AND job_id = ?",
                (tutor_id, job_id)
            ).fetchone()
            return row is not None

    def get_applications_for_job(self, job_id) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM applications WHERE job_id = ? ORDER BY created_at ASC",
                (job_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_applications_for_job(self, job_id) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE job_id = ?", (job_id,)
            ).fetchone()
            return row[0] if row else 0

    def shortlist_application(self, tutor_id, job_id):
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE applications SET status = 'shortlisted', updated_at = CURRENT_TIMESTAMP
                WHERE tutor_id = ? AND job_id = ?
                """,
                (tutor_id, job_id)
            )

    # =========================================================================
    # MATCH PAYMENTS (triggered after parent shortlists)
    # =========================================================================

    def create_match_payment(self, tutor_id, job_id, amount) -> int:
        """Creates a pending payment record that expires in 24 hours."""
        expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO match_payments (tutor_id, job_id, amount, status, expires_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (tutor_id, job_id, amount, expires_at)
            )
            return cursor.lastrowid

    def get_match_payment(self, payment_id) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM match_payments WHERE id = ?", (payment_id,)
            ).fetchone()
            return dict(row) if row else None

    def is_match_payment_expired(self, payment_id) -> bool:
        """Returns True if the 24-hour offer window has passed."""
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM match_payments WHERE id = ? AND expires_at < ?",
                (payment_id, now)
            ).fetchone()
        return row is not None

    def save_match_reference(self, payment_id, reference):
        """Stores the tutor's PayNow transaction reference number."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE match_payments SET paynow_reference = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (reference, payment_id)
            )

    def approve_match_payment(self, payment_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE match_payments SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payment_id,)
            )

    def reject_match_payment(self, payment_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE match_payments SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payment_id,)
            )

    # =========================================================================
    # CONFIRMED MATCHES
    # =========================================================================

    def record_interest(self, tutor_id, job_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO interests (tutor_id, job_id) VALUES (?, ?)",
                (tutor_id, job_id)
            )

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
                "UPDATE reports SET status = 'dismissed' WHERE id = ?", (report_id,)
            )

    # =========================================================================
    # ADMIN STATS
    # =========================================================================

    def get_stats(self) -> dict:
        with self._conn() as conn:
            tutors             = conn.execute("SELECT COUNT(*) FROM tutors WHERE active = 1").fetchone()[0]
            open_jobs          = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'open'").fetchone()[0]
            total_jobs         = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            total_applications = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            shortlisted        = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'shortlisted'").fetchone()[0]
            pending_payments   = conn.execute("SELECT COUNT(*) FROM match_payments WHERE status = 'pending'").fetchone()[0]
            confirmed_matches  = conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0]
            pending_reports    = conn.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'").fetchone()[0]
            total_earned       = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM match_payments WHERE status = 'approved'").fetchone()[0]
        return {
            "tutors":             tutors,
            "open_jobs":          open_jobs,
            "total_jobs":         total_jobs,
            "total_applications": total_applications,
            "shortlisted":        shortlisted,
            "pending_payments":   pending_payments,
            "confirmed_matches":  confirmed_matches,
            "pending_reports":    pending_reports,
            "total_earned":       total_earned,
        }
