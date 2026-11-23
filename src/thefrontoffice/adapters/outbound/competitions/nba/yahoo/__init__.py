"""NBA on Yahoo: the provider (`provider.py`), and what it reads beside it."""

from thefrontoffice.adapters.outbound.competitions.nba.yahoo.provider import YahooNBAProvider
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.reads import ONE_WIN, YAHOO_GAME

__all__ = ["ONE_WIN", "YAHOO_GAME", "YahooNBAProvider"]
