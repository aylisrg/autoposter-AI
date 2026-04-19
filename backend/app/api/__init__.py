"""Aggregate router. Import this from main.py."""
from fastapi import APIRouter

from app.api import (
    ab_tests,
    analytics,
    auth,
    business_profile,
    feedback,
    health,
    humanizer,
    linkedin_oauth,
    media,
    meta_oauth,
    plans,
    platform_credentials,
    posts,
    targets,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(business_profile.router)
api_router.include_router(targets.router)
api_router.include_router(posts.router)
api_router.include_router(plans.router)
api_router.include_router(feedback.router)
api_router.include_router(media.router)
api_router.include_router(humanizer.router)
api_router.include_router(analytics.router)
api_router.include_router(meta_oauth.router)
api_router.include_router(linkedin_oauth.router)
api_router.include_router(platform_credentials.router)
api_router.include_router(ab_tests.router)

__all__ = ["api_router"]
