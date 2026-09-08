"""
crypto.py — LandIQ LLM Configurator
------------------------------------
Encrypts API keys at rest in configurator.db (global_models.api_key).
Pattern matches sir's AI Cowork project: a Fernet key is auto-generated
on first run and appended to .env if not already present, so every
subsequent run decrypts with the same key.
"""

import os
from cryptography.fernet import Fernet

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

_fernet = None


def _load_or_create_key() -> str:
    key = os.environ.get("ENCRYPTION_KEY")
    if key:
        return key
    key = Fernet.generate_key().decode()
    os.environ["ENCRYPTION_KEY"] = key
    try:
        with open(_ENV_PATH, "a", encoding="utf-8") as f:
            f.write(f"\nENCRYPTION_KEY={key}\n")
        print(f"  [CRYPTO] Generated new ENCRYPTION_KEY and saved to {_ENV_PATH}")
    except Exception as e:
        print(f"  [CRYPTO] Could not persist ENCRYPTION_KEY to .env: {e}")
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key().encode())
    return _fernet


def encrypt_secret(plain: str) -> str:
    if not plain:
        return plain
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return cipher
    try:
        return _get_fernet().decrypt(cipher.encode()).decode()
    except Exception:
        # Not encrypted (e.g. a pre-existing plaintext value) — return as-is
        # rather than breaking a working key.
        return cipher
