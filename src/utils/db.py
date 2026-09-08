"""
db.py  — LandIQ LLM Configurator
Updated: adds start_time, end_time, cost_usd, api_key_hint to usage_logs.
"""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "configurator.db")


def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS llm_configs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                usecase_name TEXT NOT NULL,
                config_name  TEXT NOT NULL,
                full_name    TEXT UNIQUE NOT NULL,
                file_path    TEXT NOT NULL,
                status       TEXT NOT NULL CHECK (status IN ('active','disabled')),
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        ''')

        # Create with all columns including the new ones
        c.execute('''
            CREATE TABLE IF NOT EXISTS usage_logs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                config_full_name  TEXT NOT NULL,
                agent_id          TEXT,
                endpoint          TEXT NOT NULL,
                model_used        TEXT,
                api_key_hint      TEXT,
                prompt_tokens     INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens      INTEGER DEFAULT 0,
                cost_usd          REAL DEFAULT 0,
                latency_ms        REAL DEFAULT 0,
                start_time        TEXT,
                end_time          TEXT,
                success           BOOLEAN NOT NULL,
                error             TEXT,
                created_at        TEXT NOT NULL
            )
        ''')

        # Migrate existing table if columns are missing
        existing = [row[1] for row in c.execute("PRAGMA table_info(usage_logs)").fetchall()]
        for col, defn in [
            ("api_key_hint", "TEXT"),
            ("cost_usd",     "REAL DEFAULT 0"),
            ("start_time",   "TEXT"),
            ("end_time",     "TEXT"),
        ]:
            if col not in existing:
                c.execute(f"ALTER TABLE usage_logs ADD COLUMN {col} {defn}")

        c.execute('''
            CREATE TABLE IF NOT EXISTS global_models (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                litellm_model TEXT UNIQUE NOT NULL,
                provider      TEXT NOT NULL,
                api_key       TEXT,
                api_base      TEXT,
                created_at    TEXT NOT NULL
            )
        ''')
        conn.commit()


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def log_usage(config_full_name, agent_id, endpoint, model_used,
              prompt_tokens, completion_tokens, total_tokens,
              latency_ms, success, error,
              cost_usd=0.0, start_time=None, end_time=None, api_key_hint=None):
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO usage_logs
            (config_full_name, agent_id, endpoint, model_used, api_key_hint,
             prompt_tokens, completion_tokens, total_tokens, cost_usd,
             latency_ms, start_time, end_time, success, error, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (config_full_name, agent_id, endpoint, model_used, api_key_hint,
              prompt_tokens, completion_tokens, total_tokens, cost_usd or 0,
              latency_ms, start_time, end_time, success, error, now))
        conn.commit()


def get_request_logs(config_full_name: str = None, limit: int = 100) -> list:
    """Per-request logs with all fields sir requested."""
    with get_db_connection() as conn:
        c = conn.cursor()
        if config_full_name:
            c.execute('''
                SELECT id, config_full_name, agent_id, endpoint, model_used, api_key_hint,
                       prompt_tokens, completion_tokens, total_tokens, cost_usd,
                       latency_ms, start_time, end_time, success, error, created_at
                FROM usage_logs WHERE config_full_name=?
                ORDER BY id DESC LIMIT ?
            ''', (config_full_name, limit))
        else:
            c.execute('''
                SELECT id, config_full_name, agent_id, endpoint, model_used, api_key_hint,
                       prompt_tokens, completion_tokens, total_tokens, cost_usd,
                       latency_ms, start_time, end_time, success, error, created_at
                FROM usage_logs
                ORDER BY id DESC LIMIT ?
            ''', (limit,))
        return [dict(r) for r in c.fetchall()]


def get_usage_stats(config_full_name: str) -> dict:
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT COUNT(*) as calls,
                   SUM(total_tokens) as total_tokens,
                   SUM(cost_usd) as total_cost_usd,
                   AVG(latency_ms) as avg_latency_ms,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as success_count,
                   SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failure_count
            FROM usage_logs WHERE config_full_name=?
        ''', (config_full_name,))
        totals = dict(c.fetchone() or {})
        for k in ['total_tokens', 'total_cost_usd', 'avg_latency_ms']:
            totals[k] = totals.get(k) or 0

        c.execute('''
            SELECT * FROM usage_logs WHERE config_full_name=? ORDER BY id DESC LIMIT 50
        ''', (config_full_name,))
        logs = [dict(r) for r in c.fetchall()]

    return {"totals": totals, "recent_logs": logs}


def get_global_models() -> list:
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM global_models ORDER BY created_at DESC')
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['has_api_key'] = bool(r.get('api_key'))
            r.pop('api_key', None)
        return rows


def add_global_model(litellm_model, provider, api_key, api_base):
    from src.utils.crypto import encrypt_secret
    stored_key = encrypt_secret(api_key) if api_key else api_key
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO global_models (litellm_model,provider,api_key,api_base,created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(litellm_model) DO UPDATE SET
                provider=excluded.provider,
                api_key=excluded.api_key,
                api_base=excluded.api_base
        ''', (litellm_model, provider, stored_key, api_base,
              datetime.now(timezone.utc).isoformat()))
        conn.commit()


def delete_global_model(litellm_model: str):
    with get_db_connection() as conn:
        conn.execute('DELETE FROM global_models WHERE litellm_model=?', (litellm_model,))
        conn.commit()


def get_api_key_for_model(litellm_model: str) -> str:
    """Returns the decrypted API key for a model (used internally by router)."""
    from src.utils.crypto import decrypt_secret
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT api_key FROM global_models WHERE litellm_model=?', (litellm_model,))
        row = c.fetchone()
        return decrypt_secret(row['api_key']) if row and row['api_key'] else None


def get_api_key_for_provider(provider: str) -> str:
    """
    Returns any decrypted API key saved for a provider, regardless of which
    exact model string it was saved against. Lets a single "save my Groq key"
    action cover every Groq model used across every config, instead of
    requiring the same key to be re-entered per model string.
    """
    from src.utils.crypto import decrypt_secret
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT api_key FROM global_models WHERE provider=? "
            "AND api_key IS NOT NULL AND api_key != '' LIMIT 1",
            (provider,)
        )
        row = c.fetchone()
        return decrypt_secret(row['api_key']) if row and row['api_key'] else None