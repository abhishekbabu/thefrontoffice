"""The evidence behind a football decision: a player's role, and his matchup.

A projection is a single number, and it hides the mechanism behind it. The
mechanism is what a decision should rest on: how much of the offense runs
through a player — snaps, targets, carries — and how much the defense he
faces gives up to his position. Sleeper publishes neither as a figure. Both
are computed here from its per-game stat lines, so a recommendation can say
*why* rather than only *how much*.

Only games already played count. A week still under way would read a
Monday-night starter as a player who did nothing.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from thefrontoffice.adapters.outbound.competitions import matchups
from thefrontoffice.adapters.outbound.competitions.matchups import Matchup, Scored
from thefrontoffice.adapters.outbound.competitions.nfl.model import GameLine, Projection
from thefrontoffice.domain.models import Stat

ROLE_GAMES = 3
"""Recent enough to catch a changed role, long enough that one game is not a role."""

# Snaps are recorded for offensive players only; a kicker or a team defense
# has no share of anything, and saying "0% of snaps" about one is false.
SNAP_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
TARGET_POSITIONS = frozenset({"RB", "WR", "TE"})
CARRY_POSITIONS = frozenset({"QB", "RB"})


def season_lines(by_week: Mapping[int, Sequence[GameLine]]) -> list[GameLine]:
    """Every week's lines as one run, for a reading that does not care which week a line came from."""
    return [line for lines in by_week.values() for line in lines]


def took_the_field(line: GameLine) -> bool:
    """Whether a line is a game he played: offensive snaps where his position has them, a game played otherwise.

    Sleeper files a row for a game a player sat out, and averaging its noughts
    in halves a role that did not change.
    """
    return bool(line.stats.get("off_snp")) if line.position in SNAP_POSITIONS else bool(line.stats.get("gp"))


def snap_share(line: GameLine) -> float | None:
    """His share of his offense's snaps in one game; None where nobody counted them."""
    team = line.stats.get("tm_off_snp")
    return line.stats.get("off_snp", 0.0) / team if team else None


def _team_targets(lines: Sequence[GameLine], key: str = "rec_tgt") -> dict[tuple[str, int], float]:
    """Every club's targets in each week, which a player's share is of — or, by `key`, its carries."""
    totals: dict[tuple[str, int], float] = defaultdict(float)
    for line in lines:
        totals[(line.team, line.week)] += line.stats.get(key, 0.0)
    return totals


@dataclass(frozen=True)
class Appearance:
    """One game he took the field in: for whom, what he scored, and how much of it he was on for."""

    week: int
    team: str
    points: float
    snap_share: float | None
    targets: float = 0.0
    target_share: float | None = None
    """His share of his club's targets that game; None where it threw none."""
    carries: float = 0.0
    carry_share: float | None = None
    """His share of his club's carries that game; None where it ran none."""
    receiving_yards: float = 0.0
    pass_attempts: float = 0.0
    passing_yards: float = 0.0
    rushing_yards: float = 0.0

    @property
    def opportunities(self) -> float:
        """Targets and carries: the touches a back's or receiver's points are made from."""
        return self.targets + self.carries

    @property
    def game(self) -> int:
        """The week, which is which of the club's games this was (`teammates.Outing`)."""
        return self.week

    @property
    def partial(self) -> bool:
        """On for under `LEFT_EARLY` of the snaps: a game a teammate split counts as missed."""
        return self.snap_share is not None and self.snap_share < LEFT_EARLY


@dataclass(frozen=True)
class Role:
    """What a player has been asked to do, per game, over his last few games."""

    position: str
    games: int
    points: float
    snap_share: float | None = None
    targets: float = 0.0
    target_share: float | None = None
    carries: float = 0.0

    def describe(self) -> str:
        """'last 3 games: 71% of snaps, 6.3 targets (24% share), 14.2 pts'."""
        parts = []
        if self.snap_share is not None:
            parts.append(f"{self.snap_share:.0%} of snaps")
        if self.position in CARRY_POSITIONS and self.carries:
            parts.append(f"{self.carries:.1f} carries")
        if self.position in TARGET_POSITIONS:
            share = f" ({self.target_share:.0%} share)" if self.target_share is not None else ""
            parts.append(f"{self.targets:.1f} targets{share}")
        parts.append(f"{self.points:.2f} pts")
        games = "last game" if self.games == 1 else f"last {self.games} games"
        return f"{games}: {', '.join(parts)}"


@dataclass(frozen=True)
class Trend:
    """A role that grew in the latest week: his share of something, then against before.

    The pickups worth making first are the ones whose role has changed and
    whose projection has not caught up — a backup handed the starter's snaps
    the week the starter got hurt is a different player from the one his
    average describes.
    """

    measure: str
    """'snaps', 'targets' or 'carries'."""
    before: float
    """Per game across the games before the latest: a share for snaps and targets, a count for carries."""
    now: float
    week: int
    rise: float
    """How big a jump this is against the smallest that counts: 1 is just enough, 2 twice that."""
    games: int = 1
    """His games in the new role, the latest of them: two where it held, one where a teammate's absence made it."""

    def describe(self) -> str:
        """'snaps 38% → 71% in week 6'."""
        if self.measure == "carries":
            return f"carries {self.before:.1f} → {self.now:.0f} in week {self.week}"
        noun = "target share" if self.measure == "targets" else "snaps"
        return f"{noun} {self.before:.0%} → {self.now:.0%} in week {self.week}"

    def short(self) -> str:
        """The same in a table cell: 'snaps 38→71%'."""
        if self.measure == "carries":
            return f"carries {self.before:.0f}→{self.now:.0f}"
        noun = "targets" if self.measure == "targets" else "snaps"
        return f"{noun} {self.before:.0%}→{self.now:.0%}".replace("%→", "→")


REGULAR = 0.5
"""Snap share at which a teammate at his position is a regular: whose absence moves work to whoever is behind him."""

RECEIVERS = frozenset({"WR", "TE"})
"""Positions that share one pool of targets: a club's top target earner at either matters to both."""

LEFT_EARLY = 0.30
"""Snap share under which a teammate's game counts as missed: hurt early, or eased back in."""


# The smallest jump that counts as a changed role, and the least he must now
# have: a third-string back going from 2% to 12% of snaps has changed nothing.
RISES = {
    "snaps": (0.2, REGULAR),
    "targets": (0.1, 0.18),
    "carries": (6.0, 10.0),
}


@dataclass(frozen=True)
class Evidence:
    """Every rostered and available player's role, and every defense's record."""

    roles: dict[str, Role] = field(default_factory=dict)
    allowed: dict[tuple[str, str], Matchup] = field(default_factory=dict)
    games: dict[str, tuple[float, ...]] = field(default_factory=dict)
    """Each player's points in every game he played this season, oldest first."""

    positions: dict[str, str] = field(default_factory=dict)
    """The position he played those games at."""

    trends: dict[str, Trend] = field(default_factory=dict)
    """Players whose role jumped in the latest week played, by the biggest of their jumps."""

    appearances: dict[str, tuple[Appearance, ...]] = field(default_factory=dict)
    """Each player's games played this season, oldest first, week by week: what a split by who else played reads."""

    passers: dict[tuple[str, int], str] = field(default_factory=dict)
    """Each club's quarterback by the end of each week's game, by (club, week): who starts the next (`_passers`)."""

    def matchup(self, player: Projection) -> Matchup | None:
        return self.allowed.get((player.opponent, player.position)) if player.opponent else None

    def describe(self, player: Projection, trend: bool = True) -> str:
        """Both halves in one line, or empty when there is nothing played to go on.

        Without `trend` where whatever this line sits under already says how his role grew.
        """
        matchup, role = self.matchup(player), self.roles.get(player.player_id)
        grew = self.trends.get(player.player_id) if trend else None
        parts = [matchup.describe()] if matchup else []
        parts += [role.describe()] if role else []
        parts += [f"role growing: {grew.describe()}"] if grew else []
        return "; ".join(parts)

    def stat(self, player: Projection, trend: bool = True) -> Stat | None:
        """The same line labelled with the player, toned by the matchup."""
        text = self.describe(player, trend)
        if not text:
            return None
        matchup = self.matchup(player)
        return Stat(label=player.name, value=text, tone=matchup.tone if matchup else "neutral")


def gather(lines: Sequence[GameLine], scoring: str, out: Collection[str] = frozenset()) -> Evidence:
    """Roles and matchups from the season's played game lines.

    `out` is who is ruled out of the coming game: a backup's jump in the week a
    starter missed is his role only while that starter stays out.
    """
    appearances, positions = _appearances(lines, scoring)
    return Evidence(
        roles=_roles(lines, scoring),
        allowed=_allowed(lines, scoring),
        games={pid: tuple(game.points for game in each) for pid, each in appearances.items()},
        positions=positions,
        trends=_trends(lines, out),
        appearances=appearances,
        passers=_passers(lines),
    )


def _appearances(lines: Sequence[GameLine], scoring: str) -> tuple[dict[str, tuple[Appearance, ...]], dict[str, str]]:
    """Each player's games he took the field in, by the same rule his role is read by, oldest first."""
    team_targets, team_carries = _team_targets(lines), _team_targets(lines, "rush_att")
    played: dict[str, list[GameLine]] = defaultdict(list)
    for line in lines:
        if took_the_field(line):
            played[line.player_id].append(line)

    def appearance(game: GameLine) -> Appearance:
        targets, thrown = game.stats.get("rec_tgt", 0.0), team_targets[(game.team, game.week)]
        carries, ran = game.stats.get("rush_att", 0.0), team_carries[(game.team, game.week)]
        return Appearance(
            week=game.week,
            team=game.team,
            points=game.stats.get(scoring, 0.0),
            snap_share=snap_share(game),
            targets=targets,
            target_share=targets / thrown if thrown else None,
            carries=carries,
            carry_share=carries / ran if ran else None,
            receiving_yards=game.stats.get("rec_yd", 0.0),
            pass_attempts=game.stats.get("pass_att", 0.0),
            passing_yards=game.stats.get("pass_yd", 0.0),
            rushing_yards=game.stats.get("rush_yd", 0.0),
        )

    appearances = {
        pid: tuple(appearance(game) for game in sorted(each, key=lambda game: game.week))
        for pid, each in played.items()
    }
    positions = {pid: max(each, key=lambda game: game.week).position for pid, each in played.items()}
    return appearances, positions


RELIEF = 0.25
"""The share of a club's pass attempts a second quarterback must throw in a game for him to have taken over in
it: a benching or an injury, not a trick play or a kneel-down series."""


def _passers(lines: Sequence[GameLine]) -> dict[tuple[str, int], str]:
    """Each club's quarterback by the end of each week's game: who will be under centre in the next.

    The one with the most pass attempts — unless a second quarterback threw
    `RELIEF` of them and the club's quarterback the week before is the other
    one: then the second came in for him, benched or hurt, and finished the
    game. Read from the week totals alone, which is all a game line carries.
    """
    attempts: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    for line in lines:
        if line.position == "QB" and (count := line.stats.get("pass_att", 0.0)):
            attempts[(line.team, line.week)][line.player_id] = count
    found: dict[tuple[str, int], str] = {}
    last: dict[str, str] = {}
    for team, week in sorted(attempts, key=lambda key: key[1]):
        thrown = attempts[(team, week)]
        total = sum(thrown.values())
        finisher = max(thrown, key=lambda pid: thrown[pid])
        before = last.get(team)
        relievers = [pid for pid, count in thrown.items() if pid != before and count >= RELIEF * total]
        if before in thrown and relievers:
            finisher = max(relievers, key=lambda pid: thrown[pid])
        found[(team, week)] = last[team] = finisher
    return found


def _roles(lines: Sequence[GameLine], scoring: str) -> dict[str, Role]:
    team_targets = _team_targets(lines)
    by_player: dict[str, list[GameLine]] = defaultdict(list)
    for line in lines:
        if took_the_field(line):
            by_player[line.player_id].append(line)

    roles = {}
    for player_id, played in by_player.items():
        recent = sorted(played, key=lambda line: line.week, reverse=True)[:ROLE_GAMES]
        position = recent[0].position
        snaps = _total(recent, "tm_off_snp")
        targets_available = sum(team_targets[(line.team, line.week)] for line in recent)
        roles[player_id] = Role(
            position=position,
            games=len(recent),
            points=_total(recent, scoring) / len(recent),
            snap_share=_total(recent, "off_snp") / snaps if position in SNAP_POSITIONS and snaps else None,
            targets=_total(recent, "rec_tgt") / len(recent),
            target_share=(
                _total(recent, "rec_tgt") / targets_available
                if position in TARGET_POSITIONS and targets_available
                else None
            ),
            carries=_total(recent, "rush_att") / len(recent),
        )
    return roles


def _trends(lines: Sequence[GameLine], out: Collection[str]) -> dict[str, Trend]:
    """Whose role jumped in the latest week played, against his games before it.

    The latest week anybody played, not his own latest game: a jump three
    weeks ago is a role, by now, and the projection has long since read it.

    One big game is not a role. The jump counts once it has held for his last
    two games, or at once when it has a cause: a regular teammate (see
    `_absent`) missed it and is ruled out of the next. The first waits a week
    on a real breakout; the second is the backup handed the starter's snaps,
    worth knowing the week it happens.

    Either way the jump is fill-in work, not a role, while a regular teammate
    who missed every game of it is due back: not ruled out, and still with the
    club. A receiver who played a fifth of the snaps all season and nine in ten
    the two weeks the starter sat is the same receiver the week the starter
    returns.
    """
    if not lines:
        return {}
    latest = max(line.week for line in lines)
    team_targets = _team_targets(lines)
    by_player: dict[str, list[GameLine]] = defaultdict(list)
    for line in lines:
        if line.position in SNAP_POSITIONS and took_the_field(line):
            by_player[line.player_id].append(line)
    for played in by_player.values():
        played.sort(key=lambda line: line.week)

    def measures(line: GameLine) -> dict[str, float]:
        found = {}
        if (share := snap_share(line)) is not None:
            found["snaps"] = share
        if line.position in TARGET_POSITIONS and team_targets[(line.team, line.week)]:
            found["targets"] = line.stats.get("rec_tgt", 0.0) / team_targets[(line.team, line.week)]
        if line.position in CARRY_POSITIONS:
            found["carries"] = line.stats.get("rush_att", 0.0)
        return found

    def jump(recent: Sequence[GameLine], earlier: Sequence[GameLine]) -> Trend | None:
        """The biggest jump every one of the recent games makes on the earlier ones, measured by the smallest."""
        if len(earlier) < 2:
            return None
        now, before = [measures(line) for line in recent], [measures(line) for line in earlier]
        best: Trend | None = None
        for measure, (step, floor) in RISES.items():
            if any(measure not in game or game[measure] < floor for game in now):
                continue
            baseline = [game[measure] for game in before if measure in game]
            if not baseline:
                continue
            average = sum(baseline) / len(baseline)
            rise = (min(game[measure] for game in now) - average) / step
            if rise >= 1 and (best is None or rise > best.rise):
                best = Trend(
                    measure=measure, before=average, now=now[-1][measure], week=latest, rise=rise, games=len(recent)
                )
        return best

    def returning(teammate: str, team: str) -> bool:
        """Whether a teammate is due back: not ruled out, and his latest game was for this club."""
        return teammate not in out and by_player[teammate][-1].team == team

    trends = {}
    for player_id, played in by_player.items():
        last = played[-1]
        if last.week != latest:
            continue
        held = jump(played[-2:], played[:-2][-ROLE_GAMES:]) if len(played) >= 2 else None
        if held is not None:
            absent = _absent(by_player, played[-2:], played[:-2][-ROLE_GAMES:], team_targets)
            trend = None if any(returning(mate, last.team) for mate in absent) else held
        else:
            earlier = played[:-1][-ROLE_GAMES:]
            absent = _absent(by_player, [last], earlier, team_targets)
            cause = absent and not any(returning(mate, last.team) for mate in absent)
            trend = jump([last], earlier) if cause else None
        if trend is not None:
            trends[player_id] = trend
    return trends


def _absent(
    by_player: Mapping[str, Sequence[GameLine]],
    recent: Sequence[GameLine],
    earlier: Sequence[GameLine],
    team_targets: Mapping[tuple[str, int], float],
) -> list[str]:
    """His regular teammates who missed every one of his recent games: whose work a jump in them may be.

    A regular is a teammate at his position on `REGULAR` of the snaps in the
    earlier games, or — for a receiver or tight end — the club's top target
    earner at either in them, by his summed share of each game's targets. A game counts as missed where the teammate did
    not take the field for the club or was on for under `LEFT_EARLY` of it.
    """
    me = recent[-1]
    weeks = {line.week for line in earlier}
    recent_weeks = {line.week for line in recent}
    targets: dict[str, float] = defaultdict(float)
    regulars: list[str] = []
    for teammate, played in by_player.items():
        mine = [game for game in played if game.team == me.team and game.week in weeks]
        if not mine:
            continue
        shares = [share for game in mine if (share := snap_share(game)) is not None]
        if (
            teammate != me.player_id
            and played[-1].position == me.position
            and shares
            and sum(shares) / len(shares) >= REGULAR
        ):
            regulars.append(teammate)
        if me.position in RECEIVERS and played[-1].position in RECEIVERS:
            targets[teammate] = sum(
                game.stats.get("rec_tgt", 0.0) / team_targets[(game.team, game.week)]
                for game in mine
                if team_targets[(game.team, game.week)]
            )
    if targets:
        top = max(targets, key=lambda teammate: targets[teammate])
        if targets[top] and top != me.player_id and top not in regulars:
            regulars.append(top)

    def missed(teammate: str) -> bool:
        there = {
            game.week
            for game in by_player[teammate]
            if game.team == me.team and ((share := snap_share(game)) is None or share >= LEFT_EARLY)
        }
        return not (recent_weeks & there)

    return [teammate for teammate in regulars if missed(teammate)]


def misses(lines: Sequence[GameLine]) -> tuple[int, int]:
    """How often a regular missed a game his team played: (games missed, games he was there to miss).

    A regular plays at least half his team's snaps in the games he plays.
    Every game his team played after his first one for it was his to miss —
    to an injury, an illness or the coach, which a lineup feels alike.
    """
    floor = RISES["snaps"][1]
    team_weeks: dict[str, set[int]] = defaultdict(set)
    by_player: dict[str, list[GameLine]] = defaultdict(list)
    for line in lines:
        if line.position in SNAP_POSITIONS and took_the_field(line):
            team_weeks[line.team].add(line.week)
            if snap_share(line) is not None:
                by_player[line.player_id].append(line)
    missed = chances = 0
    for played in by_player.values():
        shares = [share for line in played if (share := snap_share(line)) is not None]
        if sum(shares) / len(shares) < floor:
            continue
        team = max(played, key=lambda line: line.week).team
        weeks = {line.week for line in played if line.team == team}
        later = [week for week in team_weeks[team] if week > min(weeks)]
        chances += len(later)
        missed += sum(week not in weeks for week in later)
    return missed, chances


def _allowed(lines: Sequence[GameLine], scoring: str) -> dict[tuple[str, str], Matchup]:
    """Points each defense has given up per game to each position, ranked (`matchups.allowed`)."""
    return matchups.allowed(
        Scored(line.opponent, line.position, line.week, line.stats.get(scoring, 0.0), line.team) for line in lines
    )


def _total(lines: Sequence[GameLine], key: str) -> float:
    return sum(line.stats.get(key, 0.0) for line in lines)


MIN_GAMES_FOR_AVERAGE = 2
"""Games a player needs before his average says more about him than his projection does."""


def average(evidence: Evidence, player_id: str) -> float | None:
    """His points a game this season; None until he has played enough games for it to say anything."""
    games = evidence.games.get(player_id, ())
    return sum(games) / len(games) if len(games) >= MIN_GAMES_FOR_AVERAGE else None


def season_average(evidence: Evidence, player: Projection) -> float:
    """What he is worth over a season: his average a game where he has played enough, else his projection.

    Not this week's projection alone, which reads a starter on bye as nothing.
    """
    played = average(evidence, player.player_id)
    return player.points if played is None else played
