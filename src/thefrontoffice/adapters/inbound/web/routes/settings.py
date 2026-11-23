"""The configuration, as the Settings page reads and edits it."""

from fastapi import APIRouter
from pydantic import BaseModel

from thefrontoffice.adapters.inbound.web.routes.deps import CurrentWiring
from thefrontoffice.config.env_file import SettingsGroup

router = APIRouter()


class SettingsUpdate(BaseModel):
    values: dict[str, str]


@router.get("/api/settings", response_model=list[SettingsGroup])
def read_settings(wiring: CurrentWiring) -> list[SettingsGroup]:
    """Every configurable value, grouped by what it unlocks, with secrets reported as present or absent.

    A secret's contents never leave the process. There is nothing the UI can
    do with the characters of an API key that it cannot do with the fact
    that one is set, and a page that renders them puts them in screenshots.
    """
    return wiring.env.groups()


@router.put("/api/settings", response_model=list[SettingsGroup])
def save_settings(update: SettingsUpdate, wiring: CurrentWiring) -> list[SettingsGroup]:
    """Write values to .env and re-read configuration into the running app.

    Rejects any key no setting reads rather than writing it: a line nothing
    picks up looks saved and changes nothing, which is the exact failure
    this endpoint exists to prevent.
    """
    wiring.env.write_values(update.values)
    return wiring.env.groups()
