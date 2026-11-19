"""Yahoo's transport, standing in: the SDK context both the login and the league reader ask through, and the XML it answers in."""

import threading


class FakeContext:
    """Stands in for yahoofantasy's Context, answering in Yahoo's own XML, which the real parser reads.

    `answers` maps the start of a query to its response; any other query gets
    `response`.
    """

    def __init__(
        self,
        response: str = "<fantasy_content/>",
        error: Exception | None = None,
        answers: dict[str, str] | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.answers = answers or {}
        self.fail_first: list[Exception] = []
        """Raised one per request, before any answer."""
        self.requests: list[tuple[str, str | bool]] = []
        self.barrier: threading.Barrier | None = None
        """Held by each request until all its parties arrive, so serial requests never finish."""

    def make_request(self, url: str, league: str | bool = False) -> str:
        self.requests.append((url, league))
        self._fail()
        if self.barrier:
            self.barrier.wait()
        return self._answer(url)

    def _fail(self) -> None:
        if self.fail_first:
            raise self.fail_first.pop(0)
        if self.error:
            raise self.error

    def _answer(self, query: str) -> str:
        return next((xml for prefix, xml in self.answers.items() if query.startswith(prefix)), self.response)

    @property
    def queries(self) -> list[str]:
        return [query for query, _ in self.requests]


# ── Yahoo's XML ─────────────────────────────────────────────────────────


def players_xml(*names: str) -> str:
    """A league's players response, as Yahoo serves it."""
    rows = "".join(
        f"<player><player_key>466.p.{i}</player_key><name><full>{name}</full></name><display_position>PF</display_position>"
        f"<editorial_team_abbr>LAL</editorial_team_abbr></player>"
        for i, name in enumerate(names)
    )
    return (
        '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
        f'<league><players count="{len(names)}">{rows}</players></league></fantasy_content>'
    )


def teams_xml(*teams: str) -> str:
    return f"<fantasy_content><league><teams>{''.join(teams)}</teams></league></fantasy_content>"


def league_standings_xml(*teams: str) -> str:
    """A league's standings response: its teams under `standings`, each carrying `team_standings`."""
    return f"<fantasy_content><league><standings><teams>{''.join(teams)}</teams></standings></league></fantasy_content>"


def team_xml(key: str, name: str, *, mine: bool = False, adds: int = 0, standings: str = "", extra: str = "") -> str:
    owned = "<is_owned_by_current_login>1</is_owned_by_current_login>" if mine else ""
    return (
        f"<team><team_key>{key}</team_key><name>{name}</name>{owned}"
        f"<roster_adds><value>{adds}</value></roster_adds>{extra}{standings}</team>"
    )


def standings_xml(rank: int, wins: int, losses: int, ties: int, points: str, extra: str = "") -> str:
    return (
        f"<team_standings><rank>{rank}</rank><points_for>{points}</points_for>{extra}<outcome_totals>"
        f"<wins>{wins}</wins><losses>{losses}</losses><ties>{ties}</ties></outcome_totals></team_standings>"
    )


def roster_xml(*players: str) -> str:
    return f"<fantasy_content><team><roster><players>{''.join(players)}</players></roster></team></fantasy_content>"


def rostered_xml(name: str, slot: str, status: str = "", note: str = "") -> str:
    return (
        f"<player><player_key>466.p.{len(name)}</player_key><name><full>{name}</full></name>"
        f"<display_position>PG,SG</display_position><editorial_team_abbr>BOS</editorial_team_abbr>"
        f"<status>{status}</status><injury_note>{note}</injury_note>"
        f"<selected_position><position>{slot}</position></selected_position></player>"
    )


def _side_xml(key: str, name: str, points: str, blocks: str, projected: str = "") -> str:
    forecast = f"<team_projected_points><total>{projected}</total></team_projected_points>" if projected else ""
    return (
        f"<team><team_key>{key}</team_key><name>{name}</name><team_points><total>{points}</total></team_points>"
        f"{forecast}<team_stats><stats><stat><stat_id>18</stat_id><value>{blocks}</value></stat></stats></team_stats></team>"
    )


def scoreboard_xml(start: str = "2026-02-09", end: str = "2026-02-15", projected: tuple[str, str] = ("", "")) -> str:
    mine, theirs = (
        _side_xml("t1", "Mine", "50", "12", projected[0]),
        _side_xml("t2", "Theirs", "60", "17", projected[1]),
    )
    matchup = (
        f"<matchup><week_start>{start}</week_start><week_end>{end}</week_end><teams>{mine}{theirs}</teams></matchup>"
    )
    return (
        f"<fantasy_content><league><scoreboard><matchups>{matchup}</matchups></scoreboard></league></fantasy_content>"
    )


def leagues_xml(*leagues: str) -> str:
    """A login's league list for one game, as Yahoo serves it."""
    return f"<fantasy_content><users><user><games><game><leagues>{''.join(leagues)}</leagues></game></games></user></users></fantasy_content>"


def league_xml(key: str, name: str, *, current: int | None = None, start: int = 1, end: int = 20) -> str:
    weeks = f"<current_week>{current}</current_week><start_week>{start}</start_week><end_week>{end}</end_week>"
    return f"<league><league_key>{key}</league_key><name>{name}</name>{weeks if current else ''}</league>"
