# bazis-ws — guide for AI agents

WebSocket notifications for Bazis: clients connect to `/ws`, the server delivers to them
the messages published to Redis channels (the channel of a user, the channel of an
anonymous client, the common channel of the user sessions) and keeps an online flag per
session. Use it to push
events to browsers; bazis-async-background sends its task statuses through it.

## Setup

- Not a Django app: nothing to add to `BS_INSTALLED_APPS`. One setting (`conf.py`, loaded
  with the settings of the installed Bazis packages): `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL`
  (default `false`), whether anonymous sessions receive the common channel.
- Redis: `settings.CACHES['default']['LOCATION']` (`BS_CACHES__DEFAULT__LOCATION`) must be
  a Redis URL; it is the pub/sub server.
- The user model gets the user channel and the online flag:

  ```python
  from bazis.contrib.ws.models_abstract import UserWsMixin

  class User(UserWsMixin, ..., UserAbstract, JsonApiMixin):   # see bazis-users
      pass
  ```

- Register the socket in the router module of the project (`BS_BAZIS_ROUTER_MODULE`). It
  is a Starlette route, not a `BazisRouter` route: appended to the routes of the root
  router, it keeps its path `/ws` without the API prefix, and `bazis.core.app` includes it
  with the router:

  ```python
  from bazis.contrib.ws.ws import ws_route
  from bazis.core.routing import BazisRouter

  router = BazisRouter(prefix='/api/v1')
  router.routes.append(ws_route)
  ```

  Tools import the router module, not the main module (the contract export of bazis-front
  finds the socket there). `app.router.routes.append(ws_route)` in the main module works at
  runtime, but the tools do not see the socket.

## Protocol

- The client starts a session with `?token=<token>` or the message `{"token": "<token>"}`.
  A session JWT of bazis-users (`exp` and `sub` required, signed with `SECRET_KEY` and
  `BAZIS_JWT_SESSION_ALG`, default HS256) of an active user subscribes to `user_ws::<pk>`.
  Any other token is an anonymous token: 16–128 characters `A-Z a-z 0-9 _ -`, generated
  randomly by the client; it subscribes to `user_ws:anon:<token>`. User sessions also
  receive `user_ws:common`; anonymous sessions only with
  `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true` (anybody can open one).
- Server messages: `{"type": "subscribed"}` once the subscription of the session is
  active (after each accepted token; the messages published from then on are delivered),
  `{"type": "data", "data": <published string>}` (the published JSON is delivered as a
  string: parse it on the client), `{"type": "pong"}` for `{"type": "ping"}`,
  `{"type": "error", "code": ..., "detail": ...}` with the codes `expired_token`,
  `invalid_token`, `user_not_found`, `internal_error`.
- Close codes: after a refused token (`expired_token`, `invalid_token`, `user_not_found`)
  the socket is closed with 1008: connect again only with another token. After
  `internal_error`, or if Redis fails during a session, it is closed with 1011: clients
  reconnect with a growing delay. A socket is never left open without a session that
  delivers; the messages the client sent after the close are ignored.

## Publishing

- To a user: `user.ws_publish({...})` (synchronous Redis, returns the number of
  receivers). `user.is_online` is true while a session of the user is open.
- To an anonymous client: publish to `get_anonymous_channel(token)` of
  `bazis.contrib.ws.utils`.
- To all user sessions: publish to `bazis.contrib.ws.COMMON_CHANNEL` only what every user
  may know: `{"resource": "<JSON:API type>"}`, that a resource changed, without the id
  (the format of bazis-front; the pages refetch with their own permissions). The ids, the
  notifications and the data of an item go only to the users who may see it, with
  `user.ws_publish(...)`. With `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true` the common
  channel is public: enable it only if what the project publishes there is.
- Pub/sub is not stored: a message published while the client is not subscribed is lost.
- From a write (`hook_after_create`, `hook_after_update`, the relationships hooks, an
  action of a transit: inside the transaction of the request) publish after the commit,
  robustly: a client that refetched before the commit would read the old data, a rolled
  back write must not notify, and Redis down must not fail a committed write (Django logs
  the error). Not from `validate_item`: it may run more than once for one write. Bind the
  values when the callback is made (`functools.partial`), not in a closure over a loop
  variable, or every callback publishes the last one:

  ```python
  from functools import partial

  for user in recipients:
      transaction.on_commit(partial(user.ws_publish, message_for(user)), robust=True)
  ```

- A notification of bazis-front (`@/bazis/react/ws`) to the users who may see the item:
  `{"action": "notification", "title": ..., "text": ..., "resource": "<JSON:API type>",
  "id": "<id>"}`. Build its texts in the language of each user before `on_commit`, with
  `str()` of the lazy strings inside `translation.override(user.language or
  settings.LANGUAGE_CODE)` (`language` of `UserLanguageMixin` of bazis-users).

## Rules

- Never build a channel name from client input by hand: use `get_anonymous_channel`
  (validates the token, keeps anonymous channels under `user_ws:anon:`) and
  `user.user_channel`. An anonymous token must never address a user channel, nor (by
  default) the common channel.
- The user is read by the fields `username` and `is_active` of the user model.
- The token is checked when the session starts; a session is not closed when its JWT
  expires later.
- `UserWsRouteSet` (`bazis.contrib.ws.routes_abstract`) extends the user routes of
  bazis-users with `is_online`; it needs bazis-users, which bazis-ws does not install.
  `is_online` reads Redis once per object.
