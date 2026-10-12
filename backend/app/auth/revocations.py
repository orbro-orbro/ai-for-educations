"""Token digests only; production uses the SQL adapter."""
from threading import Lock
from typing import Protocol


class AuthenticationStorageError(RuntimeError):
    pass


class TokenRevocations(Protocol):
    def revoke(self, token_digest: str, expires_at: int) -> None: ...
    def contains(self, token_digest: str) -> bool: ...


class InMemoryTokenRevocations:
    def __init__(self):
        self._digests: dict[str, int] = {}
        self._lock = Lock()

    def revoke(self, token_digest: str, expires_at: int) -> None:
        with self._lock: self._digests[token_digest] = expires_at

    def contains(self, token_digest: str) -> bool:
        with self._lock: return token_digest in self._digests
