
import json

from django.conf import settings

from redis import Redis

from bazis.core.models_abstract import InitialBase

from . import WS_PREFIX


redis = Redis.from_url(settings.CACHES['default']['LOCATION'])


class UserWsMixin(InitialBase):
    """
    Mixin for supporting user websockets
    """
    class Meta:
        abstract = True

    @property
    def user_channel(self) -> str:
        return f'{WS_PREFIX}:{self.pk}'

    @property
    def ws_session(self):
        return f'{WS_PREFIX}:{self.pk}:session'

    @property
    def is_online(self) -> bool:
        return bool(redis.get(self.ws_session))

    def ws_publish(self, data: dict) -> int:
        """
        Publishing a message to the user's channel
        """
        return redis.publish(self.user_channel, json.dumps(data))
