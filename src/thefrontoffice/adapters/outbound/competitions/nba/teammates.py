"""Whose absence a basketball player's numbers hang on, and what he has actually done without him.

Usage moves when a star sits: his shots and touches go somewhere, and the
player they go to is the pickup. Sometimes they spread around and nobody's line
moves. The season already says which — the games the star missed against the
games they both played — and that is the figure worth reading, not the guess.
How the games part, and how a split reads, is shared with football
(`competitions/teammates.py`); whose absence counts is basketball's own:

- the same club, and a regular there: `REGULAR_MINUTES` a game over his last
  `RECENT_GAMES` for it, or its top usage player — the most possessions ended a
  game (`usage`) among those with `MIN_FORM_GAMES` for it; with fewer games than
  that for it, hurt early in the season, `REGULAR_MINUTES` a game over the
  `SEASON_GAMES` or more he played last season;
- carrying a status in `HURT` today — Yahoo's where his Yahoo row is on hand,
  else ESPN's injury report (`Condition`) — or having sat out one of his club's
  last `ABSENCE_GAMES` games.

A teammate's game counts as missed where he did not play, or played under
`LEFT_EARLY_MINUTES`. A split is shown only with `MIN_FORM_GAMES` on each side:
one or two games either way is a single night reported as a rate. Where his
games are nearly all without a teammate at his position who is due back within
`RETURN_SOON` (`Returning`), there is no split to read, and that is the warning:
his role so far is the one the teammate's absence gave him.

Sleeper's box scores carry the club each game was played for, which is the
only club read here: a player whose Sleeper club is not his Yahoo one gets no
split rather than another club's.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from thefrontoffice.adapters.outbound.competitions import teammates
from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.injuries import PlayerInjuries, approximately, by_club, matched
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.form import (
    MIN_FORM_GAMES,
    RECENT_GAMES,
    BoxScores,
    nine_cat,
)
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    ASSISTS,
    POINTS,
    REBOUNDS,
    RULED_OUT,
    Line,
    fantasy_points,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.teammates import surname
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
from thefrontoffice.domain.models import Stat

REGULAR_MINUTES = 28.0
"""Minutes a game at which a teammate is a regular: a starter's share of a 48-minute game, whose
absence frees enough of it for someone else's line to move."""

LEFT_EARLY_MINUTES = 12.0
"""Minutes under which a regular's game counts as one he missed: hurt in the first half, or on a restriction."""

SEASON_GAMES = 20
"""Games last season that make his minutes then a regular's, where this season has too few: a quarter of one."""

RETURN_SOON = timedelta(days=7)
"""How soon a teammate's expected return reads as one a pickup's week runs into: a matchup week."""

GROUPS = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}
"""Each position's group: who takes whose minutes when a teammate returns."""

ABSENCE_GAMES = 5
"""How far back a club's games are read for a regular who sat out: about a week and a half of them."""

HURT = RULED_OUT | {"GTD", "DTD"}
"""The Yahoo statuses at which a teammate's absence is worth weighing: out, and the game-time calls."""

ESPN_STATUS = {"OUT": "O", "DAY-TO-DAY": "DTD", "SUSPENSION": "SUSP"}
"""ESPN's injury-report statuses in Yahoo's words, so a teammate reads the same whichever reported him."""

SPLIT_CATEGORIES = (POINTS, REBOUNDS, ASSISTS)
"""What a split shows: the counts a teammate's absence moves, and that a cell has room for."""


@dataclass(frozen=True)
class Outing:
    """One game a player played, as a split reads it (`teammates.Outing`)."""

    game: int
    """The day's ordinal: which of the club's games this was."""
    team: str
    minutes: float
    log: NBAGameLog

    @property
    def partial(self) -> bool:
        """Under `LEFT_EARLY_MINUTES`: a teammate split counts it as a game he missed."""
        return self.minutes < LEFT_EARLY_MINUTES


@dataclass(frozen=True)
class Regular:
    """A club's regular, as Sleeper names him."""

    player_id: str
    name: str
    team: str
    espn_id: str = ""
    position: str = ""
    """Sleeper's position for him: 'C'. Empty where it gives none."""


@dataclass(frozen=True)
class Condition:
    """What a regular carries today: a Yahoo status, and the day ESPN expects him back."""

    status: str = ""
    returns: date | None = None


def espn_status(status: str) -> str:
    """ESPN's 'Out' as Yahoo's 'O'; a status Yahoo has no word for is kept as ESPN wrote it."""
    return ESPN_STATUS.get(status.upper(), status)


def usage(games: Sequence[NBAGameLog]) -> float:
    """Possessions he ended a game — shots, trips to the line, turnovers: the box-score half of usage rate."""
    return sum(g.get("fga") + 0.44 * g.get("fta") + g.get("to") for g in games) / len(games)


@dataclass(frozen=True)
class Absent:
    """A regular whose absence is weighed, and what he carries today."""

    regular: Regular
    condition: Condition = Condition()

    @property
    def status(self) -> str:
        """'O' for a status; 'back' for a teammate who carries none."""
        return self.condition.status or "back"

    def detail(self, back: bool) -> str:
        """'O, back ~22 Nov' while he sits and ESPN dates his return; his status alone otherwise."""
        returns = self.condition.returns
        return f"{self.status}, back {approximately(returns)}" if returns and not back else self.status


@dataclass(frozen=True)
class Split:
    """His line a game without one regular teammate, or several who missed the very same games, and with them.

    Two regulars out together leave one set of games to read, so they share one
    split rather than two identical ones; all of them are ruled out, or none.
    """

    teammates: tuple[Absent, ...]
    without: Line
    games: int
    alongside: Line
    alongside_games: int
    without_points: float | None = None
    """Fantasy points a game without him, in a points league; None in a category league."""
    alongside_points: float | None = None

    @property
    def back(self) -> bool:
        """Whether the teammates are due to play — not ruled out — so the figure with them is the one that counts."""
        return not any(ruled_out(mate.condition.status) for mate in self.teammates)

    @property
    def gain(self) -> float:
        """How much more he scores without him, in the league's currency: fantasy points, else points."""
        if self.without_points is not None and self.alongside_points is not None:
            return self.without_points - self.alongside_points
        return self.without.get(POINTS.label, 0.0) - self.alongside.get(POINTS.label, 0.0)

    def cell(self) -> str:
        """'Antetokounmpo O', or 'Williams, Holmgren O' for two out together; each his own status where they differ."""
        statuses = {mate.status for mate in self.teammates}
        if len(statuses) == 1:
            return f"{', '.join(surname(m.regular.name) for m in self.teammates)} {statuses.pop()}"
        return ", ".join(f"{surname(m.regular.name)} {m.status}" for m in self.teammates)

    def label(self) -> str:
        """'Without Giannis Antetokounmpo (O, back ~22 Nov)', or 'With … (GTD)' once he is due to play."""
        first, *more = [(m.regular.name, m.detail(self.back)) for m in self.teammates]
        return teammates.heading(self.back, *first, *more)

    def figures(self) -> str:
        """'31.4 fpts 18.2 PTS 7.1 REB 3.0 AST in 4 games · 24.0 fpts 12.0 PTS … with', the one that counts first."""
        without = _side(self.without, self.without_points)
        alongside = _side(self.alongside, self.alongside_points)
        return teammates.figures(self.back, without, self.games, alongside, self.alongside_games, per="")

    def note(self) -> str:
        """The cell's tooltip: who, and the figures."""
        return f"{self.label()}: {self.figures()}"

    def stat(self) -> Stat:
        """The drawer's row, toned by whether the figure that counts beats the other."""
        return Stat(label=self.label(), value=self.figures(), tone=teammates.tone(self.back, self.gain, 0.0))

    def prompt(self) -> str:
        """'WITHOUT Giannis Antetokounmpo (O): 18.2p 7.1r 3.0a = 31.4 fpts in 4G, with 12.0p … in 10G'."""
        without = f"{_tagged(self.without, self.without_points)} in {self.games}G"
        alongside = f"{_tagged(self.alongside, self.alongside_points)} in {self.alongside_games}G"
        first, second = (alongside, f"without {without}") if self.back else (without, f"with {alongside}")
        return f"{self.label()}: {first}, {second}"


def _side(line: Line, fpts: float | None) -> str:
    counts = " ".join(f"{c.show(line.get(c.label, 0.0))} {c.label}" for c in SPLIT_CATEGORIES)
    return f"{fpts:.1f} fpts {counts}" if fpts is not None else counts


def _tagged(line: Line, fpts: float | None) -> str:
    counts = " ".join(c.tagged(line.get(c.label, 0.0)) for c in SPLIT_CATEGORIES)
    return f"{counts} = {fpts:.1f} fpts" if fpts is not None else counts


def shares_position(eligible: str, position: str) -> bool:
    """Whether a player eligible at `eligible` ('PF,C') plays a position in `position`'s group ('C')."""
    group = GROUPS.get(position.upper())
    return group is not None and any(GROUPS.get(p.strip().upper()) == group for p in eligible.split(","))


@dataclass(frozen=True)
class Returning:
    """A teammate at his position, out now and due back soon, beside whom he has played too few games to split.

    Nearly all he has done, he has done without him: the role the table shows
    may be the one the absence gave him, and it ends on the teammate's return.
    """

    teammate: Absent
    without: int
    """His games without the teammate."""
    alongside: int
    """His games beside him: under `MIN_FORM_GAMES`, or there would be a split."""

    @property
    def back(self) -> str:
        """' back ~24 Nov'; empty where ESPN dates no return."""
        returns = self.teammate.condition.returns
        return f" back {approximately(returns)}" if returns else ""

    def label(self) -> str:
        """'Jalen Duren (C, O) back ~24 Nov'."""
        mate = self.teammate.regular
        return f"{mate.name} ({mate.position}, {self.teammate.status}){self.back}"

    def cell(self) -> str:
        """'Duren back ~24 Nov'."""
        return f"{surname(self.teammate.regular.name)}{self.back}"

    def figures(self) -> str:
        """'14 games without him · 2 with': how much of his role is the absence."""
        return f"{teammates.games(self.without)} without him · {self.alongside} with"

    def note(self) -> str:
        """The cell's tooltip: who, when, and how few games beside him."""
        return f"{self.label()}: {self.figures()}"

    def stat(self) -> Stat:
        """The drawer's row: a warning, since the role he has shown ends on the return."""
        return Stat(label=self.label(), value=self.figures(), tone="warning")

    def prompt(self) -> str:
        """'RETURNING Jalen Duren (C, O) back ~24 Nov: 14G without him, 2G with'."""
        return f"RETURNING {self.label()}: {self.without}G without him, {self.alongside}G with"


Teammate = Split | Returning
"""What a teammate's condition says of a player: his split without him, or the warning that he returns."""


class Teammates:
    """Every club's regulars, and who of them sat out lately, read once from the window's box scores."""

    def __init__(
        self,
        scores: BoxScores,
        weights: Mapping[str, float] | None = None,
        before: Mapping[str, NBASeason] | None = None,
    ):
        """`weights` are a points league's, by Yahoo stat id: each side of a split then carries its fantasy points.

        `before` is last season's totals by Sleeper's id, which settle whether a
        teammate with too few games this season is a regular.
        """
        self.index = scores.index
        self.weights = weights
        self.outings: dict[str, list[Outing]] = {
            pid: sorted(
                (
                    Outing(game=day.toordinal(), team=log.team, minutes=log.minutes, log=log)
                    for log in logs
                    if log.team and (day := parse_day(log.date)) is not None
                ),
                key=lambda outing: outing.game,
            )
            for pid, logs in scores.logs.items()
        }
        self.club = {pid: games[-1].team for pid, games in self.outings.items() if games}
        self.absent = teammates.recently_absent(self.outings, ABSENCE_GAMES)
        self.by_club: dict[str, list[Regular]] = defaultdict(list)
        top: dict[str, tuple[float, Regular]] = {}
        for pid, club in self.club.items():
            meta = scores.players.get(pid)
            if meta is None or not meta.name:
                continue
            regular = Regular(player_id=pid, name=meta.name, team=club, espn_id=meta.espn_id, position=meta.position)
            recent = [g for g in self.outings[pid] if g.team == club][-RECENT_GAMES:]
            last = (before or {}).get(pid) if len(recent) < MIN_FORM_GAMES else None
            if last is not None and last.games >= SEASON_GAMES:
                minutes = last.minutes / last.games
            else:
                minutes = teammates.mean([g.minutes for g in recent])
            if minutes >= REGULAR_MINUTES:
                self.by_club[club].append(regular)
            ended = usage([g.log for g in recent]) if len(recent) >= MIN_FORM_GAMES else None
            if ended is not None and (club not in top or ended > top[club][0]):
                top[club] = (ended, regular)
        for club, (_, regular) in top.items():
            if regular not in self.by_club[club]:
                self.by_club[club].append(regular)

    def regulars(self) -> list[Regular]:
        """Every club's regulars: whose condition the caller looks up."""
        return [regular for club in self.by_club.values() for regular in club]

    def splits(self, player: YahooPlayer, conditions: Mapping[str, Condition]) -> list[Split]:
        """His line without each regular teammate who is hurt or lately sat out, and with him.

        The teammates ruled out first, then by how much more he does without
        them; none where Sleeper cannot place him at his Yahoo club.
        """
        pid = self.index.lookup(player.name)
        club = self.club.get(pid) if pid is not None else None
        if pid is None or club is None or club != player.team.upper():
            return []
        # Teammates who missed the very same games, and are all out or all due back, share one split.
        grouped: dict[tuple[tuple[int, ...], bool], list[Absent]] = defaultdict(list)
        games: dict[tuple[tuple[int, ...], bool], teammates.Parted[Outing]] = {}
        for mate in self.by_club.get(club, []):
            condition = conditions.get(mate.player_id, Condition())
            if mate.player_id == pid or not (condition.status.upper() in HURT or mate.player_id in self.absent):
                continue
            parted = teammates.parted(self.outings[pid], self.outings[mate.player_id], club)
            if len(parted.without) >= MIN_FORM_GAMES and len(parted.alongside) >= MIN_FORM_GAMES:
                key = (tuple(g.game for g in parted.without), not ruled_out(condition.status))
                grouped[key].append(Absent(mate, condition))
                games[key] = parted
        found = [self._split(tuple(mates), games[key]) for key, mates in grouped.items()]
        return sorted(found, key=lambda s: (s.back, -s.gain))

    def returning(self, player: YahooPlayer, conditions: Mapping[str, Condition], today: date) -> list[Returning]:
        """Each regular at his position who is hurt, due back within `RETURN_SOON` of `today`, and beside whom
        he has played too few games to split, though enough without him: soonest back first.

        None where Sleeper cannot place him at his Yahoo club, as for a split,
        or where ESPN dates no return: a return is never guessed.
        """
        pid = self.index.lookup(player.name)
        club = self.club.get(pid) if pid is not None else None
        if pid is None or club is None or club != player.team.upper():
            return []
        found: list[tuple[date, Returning]] = []
        for mate in self.by_club.get(club, []):
            condition = conditions.get(mate.player_id, Condition())
            back = condition.returns
            if mate.player_id == pid or condition.status.upper() not in HURT or back is None:
                continue
            if not today <= back <= today + RETURN_SOON or not shares_position(player.position, mate.position):
                continue
            parted = teammates.parted(self.outings[pid], self.outings[mate.player_id], club)
            if len(parted.alongside) < MIN_FORM_GAMES <= len(parted.without):
                found.append((back, Returning(Absent(mate, condition), len(parted.without), len(parted.alongside))))
        return [returning for _, returning in sorted(found, key=lambda pair: pair[0])]

    def _split(self, mates: tuple[Absent, ...], parted: teammates.Parted[Outing]) -> Split:
        apart, beside = nine_cat([g.log for g in parted.without]), nine_cat([g.log for g in parted.alongside])
        return Split(
            teammates=mates,
            without=apart,
            games=len(parted.without),
            alongside=beside,
            alongside_games=len(parted.alongside),
            without_points=fantasy_points(apart, self.weights) if self.weights else None,
            alongside_points=fantasy_points(beside, self.weights) if self.weights else None,
        )


def reported(regulars: Sequence[Regular], reports: Sequence[InjuryReport]) -> dict[str, Condition]:
    """Each regular on ESPN's injury report, by Sleeper's id, in Yahoo's words: by ESPN's id where Sleeper
    carries it, else by name within his club (`injuries.matched`, which refuses a name two of them share)."""
    clubs = by_club((espn_club(r.team), r.name, r.player_id) for r in regulars)
    injuries = PlayerInjuries(
        by_player=matched(reports, clubs, {r.espn_id: r.player_id for r in regulars if r.espn_id})
    )
    return {
        r.player_id: Condition(status=espn_status(report.status), returns=report.returns)
        for r in regulars
        if (report := injuries.of(r.player_id))
    }


def conditions(
    regulars: Iterable[Regular], yahoo: Iterable[YahooPlayer], espn: Mapping[str, Condition]
) -> dict[str, Condition]:
    """Each regular's condition by Sleeper's id: Yahoo's status where his Yahoo row is among `yahoo`, else ESPN's.

    A Yahoo row is his where the name and the club both match, and no other row
    on hand shares them. ESPN's return date stands either way: Yahoo publishes none.
    """
    rows: dict[tuple[str, str], str | None] = {}
    for p in yahoo:
        key = (normalize_name(p.name), p.team.upper())
        rows[key] = p.status if key not in rows or rows[key] == p.status else None
    found = {}
    for regular in regulars:
        on_espn = espn.get(regular.player_id, Condition())
        status = rows.get((normalize_name(regular.name), regular.team.upper()))
        found[regular.player_id] = Condition(
            status=on_espn.status if status is None else status, returns=on_espn.returns
        )
    return found
