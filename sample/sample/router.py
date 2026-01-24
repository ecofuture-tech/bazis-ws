from bazis.core.routing import BazisRouter


router = BazisRouter(prefix='/api/v1')

router.register('entity.router')
