"""SQLite storage: chat log, decaying memories (FTS5 search), small key/value meta."""
import math
import re
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY,
  character_id TEXT NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  emotion TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_char ON messages(character_id, id);

CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY,
  character_id TEXT NOT NULL,
  text TEXT NOT NULL,
  importance INTEGER NOT NULL DEFAULT 3,
  created_at REAL NOT NULL,
  last_accessed REAL NOT NULL,
  access_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mem_char ON memories(character_id);

CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def init(path: Path) -> None:
    global _conn
    _conn = sqlite3.connect(str(path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(SCHEMA)
        try:
            _conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
                "USING fts5(text, tokenize='trigram')"
            )
        except sqlite3.OperationalError:
            # very old SQLite without trigram tokenizer
            _conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text)")
        _conn.commit()


def _q(sql, args=()):
    with _lock:
        return _conn.execute(sql, args).fetchall()


def _x(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur


# ---------- meta ----------
def get_meta(key: str):
    rows = _q("SELECT value FROM meta WHERE key=?", (key,))
    return rows[0]["value"] if rows else None


def set_meta(key: str, value: str) -> None:
    _x("INSERT INTO meta(key,value) VALUES(?,?) "
       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------- messages ----------
def add_message(cid: str, role: str, text: str, emotion=None) -> int:
    cur = _x("INSERT INTO messages(character_id,role,text,emotion,created_at) VALUES(?,?,?,?,?)",
             (cid, role, text, emotion, time.time()))
    return cur.lastrowid


def recent_messages(cid: str, limit: int):
    rows = _q("SELECT id,role,text,emotion,created_at FROM messages "
              "WHERE character_id=? ORDER BY id DESC LIMIT ?", (cid, limit))
    return [dict(r) for r in reversed(rows)]


def messages_after(cid: str, after_id: int, limit: int = 40):
    rows = _q("SELECT id,role,text,emotion,created_at FROM messages "
              "WHERE character_id=? AND id>? ORDER BY id LIMIT ?", (cid, after_id, limit))
    return [dict(r) for r in rows]


def clear_messages(cid: str) -> None:
    _x("DELETE FROM messages WHERE character_id=?", (cid,))
    set_meta(f"extract:{cid}", "0")


# ---------- memories ----------
def strength(row, now: float, base_days: float) -> float:
    """importance(0.2-1.0) * exp(-days_since_last_recall / stability)."""
    days = max(0.0, (now - row["last_accessed"]) / 86400.0)
    stability = max(0.1, base_days) * (1.0 + math.log1p(row["access_count"]))
    return (row["importance"] / 5.0) * math.exp(-days / stability)


def add_memory(cid: str, text: str, importance: int = 3) -> int:
    text = text.strip()
    importance = max(1, min(5, int(importance)))
    now = time.time()
    rows = _q("SELECT id,importance FROM memories WHERE character_id=? AND text=?", (cid, text))
    if rows:
        _x("UPDATE memories SET importance=?, last_accessed=? WHERE id=?",
           (max(importance, rows[0]["importance"]), now, rows[0]["id"]))
        return rows[0]["id"]
    cur = _x("INSERT INTO memories(character_id,text,importance,created_at,last_accessed) "
             "VALUES(?,?,?,?,?)", (cid, text, importance, now, now))
    _x("INSERT INTO memories_fts(rowid,text) VALUES(?,?)", (cur.lastrowid, text))
    return cur.lastrowid


def delete_memory(mid: int) -> None:
    _x("DELETE FROM memories WHERE id=?", (mid,))
    _x("DELETE FROM memories_fts WHERE rowid=?", (mid,))


def _trigrams(text: str, limit: int = 40):
    out = []
    for seg in re.sub(r"[\s\W_]+", " ", text).split():
        for i in range(len(seg) - 2):
            g = seg[i:i + 3]
            if g not in out:
                out.append(g)
            if len(out) >= limit:
                return out
    return out


def recall(cid: str, query: str, base_days: float, min_strength: float = 0.08, k: int = 5):
    """Relevance (FTS5 trigram bm25) x strength (forgetting curve). Returns top-k dicts."""
    now = time.time()
    rel = {}
    grams = _trigrams(query)
    if grams:
        match = " OR ".join('"%s"' % g for g in grams)
        try:
            rows = _q(
                "SELECT m.id AS id, bm25(memories_fts) AS r FROM memories_fts "
                "JOIN memories m ON m.id = memories_fts.rowid "
                "WHERE memories_fts MATCH ? AND m.character_id=? ORDER BY r LIMIT 30",
                (match, cid))
            if rows:
                top = max(-r["r"] for r in rows) or 1.0
                for r in rows:
                    rel[r["id"]] = max(0.0, -r["r"]) / top
        except Exception:
            pass
    allrows = {r["id"]: r for r in _q("SELECT * FROM memories WHERE character_id=?", (cid,))}
    scored = []
    for mid, row in allrows.items():
        s = strength(row, now, base_days)
        if s < min_strength:
            continue
        score = (rel.get(mid, 0.0) + 0.3) * s
        scored.append((score, s, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    result = []
    for score, s, row in scored[:k]:
        result.append({"id": row["id"], "text": row["text"], "strength": s,
                       "created_at": row["created_at"]})
    return result


def touch_memories(ids) -> None:
    now = time.time()
    for mid in ids:
        _x("UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE id=?",
           (now, mid))


def list_memories(cid: str, base_days: float):
    now = time.time()
    out = []
    for r in _q("SELECT * FROM memories WHERE character_id=?", (cid,)):
        out.append({"id": r["id"], "text": r["text"], "importance": r["importance"],
                    "access_count": r["access_count"], "created_at": r["created_at"],
                    "strength": strength(r, now, base_days)})
    out.sort(key=lambda m: m["strength"], reverse=True)
    return out


def delete_character_data(cid: str) -> None:
    for r in _q("SELECT id FROM memories WHERE character_id=?", (cid,)):
        _x("DELETE FROM memories_fts WHERE rowid=?", (r["id"],))
    _x("DELETE FROM memories WHERE character_id=?", (cid,))
    _x("DELETE FROM messages WHERE character_id=?", (cid,))
    _x("DELETE FROM meta WHERE key=?", (f"extract:{cid}",))
