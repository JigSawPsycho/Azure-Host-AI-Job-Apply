"""Secret-store abstraction.

Two implementations:

- LocalSecretStore: AES-GCM with a key from `SECRETS_MASTER_KEY` (Fernet).
  Sufficient for local dev. Refs are stored in a JSON sidecar next to the DB.
- AzureKeyVaultSecretStore: production. Uses `DefaultAzureCredential` so
  App Service managed identity authenticates automatically. Refs are
  prefixed `kv:` and store the Key Vault secret name.

Callers store a *reference* (e.g. `"local:anthropic:42"` or `"kv:anthropic-42"`);
they never see the raw plaintext outside `get()`.
"""
from __future__ import annotations

import json
import os
import re
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


class AzureKeyVaultSecretStore(SecretStore):
    """Azure Key Vault backend.

    Auth via `DefaultAzureCredential` — App Service system-assigned managed
    identity in prod, `az login` locally. The web app's identity needs
    `get`/`set`/`delete` on the vault's secrets (RBAC: "Key Vault Secrets
    Officer", or access policy with those perms).

    Key Vault secret names are restricted to `[A-Za-z0-9-]`, so we sanitise
    the caller-supplied name. Refs are stored as `kv:<sanitised-name>`.
    """

    PREFIX = "kv:"
    _NAME_OK = re.compile(r"[^A-Za-z0-9-]")

    def __init__(self, vault_url: str) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        self._client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())

    def put(self, name: str, value: str) -> str:
        import time

        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        safe = self._NAME_OK.sub("-", name).strip("-") or "secret"
        for attempt in range(6):
            try:
                self._client.set_secret(safe, value)
                return f"{self.PREFIX}{safe}"
            except ResourceExistsError as e:
                msg = str(e)
                # Soft-deleted but recoverable → recover and retry.
                if "ObjectIsDeletedButRecoverable" in msg or "deleted but recoverable" in msg:
                    try:
                        self._client.begin_recover_deleted_secret(safe).wait()
                    except ResourceNotFoundError:
                        pass
                    continue
                # Mid-deletion — wait until it lands in soft-deleted state, then recover.
                if "ObjectIsBeingDeleted" in msg or "being deleted" in msg:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError(f"key vault secret {safe!r} stuck in deletion state")

    def get(self, ref: str) -> str:
        if not ref.startswith(self.PREFIX):
            raise ValueError(f"unknown ref scheme: {ref!r}")
        name = ref[len(self.PREFIX):]
        return self._client.get_secret(name).value

    def delete(self, ref: str) -> None:
        if not ref.startswith(self.PREFIX):
            return
        name = ref[len(self.PREFIX):]
        try:
            self._client.begin_delete_secret(name)
        except Exception:
            pass


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
    elif backend == "azure-key-vault":
        vault_url = os.environ.get("AZURE_KEY_VAULT_URL")
        if not vault_url:
            raise RuntimeError(
                "AZURE_KEY_VAULT_URL is not set. Required when SECRETS_BACKEND=azure-key-vault."
            )
        _store = AzureKeyVaultSecretStore(vault_url)
    else:
        raise NotImplementedError(f"secret backend {backend!r} not implemented")
    return _store
