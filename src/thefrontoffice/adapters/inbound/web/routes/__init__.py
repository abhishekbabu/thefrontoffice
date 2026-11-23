"""The API's routes, one `APIRouter` per resource.

`ROUTERS` is the order `create_app` includes them in, which is the order the
schema lists their paths, and so the client's generated types.
"""

from fastapi import APIRouter

from thefrontoffice.adapters.inbound.web.routes import (
    chat,
    competitions,
    free_agents,
    judgment,
    platforms,
    players,
    season,
    settings,
    teams,
    trades,
    week,
)

ROUTERS: tuple[APIRouter, ...] = (
    competitions.router,
    settings.router,
    platforms.router,
    players.router,
    week.router,
    free_agents.router,
    teams.router,
    season.router,
    trades.router,
    judgment.router,
    chat.router,
)
