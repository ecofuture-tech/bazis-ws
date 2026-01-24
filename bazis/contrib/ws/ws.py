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
import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _

from starlette.endpoints import WebSocketEndpoint
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

import psycopg
from jose import jwt
from psycopg.rows import dict_row
from redis.asyncio import Redis

from . import COMMON_CHANNEL


if TYPE_CHECKING:
    from .models_abstract import UserWsMixin

logger = logging.getLogger()
User = get_user_model()


db_settings = settings.DATABASES["default"]

psycopg3_params = {
    "host": db_settings.get("HOST", "localhost"),
    "port": db_settings.get("PORT", 5432),
    "dbname": db_settings.get("NAME"),
    "user": db_settings.get("USER"),
    "password": db_settings.get("PASSWORD"),
}

redis = Redis.from_url(settings.CACHES['default']['LOCATION'])


class WsError(Exception):
    pass


class WsEndpoint(WebSocketEndpoint):
    encoding = 'json'
    user: Optional['UserWsMixin'] = None
    is_running: bool = False

    def __init__(self, scope, receive, send):
        super().__init__(scope, receive, send)
        self.active_tasks = []

    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        logger.info('WS:on_connect::start')
        token = websocket.query_params.get('token')
        if token:
            await self.session_start(websocket, token)

    async def on_receive(self, websocket: WebSocket, data: Any) -> None:
        logger.info(f'WS:on_receive data: {data}')

        data_json = None
        if isinstance(data, dict):
            data_json = data
        else:
            try:
                data_json = json.loads(data)
            except Exception as exc:
                logger.error(f'WS:on_receive json.loads:error: {exc}')

        if data_json:
            if data_json.get('type') == 'ping':
                logger.info('WS:received ping, sending pong')
                await websocket.send_json({'type': 'pong'})
                return

            if token := data_json.get('token'):
                await self.session_start(websocket, token)

        await super().on_receive(websocket, data)

    async def on_disconnect(self, websocket: WebSocket, close_code: int):
        logger.info('WS:on_disconnect::start')
        await self.session_stop(websocket)
        logger.info('WS:on_disconnect::finish')

    async def get_user_from_token(self, token, websocket: WebSocket):
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[getattr(settings, 'BAZIS_JWT_SESSION_ALG', 'HS256')])
            username = payload.get('sub')
        except jwt.ExpiredSignatureError:
            await websocket.send_json({
                'type': 'error',
                'code': 'expired_token',
                'detail': _('Token expired'),
            })
            logger.error(f'WS:error:jwt.ExpiredSignatureError: {token}')
            return None

        logger.info(f'WS:get_user_from_token:username: {username}')

        async with await psycopg.AsyncConnection.connect(**psycopg3_params, row_factory=dict_row) as aconn:
            async with aconn.cursor() as acur:
                await acur.execute(f'SELECT * FROM {User._meta.db_table} WHERE username=%s', (username,))
                result = await acur.fetchone()
                if not result:
                    await websocket.send_json({
                        'type': 'error',
                        'code': 'user_not_found',
                        'detail': _('User not found'),
                    })
                    logger.error(f'WS:get_user_from_token:User not found: {username}')
                    return None
        return User(**result)

    async def session_start(self, websocket: WebSocket, token: str):
        await self.session_stop(websocket)

        self.user = await self.get_user_from_token(token, websocket)
        logger.info(f'WS:session_start:username: {self.user}')
        if self.user:
            self.is_running = True
            task = asyncio.create_task(self.task_online_update())
            self.active_tasks.append(task)
            task = asyncio.create_task(self.task_listen_queue(websocket))
            self.active_tasks.append(task)

    async def session_stop(self, websocket: WebSocket, code: int | None = None):
        self.is_running = False
        # waiting for background tasks to complete
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks = []

        if self.user:
            await redis.delete(self.user.ws_session)
            self.user = None

        if code:
            await websocket.close(code)

    def running_check(self):
        if not self.user:
            raise WsError('WS: User not found')
        if not self.is_running:
            raise WsError('WS: Session not running')

        for t in self.active_tasks:
            if t.cancelled():
                raise WsError(f'WS: Task {t} cancelled')

        return True

    async def task_online_update(self):
        logger.info('WS:task_online_update::start')
        try:
            while self.running_check():
                await redis.set(self.user.ws_session, '1', ex=10)
                # logger.info(f'WS:task_online_update::set: {ws_session_set}')
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f'WS:task_online_update:error: {e}')
            return
        logger.info('WS:task_online_update::finish')

    async def task_listen_queue(self, websocket: WebSocket):
        logger.info(f'WS:task_listen_queue::start {self.user.user_channel}')
        try:
            async with redis.pubsub(ignore_subscribe_messages=True) as pubsub:
                await pubsub.subscribe(self.user.user_channel, COMMON_CHANNEL)
                while self.running_check():
                    if message := await pubsub.get_message(timeout=1):
                        logger.info(f'WS:listen_queue::message::{message}')
                        if out_message := message.get('data'):
                            if isinstance(out_message, bytes):
                                out_message = out_message.decode()
                            # if isinstance(out_message, (str, bytes)):
                            #     out_message = json.loads(out_message)
                            await websocket.send_json({
                                'type': 'data',
                                'data': out_message
                            })
                await pubsub.unsubscribe()
        except Exception as e:
            logger.error(f'WS:task_listen_queue:error: {e}')
            return
        logger.info('WS:task_listen_queue::finish')


ws_route = WebSocketRoute("/ws", WsEndpoint)
