"""Assembling what a category league needs to know about one player.

Three readings meet here, and they answer different questions: Yahoo says who
holds the player, Sleeper's box scores say what they have been doing, and
Sleeper's projections say what they are expected to do over the games left in
the matchup period. A line without the games remaining is a rate with no
quantity behind it, which is why they are built together.
"""

from datetime import date

from yahoofantasy import Player  # type: ignore[import-untyped]

from thefrontoffice.adapters.outbound.competitions.nba.form import (
    FormSource,
    NineCatStats,
    PlayerStats,
    Window,
)
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex


class PlayerContextBuilder:
    """One player as a block of prompt text, rostered or on the wire.

    The same shape for both, so the model compares like with like rather than
    reading two formats and inferring which is which.
    """

    def __init__(self, nba_client: FormSource):
        self.nba = nba_client

    def _format_stats(self, stats_dict: PlayerStats) -> str:
        """Format recent trend stats into a readable string.

        Three-pointers are suffixed `tpm` rather than `3pm`: the latter renders
        "5" and "3pm" as "53pm", which the model reads as badly as a person does.
        """
        if not stats_dict:
            return "No stats available"

        parts: list[str] = []
        labels: tuple[tuple[Window, str], ...] = (("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15"))
        for key, label in labels:
            if key in stats_dict:
                s: NineCatStats = stats_dict[key]
                parts.append(
                    f"{label}: {s['PTS']}p {s['REB']}r {s['AST']}a {s['STL']}s {s['BLK']}b {s['TOV']}to {s['FG3M']}tpm FG{s['FG_PCT']:.1%} FT{s['FT_PCT']:.1%}"
                )

        return " | ".join(parts) if parts else "No recent stats"

    def get_remaining_games(self, team_abbr: str, matchup_start: date | None, matchup_end: date | None) -> int | None:
        """Get remaining games for a player's team in the matchup period."""
        if not matchup_start or not matchup_end:
            return None
        return self.nba.get_remaining_games(team_abbr, matchup_start, matchup_end)

    def build_context_for_players(
        self,
        players: list[Player],
        matchup_start: date | None = None,
        matchup_end: date | None = None,
        annotations: dict[str, str] | None = None,
        remaining_games: dict[str, int] | None = None,
        projections: ProjectionIndex | None = None,
    ) -> str:
        """One prompt line per player, concatenated.

        Args:
            annotations: player_key -> extra text, e.g. "[Top in: PTS]".
            remaining_games: precomputed counts; looked up if omitted.
        """
        return "".join(
            self.build_player_lines(players, matchup_start, matchup_end, annotations, remaining_games).values()
        )

    def build_player_lines(
        self,
        players: list[Player],
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

        remaining_games = remaining_games or {}
        if not remaining_games and matchup_start and matchup_end:
            teams = [p.editorial_team_abbr for p in players]
            remaining_games = self.nba.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        lines: dict[str, str] = {}
        for p in players:
            stats_dict = self.nba.get_player_stats(p.name.full)

            games_left = remaining_games.get(p.editorial_team_abbr.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""

            status = getattr(p, "status", None)
            injury_note = getattr(p, "injury_note", None)
            status_str = ""
            if status:
                status_str = f" [{status}]"
                if injury_note:
                    status_str += f" ({injury_note})"

            il_str = ""
            if hasattr(p, "selected_position") and getattr(p.selected_position, "position", "") in ("IL", "IL+"):
                il_str = " [IN IL SPOT]"

            note = ""
            if annotations and p.player_key in annotations:
                note = f" {annotations[p.player_key]}"

            line = f"- {p.name.full} ({p.display_position}){il_str}{status_str}{games_str}{note}"
            if stats_dict:
                line += f": {self._format_stats(stats_dict)}"
            # Recent form says what a player has been; PROJ says what the
            # matchup period is expected to yield.
            if projections is not None and (projected := projections.lookup(p.name.full)):
                line += f" | PROJ {projected.summary()}"
            lines[p.name.full] = line + "\n"

        return lines
