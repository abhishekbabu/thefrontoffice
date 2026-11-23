"""Tests for the shape of the package: which layer may know what.

The rules are in AGENTS.md; these hold the code to them, because an import
that points the wrong way compiles and runs, and is only noticed when the
thing it couples has to change. Read from the source rather than imported,
so a check costs nothing and a violation names the line.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "thefrontoffice"

VENDORS = ("Sleeper", "ESPN", "FPL", "Yahoo", "Gemini", "Groq", "OpenRouter")
"""Platforms and model vendors the core must never name: it describes what it needs, not who supplies it."""

CLIENTS = {"SleeperClient", "ESPNClient", "FPLClient", "YahooClient", "YahooAuth"}
"""Concrete platform clients, which only the composition root builds."""


SCRIPTS = PACKAGE.parent.parent / "scripts"


def _modules(under: str, root: Path = PACKAGE) -> list[Path]:
    return sorted(p for p in (root / under).rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> list[tuple[int, str]]:
    """Every module a file imports from the package, with its line.

    `from thefrontoffice import bootstrap` imports `thefrontoffice.bootstrap`,
    so a name imported from the package root counts as the module it is.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == "thefrontoffice":
            found += [(node.lineno, f"thefrontoffice.{a.name}") for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("thefrontoffice."):
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names if a.name.startswith("thefrontoffice")]
    return found


def _violations(under: str, allowed: tuple[str, ...], root: Path = PACKAGE) -> list[str]:
    """Every import under `under` of a module outside `allowed`, as `path:line imports module`."""
    return [
        f"{path.relative_to(root)}:{line} imports {module}"
        for path in _modules(under, root)
        for line, module in _imports(path)
        if not module.startswith(allowed)
    ]


def test_the_domain_imports_nothing_but_itself() -> None:
    assert _violations("domain", ("thefrontoffice.domain",)) == []


def test_the_application_imports_only_the_domain() -> None:
    assert _violations("application", ("thefrontoffice.domain", "thefrontoffice.application")) == []


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_the_core_names_no_vendor(layer: str) -> None:
    """A class in the core named for a platform is a port shaped like one adapter."""
    named = [
        f"{path.relative_to(PACKAGE)}:{node.lineno} {node.name}"
        for path in _modules(layer)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef) and any(vendor in node.name for vendor in VENDORS)
    ]
    assert named == []


INBOUND = (
    "thefrontoffice.bootstrap",
    "thefrontoffice.wiring",
    "thefrontoffice.domain",
    "thefrontoffice.application",
    "thefrontoffice.config",
    "thefrontoffice.adapters.inbound",
)
"""What an entry point may read: the wiring, the core, configuration, and the inbound adapters."""


def test_inbound_adapters_reach_outbound_ones_only_through_bootstrap() -> None:
    """A route that imports a client is a route that only works with that client.

    Everything an entry point needs arrives in the wiring bootstrap builds;
    besides it, an inbound adapter reads only the core, its own package, and
    configuration.
    """
    assert _violations("adapters/inbound", INBOUND) == []


def test_scripts_are_entry_points_like_any_other() -> None:
    """A script reaching into a competition's internals is a script that only works with that competition."""
    assert _violations(".", INBOUND, root=SCRIPTS) == []


def test_only_the_composition_root_builds_a_platform_client() -> None:
    """Everything else is handed one, so a test can hand it a fake and nothing reaches the network by default."""
    built = [
        f"{path.relative_to(PACKAGE)}:{node.lineno} {node.func.id}()"
        for path in _modules(".")
        if path.name != "bootstrap.py" and "platforms" not in path.parts
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CLIENTS
    ]
    assert built == []


def test_only_the_yahoo_platform_reads_the_yahoo_sdk() -> None:
    """yahoofantasy sets its attributes at runtime and is typed as Any, so it stays behind the client.

    Everything beyond `platforms/yahoo/` reads the client's own types; the
    composition root alone may hand the SDK's context to it.
    """
    reached = [
        f"{path.relative_to(PACKAGE)}:{node.lineno}"
        for path in _modules(".")
        if path.name != "bootstrap.py" and not path.is_relative_to(PACKAGE / "adapters/outbound/platforms/yahoo")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("yahoofantasy"))
        or (isinstance(node, ast.Import) and any(a.name.startswith("yahoofantasy") for a in node.names))
    ]
    assert reached == []


COMPETITIONS = "adapters/outbound/competitions"
COMPETITION_NAMES = sorted(p.name for p in (PACKAGE / COMPETITIONS).iterdir() if (p / "__init__.py").exists())

LEAGUE_PLATFORMS = {"nba": "yahoo", "nfl": "sleeper"}
"""Each competition's league platform, which only its provider module may name.

The Premier League is absent on purpose: FPL is not a platform hosting the
league but the game itself, so its rules are FPL's and read its types.
"""


def _reaching(under: str, forbidden: tuple[str, ...]) -> list[str]:
    """Every import under `under` of a module inside `forbidden`, as `path:line imports module`."""
    return [
        f"{path.relative_to(PACKAGE)}:{line} imports {module}"
        for path in _modules(under)
        for line, module in _imports(path)
        if module.startswith(forbidden)
    ]


def test_platforms_never_import_a_competition() -> None:
    """A platform serves every competition on it; one that knew a competition's rules would serve only that one."""
    assert _reaching("adapters/outbound/platforms", ("thefrontoffice.adapters.outbound.competitions",)) == []


@pytest.mark.parametrize("competition", COMPETITION_NAMES)
def test_a_competition_never_imports_another(competition: str) -> None:
    """What two competitions share lives beside them in `competitions/`, not inside either."""
    others = tuple(
        f"thefrontoffice.adapters.outbound.competitions.{other}" for other in COMPETITION_NAMES if other != competition
    )
    assert _reaching(f"{COMPETITIONS}/{competition}", others) == []


def test_outbound_adapters_never_reach_an_entry_point_or_the_composition_root() -> None:
    """An outbound adapter is handed what it needs; reaching back up for it would make a cycle."""
    reaching_up = ("thefrontoffice.adapters.inbound", "thefrontoffice.bootstrap", "thefrontoffice.wiring")
    assert _reaching("adapters/outbound", reaching_up) == []


def test_the_wiring_types_name_no_adapter() -> None:
    """`wiring` is what every entry point reads; a concrete class named there is one only `bootstrap` may name."""
    assert [
        f"wiring.py:{line} imports {module}"
        for line, module in _imports(PACKAGE / "wiring.py")
        if module.startswith("thefrontoffice.adapters")
    ] == []


@pytest.mark.parametrize(("competition", "platform"), sorted(LEAGUE_PLATFORMS.items()))
def test_a_competitions_rules_read_its_own_model_and_only_its_provider_names_the_league_platform(
    competition: str, platform: str
) -> None:
    """The rules are the competition's, so a second platform for one is a provider and nothing else.

    Only the provider, the module or package named for the platform that owns the
    league (`nfl/sleeper/`, `nba/yahoo/`), imports that platform; everything beside
    it reads the competition's `model.py`.
    """
    provider = PACKAGE / COMPETITIONS / competition / platform
    named = [
        f"{path.relative_to(PACKAGE)}:{line} imports {module}"
        for path in _modules(f"{COMPETITIONS}/{competition}")
        if path != provider.with_suffix(".py") and not path.is_relative_to(provider)
        for line, module in _imports(path)
        if module.startswith(f"thefrontoffice.adapters.outbound.platforms.{platform}")
    ]
    assert named == []


# ── the suite's own shape ───────────────────────────────────────────────

TESTS = PACKAGE.parent.parent / "tests"


def _suite(pattern: str) -> list[Path]:
    return sorted(p for p in TESTS.rglob(pattern) if "__pycache__" not in p.parts)


def test_no_test_imports_another_test_or_a_conftest() -> None:
    """What tests share is imported from `support/`; a conftest is found by pytest, never imported.

    Once there is more than one `conftest.py`, importing one by name reaches
    whichever the path finds first, and a test module imported by another
    runs its tests twice.
    """
    reached = [
        f"{path.relative_to(TESTS)}:{node.lineno} imports {node.module}"
        for path in _suite("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and (node.module == "conftest" or node.module.split(".")[-1].startswith("test_"))
    ]
    assert reached == []


def test_a_conftest_holds_fixtures_and_nothing_a_test_would_need_to_import() -> None:
    """Anything else in one is a helper no test can reach by name; it belongs in `support/`."""

    def is_fixture(node: ast.FunctionDef) -> bool:
        return any(
            (isinstance(d, ast.Attribute) and d.attr == "fixture")
            or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "fixture")
            for d in node.decorator_list
        )

    helpers = [
        f"{path.relative_to(TESTS)}:{node.lineno} {node.name}"
        for path in _suite("conftest.py")
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef) or (isinstance(node, ast.FunctionDef) and not is_fixture(node))
    ]
    assert helpers == []
