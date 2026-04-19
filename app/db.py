from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import time
import hashlib
import secrets
from typing import Any

from app.manifest import Manifest


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
              match_id TEXT PRIMARY KEY,
              title TEXT,
              league TEXT,
              date TEXT,
              length_sec INTEGER,
              meta_json TEXT,
              video_path TEXT,
              video_url TEXT,
              video_sha256 TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commentaries (
              commentary_id TEXT PRIMARY KEY,
              match_id TEXT NOT NULL,
              type TEXT NOT NULL,
              language TEXT,
              source TEXT,
              text_path TEXT,
              text_format TEXT,
              audio_path TEXT,
              audio_url TEXT,
              audio_format TEXT,
              audio_sample_rate_hz INTEGER,
              alignment_json TEXT,
              meta_json TEXT,
              FOREIGN KEY(match_id) REFERENCES matches(match_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS judgments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              match_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              ranking_json TEXT NOT NULL,
              mode TEXT NOT NULL,
              latency_ms INTEGER,
              reason TEXT,
              flags_json TEXT,
              created_at TEXT DEFAULT (datetime('now')),
              FOREIGN KEY(match_id) REFERENCES matches(match_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              match_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              status TEXT NOT NULL,
              expires_at INTEGER,
              created_at TEXT DEFAULT (datetime('now')),
              FOREIGN KEY(match_id) REFERENCES matches(match_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_judgments_user ON judgments(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_judgments_match ON judgments(match_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assignments_user ON assignments(user_id);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              username TEXT PRIMARY KEY,
              nickname TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL,
              needs_password_reset INTEGER NOT NULL DEFAULT 0,
              created_at TEXT DEFAULT (datetime('now')),
              approved_by TEXT,
              approved_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              username TEXT NOT NULL,
              expires_at INTEGER NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY(username) REFERENCES users(username)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              actor_username TEXT,
              action TEXT NOT NULL,
              target TEXT,
              meta_json TEXT,
              created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_inbox_state (
              username TEXT PRIMARY KEY,
              last_seen_at INTEGER NOT NULL DEFAULT 0,
              last_seen_pending_count INTEGER NOT NULL DEFAULT 0,
              last_seen_manifest_at INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(username) REFERENCES users(username)
            )
            """
        )

        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(assignments)").fetchall()}
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE assignments ADD COLUMN expires_at INTEGER;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assignments_expires ON assignments(expires_at);")
        conn.execute("DROP INDEX IF EXISTS ux_assignments_assigning_match;")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_assignments_assigning_match_user ON assignments(match_id, user_id) WHERE status = 'assigning';"
        )


@contextmanager
def connect(db_path: Path) -> Iterable[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def sync_manifest(conn: sqlite3.Connection, manifest: Manifest) -> None:
    for match in manifest.matches:
        conn.execute(
            """
            INSERT INTO matches(match_id, title, league, date, length_sec, meta_json, video_path, video_url, video_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
              title=excluded.title,
              league=excluded.league,
              date=excluded.date,
              length_sec=excluded.length_sec,
              meta_json=excluded.meta_json,
              video_path=excluded.video_path,
              video_url=excluded.video_url,
              video_sha256=excluded.video_sha256
            """,
            (
                match.match_id,
                match.title,
                match.league,
                match.date,
                match.length_sec,
                json.dumps(match.meta, ensure_ascii=False),
                match.video.path,
                match.video.url,
                match.video.sha256,
            ),
        )
        for c in match.commentaries:
            conn.execute(
                """
                INSERT INTO commentaries(
                  commentary_id, match_id, type, language, source,
                  text_path, text_format,
                  audio_path, audio_url, audio_format, audio_sample_rate_hz,
                  alignment_json, meta_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(commentary_id) DO UPDATE SET
                  match_id=excluded.match_id,
                  type=excluded.type,
                  language=excluded.language,
                  source=excluded.source,
                  text_path=excluded.text_path,
                  text_format=excluded.text_format,
                  audio_path=excluded.audio_path,
                  audio_url=excluded.audio_url,
                  audio_format=excluded.audio_format,
                  audio_sample_rate_hz=excluded.audio_sample_rate_hz,
                  alignment_json=excluded.alignment_json,
                  meta_json=excluded.meta_json
                """,
                (
                    c.commentary_id,
                    c.match_id,
                    c.type,
                    c.language,
                    c.source,
                    (c.text.path if c.text else None),
                    (c.text.format if c.text else None),
                    (c.audio.path if c.audio else None),
                    (c.audio.url if c.audio else None),
                    (c.audio.format if c.audio else None),
                    (c.audio.sample_rate_hz if c.audio else None),
                    json.dumps(c.alignment, ensure_ascii=False) if c.alignment else None,
                    json.dumps({}, ensure_ascii=False),
                ),
            )

    conn.commit()


def list_judged_match_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    rows = conn.execute("SELECT DISTINCT match_id FROM judgments WHERE user_id = ?", (user_id,)).fetchall()
    return {str(r["match_id"]) for r in rows}


def cleanup_expired_assignments(conn: sqlite3.Connection, *, now: int) -> None:
    conn.execute(
        """
        UPDATE assignments
        SET status = 'expired'
        WHERE status = 'assigning' AND (expires_at IS NULL OR expires_at <= ?)
        """,
        (now,),
    )
    conn.commit()


def try_lock_assignment(conn: sqlite3.Connection, *, match_id: str, user_id: str, expires_at: int) -> bool:
    try:
        conn.execute(
            "INSERT INTO assignments(match_id, user_id, status, expires_at) VALUES (?, ?, 'assigning', ?)",
            (match_id, user_id, expires_at),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.commit()
        return False


def get_active_assignment(conn: sqlite3.Connection, *, user_id: str, now: int) -> str | None:
    row = conn.execute(
        """
        SELECT match_id
        FROM assignments
        WHERE user_id = ? AND status = 'assigning' AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, now),
    ).fetchone()
    if row is None:
        return None
    return str(row["match_id"])


def insert_assignment(conn: sqlite3.Connection, match_id: str, user_id: str, status: str, *, expires_at: int | None = None) -> None:
    conn.execute(
        "INSERT INTO assignments(match_id, user_id, status, expires_at) VALUES (?, ?, ?, ?)",
        (match_id, user_id, status, expires_at),
    )
    conn.commit()


def insert_judgment(
    conn: sqlite3.Connection,
    *,
    match_id: str,
    user_id: str,
    ranking: list[str],
    mode: str,
    latency_ms: int | None,
    reason: str | None,
    flags: dict[str, Any] | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO judgments(match_id, user_id, ranking_json, mode, latency_ms, reason, flags_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            user_id,
            json.dumps(ranking, ensure_ascii=False),
            mode,
            latency_ms,
            reason,
            json.dumps(flags, ensure_ascii=False) if flags is not None else None,
        ),
    )
    conn.execute(
        """
        UPDATE assignments
        SET status = 'done'
        WHERE match_id = ? AND user_id = ? AND status != 'done'
        """,
        (match_id, user_id),
    )
    conn.commit()
    return int(cur.lastrowid)


def now_epoch_s() -> int:
    return int(time.time())


def _pbkdf2_hash(password: str, *, salt_b64: str, iterations: int) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_b64.encode("utf-8"), iterations)
    return dk.hex()


def hash_password(password: str) -> str:
    iterations = 120_000
    salt = secrets.token_urlsafe(16)
    digest = _pbkdf2_hash(password, salt_b64=salt, iterations=iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iters_s, salt, digest = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
    except Exception:
        return False
    return _pbkdf2_hash(password, salt_b64=salt, iterations=iterations) == digest


def seed_admins(conn: sqlite3.Connection) -> None:
    admins = ["wsq", "hjn", "sy", "csk", "mjz", "xyc"]
    for username in admins:
        row = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
        if row is not None:
            conn.execute("DELETE FROM assignments WHERE user_id = ?", (username,))
            conn.execute("DELETE FROM judgments WHERE user_id = ?", (username,))
            continue
        conn.execute(
            """
            INSERT INTO users(username, nickname, password_hash, role, status, needs_password_reset)
            VALUES (?, ?, ?, 'admin', 'active', 1)
            """,
            (username, username, hash_password("123456")),
        )
        conn.execute("DELETE FROM assignments WHERE user_id = ?", (username,))
        conn.execute("DELETE FROM judgments WHERE user_id = ?", (username,))
    conn.commit()


def audit(conn: sqlite3.Connection, *, actor_username: str | None, action: str, target: str | None, meta: dict[str, Any] | None) -> None:
    conn.execute(
        "INSERT INTO audit_logs(actor_username, action, target, meta_json) VALUES (?, ?, ?, ?)",
        (actor_username, action, target, json.dumps(meta or {}, ensure_ascii=False)),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, *, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_meta(conn: sqlite3.Connection, *, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_meta(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()


def get_manifest_synced_at(conn: sqlite3.Connection) -> int:
    v = get_meta(conn, key="manifest_synced_at")
    try:
        return int(v) if v is not None else 0
    except Exception:
        return 0


def set_manifest_synced_at(conn: sqlite3.Connection, *, ts: int) -> None:
    set_meta(conn, key="manifest_synced_at", value=str(int(ts)))


def get_user_inbox_state(conn: sqlite3.Connection, *, username: str) -> tuple[int, int, int]:
    row = conn.execute(
        """
        SELECT last_seen_at, last_seen_pending_count, last_seen_manifest_at
        FROM user_inbox_state
        WHERE username = ?
        """,
        (username,),
    ).fetchone()
    if row is None:
        return (0, 0, 0)
    return (int(row["last_seen_at"]), int(row["last_seen_pending_count"]), int(row["last_seen_manifest_at"]))


def mark_user_inbox_seen(conn: sqlite3.Connection, *, username: str, pending_count: int, manifest_at: int, seen_at: int) -> None:
    conn.execute(
        """
        INSERT INTO user_inbox_state(username, last_seen_at, last_seen_pending_count, last_seen_manifest_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
          last_seen_at=excluded.last_seen_at,
          last_seen_pending_count=excluded.last_seen_pending_count,
          last_seen_manifest_at=excluded.last_seen_manifest_at
        """,
        (username, int(seen_at), int(pending_count), int(manifest_at)),
    )
    conn.commit()


def create_session(conn: sqlite3.Connection, username: str, *, ttl_s: int = 60 * 60 * 24 * 14) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = now_epoch_s()
    expires_at = now + ttl_s
    conn.execute(
        "INSERT INTO sessions(token_hash, username, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (token_hash, username, expires_at, now),
    )
    conn.commit()
    return token


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    conn.commit()


def get_user_by_session(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = now_epoch_s()
    row = conn.execute(
        """
        SELECT u.username, u.nickname, u.role, u.status, u.needs_password_reset, s.expires_at
        FROM sessions s
        JOIN users u ON u.username = s.username
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        (token_hash, now),
    ).fetchone()
    return row


def get_user(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT username, nickname, password_hash, role, status, needs_password_reset FROM users WHERE username = ?",
        (username,),
    ).fetchone()


def create_pending_user(conn: sqlite3.Connection, nickname: str, password: str) -> None:
    username = nickname.strip()
    if username == "":
        raise ValueError("nickname_required")
    exists = conn.execute("SELECT username FROM users WHERE nickname = ? OR username = ?", (username, username)).fetchone()
    if exists is not None:
        raise ValueError("nickname_taken")
    conn.execute(
        """
        INSERT INTO users(username, nickname, password_hash, role, status, needs_password_reset)
        VALUES (?, ?, ?, 'user', 'pending', 0)
        """,
        (username, username, hash_password(password)),
    )
    conn.commit()


def list_pending_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT username, nickname, created_at
        FROM users
        WHERE status = 'pending'
        ORDER BY created_at ASC
        """
    ).fetchall()


def count_pending_users(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE status = 'pending'").fetchone()
    if row is None:
        return 0
    return int(row["c"])


def approve_user(conn: sqlite3.Connection, *, username: str, approved_by: str) -> None:
    row = conn.execute("SELECT nickname FROM users WHERE username = ?", (username,)).fetchone()
    nickname = None
    if row is not None and row["nickname"] is not None:
        nickname = str(row["nickname"])
    cur = conn.execute(
        """
        UPDATE users
        SET status='active', approved_by=?, approved_at=datetime('now')
        WHERE username = ? AND status = 'pending'
        """,
        (approved_by, username),
    )
    if cur.rowcount <= 0:
        conn.commit()
        raise ValueError("already_handled")
    audit(
        conn,
        actor_username=approved_by,
        action="approve_user",
        target=username,
        meta={"nickname": nickname} if nickname else {},
    )


def reject_user(conn: sqlite3.Connection, *, username: str, approved_by: str, reason: str | None) -> None:
    row = conn.execute("SELECT nickname FROM users WHERE username = ?", (username,)).fetchone()
    nickname = None
    if row is not None and row["nickname"] is not None:
        nickname = str(row["nickname"])
    cur = conn.execute(
        """
        UPDATE users
        SET status='disabled', approved_by=?, approved_at=datetime('now')
        WHERE username = ? AND status = 'pending'
        """,
        (approved_by, username),
    )
    if cur.rowcount <= 0:
        conn.commit()
        raise ValueError("already_handled")
    meta: dict[str, Any] = {}
    if nickname:
        meta["nickname"] = nickname
    if reason:
        meta["reason"] = reason
    audit(conn, actor_username=approved_by, action="reject_user", target=username, meta=meta)


def list_admin_messages(conn: sqlite3.Connection, *, after_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, actor_username, action, target, meta_json, created_at
        FROM audit_logs
        WHERE id > ? AND action IN ('approve_user', 'reject_user')
        ORDER BY id ASC
        """,
        (after_id,),
    ).fetchall()


def change_password(conn: sqlite3.Connection, *, username: str, new_password: str) -> None:
    conn.execute(
        "UPDATE users SET password_hash=?, needs_password_reset=0 WHERE username=?",
        (hash_password(new_password), username),
    )
    conn.commit()
