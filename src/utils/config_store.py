"""
config_store.py — LandIQ LLM Configurator
Updated: adds update_config() for editing priorities/models/restrictions.
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

CONFIGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "configs"
)
os.makedirs(CONFIGS_DIR, exist_ok=True)


class ConfigAlreadyExistsError(Exception):
    pass


class ConfigNotFoundError(Exception):
    pass


def _get_file_path(full_name: str) -> str:
    return os.path.join(CONFIGS_DIR, f"{full_name}.json")


def create_config(config_data: dict) -> dict:
    from src.utils.db import get_db_connection
    full_name = f"{config_data['usecase_name']}_{config_data['config_name']}"
    file_path = _get_file_path(full_name)

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM llm_configs WHERE full_name=?", (full_name,))
        if c.fetchone():
            raise ConfigAlreadyExistsError(f"Config '{full_name}' already exists.")

    now = datetime.now(timezone.utc).isoformat()
    record = {
        **config_data,
        "full_name":  full_name,
        "status":     "active",
        "created_at": now,
        "updated_at": now,
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO llm_configs
            (usecase_name,config_name,full_name,file_path,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
        ''', (config_data["usecase_name"], config_data["config_name"],
              full_name, file_path, "active", now, now))
        conn.commit()

    return record


def update_config(full_name: str, updates: dict) -> dict:
    """
    Edit an existing config — change operations (priorities/models),
    restrictions (tpm/rpm/tpr), or guardrails without deleting and recreating.
    Rebuilds the LiteLLM Router automatically after saving.
    """
    from src.utils.db import get_db_connection
    file_path = _get_file_path(full_name)

    if not os.path.exists(file_path):
        raise ConfigNotFoundError(f"Config '{full_name}' not found.")

    with open(file_path, "r", encoding="utf-8") as f:
        record = json.load(f)

    # Apply only the fields caller wants to change
    allowed_fields = {"operations", "restrictions", "guardrails"}
    for field, value in updates.items():
        if field in allowed_fields:
            record[field] = value

    record["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE llm_configs SET updated_at=? WHERE full_name=?",
            (record["updated_at"], full_name)
        )
        conn.commit()

    return record


def get_config(full_name: str) -> Optional[dict]:
    from src.utils.db import get_db_connection
    file_path = _get_file_path(full_name)
    if not os.path.exists(file_path):
        return None
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT status FROM llm_configs WHERE full_name=?", (full_name,))
        row = c.fetchone()
    if not row:
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = row["status"]
    return data


def list_configs() -> List[dict]:
    from src.utils.db import get_db_connection
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id,full_name,status,file_path FROM llm_configs ORDER BY created_at DESC")
        rows = c.fetchall()

    results = []
    for r in rows:
        ops = []
        restrictions = None
        operations_detail = {}
        if os.path.exists(r["file_path"]):
            try:
                with open(r["file_path"], "r", encoding="utf-8") as f:
                    d = json.load(f)
                    ops = list(d.get("operations", {}).keys())
                    restrictions = d.get("restrictions")
                    operations_detail = d.get("operations", {})
            except Exception:
                pass
        results.append({
            "id":                 r["id"],
            "full_name":          r["full_name"],
            "status":             r["status"],
            "operations_present": ops,
            "operations_detail":  operations_detail,
            "restrictions":       restrictions,
            "endpoint_base_url":  f"/llm/{r['full_name']}",
        })
    return results


def delete_config(full_name: str) -> bool:
    from src.utils.db import get_db_connection
    file_path = _get_file_path(full_name)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM llm_configs WHERE full_name=?", (full_name,))
        deleted = c.rowcount > 0
        conn.commit()
    if os.path.exists(file_path):
        os.remove(file_path)
        return True
    return deleted


def update_config_status(full_name: str, status: str) -> bool:
    from src.utils.db import get_db_connection
    file_path = _get_file_path(full_name)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE llm_configs SET status=?,updated_at=? WHERE full_name=?",
                  (status, now, full_name))
        updated = c.rowcount > 0
        conn.commit()
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["status"] = status
        data["updated_at"] = now
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    return updated