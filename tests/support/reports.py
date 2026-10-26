"""Canned reports, as test data.

Stand-ins for what the model returns, so engine and rendering tests can assert
on a report without one being generated. One per sport, because a basketball
report returned for a football assertion exercises the shape and says nothing
about the sport.

Deliberately not in the package: the application has no use for a fabricated
report, and shipping one invites a code path that returns it.
"""

from thefrontoffice.domain.models import Move, ScoutReport, TradeVerdict

MOCK_NBA_REPORT = ScoutReport(
    situation=(
        "[MOCK] Positioned for a 6-3 win. BLK is within 4 and FG% is a slim lead worth "
        "protecting; PTS is lost by a landslide and not worth chasing."
    ),
    focus=["BLK", "FG%", "REB"],
    moves=[
        Move(
            action="ADD",
            player="Mock Player One",
            position="PF,C",
            team="LAL",
            metric="4 games left",
            rationale="[MOCK] Elite rebounding across four remaining games, and blocks at volume.",
            replaces="Mock Bench Warmer",
            replaces_rationale="[MOCK] Two games left and no category he wins.",
        ),
        Move(
            action="ADD",
            player="Mock Player Two",
            position="C",
            team="BOS",
            metric="3 games left",
            rationale="[MOCK] Efficient interior scoring protects the FG% lead.",
            replaces="Mock Injured Reserve",
            replaces_rationale="[MOCK] Out indefinitely and occupying an active slot.",
        ),
        Move(
            action="ADD",
            player="Mock Player Three",
            position="SG",
            team="GSW",
            metric="4 games left",
            rationale="[MOCK] High-volume shooter to secure the 3PTM margin.",
            replaces="Mock Inconsistent Guard",
            replaces_rationale="[MOCK] Poor recent form, redundant with the current backcourt.",
        ),
    ],
    strategy="[MOCK] Add multi-category bigs to flip BLK without surrendering FG%.",
)


MOCK_NBA_VERDICT = TradeVerdict(
    verdict="ACCEPT",
    verdict_detail="[MOCK] The incoming side is the better rest-of-season value.",
    gains=["REB", "BLK"],
    losses=["AST", "FT%"],
    impact="[MOCK] Net gain in REB and BLK on recent form, roughly neutral scoring, slight FT% dip.",
    schedule="[MOCK] Incoming player has one extra game in each playoff week.",
    risk="[MOCK] Neither incoming player is on a tanking team or carrying a designation.",
    strategy="[MOCK] Accept, then stream a guard to cover the AST dip.",
)


MOCK_NFL_REPORT = ScoutReport(
    situation=(
        "[MOCK] Projected to win by 6. The margin rests on the flex slot, where the "
        "bench currently holds the higher projection."
    ),
    focus=["FLEX", "TE bye", "RB2 injury risk"],
    moves=[
        Move(
            action="START",
            player="Mock Running Back",
            position="RB",
            team="BUF",
            metric="16.7 proj pts, +4.2 over the current starter",
            rationale="[MOCK] Clear volume lead and a bottom-five run defense opposite him.",
            replaces="Mock Bench Back",
            replaces_rationale="[MOCK] Splitting carries and facing the league's best front.",
        ),
        Move(
            action="ADD",
            player="Mock Waiver Receiver",
            position="WR",
            team="NYJ",
            metric="12.4 proj pts",
            rationale="[MOCK] Promoted to the slot with the starter out; target share should spike.",
            replaces="Mock Backup Kicker",
            replaces_rationale="[MOCK] Streaming a kicker is cheaper than rostering two.",
        ),
    ],
    strategy="[MOCK] Fix the flex, then stream the open roster spot for upside.",
)

MOCK_FPL_REPORT = ScoutReport(
    situation=(
        "[MOCK] 412 points, ranked 340,112 overall and 3rd of 12 in the mini-league. "
        "The gameweek turns on the captaincy and one free transfer."
    ),
    focus=["captaincy", "DEF fixtures", "1 free transfer"],
    moves=[
        Move(
            action="CAPTAIN",
            player="Mock Striker",
            position="FWD",
            team="MCI",
            metric="7.4 xPts, fixture difficulty 2",
            rationale="[MOCK] Home to the weakest defense in the division, and on penalties.",
        ),
        Move(
            action="TRANSFER",
            player="Mock Wing Back",
            position="DEF",
            team="LIV",
            metric="£5.8m, +1.9 xPts",
            rationale="[MOCK] Three consecutive difficulty-2 fixtures and attacking returns.",
            replaces="Mock Benched Defender",
            replaces_rationale="[MOCK] Lost his place and faces two difficulty-5 fixtures.",
        ),
        Move(
            action="START",
            player="Mock Midfielder",
            position="MID",
            team="ARS",
            metric="5.1 xPts, +2.3 over the current starter",
            rationale="[MOCK] Back from suspension into a settled front three.",
            replaces="Mock Rotation Risk",
            replaces_rationale="[MOCK] Started one of the last four with a cup tie midweek.",
        ),
    ],
    strategy="[MOCK] Take the free transfer in defense, captain the premium, no hit.",
)

MOCK_REPORTS: dict[str, ScoutReport] = {
    "nba": MOCK_NBA_REPORT,
    "nfl": MOCK_NFL_REPORT,
    "fpl": MOCK_FPL_REPORT,
}


def report_for(sport: str) -> ScoutReport:
    """The canned report for a sport, falling back to the basketball one."""
    return MOCK_REPORTS.get(sport, MOCK_NBA_REPORT)
