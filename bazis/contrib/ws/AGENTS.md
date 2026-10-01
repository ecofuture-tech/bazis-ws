# bazis-ws — guide for AI agents

WebSocket notifications for Bazis: clients connect to `/ws`, the server delivers to them
the messages published to Redis channels (the channel of a user, the channel of an
anonymous client, the common channel) and keeps an online flag per session. Use it to push
events to browsers; bazis-async-background sends its task statuses through it.

## Setup

- Not a Django app: nothing to add to `BS_INSTALLED_APPS`, no settings of its own.
- Redis: `settings.CACHES['default']['LOCATION']` (`BS_CACHES__DEFAULT__LOCATION`) must be
  a Redis URL; it is the pub/sub server.
- The user model gets the user channel and the online flag:

  ```python
  from bazis.contrib.ws.models_abstract import UserWsMixin

  class User(UserWsMixin, ..., UserAbstract, JsonApiMixin):   # see bazis-users
      pass
  ```

- Register the socket on the FastAPI application (it is a Starlette route, not a
  `BazisRouter` route, so the path is `/ws` without the API prefix):

  ```python
  from bazis.contrib.ws.ws import ws_route
  from bazis.core.app import app

  app.router.routes.append(ws_route)
  ```

## Protocol

- The client starts a session with `?token=<token>` or the message `{"token": "<token>"}`.
  A session JWT of bazis-users (`exp` and `sub` required, signed with `SECRET_KEY` and
  `BAZIS_JWT_SESSION_ALG`, default HS256) of an active user subscribes to `user_ws::<pk>`.
  Any other token is an anonymous token: 16–128 characters `A-Z a-z 0-9 _ -`, generated
  randomly by the client; it subscribes to `user_ws:anon:<token>`. Every session also
  receives `user_ws:common`.
- Server messages: `{"type": "data", "data": <published string>}` (the published JSON is
  delivered as a string: parse it on the client), `{"type": "pong"}` for
  `{"type": "ping"}`, `{"type": "error", "code": ..., "detail": ...}` with the codes
  `expired_token`, `invalid_token`, `user_not_found`, `internal_error`.
- If Redis fails during a session the socket is closed with code 1011; clients reconnect.

## Publishing

- To a user: `user.ws_publish({...})` (synchronous Redis, returns the number of
  receivers). `user.is_online` is true while a session of the user is open.
- To an anonymous client: publish to `get_anonymous_channel(token)` of
  `bazis.contrib.ws.utils`; to everybody: publish to `bazis.contrib.ws.COMMON_CHANNEL`.
- Pub/sub is not stored: a message published while the client is not subscribed is lost.

## Rules

- Never build a channel name from client input by hand: use `get_anonymous_channel`
  (validates the token, keeps anonymous channels under `user_ws:anon:`) and
  `user.user_channel`. An anonymous token must never address a user channel.
- The user is read by the fields `username` and `is_active` of the user model.
- The token is checked when the session starts; a session is not closed when its JWT
  expires later.
- `UserWsRouteSet` (`bazis.contrib.ws.routes_abstract`) extends the user routes of
  bazis-users with `is_online`; it needs bazis-users, which bazis-ws does not install.
  `is_online` reads Redis once per object.
