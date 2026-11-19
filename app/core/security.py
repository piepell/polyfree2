"""
Authentication and Security for Photogrammetry Backend
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """Get current user from JWT token"""
    if not credentials:
        return None
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def require_auth(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """Require authentication - raises 401 if not authenticated"""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


class APIKeyManager:
    """Simple API key management for service-to-service auth"""
    
    def __init__(self):
        self.api_keys: Dict[str, Dict[str, Any]] = {}
    
    def generate_key(self, name: str, permissions: Optional[list] = None) -> str:
        """Generate new API key"""
        import secrets
        key = f"pf_{secrets.token_urlsafe(32)}"
        self.api_keys[key] = {
            "name": name,
            "permissions": permissions or ["read", "write"],
            "created_at": datetime.utcnow(),
            "active": True,
        }
        return key
    
    def verify_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Verify API key"""
        if key in self.api_keys and self.api_keys[key]["active"]:
            return self.api_keys[key]
        return None
    
    def revoke_key(self, key: str) -> bool:
        """Revoke API key"""
        if key in self.api_keys:
            self.api_keys[key]["active"] = False
            return True
        return False


api_key_manager = APIKeyManager()


def verify_api_key(api_key: str = Depends(security)) -> Dict[str, Any]:
    """Verify API key authentication"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )
    key_data = api_key_manager.verify_key(api_key.credentials)
    if not key_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return key_data