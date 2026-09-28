"""Auth + audit service."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, ConflictError
from app.core.logging import LoggerAdapter, get_logger
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db import models

log = LoggerAdapter(get_logger("auth"), extra={})


def register_user(db: Session, email: str, password: str) -> models.User:
    existing = db.scalar(select(models.User).where(models.User.email == email.lower()))
    if existing:
        raise ConflictError("An account with this email already exists")
    user = models.User(email=email.lower(), hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> models.User:
    user = db.scalar(select(models.User).where(models.User.email == email.lower()))
    if not user or not user.is_active:
        raise AuthError("Invalid credentials")
    if not verify_password(password, user.hashed_password):
        raise AuthError("Invalid credentials")
    return user


def issue_token(user: models.User) -> str:
    settings = get_settings()
    return create_access_token(user.email, settings.access_token_expire_minutes)


def user_from_token(db: Session, token: str) -> models.User | None:
    email = decode_access_token(token)
    if not email:
        return None
    return db.scalar(select(models.User).where(models.User.email == email))


def ensure_demo_user(db: Session) -> None:
    s = get_settings()
    if s.is_prod:
        return
    if not db.scalar(select(models.User).where(models.User.email == s.demo_user_email)):
        db.add(
            models.User(
                email=s.demo_user_email,
                hashed_password=hash_password(s.demo_user_password),
                role="user",
            )
        )
        db.commit()


def audit(
    db: Session,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        models.AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip,
            details=details,
        )
    )
    db.commit()
