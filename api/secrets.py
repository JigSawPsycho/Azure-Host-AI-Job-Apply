"""Secret-store abstraction.

Two implementations:

- LocalSecretStore: AES-GCM with a key from `SECRETS_MASTER_KEY` (Fernet).
  Sufficient for local dev. Refs are stored in a JSON sidecar next to the DB.
- AzureKeyVaultSecretStore: stub. In production use azure-identity +
  azure-keyvault-secrets and let the user's secret name (`anthropic_key_ref`,
  `github_token_ref`) point at a Key Vault secret URL.

Callers store a *reference* (e.g. `"local:anthropic:42"` or a Key Vault
secret name); they never see the raw plaintext outside `get_secret()`.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

from cryptography.fernet import Fernet


class SecretStore(ABC):
    @abstractmethod
    def put(self, name: str, value: str) -> str: ...
    @abstractmethod
    def get(self, ref: str) -> str: ...
    @abstractmethod
    def delete(self, ref: str) -> None: ...


class LocalSecretStore(SecretStore):
    """File-backed AES store for local dev.

    Reads `SECRETS_MASTER_KEY` (a urlsafe-base64 32-byte Fernet key).
    Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    """

    PREFIX = "local:"

    def __init__(self, path: Path, master_key: str) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(master_key.encode() if isinstance(master_key, str) else master_key)
        self._data: dict[str, str] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text() or "{}")

    def put(self, name: str, value: str) -> str:
        token = self._fernet.encrypt(value.encode()).decode()
        ref = f"{self.PREFIX}{name}"
        self._data[ref] = token
        self._save()
        return ref

    def get(self, ref: str) -> str:
        if not ref.startswith(self.PREFIX):
            raise ValueError(f"unknown ref scheme: {ref!r}")
        token = self._data[ref]
        return self._fernet.decrypt(token.encode()).decode()

    def delete(self, ref: str) -> None:
        self._data.pop(ref, None)
        self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True))


_store: SecretStore | None = None


def get_store() -> SecretStore:
    global _store
    if _store is not None:
        return _store
    backend = os.environ.get("SECRETS_BACKEND", "local")
    if backend == "local":
        master_key = os.environ.get("SECRETS_MASTER_KEY")
        if not master_key:
            raise RuntimeError(
                "SECRETS_MASTER_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        path = Path(os.environ.get("SECRETS_LOCAL_PATH", "data/secrets.json"))
        _store = LocalSecretStore(path, master_key)
    else:
        raise NotImplementedError(f"secret backend {backend!r} not implemented")
    return _store
