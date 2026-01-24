
from django.apps import apps

from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase
from bazis.core.schemas import SchemaField, SchemaFields


class UserRouteSet(JsonapiRouteBase):
    model = apps.get_model('entity.User')

    fields = {
        None: SchemaFields(
            include={
                'is_online': SchemaField(),
            },
        ),
    }
