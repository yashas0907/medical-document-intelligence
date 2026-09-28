from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.schemas.index import TokenOut, UserCreate, UserOut
from app.services import auth_service

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    user = auth_service.register_user(db, payload.email, payload.password)
    return user


@router.post("/login", response_model=TokenOut)
@limiter.limit(f"{get_settings().rate_limit_auth_per_min}/minute")
def login(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, payload.email, payload.password)
    token = auth_service.issue_token(user)
    auth_service.audit(db, "login", user_id=user.id, ip=request.client.host if request.client else None)
    return TokenOut(access_token=token, expires_in=get_settings().access_token_expire_minutes * 60)
