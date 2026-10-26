"""Where a team sits in a table, said the way a person says it: '5th of 14'."""


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st."""
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def place(rank: int, teams: int) -> str:
    """'5th of 14'."""
    return f"{ordinal(rank)} of {teams}"
