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

"""
Publishing the messages that bazis-front reads on the socket (`@/bazis/react/ws`) from the
code of a write:

- `publish_changed(item)`: `{"resource": "<JSON:API type>"}` on the common channel, the hint
  that a resource changed (every user session refetches it with its own permissions; no id,
  the common channel reaches every user);
- `notify(users, message)` with `notification(title, text, item)`: `{"action":
  "notification", ...}` on the channel of each user, built in the language of the user.

Both publish after the commit of the current transaction (at once outside a transaction), so
that a client refetching reads the committed data and a rolled back write publishes nothing,
and robustly: Redis down does not fail a committed write (Django logs the error), the message
is lost.
"""

import json
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import translation

from . import COMMON_CHANNEL, models_abstract


def _publish(channel: str, payload: str) -> None:
    models_abstract.redis.publish(channel, payload)


def _after_commit(channel: str, message: dict) -> None:
    # serialized now: the lazy strings are translated in the active language, and the
    # callback publishes the values of the moment of the call
    payload = json.dumps(message, cls=DjangoJSONEncoder)
    transaction.on_commit(partial(_publish, channel, payload), robust=True)


def notification(title: Any, text: Any = None, item: Any = None) -> dict:
    """
    A notification of bazis-front: `{"action": "notification", "title", "text", "resource",
    "id"}`, with the JSON:API type and the id of the item it is about (the frontend also
    refetches it). The texts may be lazy strings: `notify` translates them in the language of
    each recipient.
    """
    message = {'action': 'notification', 'title': title}
    if text is not None:
        message['text'] = text
    if item is not None:
        message['resource'] = item.get_resource_label()
        message['id'] = str(item.pk)
    return message


def notify(users: Any, message: Callable[[Any], dict]) -> None:
    """
    Publishes to the channel of each user (`UserWsMixin`) the message built for him by
    `message(user)`, after the commit. The message is built and serialized in the language of
    the user: `user.language` (`UserLanguageMixin` of bazis-users) or LANGUAGE_CODE. `users` is
    a user or an iterable of users; None and the repeated users are skipped. Send to the users
    who may see what the message says, never to the common channel.
    """
    if users is None:
        return
    if not isinstance(users, Iterable):
        users = [users]
    notified = set()
    for user in users:
        if user is None or user.pk in notified:
            continue
        notified.add(user.pk)
        with translation.override(getattr(user, 'language', None) or settings.LANGUAGE_CODE):
            _after_commit(user.user_channel, message(user))


def publish_changed(item: Any) -> None:
    """
    Tells every user session that the resource of the item (a model instance or class with
    `JsonApiMixin`) changed: `{"resource": "<JSON:API type>"}` on the common channel, after the
    commit. Without the id: the common channel reaches every user (and the anonymous sessions
    with BAZIS_WS_ANONYMOUS_COMMON_CHANNEL), the pages refetch with their own permissions.
    """
    _after_commit(COMMON_CHANNEL, {'resource': item.get_resource_label()})
