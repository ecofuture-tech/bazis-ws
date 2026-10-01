# Copyright 2026 EcoFuture Technology Services LLC and contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model

import jwt
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from redis.asyncio import Redis as AsyncRedis

from . import WS_PREFIX


logger = logging.getLogger(__name__)
User = get_user_model()

#: an anonymous client subscribes with a token it generated itself: the token is the only
#: secret protecting its channel, so it must be long enough to be unguessable
ANONYMOUS_TOKEN_RE = re.compile(r'[A-Za-z0-9_-]{16,128}')

#: anonymous channels live in their own namespace, so an anonymous token can never
#: address a user channel (`user_ws::<pk>`) or the common channel
ANONYMOUS_CHANNEL_PREFIX = f'{WS_PREFIX}anon:'

_redis_async_by_loop: dict[asyncio.AbstractEventLoop, AsyncRedis] = {}


def drop_closed_loops(registry: dict) -> None:
    """
    Removes the objects of closed event loops from a per-loop registry: the objects refer to
    their loop, so a weak registry would never release them.
    """
    for loop in [loop for loop in registry if loop.is_closed()]:
        del registry[loop]


class UserError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def get_redis_async() -> AsyncRedis:
    """
    Returns the asyncio Redis client of the running event loop: a client and its
    connections cannot be shared between event loops.
    """
    loop = asyncio.get_running_loop()
    client = _redis_async_by_loop.get(loop)
    if client is None:
        drop_closed_loops(_redis_async_by_loop)
        client = AsyncRedis.from_url(settings.CACHES['default']['LOCATION'])
        _redis_async_by_loop[loop] = client
    return client


def is_user_token(token: str) -> bool:
    """
    Whether the token looks like a JWT (a user session token) rather than an anonymous token.
    """
    return token.count('.') == 2


def get_anonymous_channel(token: str) -> str:
    """
    Returns the channel of an anonymous client identified by its own token.
    Raises UserError if the token is not a valid anonymous token.
    """
    if not ANONYMOUS_TOKEN_RE.fullmatch(token):
        raise UserError(
            message='Invalid token',
            code='invalid_token',
        )
    return f'{ANONYMOUS_CHANNEL_PREFIX}{token}'


def decode_user_token(token: str) -> dict:
    """
    Decodes a user session token built by `jwt_build` of bazis-users. Raises UserError
    for an expired or invalid token.
    """
    algorithm = getattr(settings, 'BAZIS_JWT_SESSION_ALG', 'HS256')
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[algorithm],
            # iat is informational: checking it would reject tokens issued by a server
            # whose clock is slightly ahead
            options={'require': ['exp', 'sub'], 'verify_iat': False},
        )
    except jwt.ExpiredSignatureError:
        raise UserError(
            message='Token expired',
            code='expired_token',
        ) from None
    except jwt.InvalidTokenError:
        raise UserError(
            message='Invalid token',
            code='invalid_token',
        ) from None


def _is_libpq_option(key: str, value) -> bool:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return False
    try:
        make_conninfo(**{key: value})
    except psycopg.ProgrammingError:
        return False
    return True


def _connection_params() -> dict:
    """
    The libpq parameters of the default database, as Django connects to it: empty values
    are left to libpq (an empty HOST is the Unix socket), and of OPTIONS only libpq
    parameters are passed (sslmode, sslrootcert, service, ...), not the options of the
    Django backend (isolation_level, server_side_binding, pool, ...).
    """
    db_settings = settings.DATABASES['default']
    params = {
        'host': db_settings.get('HOST'),
        'port': db_settings.get('PORT'),
        'dbname': db_settings.get('NAME'),
        'user': db_settings.get('USER'),
        'password': db_settings.get('PASSWORD'),
        'connect_timeout': 10,
    }
    params = {key: value for key, value in params.items() if value not in (None, '')}
    params.update(
        {
            key: value
            for key, value in (db_settings.get('OPTIONS') or {}).items()
            if _is_libpq_option(key, value)
        }
    )
    return params


async def get_user_from_token_async(token: str):
    """
    Returns the active user the session token was issued to. Raises UserError if the
    token is invalid or expired, or the user does not exist or is inactive.

    The user is read through a separate asynchronous connection: the Django ORM would run
    the query in the single thread of `sync_to_async`, shared by all connections.
    """
    username = decode_user_token(token)['sub']

    query = sql.SQL('SELECT * FROM {table} WHERE {username} = %s AND {is_active}').format(
        table=sql.Identifier(User._meta.db_table),
        username=sql.Identifier(User._meta.get_field('username').column),
        is_active=sql.Identifier(User._meta.get_field('is_active').column),
    )
    async with await psycopg.AsyncConnection.connect(
        **_connection_params(), row_factory=dict_row
    ) as aconn:
        async with aconn.cursor() as acur:
            await acur.execute(query, (username,))
            result = await acur.fetchone()

    if not result:
        raise UserError(
            message='User not found',
            code='user_not_found',
        )
    attnames = {field.column: field.attname for field in User._meta.concrete_fields}
    return User(**{attnames[column]: value for column, value in result.items() if column in attnames})
