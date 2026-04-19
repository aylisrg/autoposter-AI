"""Aggregate router. Import this from main.py."""
from fastapi import APIRouter

from app.api import (
    business_profile,
    feedback,
    health,
    humanizer,
    media,
    plans,
    posts,
    targets,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(business_profile.router)
api_router.include_router(targets.router)
api_router.include_router(posts.router)
api_router.include_router(plans.router)
api_router.include_router(feedback.router)
api_router.include_router(media.router)
api_router.include_router(humanizer.router)

__all__ = ["api_router"]
