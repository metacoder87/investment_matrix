from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any
import base64

from jose import jwt, JWTError
from passlib.context import CryptContext
from cryptography.fernet import Fernet
from app.config import settings

# --- Configuration ---
# You should load these from settings/env in production
SECRET_KEY = settings.SECRET_KEY or "dev_secret_key_change_me_in_prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 1 day

# Encryption Key (Must be 32 url-safe base64-encoded bytes)
# In dev we generate one if missing, but distinct runs will fail to decrypt.
# For demo purposes, we use a fixed dev key if settings is empty.
ENCRYPTION_KEY = settings.ENCRYPTION_KEY # Should be bytes
if not ENCRYPTION_KEY:
    # Deterministic key for dev (INSECURE FOR PROD)
    ENCRYPTION_KEY = base64.urlsafe_b64encode(b"01234567890123456789012345678901") 

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
fernet = Fernet(ENCRYPTION_KEY)

# --- Password Utils ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    # Bcrypt has a 72 byte limit. 
    # In a real app we might hash with sha256 first or use argon2.
    # For now, we just proceed. Passlib usually handles encoding.
    return pwd_context.hash(password)

# --- JWT Utils ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

# --- Encryption Utils ---
def encrypt_data(data: str) -> str:
    if not data: return None
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(token: str) -> str:
    if not token: return None
    return fernet.decrypt(token.encode()).decode()
