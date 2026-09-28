"""Password hashing + JWT utilities (HS256)."""
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=True)

ALGORITHM = "HS256"


def hash_password(raw: str) -> str:
    return _pwd_ctx.hash(raw[:72])  # bcrypt input limit; app also caps at 128 chars


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(raw, hashed)
    except ValueError:
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(UTC)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return subject email or None (never raise; caller maps to 401)."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
