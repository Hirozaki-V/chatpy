from .auth import router as auth_router
from .users import router as users_router
from .rooms import router as rooms_router
from .friends import router as friends_router
from .attachments import router as attachments_router

__all__ = [
    "auth_router",
    "users_router",
    "rooms_router",
    "friends_router",
    "attachments_router",
]
