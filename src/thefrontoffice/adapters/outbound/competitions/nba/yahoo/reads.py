"""What one league's Yahoo source says, read without anything the provider holds: the wire and its depths,
a player by key or by name, the table's records, a roster's averages, the league's weights, and whom ESPN's
injury report names among Yahoo's players.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from itertools import zip_longest

from thefrontoffice.adapters.outbound.competitions.injuries import PlayerInjuries, by_club, matched, unsure
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba import history
from thefrontoffice.adapters.outbound.competitions.nba import league as nba_league
from thefrontoffice.adapters.outbound.competitions.nba import strength as nba_strength
from thefrontoffice.adapters.outbound.competitions.nba import worth as nba_worth
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores, missed
from thefrontoffice.adapters.outbound.competitions.nba.model import Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    PACIFIC,
    SCOUTED,
    Line,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.yahoo.capture import YahooGame
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource, once
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import RECENT_AVERAGE
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    LeagueSettings,
    Timeframe,
    YahooLeague,
    YahooLine,
    YahooPlayer,
    YahooTeam,
    YahooTransaction,
)
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    PlayerNotFoundError,
    UnsupportedError,
)
from thefrontoffice.domain.models import (
    ActivityRow,
)

logger = logging.getLogger(__name__)


WIRE_DEPTH = {Timeframe.SEASON: 300, Timeframe.LAST_WEEK: 100}
"""How deep the wire is read under each of Yahoo's rankings: sixteen pages of 25, fetched together.

Season rank alone buries a player who has just stepped into a role — he ranks
low on a season mostly spent on the bench — so the last week's ranking is read
beside it. Three hundred deep by season is past every regular rotation player."""


STREAM_DEPTH = {Timeframe.SEASON: 75, Timeframe.LAST_WEEK: 50}
"""How deep the week's to-do list reads the wire for its adds: five pages, the top of each ranking by Yahoo's
actual rank (`paths.available`).

Three pages (50 and 25) left out rotation players a week's keeper is found
among — 59 players where five pages read 89, Keegan Murray and Jerami Grant
among the thirty. Deeper than that stretches the pool a category league is
scaled across toward players nobody would add. Every page is one the Free
agents page reads first (`WIRE_DEPTH`), past the first held for `DEEP_TTL`, so
whichever page asks first serves both and the browser sync carries them."""


LEADERS = {c.label: c.yahoo_stat for c in SCOUTED}
"""The stats the free-agent scout ranks the wire by, a request each."""


LEADERS_PER_STAT = 10


ONE_WIN = "headone"
"""Yahoo's scoring type for a category league whose week counts as one win, to whoever takes more categories."""


def weights(league: YahooLeague, yahoo: YahooSource) -> dict[str, float] | None:
    """A points league's weights by Yahoo stat id; None for a league won on categories.

    A points league whose settings carry no weights is read as a category
    one: there is nothing to sum its players' lines with.
    """
    return (yahoo.settings().weights or None) if league.by_points else None


def records(yahoo: YahooSource) -> dict[str, str]:
    """Each team's record now, by key, from the table: Yahoo's teams list carries none.

    Empty where the table will not load — a browser sync that has not
    carried it — which leaves a matchup without records rather than fail it.
    """
    try:
        standings = yahoo.standings()
    except FrontOfficeError as e:
        logger.warning(f"Showing teams without their records, the table would not load: {e}")
        return {}
    return {t.team_key: t.standing.record for t in standings if t.standing}


def records_after(yahoo: YahooSource, league: YahooLeague, week: int) -> dict[str, str]:
    """Each team's record as it stood once `week` was settled, by key, from the season's scoreboards up to it.

    Empty where a scoreboard will not load — a browser sync that has not
    carried every week — rather than today's record standing in for that one.
    """
    try:
        weeks = yahoo.matchups(list(range(league.first_week, week + 1)))
    except FrontOfficeError as e:
        logger.warning(f"Showing week {week} without its records, a scoreboard up to it would not load: {e}")
        return {}
    return nba_league.records_through(weeks, by_category=league.scoring_type == nba_league.EVERY_CATEGORY)


def played_today(yahoo: YahooSource, team_keys: list[str], day: date) -> dict[str, YahooPlayer]:
    """Each of these teams' players' line from `day`'s games, by Yahoo's key.

    Empty where Yahoo would not give it: the rows then say the game is on
    or over without what he did in it, rather than fail the page.
    """
    try:
        rosters = yahoo.day_rosters(team_keys, day)
    except FrontOfficeError as e:
        logger.warning(f"Showing today's games without the players' lines, Yahoo would not give them: {e}")
        return {}
    return {p.player_key: p for players in rosters.values() for p in players}


def activity(yahoo: YahooSource, team: YahooTeam) -> list[ActivityRow]:
    """Your team's moves still waiting, then the league's moves lately, newest first; none where Yahoo would not
    give them, rather than no table."""
    waiting = history.pending(pending(yahoo, team.team_key), team.name)
    try:
        transactions = yahoo.transactions()
    except FrontOfficeError as e:
        logger.warning(f"Showing the league without its activity, Yahoo would not give its moves: {e}")
        return waiting
    return [*waiting, *history.recent(transactions, datetime.now(UTC), team.name)]


def pending(yahoo: YahooSource, team_key: str) -> list[YahooTransaction]:
    """The team's claims and offers still waiting; none where Yahoo would not say, which costs only their rows."""
    try:
        return yahoo.pending(team_key)
    except FrontOfficeError as e:
        logger.warning(f"Reading the league without your waiting claims, Yahoo would not give them: {e}")
        return []


def judged_on(league: YahooLeague, rules: LeagueSettings) -> tuple[nba_strength.Scored, ...]:
    """The categories a week is won on, none in a points league.

    Raises:
        UnsupportedError: a week the season's simulation cannot settle as one result.
    """
    if rules.best_game:
        raise UnsupportedError(league.name, "a trade search where only each player's best game scores")
    if league.by_points:
        if not rules.weights:
            raise UnsupportedError(league.name, "a trade search without the points its settings would sum")
        return ()
    if league.scoring_type != ONE_WIN:
        raise UnsupportedError(league.name, "a trade search where every category counts in the table")
    return nba_strength.scored(rules.categories)


def roster_averages(yahoo: YahooSource, team_key: str) -> dict[str, YahooLine]:
    """Each of a team's players' averages over the last month, in one read; none where it will not load.

    Enrichment: a roster without them is a table of dashes, not a failed page.
    """
    try:
        return yahoo.roster_averages(team_key, RECENT_AVERAGE)
    except FrontOfficeError as e:
        logger.warning(f"Showing the roster without Yahoo's averages: {e}")
        return {}


def player(yahoo: YahooSource, player_id: str) -> YahooPlayer:
    """The player a key names, with whose roster he is on.

    Raises:
        PlayerNotFoundError: the league knows nobody by that key.
    """
    found = yahoo.players([player_id])
    if not found:
        raise PlayerNotFoundError([player_id])
    return found[0]


def points_valuer(weights: Mapping[str, float] | None) -> nba_worth.Valuer | None:
    """A points league's fantasy points, which need no pool; None in a category league, which does."""
    return nba_worth.points_value(weights) if weights else None


def injuries(players: Sequence[Player], reports: Sequence[InjuryReport]) -> PlayerInjuries:
    """Each of `players` on ESPN's injury report, keyed by Yahoo's key, where it names him.

    Yahoo carries no ESPN id, so the join is by full name within his club
    alone, refusing a name two of them there share.
    """
    clubs = by_club((espn_club(p.team), p.name, p.player_key) for p in players)
    return PlayerInjuries(by_player=matched(reports, clubs, {}))


def averages(yahoo: YahooSource, *team_keys: str) -> dict[str, YahooLine]:
    """Yahoo's averages over the last month for every player these teams hold, by key (`roster_averages`)."""
    return {key: line for team in team_keys for key, line in roster_averages(yahoo, team).items()}


def returns(players: Sequence[Player], reports: Sequence[InjuryReport]) -> dict[str, date]:
    """The day ESPN expects each of `players` back, keyed by Yahoo's key; nobody it gives none for."""
    found = injuries(players, reports)
    return {p.player_key: back for p in players if (back := found.returns(p.player_key))}


MISSED = 4
"""Games in a row his club has played without him from which a return the report leaves open (`injuries.unsure`) is
not counted on: over a week out, past the short-term knock 'day-to-day' is first said of."""


def doubts(players: Sequence[Player], reports: Sequence[InjuryReport], scores: BoxScores) -> dict[str, int]:
    """Each of `players` hurt, out `MISSED` games in a row or more, whose report gives no firm return, by Yahoo's key:
    the games missed. His games are then counted from no return, rather than from one the report only estimates."""
    found = injuries(players, reports)
    doubted: dict[str, int] = {}
    for p in players:
        report = found.of(p.player_key)
        if p.status and report is not None and unsure(report) and (gone := missed(scores, p.name)) >= MISSED:
            doubted[p.player_key] = gone
    return doubted


def valuer(
    yahoo: YahooSource, weights: Mapping[str, float] | None, lines: list[Line]
) -> tuple[nba_worth.Valuer, dict[str, nba_worth.Scale]]:
    """What a game is worth in the league's scoring, and each category's scale: fantasy points under `weights`, or
    a category league's value scaled across `lines` (`worth.category_value`)."""
    if weights:
        return nba_worth.points_value(weights), {}
    scored = yahoo.settings().categories
    return nba_worth.category_value(scored, lines), nba_worth.scales(scored, lines)


def carried(players: Sequence[Player]) -> dict[str, PrintedLine]:
    """The averages over the last month each of `players` carries, by key, where his page read them."""
    return {p.player_key: p.line for p in players if p.coverage == RECENT_AVERAGE}


def wire(yahoo: YahooSource, depths: Mapping[Timeframe, int] = WIRE_DEPTH) -> list[YahooPlayer]:
    """The available players under every ranking in `depths`, taken from each in turn, each player once.

    Interleaved rather than one list after the other, so the week's risers sit
    beside the season's best instead of below three hundred of them.
    """
    rankings = list(yahoo.fetch_available(depths).values())
    return once(p for row in zip_longest(*rankings) for p in row if p is not None)


def find_player(yahoo: YahooSource, name: str) -> YahooPlayer | None:
    """The one Yahoo player a name refers to, or None — never a guess.

    Yahoo's search matches substrings, so a name can come back with others
    beside it, and an exact match among them wins. Failing any match, the
    surname alone tolerates first-name spelling ("Lebron" for "LeBron"), but
    only where it finds one player: two Williamses resolve to neither.
    """
    players = yahoo.search_players(name)
    parts = name.split()
    if not players and len(parts) > 1:
        players = yahoo.search_players(parts[-1])

    wanted = normalize_name(name)
    candidates = [p for p in players if normalize_name(p.name) == wanted] or players
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.warning(f"{len(candidates)} players match {name!r}; resolving to none rather than guessing")
    return None


YAHOO_GAME = YahooGame(
    code="nba",
    season=nba_league.season_year,
    available=WIRE_DEPTH,
    leaders=LEADERS,
    per_stat=LEADERS_PER_STAT,
    clock=lambda: datetime.now(PACIFIC),
)
"""What this provider reads of Yahoo's NBA game, so a browser sync captures exactly that."""
