from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

from bazis.contrib.ws.models_abstract import UserWsMixin
from bazis.core.models_abstract import JsonApiMixin


class User(UserWsMixin, JsonApiMixin, AbstractUser):
    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')

