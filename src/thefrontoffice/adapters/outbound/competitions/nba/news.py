"""The news behind each basketball player: ESPN's club feeds, joined to Yahoo by name (`competitions/news.py`),
and each club's stories that change every one of its players' work (`competitions/stories.py`).

Usage moves when the club changes around a player, though the story never names
him. Read as football's are, conservatively, from the story's own words and the
players it names — Sleeper's regulars, the players whose minutes a change moves
(`teammates.Teammates.regulars`):

- a trade: a regular of any club as the trade's object, in this club's feed —
  'Hawks acquire Trae Young', 'Trae Young traded to Atlanta';
- a coach: the head coach hired, fired or replaced; an assistant's is not the rotation's;
- out long-term: one of this club's regulars named beside a season-ending,
  indefinite or month-long absence (`stories.out_long`) — his shots and minutes are somebody else's for a while.

A player's own news can say his role may not last though nothing has moved yet: named in trade talk
(`stories.trade_talk`), which a keeper is read against (`talked`).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from thefrontoffice.adapters.outbound.competitions import news, stories
from thefrontoffice.adapters.outbound.competitions.injuries import by_club
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Regular
from thefrontoffice.adapters.outbound.competitions.news import ClubStory, PlayerNews
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

TRADE, COACH, OUT_LONG = "Trade", "Coach", "Out long-term"
"""The kinds of club story, as the drawer and the prompt label them."""

TRADE_TALK = "Trade talk"
"""What a player named in trade talk is flagged as, wherever the plan shows him."""

HEAD_COACH = ("head coach", "interim coach", "interim head coach")
COACH_MOVES = (
    *("fire coach", "fires coach", "fired coach", "hire coach", "hires coach", "hired coach"),
    *("coach fired", "coach dismissed", "coach is out", "names coach", "named coach", "part ways with coach"),
)
"""The head coach's job changing hands, said without 'head': 'Bucks fire coach Doc Rivers'."""
NOT_THE_HEAD = (" assistant ", " associate head ", " g league ")


def attach(
    feeds: dict[str, list[NewsArticle]], players: Sequence[Player], regulars: Sequence[Regular], now: datetime
) -> PlayerNews:
    """Each of `players`' articles from his own club's feed, by Yahoo's key, and each club's stories."""
    clubs = {p.player_key: espn_club(p.team) for p in players if p.team}
    found = news.attach(feeds, by_club((clubs[p.player_key], p.name, p.player_key) for p in players if p.team), now)
    return replace(found, by_club=club_stories(feeds, regulars, now), club_of=clubs)


def club_stories(
    feeds: dict[str, list[NewsArticle]], regulars: Sequence[Regular], now: datetime
) -> dict[str, list[ClubStory]]:
    """Each club's stories from the last `news.NEWS_WINDOW`, newest first, by the module's rules."""
    clubs: dict[str, set[str]] = defaultdict(set)
    for regular in regulars:
        clubs[normalize_name(regular.name)].add(espn_club(regular.team))
    found: dict[str, list[ClubStory]] = {}
    for club, articles in feeds.items():
        told = [ClubStory(kind=k, article=a) for a in articles if news.recent(a, now) and (k := _kind(a, club, clubs))]
        if told:
            found[club] = sorted(told, key=lambda s: s.article.published, reverse=True)
    return found


def _kind(article: NewsArticle, club: str, clubs: Mapping[str, set[str]]) -> str | None:
    """Which kind of story the article is for this club, if any."""
    text = stories.text_of(article)
    named = news.mentioned(article, clubs)
    if stories.talk(article, text) or stories.roundup(c for key in named for c in clubs[key]):
        return None
    if stories.moved(text, named, stories.TRADED, stories.TRADED_TO):
        return TRADE
    theirs = {key for key in named if club in clubs[key]}
    if theirs and stories.out_long(article, text):
        return OUT_LONG
    changed = stories.says(text, COACH_MOVES) or (
        stories.says(text, HEAD_COACH) and stories.says(text, stories.HIRED_OR_FIRED)
    )
    if changed and not any(word in text for word in NOT_THE_HEAD):
        return COACH
    return None


def lines_with_team_news(lines: Mapping[str, str], players: Iterable[Player], found: PlayerNews) -> dict[str, str]:
    """Each player's prompt line, by name, with its pointer to his club's stories (`news.team_reference`)."""
    keys = {p.name: p.player_key for p in players}
    return {
        name: line + (news.team_reference(found, keys[name]) if name in keys else "") for name, line in lines.items()
    }


def block(found: PlayerNews, players: Iterable[Player]) -> str:
    """Each club's stories once, for the clubs of `players`, set off from what it follows; empty where none has any."""
    told = news.team_block(found, (p.player_key for p in players))
    return f"\n{told}" if told else ""


def talked(
    found: PlayerNews, players: Iterable[Player], own: Mapping[str, Sequence[NewsArticle]] | None = None
) -> dict[str, str]:
    """Each of `players` his news puts in trade talk (`stories.trade_talk`), by Yahoo's key: the newest such story,
    'Fri 21 Nov: Bucks open to trading Myles Turner'. Read from his club's feed, and from `own` — his ESPN page's
    stories, their text read — where given. In a story's text he may be named by surname once it names him in
    full: 'Turner' four paragraphs after 'Myles Turner'."""
    told: dict[str, str] = {}
    for player in players:
        full = normalize_name(player.name)
        read = [*found.by_player.get(player.player_key, []), *(own or {}).get(player.player_key, [])]
        story = next((a for a in sorted(read, key=lambda a: a.published, reverse=True) if _talks(a, full)), None)
        if story is not None:
            told[player.player_key] = f"{news.dated(story)}: {story.headline}"
    return told


def _talks(article: NewsArticle, full: str) -> bool:
    """Whether the story talks of trading him, named in full, or by surname in a story that names him in full."""
    named = f" {full} " in f" {normalize_name(f'{article.headline} {article.summary} {article.body}')} "
    keys = [full, *([full.split()[-1]] if named and " " in full else [])]
    return stories.trade_talk(article, keys)
