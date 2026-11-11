from unittest import mock

import aiohttp
import pytest

from server.config import config
from server.games import GameState, GameType, VisibilityState
from server.public import (
    PUBLIC_GAME_FIELDS,
    PublicServer,
    is_public_lobby,
    public_game_dict
)


def make_game(
    uid=1,
    state=GameState.LOBBY,
    visibility=VisibilityState.PUBLIC,
    game_type=GameType.CUSTOM,
    host="Paula_Bean",
):
    game = mock.Mock()
    game.state = state
    game.visibility = visibility
    game.game_type = game_type
    game.host = mock.Mock(login=host) if host else None
    game.to_dict.return_value = {
        "command": "game_info",
        "visibility": visibility.value,
        "password_protected": False,
        "uid": uid,
        "title": "Some game name",
        "state": "open",
        "game_type": game_type.value,
        "featured_mod": "faf",
        "sim_mods": {},
        "mapname": "scmp_007",
        "map_file_path": "maps/scmp_007.zip",
        "host": host or "",
        "num_players": 1,
        "max_players": 8,
        "hosted_at": "2026-11-10T22:00:00+00:00",
        "launched_at": None,
        "rating_type": "global",
        "rating_min": None,
        "rating_max": None,
        "enforce_rating_range": False,
        "teams_ids": [{"team_id": 1, "player_ids": [1]}],
        "teams": {1: [host]},
    }
    return game


@pytest.mark.parametrize("game_type", [GameType.CUSTOM, GameType.COOP])
def test_open_public_lobby_is_listed(game_type):
    assert is_public_lobby(make_game(game_type=game_type))


@pytest.mark.parametrize("game", [
    make_game(visibility=VisibilityState.FRIENDS),
    make_game(state=GameState.INITIALIZING),
    make_game(state=GameState.LIVE),
    make_game(state=GameState.ENDED),
    make_game(game_type=GameType.MATCHMAKER),
    make_game(host=None),
])
def test_other_games_are_not_listed(game):
    assert not is_public_lobby(game)


def test_public_game_dict_has_only_public_fields():
    info = public_game_dict(make_game())

    assert tuple(info) == PUBLIC_GAME_FIELDS
    for private in ("command", "visibility", "map_file_path", "teams_ids", "launched_at"):
        assert private not in info


@pytest.fixture
async def public_server(unused_tcp_port):
    game_service = mock.Mock()
    game_service.all_games = []
    lobby_server = mock.Mock(services={"game_service": game_service})

    server = PublicServer(lobby_server)
    await server.start("127.0.0.1", unused_tcp_port)

    yield server

    await server.shutdown()


async def get_games(server):
    url = f"http://{server.host}:{server.port}/games"
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        async with session.get(url) as resp:
            return resp.headers, await resp.json()


async def test_games_lists_only_public_lobbies(public_server):
    listed = make_game(uid=1)
    public_server.game_service.all_games = [
        listed,
        make_game(uid=2, visibility=VisibilityState.FRIENDS),
        make_game(uid=3, state=GameState.LIVE),
    ]

    headers, data = await get_games(public_server)

    assert data == {"games": [public_game_dict(listed) | {"teams": {"1": ["Paula_Bean"]}}]}
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert headers["Cache-Control"].startswith("public, max-age=")


async def test_games_list_is_served_from_cache(public_server):
    with mock.patch.object(config, "PUBLIC_GAMES_CACHE_SECONDS", 60):
        _, first = await get_games(public_server)
        public_server.game_service.all_games = [make_game()]
        _, second = await get_games(public_server)

    assert first == second == {"games": []}


async def test_games_list_refreshes_after_cache_expires(public_server):
    with mock.patch.object(config, "PUBLIC_GAMES_CACHE_SECONDS", 0):
        _, first = await get_games(public_server)
        public_server.game_service.all_games = [make_game()]
        _, second = await get_games(public_server)

    assert first == {"games": []}
    assert [game["uid"] for game in second["games"]] == [1]
