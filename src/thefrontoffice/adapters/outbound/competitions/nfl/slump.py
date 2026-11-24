"""A starter whose games have fallen well short of his projection: a slump the projection has not read.

A projection keeps the number a player's name earned while his weeks say
something else: the tight end on his usual snaps whose targets stopped turning
into yards, the receiver whose quarterback changed. `worth` already blends his
form in, but every free agent at his position is read the same way, so a
starter projected well above what he scores still outranks a streamer playing
better. Once his games and his projection disagree by enough, for long enough,
the slot is weighed on form instead — a call the list labels as one, never a
projection it quotes.

Only a real gap counts: his points a game over his last few games played,
well under this week's projection, in all but one of them. One bad afternoon
is noise either way; three out of four is a trend.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.matchups import matchup_factor
from thefrontoffice.adapters.outbound.competitions.news import dated
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import (
    MIN_GAMES_FOR_AVERAGE,
    TARGET_POSITIONS,
    Appearance,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.adapters.outbound.competitions.nfl.news import QB_CHANGE
from thefrontoffice.adapters.outbound.competitions.nfl.rules import STREAMED
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.nfl.worth import plays, usage

SLUMP_LABEL, QB_CHANGE_LABEL = "Slump", "QB change"
"""What a starter in trouble is called wherever he is shown — the drawer, a roster row's note, a model's player
line: a slump where his games fell short, a QB change where only his quarterback did."""

SLUMP_GAMES = 4
"""His last games played that a slump is read over, games he missed left out: one bad afternoon is a quarter of it."""

FEWEST = 3
"""Games played the window needs: two is one bad game and a coin flip."""

SHORT_OF = 0.6
"""The share of this week's projection his points a game must fall under. Weekly scoring swings by
about half a projection either way, so a month under three-fifths of it is not a projection running cold."""

SHORT_BY = 3.0
"""And the points a game under it: a five-point player projected seven is not the question a slot turns on."""

COLLAPSED = 0.75
"""Efficiency now against before under which it has collapsed: yards a target for a receiver or tight end,
points a touch for a back. A quarter off is beyond what a month's matchups explain."""

HOLDS = 0.9
"""Usage now against before at which it holds: within a tenth of the snaps, and of the target share."""


@dataclass(frozen=True)
class Change:
    """One measure over the slump against his games before it."""

    measure: str
    now: float
    before: float

    @property
    def ratio(self) -> float:
        return self.now / self.before if self.before else 1.0


THIS_WEEK, THOSE_WEEKS = "this week", "those weeks"
"""What a slump's games are measured against: this week's projection, or Sleeper's projections for the games."""


@dataclass(frozen=True)
class QBChange:
    """His club's quarterback changing: by its games, by its news, or both."""

    was: str = ""
    """The club's usual quarterback before, by surname; empty where only the news says so."""
    now: str = ""
    since: int | None = None
    """The first week the new quarterback started, where he has; form since then is his form now."""
    story: str = ""
    """The club story saying so, 'Sun 23 Nov: <headline>', where there is one."""

    def short(self) -> str:
        """'QB Jones→Leonard since week 11', or the story where no game has been played under the new one."""
        if self.was and self.now:
            return f"QB {self.was}→{self.now}" + (f" since week {self.since}" if self.since is not None else "")
        return self.story


@dataclass(frozen=True)
class Slump:
    """A starter in trouble: scoring well under his projection over his last few games, or his club's quarterback
    changed under him — and what the games say about why."""

    player_id: str
    games: int
    recent: float
    """His points a game over them."""
    projected: float
    """What he was projected for those same weeks, a game — or this week's projection, where `basis` says so."""
    basis: str = THIS_WEEK
    """What `projected` is: `THOSE_WEEKS` where Sleeper's projections for the games themselves loaded."""
    short_of: bool = True
    """Whether his games fell short of the projection (`SHORT_OF`, `SHORT_BY`): false where only a QB change fired."""
    efficiency: Change | None = None
    """Yards a target ('yds/tgt'), points a touch ('pts/touch') for a back, yards an attempt ('yds/att') for a
    quarterback; None without games before to compare."""
    snaps: Change | None = None
    targets: Change | None = None
    """His share of his club's targets."""
    rushing: Change | None = None
    """A quarterback's rushing yards a game."""
    qb: QBChange | None = None
    since_form: float | None = None
    """His points a game since his new quarterback's first start, where he has played since."""

    @property
    def label(self) -> str:
        """What he is flagged as: a slump where his games fell short, a QB change where only that fired."""
        return SLUMP_LABEL if self.short_of else QB_CHANGE_LABEL

    @property
    def collapsed(self) -> bool:
        """Whether his efficiency fell by `COLLAPSED` or more."""
        return self.efficiency is not None and self.efficiency.ratio <= COLLAPSED

    @property
    def usage_holds(self) -> bool | None:
        """Whether his snaps and target share held (`HOLDS`); None with nothing before to compare."""
        measured = [change for change in (self.snaps, self.targets) if change is not None]
        if not measured:
            return None
        return all(change.ratio >= HOLDS for change in measured)

    @property
    def since(self) -> int | None:
        """The week his form now starts: the new quarterback's first start, where he has one."""
        return self.qb.since if self.qb is not None else None

    def short(self) -> str:
        """'4.95/g L4 vs 11.90 proj those weeks · 3.4 yds/tgt, was 5.9 (collapsed) · usage down: snaps 79%, was 91%;
        tgt share 22%, was 21% · QB Jones→Leonard since week 11'."""
        if not self.short_of and self.qb is not None:
            since = f" · {self.since_form:.2f}/g since" if self.since_form is not None else ""
            return self.qb.short() + since
        parts = [f"{self.recent:.2f}/g L{self.games} vs {self.projected:.2f} proj {self.basis}"]
        if (rate := self.efficiency) is not None:
            parts.append(
                f"{rate.now:.1f} {rate.measure}, was {rate.before:.1f}" + (" (collapsed)" if self.collapsed else "")
            )
        if (holds := self.usage_holds) is not None:
            shares = [
                f"{name} {change.now:.0%}, was {change.before:.0%}"
                for name, change in (("snaps", self.snaps), ("tgt share", self.targets))
                if change is not None
            ]
            parts.append(f"usage {'holds' if holds else 'down'}: {'; '.join(shares)}")
        if (rush := self.rushing) is not None:
            parts.append(f"{rush.now:.0f} rush yds/g, was {rush.before:.0f}")
        if self.qb is not None:
            parts.append(self.qb.short())
        return " · ".join(parts)


SLUMP_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
"""Whose own line can say his projection is wrong: a kicker or a defense is streamed on the week's matchup instead."""


def slump(state: Week, player: Projection) -> Slump | None:
    """His trouble, where there is any; None otherwise.

    A quarterback, back, receiver or tight end with a game this week and at
    least `FEWEST` games played, whose last `SLUMP_GAMES` fall short of what
    Sleeper projected for those same games — or of this week's projection,
    where those did not load: his points a game under `SHORT_OF` of it and by
    `SHORT_BY`, with all but one of the games under their line. Or, for a back,
    receiver or tight end, whose club's quarterback changed under him (`QBChange`):
    flagged before his production drops, and read on his games since.
    """
    if player.position not in SLUMP_POSITIONS or not plays(state, player) or player.points <= 0:
        return None
    played = state.evidence.appearances.get(player.player_id, ())
    window, before = played[-SLUMP_GAMES:], played[:-SLUMP_GAMES]
    if len(window) < FEWEST:
        return None
    lines, basis = _lines(state, player, window)
    scored = sum(game.points for game in window) / len(window)
    projected = sum(lines) / len(lines)
    short_of = (
        scored < SHORT_OF * projected
        and projected - scored >= SHORT_BY
        and sum(game.points < SHORT_OF * line for game, line in zip(window, lines, strict=True)) >= len(window) - 1
    )
    qb = _qb_change(state, player, played) if player.position in TARGET_POSITIONS else None
    if not short_of and qb is None:
        return None
    earlier = before if len(before) >= MIN_GAMES_FOR_AVERAGE else ()
    quarterback = player.position == "QB"
    return Slump(
        player_id=player.player_id,
        games=len(window),
        recent=scored,
        projected=projected,
        basis=basis,
        short_of=short_of,
        efficiency=_efficiency(player.position, window, earlier),
        snaps=None if quarterback else _mean_change("snaps", window, earlier, lambda game: game.snap_share),
        targets=None if quarterback else _mean_change("targets", window, earlier, lambda game: game.target_share),
        rushing=_mean_change("rushing", window, earlier, lambda game: game.rushing_yards) if quarterback else None,
        qb=qb,
        since_form=recent(state, player.player_id, qb.since) if qb is not None and qb.since is not None else None,
    )


def _lines(state: Week, player: Projection, window: Sequence[Appearance]) -> tuple[list[float], str]:
    """What each of his games was projected, and on what basis: Sleeper's projection for that week where it has
    one for every game of the window, this week's for all of them otherwise."""
    projected = [state.past.get(game.week, {}).get(player.player_id, 0.0) for game in window]
    if all(projected):
        return projected, THOSE_WEEKS
    return [player.points] * len(window), THIS_WEEK


def slumps(state: Week) -> dict[str, Slump]:
    """Every starter in trouble in your lineup as set, by player id."""
    found = {}
    for slot in state.lineup:
        if slot.player is not None and (sunk := slump(state, slot.player)) is not None:
            found[slot.player.player_id] = sunk
    return found


def _efficiency(position: str, now: Sequence[Appearance], before: Sequence[Appearance]) -> Change | None:
    """Yards a target for a receiver or tight end, points a touch for a back, yards an attempt for a quarterback."""

    def rate(games: Sequence[Appearance]) -> float | None:
        if position == "RB":
            touches = sum(game.opportunities for game in games)
            return sum(game.points for game in games) / touches if touches else None
        if position == "QB":
            attempts = sum(game.pass_attempts for game in games)
            return sum(game.passing_yards for game in games) / attempts if attempts else None
        targets = sum(game.targets for game in games)
        return sum(game.receiving_yards for game in games) / targets if targets else None

    measure = {"RB": "pts/touch", "QB": "yds/att"}.get(position, "yds/tgt")
    found, earlier = rate(now), rate(before)
    return None if found is None or earlier is None else Change(measure, found, earlier)


def _mean_change(
    measure: str,
    now: Sequence[Appearance],
    before: Sequence[Appearance],
    read: Callable[[Appearance], float | None],
) -> Change | None:
    """A per-game reading's average over the slump against before; None where either has no reading."""
    found = [value for game in now if (value := read(game)) is not None]
    earlier = [value for game in before if (value := read(game)) is not None]
    if not found or not earlier:
        return None
    return Change(measure, sum(found) / len(found), sum(earlier) / len(earlier))


def _qb_change(state: Week, player: Projection, played: Sequence[Appearance]) -> QBChange | None:
    """His club's quarterback changing under him: by the club's own games, within his last `SLUMP_GAMES`, or by a
    club story the news calls a quarterback change. None where neither says so."""
    stories = [story for story in state.news.team(player.player_id) if story.kind == QB_CHANGE]
    story = f"{dated(stories[0].article)}: {stories[0].article.headline}" if stories else ""
    found = _passer_change(state, played)
    if found is not None:
        was, now, since = found
        return QBChange(was=was, now=now, since=since, story=story)
    return QBChange(story=story) if story else None


def _passer_change(state: Week, played: Sequence[Appearance]) -> tuple[str, str, int] | None:
    """His club's usual quarterback before, the one now, and the week the new one first started, by his own games:
    where the change came within his last `SLUMP_GAMES` and the new one has started since."""
    passers = state.evidence.passers
    latest = played[-1]
    current = passers.get((latest.team, latest.week))
    if current is None:
        return None
    # The weeks the current quarterback finished, back from the latest: his starts are the week after each.
    run = []
    for game in reversed(played):
        if game.team != latest.team or passers.get((game.team, game.week)) != current:
            break
        run.append(game)
    usual = [
        passer
        for game in played[: len(played) - len(run)]
        if game.team == latest.team and (passer := passers.get((game.team, game.week)))
    ]
    if not usual or run[-1].week < state.week - SLUMP_GAMES:
        return None
    was = max(set(usual), key=usual.count)
    if was == current:
        return None
    return _name(state, was), _name(state, current), run[-1].week


def _name(state: Week, player_id: str) -> str:
    meta = state.players.get(player_id)
    return meta.name.split(" ")[-1] if meta else player_id


# ── the form call ───────────────────────────────────────────────────────

CALL_FORM = 0.75
"""Form's share of a form call, against the projection's: `worth` weighs them evenly, which is what kept a
slumping starter ahead of every streamer. A quarter stays with the projection, which still reads the week."""

STREAM_FORM = 0.5
"""Form's share of a kicker's or a defense's form call: half, since his projection is built on the matchup that
decides a streamer's week, and a month of field goals or sacks is a small sample of it."""

CALL_BY = 2.0
"""Points a form call must favour the player coming in by: under it the two are a coin flip, and a hunch is no move."""


def called(state: Week, player: Projection, since: int | None = None) -> float | None:
    """What a form call weighs him by: `CALL_FORM` of his points a game over his last `SLUMP_GAMES` played — or his
    games from week `since`, where his quarterback changed then — and the rest his projection, times his `usage`
    and his `matchup_factor`. A kicker or a defense weighs form `STREAM_FORM` instead: his projection already reads
    the matchup that decides a streamer's week. None with too few games to read form from, or no game this week."""
    form = recent(state, player.player_id, since)
    if form is None or not plays(state, player):
        return None
    weight = STREAM_FORM if player.position in STREAMED else CALL_FORM
    blended = weight * form + (1 - weight) * player.points
    return blended * usage(state, player.player_id) * matchup_factor(state.evidence.matchup(player))


def recent(state: Week, player_id: str, since: int | None = None) -> float | None:
    """His points a game over his last `SLUMP_GAMES` played, as a form call reads them — or over his games from
    week `since`, however few; None with too few, or none since."""
    played = state.evidence.appearances.get(player_id, ())
    if since is not None:
        games = [game.points for game in played if game.week >= since]
        return sum(games) / len(games) if games else None
    games = [game.points for game in played[-SLUMP_GAMES:]]
    return sum(games) / len(games) if len(games) >= MIN_GAMES_FOR_AVERAGE else None
