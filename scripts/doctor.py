"""Report what this machine is configured for, without printing any secret.

Setting a project up on a second machine means retyping a handful of values,
and the failure mode is silent: `AppSettings` ignores keys it does not
recognize, so `GOOGLE_APIKEY` for `GOOGLE_API_KEY` produces no error at all —
the AI simply reports itself unavailable, three commands later.

This names every setting the app reads, says whether it is present, and flags
anything in .env that no setting will ever pick up. What a setting is called,
which are secret and how a value is spelled are `config.env_file`'s, which the
Settings page reads too.

Run with `just doctor`.
"""

from thefrontoffice.bootstrap import REGISTRY, ai_providers
from thefrontoffice.config import env_file
from thefrontoffice.config.settings import settings

TRACING = "Tracing (Logfire)"


def describe(field: str) -> str:
    """Whether a field has a value, and what kind, never the value itself."""
    value = getattr(settings, field)
    if value is None or value == "":
        return "not set"
    if env_file.env_var(field) in env_file.SECRET_KEYS:
        return f"set ({len(str(value))} chars)"
    return env_file.spelled(value)


def main() -> int:
    path = env_file.ENV_PATH
    print()
    print(f"  .env: {path}" if path.exists() else f"  .env: MISSING — copy .env.template to {path}")
    print()

    declared = env_file.declared()
    # One column width across all three tables, so a long label does not
    # push its own row out of alignment with the rest.
    width = max([len(var) for var in declared] + [len(e.label) for e in REGISTRY.entries] + [len(TRACING)])

    print("  Settings")
    print("  " + "─" * (width + 22))
    for var, field in declared.items():
        print(f"  {var.ljust(width)}   {describe(field)}")

    print()
    print("  Competitions")
    print("  " + "─" * (width + 22))
    for entry in REGISTRY.entries:
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
    print(f"  {TRACING.ljust(width)}   {telemetry}")
    if settings.logfire_capture_prompts:
        print(f"  {''.ljust(width)}   prompt text IS being exported")

    # The whole reason this script exists: a mistyped key is silently ignored.
    unknown = [key for key in env_file.read_values() if key not in declared]
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
