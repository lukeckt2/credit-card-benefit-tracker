from fastapi import APIRouter, Depends
from app.auth import get_current_user, AUTHELIA_URL
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    logout_url = f"{AUTHELIA_URL}/logout" if AUTHELIA_URL else None
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "logout_url": logout_url,
    }
