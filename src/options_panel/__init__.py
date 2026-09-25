from .api import create_app
from .config import Settings, APP_VERSION

__all__ = ["Settings", "create_app"]
__version__ = APP_VERSION
