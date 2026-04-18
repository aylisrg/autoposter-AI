"""Platform registry. Add new platforms here as you build them."""
from app.platforms.base import Platform
from app.platforms.facebook import FacebookPlatform

PLATFORMS: dict[str, Platform] = {
    FacebookPlatform.id: FacebookPlatform(),
    # Future:
    # LinkedInPlatform.id: LinkedInPlatform(),
    # XPlatform.id: XPlatform(),
    # TelegramPlatform.id: TelegramPlatform(),
}


def get_platform(platform_id: str) -> Platform:
    if platform_id not in PLATFORMS:
        raise KeyError(f"Unknown platform: {platform_id}. Registered: {list(PLATFORMS)}")
    return PLATFORMS[platform_id]
