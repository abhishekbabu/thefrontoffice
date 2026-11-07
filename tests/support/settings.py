"""Settings built for one test: nothing read from this machine, every path under the test's own directory."""

from pathlib import Path

from thefrontoffice.config.settings import AppSettings, env_var, is_local


def isolated_settings(directory: Path, **values: object) -> AppSettings:
    """Every setting at its default, every local path under `directory`, then `values` by field name.

    Each field is given explicitly, so neither a `.env` nor a shell variable on
    this machine reaches it; the token file under `directory` does not exist,
    so Yahoo reads as never authorized.
    """
    given = {field: info.default for field, info in AppSettings.model_fields.items()}
    given |= {field: str(directory / field) for field in AppSettings.model_fields if is_local(field)}
    given |= values
    return AppSettings(_env_file=None, **{env_var(field): value for field, value in given.items()})
