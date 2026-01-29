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
from typing import Any

from django.conf import settings
from django.utils.translation import gettext as _

from starlette.endpoints import WebSocketEndpoint
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

from redis.asyncio import Redis

from . import COMMON_CHANNEL
from .utils import UserError, get_user_from_token_async


logger = logging.getLogger()

redis = Redis.from_url(settings.CACHES['default']['LOCATION'])


class WsError(Exception):
    pass


class WsEndpoint(WebSocketEndpoint):
    encoding = 'json'
    session_key: str | None
    channel_name: str | None
    is_running: bool

    def __init__(self, scope, receive, send):
        super().__init__(scope, receive, send)
        self.active_tasks = []
        self.session_key = None
        self.channel_name = None
        self.is_running = False

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

    async def session_start(self, websocket: WebSocket, token: str):
        await self.session_stop(websocket)

        if token.count('.') == 2:
            try:
                user = await get_user_from_token_async(token)
            except UserError as exc:
                await websocket.send_json(
                    {
                        'type': 'error',
                        'code': exc.code,
                        'detail': exc.message,
                    }
                )
                logger.info(f'WS:session_start:error: {exc.message}')
                return
            except Exception as exc:
                await websocket.send_json(
                    {
                        'type': 'error',
                        'code': 'internal_error',
                        'detail': _('Internal server error'),
                    }
                )
                logger.error(f'WS:session_start:error: {exc}')
                return

            logger.info(f'WS:session_start:username: {user}')
            self.session_key = user.ws_session
            self.channel_name = user.user_channel
        else:
            logger.info(f'WS:session_start:token: {token}')
            self.session_key = f'{token}:session'
            self.channel_name = token

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

        if self.session_key:
            await redis.delete(self.session_key)
        self.session_key = None
        self.channel_name = None

        if code:
            await websocket.close(code)

    def running_check(self):
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
                await redis.set(self.session_key, '1', ex=10)
                # logger.info(f'WS:task_online_update::set: {ws_session_set}')
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f'WS:task_online_update:error: {e}')
            return
        logger.info('WS:task_online_update::finish')

    async def task_listen_queue(self, websocket: WebSocket):
        logger.info(f'WS:task_listen_queue::start {self.channel_name}')
        try:
            async with redis.pubsub(ignore_subscribe_messages=True) as pubsub:
                await pubsub.subscribe(self.channel_name, COMMON_CHANNEL)
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
