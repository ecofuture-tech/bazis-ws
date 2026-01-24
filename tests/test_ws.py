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

from django.contrib.auth import get_user_model
from jose import jwt as jose_jwt

from bazis.contrib.ws import WS_PREFIX
from bazis.contrib.ws.models_abstract import UserWsMixin
from bazis.contrib.ws.ws import WsEndpoint


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


def test_user_ws_mixin_channels(monkeypatch):
    from bazis.contrib.ws import models_abstract

    dummy_redis = DummyRedis()
    monkeypatch.setattr(models_abstract, 'redis', dummy_redis)

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

    assert dummy_redis.published == [
        (user.user_channel, '{"type": "message", "value": 1}')
    ]


def test_ws_endpoint_ping_pong():
    endpoint = WsEndpoint(scope={'type': 'websocket'}, receive=None, send=None)
    websocket = DummyWebSocket()

    asyncio.run(endpoint.on_receive(websocket, {'type': 'ping'}))

    assert websocket.sent == [{'type': 'pong'}]


def test_ws_endpoint_token_triggers_session_start(monkeypatch):
    endpoint = WsEndpoint(scope={'type': 'websocket'}, receive=None, send=None)
    websocket = DummyWebSocket()
    called = {}

    async def fake_session_start(_websocket, token):
        called['token'] = token

    monkeypatch.setattr(endpoint, 'session_start', fake_session_start)

    asyncio.run(endpoint.on_receive(websocket, {'token': 'abc'}))

    assert called == {'token': 'abc'}


def test_ws_endpoint_expired_token(monkeypatch):
    from bazis.contrib.ws import ws as ws_module

    endpoint = WsEndpoint(scope={'type': 'websocket'}, receive=None, send=None)
    websocket = DummyWebSocket()

    def fake_decode(*_args, **_kwargs):
        raise jose_jwt.ExpiredSignatureError()

    monkeypatch.setattr(ws_module.jwt, 'decode', fake_decode)

    result = asyncio.run(endpoint.get_user_from_token('expired', websocket))

    assert result is None
    assert websocket.sent == [
        {'type': 'error', 'code': 'expired_token', 'detail': 'Token expired'}
    ]
