from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class Role(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    role: Role

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        object.__setattr__(self, "role", Role(self.role))


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    username: str
    password_hash: str
    role: Role
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))

    @classmethod
    def with_password(
        cls,
        user_id: str,
        username: str,
        password: str,
        role: Role,
        *,
        active: bool = True,
    ) -> User:
        if not password:
            raise ValueError("password is required")
        salt = secrets.token_bytes(16)
        iterations = 210_000
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
        encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
        password_hash = (
            f"pbkdf2_sha256${iterations}${encoded_salt}${encoded_digest}"
        )
        return cls(user_id, username, password_hash, role, active)

    def verify_password(self, password: str) -> bool:
        try:
            algorithm, raw_iterations, raw_salt, raw_digest = (
                self.password_hash.split("$", maxsplit=3)
            )
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(raw_salt.encode("ascii"))
            expected = base64.urlsafe_b64decode(raw_digest.encode("ascii"))
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(raw_iterations)
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, expected)


class UserRepository:
    """Small repository boundary; a database adapter can replace it later."""

    def __init__(self, users: Iterable[User] = ()) -> None:
        self._by_id: dict[str, User] = {}
        self._by_username: dict[str, User] = {}
        for user in users:
            self.add(user)

    def add(self, user: User) -> None:
        if user.user_id in self._by_id or user.username in self._by_username:
            raise ValueError("duplicate user")
        self._by_id[user.user_id] = user
        self._by_username[user.username] = user

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def find_by_username(self, username: str) -> User | None:
        return self._by_username.get(username)
