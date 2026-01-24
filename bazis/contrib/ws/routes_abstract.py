from bazis.contrib.users.routes import UserRouteSet as UserRouteSetBase
from bazis.core.schemas import SchemaField, SchemaFields


class UserWsRouteSet(UserRouteSetBase):
    fields = {
        None: SchemaFields(
            include={
                'is_online': SchemaField(),
            },
        ),
    }
