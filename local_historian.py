import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


# Deliberately NOT setup_logger(): a second independent
# RotatingFileHandler on the same file caused a Windows file-locking
# hang when two handlers tried to roll over telemetry_poller.log at
# once (see offline_buffer.py, which hit this first). Child logger
# name propagates into telemetry-poller's single already-configured
# handler instead of owning its own.
logger = logging.getLogger("telemetry-poller.local_historian")

_database_lock = threading.Lock()

BASE_DIR = Path(__file__).resolve().parent

# Same SQLite file as offline_buffer.py's send-queue, different table.
# Reusing the file means WAL mode, disk location, and backup/restore
# handling are already solved by the existing queue -- no reason to
# duplicate any of that for a second table.
DATABASE_PATH = BASE_DIR / "gateway_buffer.db"

# Unlike offline_buffer's telemetry_queue (a transient send-queue that
# prunes "sent" rows down to the newest 1000), this table exists to
# answer "what actually happened here" during an outage or after one
# -- so it prunes by age, not by count. This is also where edge alarm
# evaluation's baseline/recent-value lookups should read from once
# that's built, not the transient queue.
HISTORY_RETENTION_DAYS = 30


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=FULL;")
    connection.execute("PRAGMA foreign_keys=ON;")

    return connection


def initialize_database() -> None:
    """Create the local history table if it does not exist."""
    with _database_lock:
        with get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    value REAL NOT NULL,
                    quality TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_history_device_tag_ts
                ON telemetry_history(device_id, tag_id, source_timestamp)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_history_created_at
                ON telemetry_history(created_at)
                """
            )

            connection.commit()


def record_reading(
    device_id: int,
    tag_id: int,
    value: float,
    quality: str,
    source_timestamp: str,
) -> None:
    """Append one reading to the local history. Best-effort -- a
    failure here must never block or fail the actual telemetry
    upload path, which is why callers wrap this in its own
    try/except rather than letting an exception here propagate."""

    with _database_lock:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO telemetry_history
                    (device_id, tag_id, value, quality,
                     source_timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(device_id),
                    int(tag_id),
                    float(value),
                    str(quality),
                    source_timestamp,
                    utc_now_iso(),
                ),
            )

            connection.commit()


def prune_old_history() -> int:
    """Deletes rows older than HISTORY_RETENTION_DAYS. Returns the
    number of rows removed."""

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=HISTORY_RETENTION_DAYS)
    ).isoformat()

    with _database_lock:
        with get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM telemetry_history WHERE created_at < ?",
                (cutoff,),
            )

            connection.commit()

            return cursor.rowcount


def get_recent_readings(
    device_id: int,
    tag_id: int,
    since_iso: str,
) -> list[sqlite3.Row]:
    """Every reading for one device/tag since a given ISO timestamp,
    oldest first. The building block edge alarm evaluation needs for
    delay_seconds handling and any future local baseline math."""

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT value, quality, source_timestamp
            FROM telemetry_history
            WHERE device_id = ?
              AND tag_id = ?
              AND source_timestamp >= ?
            ORDER BY source_timestamp ASC
            """,
            (int(device_id), int(tag_id), since_iso),
        )

        return cursor.fetchall()
