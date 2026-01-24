from bazis.core.routing import BazisRouter

from . import routes


router = BazisRouter(tags=['Users'])
router.register(routes.UserRouteSet.as_router())
