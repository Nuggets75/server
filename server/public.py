"""
Public read-only http server for the open lobby list.

Serves `GET /games`: the open lobbies anyone could find in the game list,
for websites and apps that show them without a lobby connection.

Only open lobbies that are public and custom or coop are listed, with a fixed
set of fields. Friends-only lobbies, running games and matchmaker games are
never listed. Viewers are anonymous, so per-player rules (a host's foe list,
rating restrictions) cannot be applied here; they still apply when joining.
"""

import asyncio
import json
import logging
import socket
from typing import TYPE_CHECKING, ClassVar, Optional, cast

from aiohttp import web

from .config import config
from .decorators import with_logger
from .game_service import GameService
from .games import Game, GameState, GameType, VisibilityState

if TYPE_CHECKING:
    from server import ServerInstance


# The fields of `Game.to_dict` that are published. Anything not named here,
# including fields added to `to_dict` later, stays private.
PUBLIC_GAME_FIELDS = (
    "uid",
    "title",
    "state",
    "game_type",
    "featured_mod",
    "sim_mods",
    "mapname",
    "host",
    "num_players",
    "max_players",
    "password_protected",
    "hosted_at",
    "rating_type",
    "rating_min",
    "rating_max",
    "enforce_rating_range",
    "teams",
)

PUBLIC_GAME_TYPES = (GameType.CUSTOM, GameType.COOP)


def is_public_lobby(game: Game) -> bool:
    return (
        game.state is GameState.LOBBY
        and game.visibility is VisibilityState.PUBLIC
        and game.game_type in PUBLIC_GAME_TYPES
        and game.host is not None
    )


def public_game_dict(game: Game) -> dict:
    info = game.to_dict()
    return {field: info[field] for field in PUBLIC_GAME_FIELDS}


@with_logger
class PublicServer:
    _logger: ClassVar[logging.Logger]

    def __init__(
        self,
        lobby_server: "ServerInstance",
    ):
        self.game_service = cast(GameService, lobby_server.services["game_service"])
        self.host: Optional[str] = None
        self.port: Optional[int] = None
        self._body: Optional[str] = None
        self._body_time = 0.0

        self.app = web.Application()
        self.runner = web.AppRunner(self.app)

        self.app.add_routes([
            web.get("/games", self.games),
        ])

    async def run_from_config(self) -> None:
        """
        Initialize the public http server
        """
        host = socket.gethostbyname(socket.gethostname())
        port = config.PUBLIC_SERVER_PORT

        await self.shutdown()
        await self.start(host, port)

    async def start(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()
        self._logger.info(
            "Public server listening on http://%s:%s", host, port
        )

    async def shutdown(self) -> None:
        await self.runner.cleanup()
        self.host = None
        self.port = None

    def _games_body(self) -> str:
        # Every request is served from one serialized copy, rebuilt at most
        # once per PUBLIC_GAMES_CACHE_SECONDS, so request volume does not
        # translate into work on the game list.
        now = asyncio.get_running_loop().time()
        if (
            self._body is None
            or now - self._body_time >= config.PUBLIC_GAMES_CACHE_SECONDS
        ):
            self._body = json.dumps({
                "games": [
                    public_game_dict(game)
                    for game in self.game_service.all_games
                    if is_public_lobby(game)
                ]
            })
            self._body_time = now
        return self._body

    async def games(self, request: web.Request) -> web.Response:
        max_age = max(0, int(config.PUBLIC_GAMES_CACHE_SECONDS))
        return web.Response(
            text=self._games_body(),
            content_type="application/json",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": f"public, max-age={max_age}",
            },
        )
