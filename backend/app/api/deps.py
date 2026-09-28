"""Shared dependencies: DB session + current user."""
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import AuthError
from app.db.models import User
from app.db.session import get_session_factory
from app.services import auth_service


def get_db():
    sf = get_session_factory()
    db = sf()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    user = auth_service.user_from_token(db, token)
    if not user:
        raise AuthError("Invalid or expired token")
    return user
