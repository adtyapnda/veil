"""veil -- a modular, polite scraper that cascades from cheap HTTP to a browser."""
from veil.engine import Engine
from veil.models import (
    AllStrategiesFailed,
    BlockedError,
    FetchRequest,
    FetchResponse,
)
from veil.politeness import Politeness
from veil.proxies import ProxyPool

__version__ = "0.1.0"

__all__ = [
    "Engine",
    "FetchRequest",
    "FetchResponse",
    "BlockedError",
    "AllStrategiesFailed",
    "Politeness",
    "ProxyPool",
]
