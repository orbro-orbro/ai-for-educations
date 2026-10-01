from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.models import Actor, Role, UserRepository


class AuthenticationFailed(Exception):
    pass


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


class TokenCodec:
    """Minimal HS256 JWT codec with no external identity dependency."""

    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 16:
            raise ValueError("token secret must contain at least 16 bytes")
        self._secret = secret.encode("utf-8")

    @classmethod
    def from_environment(cls, variable: str = "AUTH_TOKEN_SECRET") -> TokenCodec:
        secret = os.environ.get(variable)
        if not secret:
            raise RuntimeError(f"{variable} must be set")
        return cls(secret)

    def issue(self, actor: Actor, *, ttl_seconds: int = 3600) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": actor.user_id,
            "role": actor.role.value,
            "exp": int(time.time()) + ttl_seconds,
        }
        segments = [
            _base64url_encode(
                json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
            ),
            _base64url_encode(
                json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
            ),
        ]
        signing_input = ".".join(segments).encode("ascii")
        signature = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return ".".join([*segments, _base64url_encode(signature)])

    def verify(self, token: str) -> Actor:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
            signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
            actual_signature = _base64url_decode(encoded_signature)
            expected_signature = hmac.new(
                self._secret, signing_input, hashlib.sha256
            ).digest()
            if not hmac.compare_digest(actual_signature, expected_signature):
                raise AuthenticationFailed()
            header: dict[str, Any] = json.loads(_base64url_decode(encoded_header))
            payload: dict[str, Any] = json.loads(_base64url_decode(encoded_payload))
            if header != {"alg": "HS256", "typ": "JWT"}:
                raise AuthenticationFailed()
            if int(payload["exp"]) <= int(time.time()):
                raise AuthenticationFailed()
            return Actor(str(payload["sub"]), Role(payload["role"]))
        except AuthenticationFailed:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AuthenticationFailed() from error


class Authenticator:
    def __init__(self, users: UserRepository, tokens: TokenCodec) -> None:
        self._users = users
        self._tokens = tokens

    def login(self, username: str, password: str) -> tuple[str, Actor]:
        user = self._users.find_by_username(username)
        if user is None or not user.active or not user.verify_password(password):
            raise AuthenticationFailed()
        actor = Actor(user.user_id, user.role)
        return self._tokens.issue(actor), actor

    def authenticate_token(self, token: str) -> Actor:
        claimed_actor = self._tokens.verify(token)
        user = self._users.get(claimed_actor.user_id)
        if user is None or not user.active or user.role is not claimed_actor.role:
            raise AuthenticationFailed()
        return Actor(user.user_id, user.role)

    def authenticate_header(self, authorization: str | None) -> Actor:
        if not authorization:
            raise AuthenticationFailed()
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationFailed()
        return self.authenticate_token(token)


class LoginRequest(BaseModel):
    username: str
    password: str


class ActorResponse(BaseModel):
    user_id: str
    role: Role


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    actor: ActorResponse


def authentication_error(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "code": "AUTHENTICATION_FAILED",
            "message": "Authentication failed.",
            "request_id": str(
                getattr(request.state, "request_id", "unavailable")
            ),
        },
    )


def create_auth_router(authenticator: Authenticator) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest, request: Request):
        try:
            token, actor = authenticator.login(payload.username, payload.password)
        except AuthenticationFailed:
            return authentication_error(request)
        return LoginResponse(
            access_token=token,
            actor=ActorResponse(user_id=actor.user_id, role=actor.role),
        )

    return router
