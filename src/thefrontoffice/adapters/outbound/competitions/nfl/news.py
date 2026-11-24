"""The news behind each football player: ESPN's club feeds, joined to Sleeper (`competitions/news.py`).

Sleeper carries ESPN's id for barely a quarter of active players, so the join
is by name within one club, like every competition's; this says which of
Sleeper's players are a club's to read its feed for.

It also says which of a club's stories are every one of its players' news
(`ClubStory`): a tight end's week turns on who throws to him and who else is
running routes, though the story never names him. Read conservatively, from
the article's own words and the players it names — a story counts only where
it names the change, and never while it is talk of one (a question, a rumor):

- a quarterback change: a club's quarterback named beside a benching, or as
  the one a release or trade moves ('cut QB Daniel Jones'); one who is not its starter
  (Sleeper's depth chart) named beside starting; or a free agent quarterback
  named beside his release — Sleeper may already have moved both, the new
  starter to the top of the depth chart and the old one off the club;
- a trade: trade wording and an offensive player anywhere in the league, who
  has left by the time the story runs, and not only a starting quarterback;
- a play caller: the offensive coordinator or play-calling named beside a
  hiring or firing — a defense's is not the offense's.

A story naming players of more than `ROUNDUP` clubs is the league's, not one club's.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

from thefrontoffice.adapters.outbound.competitions import news
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.news import ClubStory, PlayerNews
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club, on_a_club, players_by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

QB_CHANGE, TRADE, PLAY_CALLER = "QB change", "Trade", "Play caller"
"""The kinds of club story, as the drawer and the prompt label them."""

OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
"""Whose trade changes who gets the ball."""

BENCHED = ("bench", "benched", "benches", "benching", "demoted", "demotes", "replaced", "replaces", "replacing")
RELEASED = ("cut", "cuts", "release", "released", "releases", "releasing", "waive", "waived", "waives")
"""A release of a club's quarterback, as a story puts it: as much a change as a benching."""
QUARTERBACK = ("", "qb ", "quarterback ")
"""What may stand between a verb and the quarterback it moves: 'cut QB Daniel Jones'."""
STARTING = (
    *("to start", "will start", "next start", "first start", "nfl start", "fill in start", "start against", "start vs"),
    *("starts", "starter", "starting", "under center", "take over", "takes over", "taking over"),
    *("turn to", "turns to", "turning to"),
)
"""Starting at quarterback; never a bare 'start', which is as often a club's 3-7 start to the season."""
TRADED = ("trade", "traded", "trades", "acquire", "acquires", "acquired", "dealt")
CALLER = ("offensive coordinator", "play caller", "playcaller", "play calling", "playcalling", "call plays")
CHANGED = (
    *(
        "fire",
        "fired",
        "fires",
        "hire",
        "hires",
        "hired",
        "promoted",
        "promotes",
        "relieved",
        "dismissed",
        "parted ways",
    ),
    *("take over", "takes over", "replaced", "replaces", "stripped", "named"),
)
TALK = (
    *("rumor", "rumors", "could", "would", "might", "should", "interest", "interested", "possible", "potential"),
    *("hopeful", "optimistic", "expects", "expected", "proposing", "proposed", "proposal"),
)
"""Words of a story about what may happen; none of them is a change yet."""

ROUNDUP = 2
"""The most clubs a story's players can come from and it still be a club's own: a trade names two."""


def attach(feeds: dict[str, list[NewsArticle]], players: Mapping[str, PlayerInfo], now: datetime) -> PlayerNews:
    """Each player's articles from the last `news.NEWS_WINDOW`, from his own club's feed, and his club's stories."""
    found = news.attach(feeds, players_by_club(players), now)
    clubs = {pid: espn_club(meta.team) for pid, meta in players.items() if on_a_club(meta)}
    return replace(found, by_club=club_stories(feeds, players, now), club_of=clubs)


def club_stories(
    feeds: dict[str, list[NewsArticle]], players: Mapping[str, PlayerInfo], now: datetime
) -> dict[str, list[ClubStory]]:
    """Each club's stories from the last `news.NEWS_WINDOW`, newest first, by the module's rules."""
    league = _Offense()
    for meta in players.values():
        if on_a_club(meta) and meta.position in OFFENSE:
            league.add(meta)
        elif meta.team == FREE_AGENT and meta.position == "QB":
            league.released.add(normalize_name(meta.name))

    stories: dict[str, list[ClubStory]] = {}
    for club, articles in feeds.items():
        found = [
            ClubStory(kind=kind, article=a) for a in articles if news.recent(a, now) and (kind := league.kind(a, club))
        ]
        if found:
            stories[club] = sorted(found, key=lambda s: s.article.published, reverse=True)
    return stories


@dataclass
class _Offense:
    """Every club's offensive players by normalized name: who could be a story's subject."""

    clubs: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """Each name's clubs, under ESPN's spelling."""
    quarterbacks: dict[str, dict[str, bool]] = field(default_factory=lambda: defaultdict(dict))
    """Each club's quarterbacks, and whether he is its starter."""
    released: set[str] = field(default_factory=set)
    """Quarterbacks on no club: one a club's feed names was most likely its own, let go."""

    def add(self, meta: PlayerInfo) -> None:
        club, key = espn_club(meta.team), normalize_name(meta.name)
        self.clubs[key].add(club)
        if meta.position == "QB":
            self.quarterbacks[club][key] = meta.depth_chart_order == 1

    def kind(self, article: NewsArticle, club: str) -> str | None:
        """Which kind of story the article is for this club, if any."""
        said = f"{article.headline} {article.summary}"
        # The deadline is a date on the calendar, and a question is talk of a change.
        text = f" {normalize_name(said)} ".replace(" trade deadline ", " ")
        named = news.mentioned(article, self.clubs)
        # A roundup of the league names players of every club, and is none of theirs.
        if "?" in said or _says(text, TALK) or len(set().union(*(self.clubs[key] for key in named))) > ROUNDUP:
            return None
        quarterbacks = self.quarterbacks.get(club, {})
        theirs = named & quarterbacks.keys()
        gone = news.mentioned(article, self.released)
        # Only against a listed starter is anyone else a backup: before a depth chart, every quarterback is unlisted.
        backup = any(quarterbacks.values()) and any(not quarterbacks[key] for key in theirs)
        # A release or a trade moves the quarterback only where he is its object; the trade
        # that sends three defenders to Jacksonville mentions Trevor Lawrence too.
        let_go = _moves(text, theirs | gone, (*RELEASED, *TRADED))
        if (theirs and _says(text, BENCHED)) or let_go or (backup and _says(text, STARTING)):
            return QB_CHANGE
        # A starting quarterback is named in every story about his club, a trade of others included.
        if _says(text, TRADED) and any(not self._starts(key) for key in named):
            return TRADE
        if " defensive " not in text and _says(text, CALLER) and _says(text, CHANGED):
            return PLAY_CALLER
        return None

    def _starts(self, key: str) -> bool:
        return any(self.quarterbacks[club].get(key, False) for club in self.clubs[key])


def _moves(text: str, keys: Iterable[str], verbs: Iterable[str]) -> bool:
    """Whether one of the verbs takes one of these players as its object: 'cut qb daniel jones'."""
    return any(f" {verb} {title}{key} " in text for key in keys for verb in verbs for title in QUARTERBACK)


def _says(text: str, words: Iterable[str]) -> bool:
    """Whether the padded, normalized text has any of these as whole words."""
    return any(f" {word} " in text for word in words)
