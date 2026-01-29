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

import logging

from django.conf import settings
from django.contrib.auth import get_user_model

import psycopg
from jose import jwt
from psycopg.rows import dict_row


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


class UserError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


async def get_user_from_token_async(token):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[getattr(settings, 'BAZIS_JWT_SESSION_ALG', 'HS256')])
        username = payload.get('sub')
    except jwt.ExpiredSignatureError:
        raise UserError(
            message='Token expired',
            code='expired_token',
        ) from None
    except jwt.JWTError:
        raise UserError(
            message='Invalid token',
            code='invalid_token',
        ) from None

    if not username:
        raise UserError(
            message='Invalid token',
            code='invalid_token',
        )

    logger.info(f'User:get_user_from_token:username: {username}')

    async with await psycopg.AsyncConnection.connect(**psycopg3_params, row_factory=dict_row) as aconn:
        async with aconn.cursor() as acur:
            await acur.execute(f'SELECT * FROM {User._meta.db_table} WHERE username=%s', (username,))
            result = await acur.fetchone()
            if not result:
                raise UserError(
                    message='User not found',
                    code='user_not_found',
                )
    return User(**result)
