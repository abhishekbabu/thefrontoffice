"""Reading a club's feed for the stories that change every one of its players' work, whoever they name.

A trade, a release, a coaching change or a star out for the season reaches a
club's whole roster though the story names two of its players. Each
competition says which players a story has to name and how (`nfl/news.py`,
`nba/news.py`); the vocabulary, and how a story is read for it, is shared:

- a story is read as one padded, normalized text (`text_of`), so a phrase is
  matched as whole words within a clause and 'Richardson Sr.' reads as Sleeper's name for him;
- a move counts only where the player is its object — 'cut QB Daniel Jones',
  'Daniel Jones traded to Minnesota', 'deal sends Daniel Jones' — never a
  player merely mentioned beside the verb (`moved`);
- talk of a change is not one: a question, a rumor, a hope (`talk`);
- a roundup naming players of more than `ROUNDUP` clubs is the league's, not one club's;
- a player in trade talk is named beside it, in the story's own words (`trade_talk`): no trade yet, but a role
  that may not last.
"""

import re
from collections.abc import Iterable

from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

TALK = (
    *("rumor", "rumors", "could", "would", "might", "should", "interest", "interested", "possible", "potential"),
    *("hopeful", "optimistic", "expects", "expected", "proposing", "proposed", "proposal"),
)
"""Words of a story about what may happen; none of them is a change yet."""

ROUNDUP = 2
"""The most clubs a story's players can come from and it still be a club's own: a trade names two."""

RELEASED = (
    *("cut", "cuts", "release", "released", "releases", "releasing", "waive", "waived", "waives"),
    *("parts ways with", "parted ways with", "part ways with", "moves on from", "moving on from", "move on from"),
)
"""Letting a player go, as a verb taking him as its object."""

RELEASED_BY = ("released", "waived", "was released", "was waived", "is released", "is waived", "cut by")
"""The same, with the player first: 'Daniel Jones released by Colts'."""

TRADED = (
    *("trade", "trades", "traded", "trade for", "trades for", "traded for", "acquire", "acquires", "acquired"),
    *("acquiring", "dealt", "deal for", "deal sends", "deal sending", "trade sends", "trade sending"),
    *("land", "lands", "landed"),
)
"""Trading for or away a player, as a verb taking him as its object: 'acquire Kirk Cousins'."""

TRADED_TO = ("traded to", "dealt to", "is traded", "was traded", "acquired by", "heads to", "shipped to", "sent to")
"""The same, with the player first: 'Kirk Cousins traded to Minnesota'."""

OUT_LONG = (
    *("out for the season", "out for season", "out for the year", "season ending", "season over", "miss the season"),
    *("miss the rest of the season", "out indefinitely", "ruled out indefinitely", "out the rest of the season"),
    *("a month", "months", "step away", "stepping away"),
)
"""A player out long enough that his work is somebody else's for what is left of the season, or a month of it."""

LONG_WEEKS = 3
"""Weeks out, at the most a story gives, from which an absence is long: a third of a basketball month's games."""

WEEKS = re.compile(
    r"\b(?<!past )(?<!through )(?<!last )(?<!first )(?<!over )"
    r"(\d+|two|three|four|five|six|seven|eight|nine|ten|twelve)(?:\s*(?:-|\u2013|to)\s*(\d+|\w+))?\s+weeks?\b",
    re.I,
)
"""A span of weeks — not the past three, nor the first ten: those are the season so far."""

ABSENT = ("out", "miss", "misses", "missing", "sidelined", "reevaluated", "re evaluated", "surgery", "shut down")
"""That a span of weeks is somebody's absence."""
NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
NUMBERS["twelve"] = 12

HIRED_OR_FIRED = (
    *("fire", "fired", "fires", "hire", "hires", "hired", "promoted", "promotes", "relieved", "dismissed"),
    *("parted ways", "parts ways", "take over", "takes over", "replaced", "replaces", "stripped", "named", "interim"),
)
"""A coaching job changing hands."""


CLAUSE = re.compile(r"[,;:!?()\"\u2014\u2013]|(?<=[a-z]{3})\.\s")
"""Where one clause ends and the next begins: punctuation, and a sentence's full stop — not an initial's or 'Sr.'."""


def text_of(article: NewsArticle) -> str:
    """The headline and summary as one padded, normalized text, its clauses kept apart by '|'.

    Kept apart so 'adds three linebackers in trades, Josh Downs says' does not read as
    'trades Josh Downs'. The trade deadline is a date, not a trade.
    """
    clauses = CLAUSE.split(f"{article.headline}. {article.summary}")
    return f" {' | '.join(normalize_name(c) for c in clauses)} ".replace(" trade deadline ", " ")


def talk(article: NewsArticle, text: str) -> bool:
    """Whether the story is about what may happen rather than what has: a question, a rumor, a hope."""
    return "?" in f"{article.headline} {article.summary}" or says(text, TALK)


def says(text: str, words: Iterable[str]) -> bool:
    """Whether the padded, normalized text has any of these as whole words."""
    return any(f" {word} " in text for word in words)


def moved(
    text: str, keys: Iterable[str], verbs: Iterable[str], after: Iterable[str] = (), titles: Iterable[str] = ("",)
) -> bool:
    """Whether one of the players is the object of one of the verbs, or the subject of one of the `after` phrases.

    `titles` are what may stand between a verb and its player: 'cut QB Daniel Jones'.
    """
    verbs, after, titles = tuple(verbs), tuple(after), tuple(titles)
    return any(
        any(f" {verb} {title}{key} " in text for verb in verbs for title in titles)
        or any(f" {key} {phrase} " in text for phrase in after)
        for key in keys
    )


def out_long(article: NewsArticle, text: str) -> bool:
    """Whether the story puts somebody out for long: the season, indefinitely, a month, or `LONG_WEEKS` or more
    at the most it gives ('8-10 weeks', 'two to four weeks')."""
    weeks = [
        NUMBERS.get(n.lower()) if not n.isdigit() else int(n)
        for match in WEEKS.finditer(f"{article.headline} {article.summary}")
        for n in match.groups()
        if n
    ]
    long = says(text, ABSENT) and max((w for w in weeks if w is not None), default=0) >= LONG_WEEKS
    return says(text, OUT_LONG) or long


NEAR = 4
"""The most words between a player and what a story says of him, within one clause: 'turn to 40-year-old Josh
Johnson' is three; a start in the next sentence, or another player's, is not his."""


def near(text: str, keys: Iterable[str], words: Iterable[str], span: int = NEAR) -> bool:
    """Whether one of the phrases stands within `span` words of one of the players, in the same clause."""
    words = tuple(words)
    for clause in text.split("|"):
        tokens = clause.split()
        spans = [_spans(tokens, word) for word in words]
        said = [found for each in spans for found in each]
        for key in keys:
            for start, end in _spans(tokens, key):
                if any(s - end <= span and start - e <= span for s, e in said):
                    return True
    return False


def _spans(tokens: list[str], phrase: str) -> list[tuple[int, int]]:
    """Where the phrase stands among the tokens, as (first, last) indices."""
    words = phrase.split()
    n = len(words)
    return [(i, i + n - 1) for i in range(len(tokens) - n + 1) if tokens[i : i + n] == words] if n else []


SCORE = re.compile(r"\b\d{1,3}-\d{1,3}\b")
RECAP_VERBS = (
    *("beat", "beats", "top", "tops", "rout", "routs", "edge", "edges", "defeat", "defeats", "down", "downs"),
    *("outlast", "outlasts", "rally", "rallies", "hold off", "holds off", "win", "wins", "fall", "falls", "lose"),
    *("loses", "stun", "stuns", "blank", "blanks", "survive", "survives", "snap", "snaps", "cruise", "cruises"),
    *("roll", "rolls", "victory", "loss", "past", "over"),
)
"""How a game's result is put in a recap's headline: 'Seahawks beat Raiders 21-13'."""


def recap(article: NewsArticle) -> bool:
    """Whether the story is a game's recap: a score and a result in its headline. Who played in it is the box
    score's to say; a recap reports last week's lineup, not a change to this week's."""
    headline = article.headline
    return bool(SCORE.search(headline)) and says(f" {normalize_name(headline)} ", RECAP_VERBS)


def roundup(clubs: Iterable[str]) -> bool:
    """Whether the clubs a story's players come from make it the league's story rather than one club's."""
    return len(set(clubs)) > ROUNDUP


TRADE_TALK = (
    *("trade candidate", "trade candidates", "trade target", "trade targets", "trade block", "on the block"),
    *("trade market", "trade talks", "trade talk", "trade rumors", "trade buzz", "trade interest", "trade request"),
    *("requested a trade", "requests a trade", "request a trade", "requested trade", "requests trade"),
    *("wants a trade", "wants trade", "wants out", "shopping", "shopped", "available in trades", "available via trade"),
)
"""Words of a player's possible move, said of him: a trade not yet made."""


def trade_talk(article: NewsArticle, keys: Iterable[str], others: Iterable[str] = ()) -> bool:
    """Whether the story puts one of the players in trade talk: named within `NEAR` words of it (`TRADE_TALK`), or of a
    trade where the story is talk of one (`talk`) — never a trade made, which is the club's story. Its headline and
    summary are read as one, and each sentence of its text, where it was read, on its own: the player has to be
    named in the sentence that talks of trading him.

    Or referred back to there (`REFERS`: 'he', 'the center'), in a story about him — its headline, summary or first
    sentence names him — straight after a sentence that names him, and only where it names nobody of `others`, the
    other players' names: 'He could be traded, he said of Giannis' is not his.
    """
    keys = tuple(keys)
    if _talked(article, keys):
        return True
    lines = sentences(article.body)
    about = _names(f"{article.headline} {article.summary} {lines[0] if lines else ''}", keys)
    strangers = tuple(others)
    after = False
    for line in lines:
        sentence = NewsArticle(article_id="", published=article.published, headline=line)
        if _talked(sentence, keys):
            return True
        if about and after and not _names(line, strangers) and not _someone(line, keys) and _talked(sentence, REFERS):
            return True
        after = _names(line, keys)
    return False


REFERS = (
    *("he", "him", "his", "the center", "the big man", "the forward", "the guard", "the wing", "the veteran"),
    *("the rookie", "the star", "the point guard", "the shooting guard", "the power forward", "the small forward"),
)
"""How a story refers back to the player it just named: a pronoun, or his position."""


PROPER = re.compile(r"\b[A-Z][a-z'.]+(?:\s+[A-Z][a-z'.]+)+")
"""A run of capitalized words: somebody's name, or a club's."""


def _someone(text: str, keys: Iterable[str]) -> bool:
    """Whether the sentence names somebody in full who is not one of the players — a coach, another player — a
    sentence-opening 'The' left aside, so 'The Bucks' names a club, not a person."""
    found = (normalize_name(m.group().removeprefix("The ")) for m in PROPER.finditer(text))
    return any(name and " " in name and name not in keys for name in found)


def _names(text: str, keys: Iterable[str]) -> bool:
    """Whether the text names one of these normalized names as whole words."""
    padded = f" {normalize_name(text)} "
    return any(key and f" {key} " in padded for key in keys)


SENTENCE = re.compile(r"(?<=[a-z0-9\"')]{2}[.!?])\s+(?=[A-Z\"'])")
"""Where a story's sentence ends: a full stop after a word, not after an initial."""


def sentences(text: str) -> list[str]:
    """A story's text, a sentence at a time."""
    return [s.strip() for s in SENTENCE.split(text) if s.strip()] if text else []


def _talked(article: NewsArticle, keys: tuple[str, ...]) -> bool:
    text = text_of(article)
    if moved(text, keys, TRADED, TRADED_TO) and not talk(article, text):
        return False
    return near(text, keys, TRADE_TALK) or (talk(article, text) and near(text, keys, TRADED))
