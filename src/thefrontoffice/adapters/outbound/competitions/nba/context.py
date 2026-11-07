"""Assembling what a category league needs to know about one player.

Three readings meet here, and they answer different questions: Yahoo says who
holds the player, Sleeper's box scores say what they have been doing, and
Sleeper's projections say what they are expected to do over the games left in
the matchup period. A line without the games remaining is a rate with no
quantity behind it, which is why they are built together.
"""

from datetime import date

from thefrontoffice.adapters.outbound.competitions.nba import prompt
from thefrontoffice.adapters.outbound.competitions.nba.form import FormSource, PlayerStats, Window
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer

WINDOW_TAGS: tuple[tuple[Window, str], ...] = (("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15"))


class PlayerContextBuilder:
    """One player as a block of prompt text, rostered or on the wire.

    The same shape for both, so the model compares like with like rather than
    reading two formats and inferring which is which.
    """

    def __init__(self, nba_client: FormSource):
        self.nba = nba_client

    @staticmethod
    def _format_stats(stats: PlayerStats) -> str:
        """Each recent window that can be filled, as one nine-category line."""
        parts = [f"{tag}: {prompt.categories(stats[window])}" for window, tag in WINDOW_TAGS if window in stats]
        return " | ".join(parts) if parts else "No recent stats"

    def build_context_for_players(
        self,
        players: list[YahooPlayer],
        matchup_start: date | None = None,
        matchup_end: date | None = None,
        annotations: dict[str, str] | None = None,
        remaining_games: dict[str, int] | None = None,
        projections: ProjectionIndex | None = None,
    ) -> str:
        """One prompt line per player, concatenated.

        Args:
            annotations: player_key -> extra text, e.g. "[Top in: PTS]".
            remaining_games: precomputed counts, empty where unknown; looked up if omitted.
        """
        return "".join(
            self.build_player_lines(
                players, matchup_start, matchup_end, annotations, remaining_games, projections
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
                remaining_games = self.nba.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        lines: dict[str, str] = {}
        for p in players:
            stats_dict = self.nba.get_player_stats(p.name)

            games_left = remaining_games.get(p.team.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""

            status_str = ""
            if p.status:
                status_str = f" [{p.status}]"
                if p.injury_note:
                    status_str += f" ({p.injury_note})"

            il_str = " [IN IL SPOT]" if p.slot in INJURED_SLOTS else ""

            note = ""
            if annotations and p.player_key in annotations:
                note = f" {annotations[p.player_key]}"

            line = f"- {p.name} ({p.position}){il_str}{status_str}{games_str}{note}"
            if stats_dict:
                line += f": {self._format_stats(stats_dict)}"
            if projections is not None and (projected := projections.lookup(p.name)):
                line += f" | PROJ {projected.games}G {prompt.categories(projected.line)}"
            lines[p.name] = line + "\n"

        return lines
