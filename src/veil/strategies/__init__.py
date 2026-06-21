from veil.strategies.base import Strategy
from veil.strategies.browser import BrowserStrategy
from veil.strategies.http_basic import HttpBasicStrategy
from veil.strategies.tls_impersonate import TlsImpersonateStrategy

__all__ = [
    "Strategy",
    "HttpBasicStrategy",
    "TlsImpersonateStrategy",
    "BrowserStrategy",
]
