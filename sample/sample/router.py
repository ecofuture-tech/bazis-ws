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

from bazis.contrib.ws.ws import ws_route
from bazis.core.routing import BazisRouter


router = BazisRouter(prefix='/api/v1')
# the socket is registered in the router module (BS_BAZIS_ROUTER_MODULE), which tools such as
# the contract export of bazis-front import; appended as it is, it keeps its path `/ws`
router.routes.append(ws_route)

router.register('entity.router')
