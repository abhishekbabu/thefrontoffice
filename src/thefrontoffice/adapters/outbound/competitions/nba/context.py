"""Assembling what a category league needs to know about one player.

Three readings meet here, and they answer different questions: Yahoo says who
holds the player, Sleeper's box scores say what they have been doing, and
Sleeper's projections say what they are expected to do over the games left in
the matchup period. A line without the games remaining is a rate with no
quantity behind it, which is why they are built together.

Which free agents the scout reads is decided here too: the lines are only as
useful as the candidates they are written for.
"""

from collections.abc import Callable, Mapping
from datetime import date

from thefrontoffice.adapters.outbound.competitions.injuries import approximately
from thefrontoffice.adapters.outbound.competitions.nba import prompt
from thefrontoffice.adapters.outbound.competitions.nba.form import WINDOWS, FormSource, PlayerStats, Window
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS
from thefrontoffice.adapters.outbound.competitions.nba.views import points
from thefrontoffice.adapters.outbound.competitions.nba.week import ScheduleSource
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer

WINDOW_TAGS: tuple[tuple[Window, str], ...] = (("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15"))

POINTS_POOL = 30
"""Free agents a points league's scout reads, best fantasy points per game first."""


def rank_free_agents(leaders: Mapping[str, list[YahooPlayer]]) -> tuple[list[YahooPlayer], dict[str, str]]:
    """Top available players per category, deduplicated, most versatile first.

    `leaders` is Yahoo's leaders on the wire, by category label. A player
    leading several categories appears once, annotated with all of them, and
    ahead of single-category players — the ordering the prompt relies on when
    it asks for the three best adds.
    """
    categories_by_key: dict[str, list[str]] = {}
    player_by_key: dict[str, YahooPlayer] = {}
    for label, players in leaders.items():
        for p in players:
            key = p.player_key
            if key not in categories_by_key:
                categories_by_key[key] = []
                player_by_key[key] = p
            categories_by_key[key].append(label)

    ranked = sorted(categories_by_key.items(), key=lambda kv: len(kv[1]), reverse=True)
    players = [player_by_key[key] for key, _ in ranked]
    annotations = {key: f"[Top in: {', '.join(cats)}]" for key, cats in ranked}
    return players, annotations


def rank_by_points(
    available: list[YahooPlayer], stats_for: Callable[[str], PlayerStats | None], weights: Mapping[str, float]
) -> tuple[list[YahooPlayer], dict[str, str]]:
    """The available players a points league's scout reads: best fantasy points per game first.

    `available` is Yahoo's own ranking of the wire, reordered by what the
    league's weights make of each one's recent run; a player with no line has
    nothing to rank him by, and is left out.
    """
    scored = [(player, fpts) for player in available if (fpts := points(stats_for(player.name), weights)) is not None]
    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)[:POINTS_POOL]
    return [p for p, _ in ranked], {p.player_key: f"[{fpts:.1f} fpts/g]" for p, fpts in ranked}


class PlayerContextBuilder:
    """One player as a block of prompt text, rostered or on the wire.

    The same shape for both, so the model compares like with like rather than
    reading two formats and inferring which is which.
    """

    def __init__(self, form: FormSource, schedule: ScheduleSource, weights: Mapping[str, float] | None = None):
        """`weights` are a points league's, by Yahoo stat id: each line then closes on its fantasy points."""
        self.form = form
        self.schedule = schedule
        self.weights = weights

    def _format_stats(self, stats: PlayerStats) -> str:
        """Each recent window that can be filled, as one nine-category line.

        A player short of fifteen games also carries every game he has, tagged
        with its count — otherwise twelve games in reads as only his last ten.
        """
        parts = [
            f"{tag}: {prompt.scored(stats[window], self.weights)}" for window, tag in WINDOW_TAGS if window in stats
        ]
        if (recent := stats.get("recent")) and recent.games not in WINDOWS:
            parts.append(f"L{recent.games}: {prompt.scored(recent.line, self.weights)}")
        return " | ".join(parts) if parts else "No recent stats"

    def build_context_for_players(
        self,
        players: list[YahooPlayer],
        matchup_start: date | None = None,
        matchup_end: date | None = None,
        annotations: dict[str, str] | None = None,
        remaining_games: dict[str, int] | None = None,
        projections: ProjectionIndex | None = None,
        returns: Mapping[str, date] | None = None,
    ) -> str:
        """One prompt line per player, concatenated.

        Args:
            annotations: player_key -> extra text, e.g. "[Top in: PTS]".
            remaining_games: precomputed counts, empty where unknown; looked up if omitted.
            returns: player_key -> the day ESPN expects him back, for whoever it has hurt.
        """
        return "".join(
            self.build_player_lines(
                players, matchup_start, matchup_end, annotations, remaining_games, projections, returns
            ).values()
        )

    def build_player_lines(
        self,
        players: list[YahooPlayer],
        matchup_start: date | None = None,
        matchup_end: date | None = None,
        annotations: dict[str, str] | None = None,
        remaining_games: dict[str, int] | None = None,
        projections: ProjectionIndex | None = None,
        returns: Mapping[str, date] | None = None,
    ) -> dict[str, str]:
        """Same as build_context_for_players, keyed by player name.

        Lets a caller keep only the lines it needs — the follow-up briefing
        carries the recommended free agents rather than all thirty.
        """
        if not players:
            return {}

        if remaining_games is None:
            remaining_games = {}
            if matchup_start and matchup_end:
                teams = [p.team for p in players]
                remaining_games = self.schedule.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        lines: dict[str, str] = {}
        for p in players:
            stats_dict = self.form.get_player_stats(p.name)

            games_left = remaining_games.get(p.team.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""

            status_str = ""
            if p.status:
                status_str = f" [{p.status}]"
                if p.injury_note:
                    status_str += f" ({p.injury_note})"
            if returns and (back := returns.get(p.player_key)):
                status_str += f" [back {approximately(back)}]"

            il_str = " [IN IL SPOT]" if p.slot in INJURED_SLOTS else ""

            note = ""
            if annotations and p.player_key in annotations:
                note = f" {annotations[p.player_key]}"

            line = f"- {p.name} ({p.position}){il_str}{status_str}{games_str}{note}"
            if stats_dict:
                line += f": {self._format_stats(stats_dict)}"
            if projections is not None and (projected := projections.lookup(p.name)):
                line += f" | PROJ {projected.games}G {prompt.scored(projected.line, self.weights)}"
            lines[p.name] = line + "\n"

        return lines
