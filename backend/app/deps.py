from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.models import User

bearer = HTTPBearer(auto_error=False)
ROLE_RANK = {"staff": 0, "manager": 1, "admin": 2, "owner": 3}


@dataclass
class Ctx:
    """Request context. tenant_id comes from the verified token, never from the client body."""

    db: Session
    user: User

    @property
    def tenant_id(self) -> str:
        return self.user.tenant_id


def get_ctx(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Ctx:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = decode_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session token")
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active or user.tenant_id != payload.get("tid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    return Ctx(db=db, user=user)


def require_role(minimum: str):
    def checker(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if ROLE_RANK[ctx.user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum} role or higher")
        return ctx

    return checker
