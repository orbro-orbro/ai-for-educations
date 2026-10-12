from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from app.auth.revocations import AuthenticationStorageError
from app.persistence.models import TokenRevocationRow


class SqlTokenRevocations:
    def __init__(self, sessions):
        self._sessions = sessions

    def contains(self, token_digest: str) -> bool:
        try:
            with self._sessions() as session:
                return session.get(TokenRevocationRow, token_digest) is not None
        except SQLAlchemyError:
            raise AuthenticationStorageError("Authentication storage unavailable") from None

    def revoke(self, token_digest: str, expires_at: int) -> None:
        try:
            with self._sessions.begin() as session:
                if session.bind.dialect.name == "postgresql":
                    session.execute(insert(TokenRevocationRow).values(token_digest=token_digest, expires_at=expires_at).on_conflict_do_nothing())
                else:
                    session.merge(TokenRevocationRow(token_digest=token_digest, expires_at=expires_at))
        except SQLAlchemyError:
            raise AuthenticationStorageError("Authentication storage unavailable") from None
