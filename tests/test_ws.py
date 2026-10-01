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
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.timezone import now

import jwt
import pytest
from bazis_test_utils.utils import get_api_client
from redis import Redis

from bazis.contrib.ws import COMMON_CHANNEL, WS_PREFIX
from bazis.contrib.ws.models_abstract import UserWsMixin
from bazis.contrib.ws.utils import ANONYMOUS_CHANNEL_PREFIX, UserError, get_anonymous_channel
from bazis.contrib.ws.ws import WsEndpoint


ANONYMOUS_TOKEN = 'anonymous-token-0123456789'


class DummyRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    def get(self, key):
        return self.values.get(key)

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


class DummyWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def _user_token(username: str, **payload) -> str:
    return jwt.encode(
        {'sub': username, 'exp': now() + timedelta(hours=1)} | payload,
        settings.SECRET_KEY,
        algorithm='HS256',
    )


@pytest.fixture
def redis_client():
    return Redis.from_url(settings.CACHES['default']['LOCATION'])


@pytest.fixture
def ws_client(sample_app):
    return get_api_client(sample_app).client


def _wait_subscribed(redis_client, channel: str):
    """
    Waits until the socket subscribed to the channel: a message published before is lost.
    """
    for _ in range(100):
        if redis_client.pubsub_numsub(channel)[0][1]:
            return
        asyncio.run(asyncio.sleep(0.05))
    raise AssertionError(f'nobody subscribed to {channel}')


def test_user_ws_mixin_channels(monkeypatch):
    from bazis.contrib.ws import models_abstract

    monkeypatch.setattr(models_abstract, 'redis', DummyRedis())

    user = get_user_model()(pk=123, username='tester')
    assert isinstance(user, UserWsMixin)
    assert user.user_channel == f'{WS_PREFIX}:{user.pk}'
    assert user.ws_session == f'{WS_PREFIX}:{user.pk}:session'


def test_user_ws_mixin_is_online(monkeypatch):
    from bazis.contrib.ws import models_abstract

    dummy_redis = DummyRedis()
    monkeypatch.setattr(models_abstract, 'redis', dummy_redis)

    user = get_user_model()(pk=1, username='tester')
    assert user.is_online is False
    dummy_redis.values[user.ws_session] = '1'
    assert user.is_online is True


def test_user_ws_mixin_publish(monkeypatch):
    from bazis.contrib.ws import models_abstract

    dummy_redis = DummyRedis()
    monkeypatch.setattr(models_abstract, 'redis', dummy_redis)

    user = get_user_model()(pk=7, username='tester')
    user.ws_publish({'type': 'message', 'value': 1})

    assert dummy_redis.published == [(user.user_channel, '{"type": "message", "value": 1}')]


def test_ws_endpoint_ping_pong():
    endpoint = WsEndpoint(scope={'type': 'websocket'}, receive=None, send=None)
    websocket = DummyWebSocket()

    asyncio.run(endpoint.on_receive(websocket, {'type': 'ping'}))
    asyncio.run(endpoint.on_receive(websocket, '{"type": "ping"}'))
    asyncio.run(endpoint.on_receive(websocket, 'not json'))
    asyncio.run(endpoint.on_receive(websocket, ['not', 'a', 'dict']))

    assert websocket.sent == [{'type': 'pong'}, {'type': 'pong'}]


def test_ws_endpoint_token_triggers_session_start(monkeypatch):
    endpoint = WsEndpoint(scope={'type': 'websocket'}, receive=None, send=None)
    called = {}

    async def fake_session_start(_websocket, token):
        called['token'] = token

    monkeypatch.setattr(endpoint, 'session_start', fake_session_start)

    asyncio.run(endpoint.on_receive(DummyWebSocket(), {'token': 'abc'}))

    assert called == {'token': 'abc'}


@pytest.mark.parametrize(
    'token',
    [
        'short',
        'x' * 129,
        f'{WS_PREFIX}:1',  # the channel of the user 1
        COMMON_CHANNEL,
        'contains spaces 0123456789',
        'contains/slash/0123456789',
    ],
)
def test_anonymous_token_invalid(token):
    with pytest.raises(UserError):
        get_anonymous_channel(token)


def test_anonymous_channel_namespace():
    channel = get_anonymous_channel(ANONYMOUS_TOKEN)
    assert channel == f'{ANONYMOUS_CHANNEL_PREFIX}{ANONYMOUS_TOKEN}'
    assert not channel.startswith(f'{WS_PREFIX}:')


@pytest.mark.parametrize(
    'make_token, code',
    [
        (lambda u: _user_token(u.username, exp=now() - timedelta(seconds=1)), 'expired_token'),
        (
            lambda u: jwt.encode(
                {'sub': u.username, 'exp': now() + timedelta(hours=1)}, 'x' * 40, algorithm='HS256'
            ),
            'invalid_token',
        ),
        (
            lambda u: jwt.encode({'sub': u.username}, settings.SECRET_KEY, algorithm='HS256'),
            'invalid_token',
        ),
        (lambda u: _user_token('unknown-user'), 'user_not_found'),
    ],
    ids=['expired', 'foreign-key', 'no-exp', 'unknown-user'],
)
@pytest.mark.django_db(transaction=True)
def test_ws_user_token_rejected(ws_client, make_token, code):
    user = get_user_model().objects.create_user('ws_user', password='weak_password_1')
    with ws_client.websocket_connect('/ws') as websocket:
        websocket.send_json({'token': make_token(user)})
        assert websocket.receive_json()['code'] == code


@pytest.mark.django_db(transaction=True)
def test_ws_inactive_user_rejected(ws_client):
    user = get_user_model().objects.create_user('ws_user', password='weak_password_1')
    user.is_active = False
    user.save()
    with ws_client.websocket_connect(f'/ws?token={_user_token(user.username)}') as websocket:
        assert websocket.receive_json() == {
            'type': 'error',
            'code': 'user_not_found',
            'detail': 'User not found',
        }


@pytest.mark.django_db(transaction=True)
def test_ws_user_session(ws_client, redis_client):
    user = get_user_model().objects.create_user('ws_user', password='weak_password_1')

    with ws_client.websocket_connect(f'/ws?token={_user_token(user.username)}') as websocket:
        _wait_subscribed(redis_client, user.user_channel)
        assert user.is_online is True

        user.ws_publish({'value': 1})
        assert websocket.receive_json() == {'type': 'data', 'data': '{"value": 1}'}

        redis_client.publish(COMMON_CHANNEL, 'for everybody')
        assert websocket.receive_json() == {'type': 'data', 'data': 'for everybody'}

        websocket.send_json({'type': 'ping'})
        assert websocket.receive_json() == {'type': 'pong'}

        # the session key is removed when the client disconnects (checked before leaving the
        # context: the test client cancels the application when the context exits)
        websocket.close()
        for _ in range(100):
            if not user.is_online:
                break
            asyncio.run(asyncio.sleep(0.05))
        assert user.is_online is False


@pytest.mark.django_db(transaction=True)
def test_ws_anonymous_session(ws_client, redis_client):
    user = get_user_model().objects.create_user('ws_user', password='weak_password_1')
    channel = get_anonymous_channel(ANONYMOUS_TOKEN)

    with ws_client.websocket_connect('/ws') as websocket:
        # an anonymous client cannot subscribe to the channel of a user
        websocket.send_json({'token': user.user_channel})
        assert websocket.receive_json()['code'] == 'invalid_token'

        websocket.send_json({'token': ANONYMOUS_TOKEN})
        _wait_subscribed(redis_client, channel)
        assert redis_client.get(f'{channel}:session') == b'1'

        user.ws_publish({'private': True})
        redis_client.publish(channel, 'for the anonymous client')
        # the message of the user channel is not delivered
        assert websocket.receive_json() == {'type': 'data', 'data': 'for the anonymous client'}

        # a new token replaces the session
        other_token = 'other-anonymous-token-0123'
        websocket.send_json({'token': other_token})
        _wait_subscribed(redis_client, get_anonymous_channel(other_token))
        assert redis_client.pubsub_numsub(channel)[0][1] == 0
        assert redis_client.get(f'{channel}:session') is None


def test_ws_redis_failure_closes_socket(ws_client, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    from bazis.contrib.ws import ws as ws_module

    class BrokenRedis:
        async def set(self, *args, **kwargs):
            raise ConnectionError('Redis is down')

        async def delete(self, *args, **kwargs):
            raise ConnectionError('Redis is down')

        def pubsub(self, **kwargs):
            raise ConnectionError('Redis is down')

    monkeypatch.setattr(ws_module, 'get_redis_async', BrokenRedis)

    with ws_client.websocket_connect(f'/ws?token={ANONYMOUS_TOKEN}') as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 1011


def test_connection_params(settings):
    from bazis.contrib.ws.utils import _connection_params

    settings.DATABASES = {
        'default': {
            'NAME': 'db',
            'USER': 'user',
            'PASSWORD': '',
            'HOST': '',
            'PORT': '',
            'OPTIONS': {
                'sslmode': 'require',
                'server_side_binding': True,
                'isolation_level': 1,
                'pool': {'min_size': 2},
            },
        }
    }
    assert _connection_params() == {
        'dbname': 'db',
        'user': 'user',
        'connect_timeout': 10,
        'sslmode': 'require',
    }


def test_user_token_issued_in_the_future_accepted():
    from bazis.contrib.ws.utils import decode_user_token

    token = _user_token('user', iat=now() + timedelta(seconds=5))
    assert decode_user_token(token)['sub'] == 'user'


def test_redis_clients_of_closed_loops_are_dropped():
    """
    The asyncio Redis clients are kept per event loop; the clients of closed loops were
    never released (a weak registry cannot release them: the client refers to its loop).
    """
    from bazis.contrib.ws import utils

    async def client():
        return utils.get_redis_async()

    utils._redis_async_by_loop.clear()
    first = asyncio.run(client())
    second = asyncio.run(client())
    assert first is not second
    assert list(utils._redis_async_by_loop.values()) == [second]
