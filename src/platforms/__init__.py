from typing import Dict, List, Optional, Type, Any
from .base import JobPlatform
from .naukri import NaukriPlatform
from .linkedin import LinkedInPlatform
from .foundit import FounditPlatform
from .indeed import IndeedPlatform
from .shine import ShinePlatform
from .instahyre import InstahyrePlatform
from ..utils import setup_logger

logger = setup_logger("platforms")

# Registry mapping platform identifiers to adapter classes
PLATFORM_REGISTRY: Dict[str, Type[JobPlatform]] = {
    "naukri": NaukriPlatform,
    "linkedin": LinkedInPlatform,
    "foundit": FounditPlatform,
    "indeed": IndeedPlatform,
    "shine": ShinePlatform,
    "instahyre": InstahyrePlatform,
}


def register_platform(name: str, platform_cls: Type[JobPlatform]):
    """Register a new platform adapter."""
    PLATFORM_REGISTRY[name.lower()] = platform_cls


def get_platform(name: str) -> Optional[JobPlatform]:
    """Retrieve an instantiated platform adapter by name."""
    cls = PLATFORM_REGISTRY.get(name.lower())
    if cls:
        return cls()
    return None


def get_enabled_platforms(
    settings: Dict[str, Any], 
    requested_sites: Optional[List[str]] = None
) -> List[JobPlatform]:
    """
    Get list of active platform adapters based on settings configuration or CLI overrides.
    Supported sites: naukri, linkedin, foundit, indeed, shine, instahyre
    """
    if requested_sites:
        site_names = [s.strip().lower() for s in requested_sites if s.strip()]
    else:
        configured_sites = settings.get("sites", ["naukri"])
        if isinstance(configured_sites, list):
            site_names = [str(s).strip().lower() for s in configured_sites]
        elif isinstance(configured_sites, str):
            site_names = [s.strip().lower() for s in configured_sites.split(",")]
        else:
            site_names = ["naukri"]

    adapters: List[JobPlatform] = []
    for name in site_names:
        adapter = get_platform(name)
        if adapter:
            adapters.append(adapter)
        else:
            logger.warning(
                f"Platform '{name}' is listed in config, but adapter is not yet registered. Skipping."
            )

    return adapters
