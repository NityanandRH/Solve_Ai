"""
utils.py — Database setup, session management, token tracking, and helper functions.
"""

import os
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "user.db")
USERS_JSON = os.path.join(os.path.dirname(__file__), "users.json")


# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,   -- UPN / email from AAD
    aad_oid TEXT UNIQUE,             -- Azure AD Object ID (stable across renames)
    email TEXT,                      -- UPN / email (same as username, explicit)
    display_name TEXT,               -- Full name from AAD claims
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    initial_context TEXT DEFAULT '',
    stage_status TEXT DEFAULT '{"context":false,"ideate":false,"analyze":false,"solve":false,"triz":false,"patent":false}',
    ideate_data TEXT DEFAULT '{}',
    analyze_data TEXT DEFAULT '{}',
    solve_data TEXT DEFAULT '{}',
    triz_data TEXT DEFAULT '{}',
    patent_data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS telemetry (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    stage TEXT,
    model TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    timestamp TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    tool_used TEXT,
    detail TEXT,
    timestamp TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


# ── Initialization ───────────────────────────────────────────────────────────

def init_db():
    """Create tables. Users are provisioned on first SSO login, not seeded."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


async def get_or_create_sso_user(aad_oid: str, upn: str,
                                  display_name: str, role: str) -> Dict:
    """
    Look up a user by AAD Object ID. Create them if first login.
    Update display_name and role on every login (role controlled by ADMIN_USERS env var).
    Returns the DB user dict.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Try by AAD OID first (most stable identifier)
        async with db.execute(
            "SELECT * FROM users WHERE aad_oid = ?", (aad_oid,)
        ) as cur:
            row = await cur.fetchone()

        if row:
            # Update role, display_name and last_seen on every login
            await db.execute(
                """UPDATE users SET role = ?, display_name = ?, email = ?,
                   last_seen = datetime('now') WHERE aad_oid = ?""",
                (role, display_name, upn, aad_oid)
            )
            await db.commit()
            async with db.execute(
                "SELECT * FROM users WHERE aad_oid = ?", (aad_oid,)
            ) as cur:
                row = await cur.fetchone()
            return dict(row)

        # First login — create user record
        new_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO users (id, username, aad_oid, email, display_name, role)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (new_id, upn, aad_oid, upn, display_name, role)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM users WHERE id = ?", (new_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row)


# ── User DB ──────────────────────────────────────────────────────────────────

async def get_user_by_username(username: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_users() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, username, email, display_name, role, created_at, last_seen FROM users"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Session DB ───────────────────────────────────────────────────────────────

def _json_field(data: Any) -> str:
    return json.dumps(data) if data is not None else "{}"


def _parse_session(row: dict) -> dict:
    """Parse JSON fields in a session row."""
    for field in ["stage_status", "ideate_data", "analyze_data",
                  "solve_data", "triz_data", "patent_data"]:
        if isinstance(row.get(field), str):
            try:
                row[field] = json.loads(row[field])
            except Exception:
                row[field] = {}
    return row


async def create_session(user_id: str, name: str) -> Dict:
    session_id = str(uuid.uuid4())
    default_status = json.dumps({
        "context": False, "ideate": False, "analyze": False,
        "solve": False, "triz": False, "patent": False
    })
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO sessions (id, user_id, name, stage_status)
               VALUES (?, ?, ?, ?)""",
            (session_id, user_id, name, default_status)
        )
        await db.commit()
    return await get_session(session_id)


async def get_session(session_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return _parse_session(dict(row)) if row else None


async def get_user_sessions(user_id: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [_parse_session(dict(r)) for r in rows]


async def update_session_field(session_id: str, field: str, data: Any):
    """Update a single JSON field in a session."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE sessions SET {field} = ?, updated_at = datetime('now') WHERE id = ?",
            (_json_field(data), session_id)
        )
        await db.commit()


async def update_session_context(session_id: str, context: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sessions SET initial_context = ?, updated_at = datetime('now') WHERE id = ?",
            (context, session_id)
        )
        await db.commit()


async def update_stage_status(session_id: str, stage: str, completed: bool):
    session = await get_session(session_id)
    if not session:
        return
    status = session["stage_status"]
    status[stage] = completed
    await update_session_field(session_id, "stage_status", status)


async def rename_session(session_id: str, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sessions SET name = ?, updated_at = datetime('now') WHERE id = ?",
            (name, session_id)
        )
        await db.commit()


async def delete_session(session_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.execute("DELETE FROM telemetry WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM checkpoints WHERE session_id = ?", (session_id,))
        await db.commit()


async def reset_stages_after(session_id: str, from_stage: str):
    """Reset all stages after (and including) the given stage."""
    stage_order = ["context", "ideate", "analyze", "solve", "triz", "patent"]
    if from_stage not in stage_order:
        return
    idx = stage_order.index(from_stage)
    stages_to_reset = stage_order[idx:]

    session = await get_session(session_id)
    if not session:
        return

    status = session["stage_status"]
    for s in stages_to_reset:
        status[s] = False

    async with aiosqlite.connect(DB_PATH) as db:
        fields_to_reset = []
        values = []
        if "ideate" in stages_to_reset:
            fields_to_reset.append("ideate_data = ?")
            values.append("{}")
        if "analyze" in stages_to_reset:
            fields_to_reset.append("analyze_data = ?")
            values.append("{}")
        if "solve" in stages_to_reset:
            fields_to_reset.append("solve_data = ?")
            values.append("{}")
        if "triz" in stages_to_reset:
            fields_to_reset.append("triz_data = ?")
            values.append("{}")
        if "patent" in stages_to_reset:
            fields_to_reset.append("patent_data = ?")
            values.append("{}")

        fields_to_reset.append("stage_status = ?")
        values.append(json.dumps(status))
        fields_to_reset.append("updated_at = datetime('now')")
        values.append(session_id)

        query = f"UPDATE sessions SET {', '.join(fields_to_reset)} WHERE id = ?"
        await db.execute(query, values)
        await db.commit()


# ── Telemetry DB ─────────────────────────────────────────────────────────────

async def log_token_usage(user_id: str, session_id: str, stage: str,
                           model: str, prompt_tokens: int, completion_tokens: int,
                           duration_ms: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO telemetry
               (id, user_id, session_id, stage, model, prompt_tokens,
                completion_tokens, total_tokens, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, session_id, stage, model,
             prompt_tokens, completion_tokens,
             prompt_tokens + completion_tokens, duration_ms)
        )
        await db.commit()


async def log_checkpoint(user_id: str, session_id: str, stage: str,
                          tool_used: str = None, detail: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO checkpoints (id, user_id, session_id, stage, tool_used, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, session_id, stage, tool_used, detail)
        )
        await db.commit()


# ── Admin Telemetry ──────────────────────────────────────────────────────────

async def get_admin_telemetry() -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Total users
        async with db.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'user'") as c:
            total_users = (await c.fetchone())["cnt"]

        # Token usage per user
        async with db.execute("""
            SELECT u.username, u.id as user_id,
                   SUM(t.total_tokens) as total_tokens,
                   SUM(t.prompt_tokens) as prompt_tokens,
                   SUM(t.completion_tokens) as completion_tokens,
                   COUNT(DISTINCT t.session_id) as session_count
            FROM users u
            LEFT JOIN telemetry t ON t.user_id = u.id
            WHERE u.role = 'user'
            GROUP BY u.id
        """) as cur:
            token_usage = [dict(r) for r in await cur.fetchall()]

        # Session time (approximated by session activity windows)
        async with db.execute("""
            SELECT u.username, s.id as session_id, s.name as session_name,
                   s.initial_context,
                   s.created_at, s.updated_at,
                   (julianday(s.updated_at) - julianday(s.created_at)) * 24 * 60 as duration_minutes
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            ORDER BY s.updated_at DESC
        """) as cur:
            sessions = [dict(r) for r in await cur.fetchall()]

        # Stage checkpoints per user
        async with db.execute("""
            SELECT u.username, cp.stage, cp.tool_used, cp.detail, cp.timestamp, cp.session_id
            FROM checkpoints cp
            JOIN users u ON u.id = cp.user_id
            ORDER BY cp.timestamp DESC
        """) as cur:
            checkpoints = [dict(r) for r in await cur.fetchall()]

        # Daily token usage (last 30 days)
        async with db.execute("""
            SELECT DATE(timestamp) as date, SUM(total_tokens) as tokens,
                   model, COUNT(*) as calls
            FROM telemetry
            WHERE timestamp >= datetime('now', '-30 days')
            GROUP BY DATE(timestamp), model
            ORDER BY date
        """) as cur:
            daily_usage = [dict(r) for r in await cur.fetchall()]

        # Stage completion stats
        async with db.execute("""
            SELECT stage, tool_used, COUNT(*) as count
            FROM checkpoints
            GROUP BY stage, tool_used
        """) as cur:
            stage_stats = [dict(r) for r in await cur.fetchall()]

        return {
            "total_users": total_users,
            "token_usage_per_user": token_usage,
            "sessions": sessions,
            "checkpoints": checkpoints,
            "daily_usage": daily_usage,
            "stage_stats": stage_stats
        }


async def get_telemetry_summary_for_llm() -> str:
    data = await get_admin_telemetry()

    lines = [
        "=== INNOVATETOOL TELEMETRY REPORT ===",
        f"Total registered users (non-admin): {data['total_users']}",
        f"Total sessions across all users: {len(data['sessions'])}",
        "",
        "--- PER-USER TOKEN USAGE ---",
    ]

    for u in data["token_usage_per_user"]:
        lines.append(
            f"User '{u['username']}': {u['total_tokens'] or 0} total tokens "
            f"({u['prompt_tokens'] or 0} prompt + {u['completion_tokens'] or 0} completion) "
            f"across {u['session_count'] or 0} sessions"
        )

    # Per-user stage completion breakdown
    lines += ["", "--- PER-USER STAGE PROGRESS ---"]
    user_stages: Dict[str, Dict[str, int]] = {}
    user_tools: Dict[str, list] = {}
    for cp in data["checkpoints"]:
        uname = cp["username"]
        if uname not in user_stages:
            user_stages[uname] = {}
            user_tools[uname] = []
        user_stages[uname][cp["stage"]] = user_stages[uname].get(cp["stage"], 0) + 1
        if cp.get("tool_used"):
            user_tools[uname].append(f"{cp['stage']}:{cp['tool_used']}")

    all_stages = ["context", "ideate", "analyze", "solve", "triz", "patent"]
    for uname, stages in user_stages.items():
        completed = [s for s in all_stages if s in stages]
        pending = [s for s in all_stages if s not in stages]
        tools = list(dict.fromkeys(user_tools.get(uname, [])))
        lines.append(
            f"User '{uname}': completed stages = [{', '.join(completed) or 'none'}] | "
            f"not yet started = [{', '.join(pending) or 'none'}] | "
            f"tools used = [{', '.join(tools) or 'none'}]"
        )

    # Sessions with their initial context topics
    lines += ["", "--- WHAT EACH USER IS WORKING ON (SESSION TOPICS) ---"]
    # Group sessions by user
    user_sessions: Dict[str, list] = {}
    for s in data["sessions"]:
        uname = s["username"]
        if uname not in user_sessions:
            user_sessions[uname] = []
        context_snippet = (s.get("initial_context") or "").strip()
        if context_snippet:
            context_snippet = context_snippet[:300].replace("\n", " ")
        user_sessions[uname].append({
            "name": s["session_name"],
            "context": context_snippet,
            "last_active": s["updated_at"][:10]
        })

    for uname, sessions in user_sessions.items():
        lines.append(f"User '{uname}' sessions:")
        for sess in sessions:
            ctx = sess["context"] or "(no context entered yet)"
            lines.append(f"  - '{sess['name']}' (last active {sess['last_active']}): {ctx}")

    # Detect potentially overlapping topics across users
    lines += ["", "--- POTENTIAL COLLABORATION OPPORTUNITIES ---"]
    all_user_contexts = []
    for s in data["sessions"]:
        ctx = (s.get("initial_context") or "").strip()
        if ctx and s["username"]:
            all_user_contexts.append({"username": s["username"], "session": s["session_name"], "context": ctx[:200]})

    if len(all_user_contexts) >= 2:
        lines.append(
            "The following users have active sessions — compare their contexts to identify "
            "if any are working on similar or complementary topics and could benefit from collaboration:"
        )
        for item in all_user_contexts:
            lines.append(f"  User '{item['username']}' / Session '{item['session']}': {item['context']}")
        lines.append(
            "(When answering admin questions, proactively flag if two users appear to be "
            "working on the same domain or problem area and suggest they collaborate.)"
        )
    else:
        lines.append("Not enough sessions yet to detect overlapping topics.")

    # Overall stage stats
    lines += ["", "--- OVERALL STAGE COMPLETION COUNTS ---"]
    stage_map: Dict[str, int] = {}
    for cp in data["checkpoints"]:
        stage_map[cp["stage"]] = stage_map.get(cp["stage"], 0) + 1
    for stage in all_stages:
        count = stage_map.get(stage, 0)
        lines.append(f"Stage '{stage}': completed {count} time(s) across all users")

    return "\n".join(lines)


# ── OpenAI wrapper with token tracking ───────────────────────────────────────

async def call_llm(client, messages: list, model: str, user_id: str,
                    session_id: str, stage: str,
                    stream: bool = False, temperature: float = 0.7):
    """Wrapper around OpenAI chat completion with automatic token logging."""
    import time
    start = time.time()

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=stream
    )

    if not stream:
        duration_ms = int((time.time() - start) * 1000)
        usage = response.usage
        await log_token_usage(
            user_id, session_id, stage, model,
            usage.prompt_tokens, usage.completion_tokens, duration_ms
        )
        return response.choices[0].message.content

    return response  # caller handles streaming
