"""What a competition can do beyond its core port, each read off a port its provider implements.

One row per port: the flag the picker offers it under, and what is refused
where a competition lacks it. The routes, the picker's flags, the CLI and the
scripts all read this table, so an offer and its refusal cannot drift apart,
and two routes needing one port cannot word its refusal two ways.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from thefrontoffice.domain.ports import (
    ForecastProvider,
    LeagueRefreshProvider,
    OutlookProvider,
    PlayerSearchProvider,
    PlayerTabProvider,
    RangeTuningProvider,
    TradeMarketProvider,
    TradeProvider,
    WeekBrowsingProvider,
    WireProvider,
)


@dataclass(frozen=True)
class Capability:
    """One thing a competition may be able to do."""

    refusal: str
    """What is refused where it cannot, as `UnsupportedError` words it: 'judging free agents'."""

    flag: str = ""
    """The picker's field that offers it, where the UI asks before offering; empty where nothing does."""


CAPABILITIES: Mapping[type[object], Capability] = {
    WireProvider: Capability("judging free agents", flag="judges_wire"),
    OutlookProvider: Capability("planning the weeks ahead", flag="plans_weeks"),
    WeekBrowsingProvider: Capability("browsing other weeks", flag="browses_weeks"),
    TradeMarketProvider: Capability("finding trades", flag="finds_trades"),
    PlayerSearchProvider: Capability("finding players by name", flag="searches_players"),
    PlayerTabProvider: Capability("a player's deferred tabs"),
    LeagueRefreshProvider: Capability("refreshing a league", flag="refreshes"),
    TradeProvider: Capability("trade evaluation"),
    ForecastProvider: Capability("simulating a matchup"),
    RangeTuningProvider: Capability("tuning player ranges"),
}
"""Every port a caller may ask a competition for beyond `CompetitionProvider`, by the port."""
