import aiohttp

from server.public import PUBLIC_GAME_FIELDS, public_game_dict
from tests.utils import fast_forward

from .conftest import connect_and_sign_in, read_until_command


def listify(obj: dict):
    for k, v in obj.items():
        if isinstance(v, tuple):
            obj[k] = list(v)
        elif isinstance(v, dict):
            obj[k] = listify(v)
    return obj


async def host_lobby(lobby_server, credentials, visibility):
    player_id, _, proto = await connect_and_sign_in(credentials, lobby_server)
    await proto.send_message({
        "command": "game_host",
        "mod": "faf",
        "visibility": visibility
    })
    msg = await read_until_command(proto, "game_launch")
    await proto.send_message({
        "target": "game",
        "command": "GameState",
        "args": ["Idle"]
    })
    await proto.send_message({
        "target": "game",
        "command": "PlayerOption",
        # Send this as a string because json object keys can only be strings.
        # This makes our assertion check easier.
        "args": [player_id, "Team", "1"]
    })
    return msg["uid"]


async def get_public_games(public_server):
    url = f"http://{public_server.host}:{public_server.port}/games"
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        async with session.get(url) as resp:
            return await resp.json()


@fast_forward(2)
async def test_public_lobby_is_listed(public_server, lobby_server, game_service):
    game_id = await host_lobby(lobby_server, ("test", "test_password"), "public")

    data = await get_public_games(public_server)

    assert data == {"games": [listify(public_game_dict(game_service[game_id]))]}
    assert tuple(data["games"][0]) == PUBLIC_GAME_FIELDS


@fast_forward(2)
async def test_friends_only_lobby_is_not_listed(public_server, lobby_server):
    await host_lobby(lobby_server, ("test", "test_password"), "friends")

    data = await get_public_games(public_server)

    assert data == {"games": []}
