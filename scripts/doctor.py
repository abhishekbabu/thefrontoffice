"""Report what this machine is configured for, without printing any secret.

Setting a project up on a second machine means retyping a handful of values,
and the failure mode is silent: `AppSettings` ignores keys it does not
recognize, so `GOOGLE_APIKEY` for `GOOGLE_API_KEY` produces no error at all —
the AI simply reports itself unavailable, three commands later.

This names every setting the app reads, says whether it is present, and flags
anything in .env that no setting will ever pick up. Each setting is described
by `EnvFile.describe`, the one the Settings page reads, so a secret is withheld
here exactly as it is there.

Run with `just doctor`.
"""

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.remedies import remedy
from thefrontoffice.bootstrap import CompetitionEntry, Registry
from thefrontoffice.config.env_file import EnvFile, Setting

TRACING = "Tracing (Logfire)"


def shown(setting: Setting) -> str:
    """A setting as this report prints it: whether it has a value, and the value itself only where it is no secret."""
    if not setting.present:
        return "not set"
    return "set" if setting.secret else setting.effective


def readiness(entry: CompetitionEntry) -> str:
    """'ready', or what stands in the way and how a terminal fixes it — as the web picker judges it."""
    blocker = entry.blocker()
    if blocker is None:
        return "ready"
    fix = remedy(blocker)
    return f"{blocker} {fix.command}" if fix and fix.command else str(blocker)


def main(*, env: EnvFile, registry: Registry, providers: list[str]) -> int:
    """Print the report; 1 where `.env` holds a key nothing reads.

    Args:
        providers: the model providers with a key, in the order they are tried.
    """
    print()
    print(f"  .env: {env.path}" if env.path.exists() else f"  .env: MISSING — copy .env.template to {env.path}")
    print()

    settings = [setting for group in env.groups() for setting in group.settings]
    # One column width across all three tables, so a long label does not
    # push its own row out of alignment with the rest.
    width = max([len(s.key) for s in settings] + [len(e.label) for e in registry.entries] + [len(TRACING)])

    print("  Settings")
    print("  " + "─" * (width + 22))
    for setting in settings:
        print(f"  {setting.key.ljust(width)}   {shown(setting)}")

    print()
    print("  Competitions")
    print("  " + "─" * (width + 22))
    for entry in registry.entries:
        print(f"  {entry.label.ljust(width)}   {readiness(entry)}")

    print()
    print("  Features")
    print("  " + "─" * (width + 22))
    ai = (
        f"ready — {', '.join(providers)}, in that order" if providers else "no key — reports and trades are not offered"
    )
    print(f"  {'AI'.ljust(width)}   {ai}")
    config = env.settings
    telemetry = "exporting" if config.logfire_token else "inert — no token, nothing leaves this machine"
    print(f"  {TRACING.ljust(width)}   {telemetry}")
    if config.logfire_capture_prompts:
        print(f"  {''.ljust(width)}   prompt text IS being exported")

    # The whole reason this script exists: a mistyped key is silently ignored.
    if unknown := env.unknown():
        print()
        print("  Unrecognized keys in .env — nothing reads these:")
        for key in unknown:
            print(f"    {key}")
        print("  A typo here is silent: the setting keeps its default.")
        return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(env=bootstrap.env_file(), registry=bootstrap.registry(), providers=bootstrap.ai_providers()))
