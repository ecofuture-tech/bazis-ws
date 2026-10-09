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
The messages of bazis-front published from the code of a write (`bazis.contrib.ws.messages`).
"""

import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import translation
from django.utils.timezone import now
from django.utils.translation import gettext_lazy

import jwt
import pytest
from bazis_test_utils.utils import get_api_client

from bazis.contrib.ws import COMMON_CHANNEL
from bazis.contrib.ws.messages import notification, notify, publish_changed


#: a message of the Django catalogs, translated to Russian
REQUIRED = gettext_lazy('This field is required.')
REQUIRED_RU = 'Обязательное поле.'


class DummyRedis:
    def __init__(self):
        self.published = []

    def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))
        return 1


@pytest.fixture
def dummy_redis(monkeypatch):
    from bazis.contrib.ws import models_abstract

    redis = DummyRedis()
    monkeypatch.setattr(models_abstract, 'redis', redis)
    return redis


def _user(pk, language=None):
    user = get_user_model()(pk=pk, username=f'user{pk}')
    if language is not None:
        # the field of UserLanguageMixin of bazis-users
        user.language = language
    return user


def test_notification_format():
    """
    The format that bazis-front reads (`notificationOf` of `@/bazis/react/ws`).
    """
    item = _user(5)
    assert notification('Title', 'Text', item) == {
        'action': 'notification',
        'title': 'Title',
        'text': 'Text',
        'resource': 'entity.user',
        'id': '5',
    }
    assert notification('Title') == {'action': 'notification', 'title': 'Title'}


@pytest.mark.django_db(transaction=True)
def test_notify_in_the_language_of_each_user(dummy_redis):
    """
    The message is built and serialized in the language of each user (`language`, or
    LANGUAGE_CODE without one): lazy strings are translated per recipient.
    """
    ru_user, default_user = _user(1, language='ru'), _user(2)
    languages = {}

    def message(user):
        languages[user.pk] = translation.get_language()
        return notification(REQUIRED, item=_user(5))

    with transaction.atomic():
        notify([ru_user, default_user], message)
        # not before the commit
        assert dummy_redis.published == []

    assert languages == {1: 'ru', 2: settings.LANGUAGE_CODE}
    assert dummy_redis.published == [
        (
            ru_user.user_channel,
            {
                'action': 'notification',
                'title': REQUIRED_RU,
                'resource': 'entity.user',
                'id': '5',
            },
        ),
        (
            default_user.user_channel,
            {
                'action': 'notification',
                'title': 'This field is required.',
                'resource': 'entity.user',
                'id': '5',
            },
        ),
    ]


@pytest.mark.django_db(transaction=True)
def test_notify_recipients(dummy_redis):
    """
    A single user or an iterable; None and the repeated users are skipped.
    """
    first, second = _user(1), _user(2)

    notify(None, lambda user: notification('x'))
    notify(first, lambda user: notification(str(user.pk)))
    notify([first, None, second, _user(1)], lambda user: notification(str(user.pk)))

    assert dummy_redis.published == [
        (first.user_channel, {'action': 'notification', 'title': '1'}),
        (first.user_channel, {'action': 'notification', 'title': '1'}),
        (second.user_channel, {'action': 'notification', 'title': '2'}),
    ]


@pytest.mark.django_db(transaction=True)
def test_notify_rolled_back_and_redis_down(dummy_redis, monkeypatch):
    """
    A rolled back write publishes nothing; Redis down does not fail a committed write.
    """
    with pytest.raises(RuntimeError), transaction.atomic():
        notify(_user(1), lambda user: notification('x'))
        publish_changed(get_user_model())
        raise RuntimeError('rolled back')
    assert dummy_redis.published == []

    def fail(channel, payload):
        raise ConnectionError('Redis is down')

    monkeypatch.setattr(dummy_redis, 'publish', fail)
    with transaction.atomic():
        get_user_model().objects.create_user('committed')
        notify(_user(1), lambda user: notification('x'))
        publish_changed(get_user_model())
    assert get_user_model().objects.filter(username='committed').exists()


@pytest.mark.django_db(transaction=True)
def test_publish_changed(dummy_redis):
    """
    The hint on the common channel names the resource only, never the id.
    """
    item = _user(5)
    with transaction.atomic():
        publish_changed(item)
        publish_changed(get_user_model())
        assert dummy_redis.published == []
    assert dummy_redis.published == [
        (COMMON_CHANNEL, {'resource': 'entity.user'}),
        (COMMON_CHANNEL, {'resource': 'entity.user'}),
    ]


@pytest.mark.django_db(transaction=True)
def test_notify_delivered_to_the_socket(sample_app):
    """
    The user session receives the notification as the published JSON string.
    """
    from tests.test_ws import WS_PATH, _receive_subscribed

    user = get_user_model().objects.create_user('ws_user', password='weak_password_1')
    token = jwt.encode(
        {'sub': user.username, 'exp': now() + timedelta(hours=1)},
        settings.SECRET_KEY,
        algorithm='HS256',
    )

    with get_api_client(sample_app).client.websocket_connect(
        f'{WS_PATH}?token={token}'
    ) as websocket:
        _receive_subscribed(websocket)
        with transaction.atomic():
            notify(user, lambda user: notification('Changed', 'Details', user))
            publish_changed(user)

        received = [websocket.receive_json() for _ in range(2)]
        assert [message['type'] for message in received] == ['data', 'data']
        assert [json.loads(message['data']) for message in received] == [
            {
                'action': 'notification',
                'title': 'Changed',
                'text': 'Details',
                'resource': 'entity.user',
                'id': str(user.pk),
            },
            {'resource': 'entity.user'},
        ]
