"""Report what this machine is configured for, without printing any secret.

Setting a project up on a second machine means retyping a handful of values,
and the failure mode is silent: `AppSettings` ignores keys it does not
recognize, so `GOOGLE_APIKEY` for `GOOGLE_API_KEY` produces no error at all —
the AI simply reports itself unavailable, three commands later.

This names every setting the app reads, says whether it is present, and flags
anything in .env that no setting will ever pick up.

Run with `just doctor`.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from thefrontoffice.bootstrap import ai_providers, all_competitions  # noqa: E402
from thefrontoffice.config import env_file  # noqa: E402
from thefrontoffice.config.settings import PROJECT_ROOT as SETTINGS_ROOT  # noqa: E402
from thefrontoffice.config.settings import AppSettings, settings  # noqa: E402

ENV_FILE = SETTINGS_ROOT / ".env"

SECRETS = env_file.SECRET_KEYS
"""Values never echoed back, only reported as present or absent."""

# Derived state, not configuration — reporting them as unset would be misleading.
DERIVED = frozenset({"DEFAULT_MODEL"})


def _env_var(name: str) -> str:
    """The environment variable a settings field reads."""
    field = AppSettings.model_fields[name]
    alias = field.validation_alias
    return str(alias) if isinstance(alias, str) else name.upper()


def _declared() -> dict[str, str]:
    """Every environment variable the app reads, mapped to its field name."""
    return {_env_var(name): name for name in AppSettings.model_fields}


def _file_keys() -> list[str]:
    """The keys actually present in .env, in file order."""
    if not ENV_FILE.exists():
        return []
    keys = []
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.append(stripped.split("=", 1)[0].strip())
    return keys


def _describe(name: str) -> str:
    """Whether a field has a value, and what kind, never the value itself."""
    value = getattr(settings, name)
    if value is None or value == "":
        return "not set"
    if _env_var(name) in SECRETS:
        return f"set ({len(str(value))} chars)"
    # Booleans arrive from .env spelled as they are written there.
    return str(value).lower() if isinstance(value, bool) else str(value)


def main() -> int:
    print()
    print(f"  .env: {ENV_FILE}" if ENV_FILE.exists() else f"  .env: MISSING — copy .env.template to {ENV_FILE}")
    print()

    declared = _declared()
    # One column width across all three tables, so a long sport label does not
    # push its own row out of alignment with the rest.
    width = max(
        [len(var) for var in declared] + [len(e.label) for e in all_competitions()] + [len("Tracing (Logfire)")]
    )

    print("  Settings")
    print("  " + "─" * (width + 22))
    for var, name in declared.items():
        if var in DERIVED:
            continue
        print(f"  {var.ljust(width)}   {_describe(name)}")

    print()
    print("  Sports")
    print("  " + "─" * (width + 22))
    for entry in all_competitions():
        state = "ready" if entry.is_configured() else f"needs {entry.requires}"
        print(f"  {entry.label.ljust(width)}   {state}")

    print()
    print("  Features")
    print("  " + "─" * (width + 22))
    providers = ai_providers()
    ai = (
        f"ready — {', '.join(providers)}, in that order" if providers else "no key — reports and trades are not offered"
    )
    print(f"  {'AI'.ljust(width)}   {ai}")
    telemetry = "exporting" if settings.logfire_token else "inert — no token, nothing leaves this machine"
    print(f"  {'Tracing (Logfire)'.ljust(width)}   {telemetry}")
    if settings.logfire_capture_prompts:
        print(f"  {''.ljust(width)}   prompt text IS being exported")

    # The whole reason this script exists: a mistyped key is silently ignored.
    unknown = [key for key in _file_keys() if key not in declared]
    if unknown:
        print()
        print("  Unrecognized keys in .env — nothing reads these:")
        for key in unknown:
            print(f"    {key}")
        print("  A typo here is silent: the setting keeps its default.")
        return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
