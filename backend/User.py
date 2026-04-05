import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key-change-this")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Pydantic models ──────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None


# ── Password utilities ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT utilities ────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        role: str = payload.get("role")
        if username is None:
            return None
        return TokenData(username=username, user_id=user_id, role=role)
    except JWTError:
        return None
