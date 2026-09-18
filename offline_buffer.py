import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "gateway_buffer.db"

# Deliberately NOT setup_logger(): a second independent
# RotatingFileHandler on the same file caused a Windows file-locking
# hang when two handlers tried to roll over telemetry_poller.log at
# once. This is a child of the "telemetry-poller" logger (dotted name)
# so it propagates into that logger's single already-configured
# handler instead of owning its own.
logger = logging.getLogger("telemetry-poller.offline_buffer")

_database_lock = threading.Lock()
_connection: sqlite3.Connection | None = None
_connection_path: Path | None = None


def utc_now_iso() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    """
    Return the shared local SQLite connection, opening it once.

    Every caller in this module does `with _database_lock: with
    get_connection() as connection:` -- `with connection:` only manages
    the transaction (commit/rollback), it never closes the connection,
    so this used to open (and never explicitly close) a brand-new
    connection plus reissue every PRAGMA below on every single call --
    called twice per telemetry reading via
    dynamic_modbus_poller.save_telemetry. _database_lock already
    serializes every access, so one long-lived connection, reused for
    the life of the process, is safe here; check_same_thread=False is
    only safe *because* of that serialization -- don't touch this
    connection anywhere the lock isn't held. Relies on
    initialize_database() being called once at startup before any
    other thread reaches this function (main() does exactly that),
    since the lazy check below isn't itself lock-protected (it can't
    be -- every caller already holds _database_lock before calling in).

    Reopens if DATABASE_PATH has changed since the cached connection
    was opened (the test suite monkeypatches it per-test via
    initialize_database()) rather than caching by process lifetime
    alone -- production never changes DATABASE_PATH after startup, so
    this is a no-op there.

    WAL mode provides better reliability when the gateway reads and
    writes the buffer at the same time. synchronous=NORMAL is safe
    under WAL -- durable against an application crash; only an OS
    crash or power loss at the moment of commit could lose the single
    most recent transaction -- without forcing a full fsync on every
    write the way synchronous=FULL does.
    """
    global _connection, _connection_path

    if _connection is not None and _connection_path == DATABASE_PATH:
        return _connection

    if _connection is not None:
        _connection.close()

    _connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
        check_same_thread=False,
    )
    _connection_path = DATABASE_PATH

    _connection.row_factory = sqlite3.Row

    _connection.execute(
        "PRAGMA journal_mode=WAL;"
    )

    _connection.execute(
        "PRAGMA synchronous=NORMAL;"
    )

    _connection.execute(
        "PRAGMA foreign_keys=ON;"
    )

    return _connection


def initialize_database() -> None:
    """Create the offline telemetry queue if it does not exist."""
    with _database_lock:
        with get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    device_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    value REAL NOT NULL,
                    quality TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    last_attempt_at TEXT,
                    sent_at TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_queue_status_id
                ON telemetry_queue(status, id)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_queue_created_at
                ON telemetry_queue(created_at)
                """
            )

            connection.commit()

    logger.info(
        "Offline buffer database initialized: %s",
        DATABASE_PATH,
    )


def enqueue_telemetry(
    device_id: int,
    tag_id: int,
    value: float,
    quality: str,
    source_timestamp: Optional[str] = None,
) -> str:
    """
    Store one telemetry message in the local SQLite queue.

    Returns the generated unique message ID.
    """
    message_id = str(uuid.uuid4())

    timestamp = (
        source_timestamp
        or utc_now_iso()
    )

    payload = {
        "message_id": message_id,
        "device_id": int(device_id),
        "tag_id": int(tag_id),
        "value": float(value),
        "quality": str(quality),
        "source_timestamp": timestamp,
    }

    payload_json = json.dumps(
        payload,
        separators=(",", ":"),
    )

    created_at = utc_now_iso()

    with _database_lock:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO telemetry_queue (
                    message_id,
                    device_id,
                    tag_id,
                    value,
                    quality,
                    source_timestamp,
                    payload_json,
                    status,
                    attempts,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (
                    message_id,
                    int(device_id),
                    int(tag_id),
                    float(value),
                    str(quality),
                    timestamp,
                    payload_json,
                    created_at,
                ),
            )

            connection.commit()

    # Every reading now goes through this queue as the normal path
    # (see dynamic_modbus_poller.save_telemetry), not just on upload
    # failure -- debug, not warning, or this would log at warning level
    # on every single poll.
    logger.debug(
        "Telemetry queued for batch upload | "
        "message_id=%s | device_id=%s | tag_id=%s",
        message_id,
        device_id,
        tag_id,
    )

    return message_id


def get_pending_messages(
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return pending messages in oldest-first order."""
    safe_limit = max(
        1,
        min(int(limit), 1000),
    )

    with _database_lock:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    message_id,
                    device_id,
                    tag_id,
                    value,
                    quality,
                    source_timestamp,
                    payload_json,
                    attempts,
                    created_at,
                    last_attempt_at,
                    last_error
                FROM telemetry_queue
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

    messages = []

    for row in rows:
        item = dict(row)

        try:
            item["payload"] = json.loads(
                item["payload_json"]
            )
        except json.JSONDecodeError:
            item["payload"] = None

        messages.append(item)

    return messages


def mark_message_sent(
    message_id: str,
) -> None:
    """Mark a buffered message as uploaded successfully."""
    now = utc_now_iso()

    with _database_lock:
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE telemetry_queue
                SET
                    status = 'sent',
                    sent_at = ?,
                    last_attempt_at = ?,
                    last_error = NULL
                WHERE message_id = ?
                """,
                (
                    now,
                    now,
                    message_id,
                ),
            )

            connection.commit()


def mark_message_failed(
    message_id: str,
    error_message: str,
) -> None:
    """Record a failed resend attempt."""
    now = utc_now_iso()

    with _database_lock:
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE telemetry_queue
                SET
                    attempts = attempts + 1,
                    last_attempt_at = ?,
                    last_error = ?
                WHERE message_id = ?
                """,
                (
                    now,
                    str(error_message)[:1000],
                    message_id,
                ),
            )

            connection.commit()


def count_pending_messages() -> int:
    """Return the number of messages waiting for upload."""
    with _database_lock:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM telemetry_queue
                WHERE status = 'pending'
                """
            ).fetchone()

    return int(row["total"])


def count_all_messages() -> int:
    """Return the total number of queue records."""
    with _database_lock:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM telemetry_queue
                """
            ).fetchone()

    return int(row["total"])


def delete_sent_messages(
    keep_latest: int = 1000,
) -> int:
    """
    Delete older successfully uploaded messages.

    The newest sent records are retained for diagnostics.
    """
    safe_keep_latest = max(
        0,
        int(keep_latest),
    )

    with _database_lock:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM telemetry_queue
                WHERE status = 'sent'
                  AND id NOT IN (
                      SELECT id
                      FROM telemetry_queue
                      WHERE status = 'sent'
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (safe_keep_latest,),
            )

            deleted_count = cursor.rowcount
            connection.commit()

    return max(
        0,
        int(deleted_count),
    )


if __name__ == "__main__":
    initialize_database()

    print(f"Database: {DATABASE_PATH}")
    print(
        "Pending messages:",
        count_pending_messages(),
    )
    print(
        "Total messages:",
        count_all_messages(),
    )