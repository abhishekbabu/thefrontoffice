"""The news behind each football player: ESPN's club feeds, joined to Sleeper (`competitions/news.py`).

Sleeper carries ESPN's id for barely a quarter of active players, so the join
is by name within one club, like every competition's; this says which of
Sleeper's players are a club's to read its feed for.

It also says which of a club's stories are every one of its players' news
(`ClubStory`): a tight end's week turns on who throws to him and who else is
running routes, though the story never names him. Read conservatively, from
the article's own words and the players it names — a story counts only where
it names the change, and never while it is talk of one (a question, a rumor):

- a quarterback change: a club's quarterback named beside a benching; one a
  release or trade moves ('cut QB Daniel Jones', 'Kirk Cousins traded to
  Minnesota', 'Vikings acquire Kirk Cousins') — a free agent in the release,
  since Sleeper may already have let him go; one named or elevated to starter
  ('Colts name Anthony Richardson the starter'); its starter out long
  (`stories.out_long`: the season, a month, three weeks or more); or, more weakly, its starter
  replaced, or a backup (Sleeper's depth chart) said to start (`stories.near`) — weaker because an
  injury in a game reads the same, so neither counts once that starter is listed first again and
  fit, nor in a game's recap (`stories.recap`), which reports last week's lineup;
- a trade: an offensive player anywhere in the league as the trade's object,
  who may have left by the time the story runs, and not only a starting quarterback;
- a play caller: the offensive coordinator or play-calling named beside a
  hiring or firing — a defense's is not the offense's.

How a story is read — talk, roundups, a move's object — is `competitions/stories.py`'s. Where no
story says so, a change of the depth chart's starter between days is one too (`nfl/starters.py`).
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

from thefrontoffice.adapters.outbound.competitions import news, stories
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.news import ClubStory, PlayerNews
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club, on_a_club, players_by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo
from thefrontoffice.adapters.outbound.competitions.nfl.rules import listed
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

QB_CHANGE, TRADE, PLAY_CALLER = "QB change", "Trade", "Play caller"
"""The kinds of club story, as the drawer and the prompt label them."""

OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
"""Whose trade changes who gets the ball."""

BENCHED = ("bench", "benched", "benches", "benching", "demoted", "demotes")
REPLACED = ("replaced", "replaces", "replacing", "relieved by", "in relief")
"""A quarterback replaced, as an injury in a game puts it as often as a benching: it holds only while he is out."""
QUARTERBACK = ("", "qb ", "quarterback ")
"""What may stand between a verb and the quarterback it moves: 'cut QB Daniel Jones'."""
STARTING = (
    *("to start", "will start", "next start", "first start", "nfl start", "fill in start", "start against", "start vs"),
    *("starts", "starter", "starting", "under center", "take over", "takes over", "taking over"),
    *("turn to", "turns to", "turning to"),
)
"""Starting at quarterback, said of a backup; never a bare 'start', which is as often a club's 3-7 start."""
NAMED = ("named", "names", "name", "elevated", "elevates", "elevate", "promoted", "promotes", "promote")
"""Making a quarterback the starter, as a verb taking him as its object: 'Colts name Anthony Richardson'."""
AS_STARTER = (
    *("the starter", "starter", "the starting quarterback", "starting quarterback", "starting qb", "to start"),
    *("will start", "under center", "takes over as starter", "take over as starter", "takes over as the starter"),
)
"""What he is made, said outright: the change holds whatever the depth chart already says."""
CALLER = ("offensive coordinator", "play caller", "playcaller", "play calling", "playcalling", "call plays")


def attach(
    feeds: dict[str, list[NewsArticle]],
    players: Mapping[str, PlayerInfo],
    now: datetime,
    depth: Mapping[str, ClubStory],
) -> PlayerNews:
    """Each player's articles from the last `news.NEWS_WINDOW`, from his own club's feed, and his club's stories.

    `depth` is each club's change of starter read off the depth chart (`nfl/starters.py`), kept
    only where no story in the club's feed already reports a quarterback change.
    """
    found = news.attach(feeds, players_by_club(players), now)
    clubs = {pid: espn_club(meta.team) for pid, meta in players.items() if on_a_club(meta)}
    told = club_stories(feeds, players, now)
    for club, story in depth.items():
        if not any(s.kind == QB_CHANGE for s in told.get(club, [])):
            told[club] = sorted([*told.get(club, []), story], key=lambda s: s.article.published, reverse=True)
    return replace(found, by_club=told, club_of=clubs)


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
    fit: set[str] = field(default_factory=set)
    """Quarterbacks carrying no injury designation."""
    released: set[str] = field(default_factory=set)
    """Quarterbacks on no club: one a club's feed names was most likely its own, let go."""

    def add(self, meta: PlayerInfo) -> None:
        club, key = espn_club(meta.team), normalize_name(meta.name)
        self.clubs[key].add(club)
        if meta.position == "QB":
            self.quarterbacks[club][key] = meta.depth_chart_order == 1
            if not listed(meta.injury_status):
                self.fit.add(key)

    def kind(self, article: NewsArticle, club: str) -> str | None:
        """Which kind of story the article is for this club, if any."""
        text = stories.text_of(article)
        named = news.mentioned(article, self.clubs)
        if stories.talk(article, text) or stories.roundup(c for key in named for c in self.clubs[key]):
            return None
        if self._quarterback(article, text, named, club):
            return QB_CHANGE
        # A trade's own player is its object: 'trade Josh Downs', 'Josh Downs traded to Kansas City'.
        # A starting quarterback is named in every story about his club, a trade of others included.
        if stories.moved(text, {key for key in named if not self._starts(key)}, stories.TRADED, stories.TRADED_TO):
            return TRADE
        if " defensive " not in text and stories.says(text, CALLER) and stories.says(text, stories.HIRED_OR_FIRED):
            return PLAY_CALLER
        return None

    def _quarterback(self, article: NewsArticle, text: str, named: set[str], club: str) -> bool:
        """Whether the story changes who plays quarterback for this club."""
        quarterbacks = self.quarterbacks.get(club, {})
        theirs = named & quarterbacks.keys()
        starters = {key for key in theirs if quarterbacks[key]}
        # Only against a listed starter is anyone else a backup: before a depth chart, every quarterback is unlisted.
        backup = any(quarterbacks.values()) and theirs != starters
        # A move counts where a quarterback is its object; the trade that sends three
        # defenders to Jacksonville mentions Trevor Lawrence too. A release may name one
        # Sleeper already has on no club. One traded away whom Sleeper has already put on
        # his new club is no longer this club's to name: the depth chart says it instead.
        moved = theirs | self.released
        changed = (
            stories.moved(text, moved, stories.RELEASED, stories.RELEASED_BY, QUARTERBACK)
            or stories.moved(text, theirs, stories.TRADED, stories.TRADED_TO, QUARTERBACK)
            or bool(theirs and stories.says(text, BENCHED))
            or (stories.moved(text, theirs, NAMED, (), QUARTERBACK) and stories.says(text, AS_STARTER))
            or stories.moved(text, theirs, (), ("takes over as starter", "named the starter", "named starter"))
            or bool(starters and stories.out_long(article, text))
        )
        if changed:
            return True
        # A recap reports who played last week; the box scores say that, and the slump reads them.
        if stories.recap(article):
            return False
        # Weaker: a starter replaced in a game, or a backup said to start — his start, not another's. Neither
        # holds once the starter it names is listed first again and fit: Geno Smith hurt and replaced on a
        # Sunday, back under center the next.
        replaced = bool(theirs and stories.says(text, REPLACED))
        fills_in = backup and stories.near(text, theirs - starters, STARTING)
        back = any(key in self.fit for key in starters)
        return (replaced or fills_in) and not back

    def _starts(self, key: str) -> bool:
        return any(self.quarterbacks[club].get(key, False) for club in self.clubs[key])
