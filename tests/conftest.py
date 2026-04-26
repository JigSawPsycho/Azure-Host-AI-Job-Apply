"""Test fixtures — set required env vars and put repo root on sys.path."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("SECRETS_MASTER_KEY", Fernet.generate_key().decode())
os.environ.setdefault("GITHUB_CLIENT_ID", "test-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-secret")

# Per-test isolated DB + secrets file.
_tmpdir = tempfile.mkdtemp(prefix="ai-apply-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/ai-apply-test.db"
os.environ["SECRETS_LOCAL_PATH"] = f"{_tmpdir}/secrets.json"
