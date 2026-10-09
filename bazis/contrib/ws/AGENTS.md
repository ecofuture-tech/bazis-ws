# bazis-ws — guide for AI agents

WebSocket notifications for Bazis: clients connect to the socket (`/api/v1/ws` under the
prefix of the project router), the server delivers to them the messages published to Redis
channels (the channel of a user, the channel of an anonymous client, the common channel of
the user sessions) and keeps an online flag per session. Use it to push events to browsers:
`notify` and `publish_changed` publish the messages of bazis-front after the commit;
bazis-async-background sends its task statuses through it.

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

- Register the socket in the router module of the project (`BS_BAZIS_ROUTER_MODULE`), like
  the routers of the apps; it is routed under the prefix of the router (`/api/v1/ws` here):

  ```python
  from bazis.core.routing import BazisRouter

  router = BazisRouter(prefix='/api/v1')
  router.register('bazis.contrib.ws.router')
  ```

  Tools import the router module, not the main module (the contract export of bazis-front
  finds the socket and its path there; the frontend connects to that path). Do not append
  `ws_route` by hand: `router.routes.append(ws_route)` (the path `/ws`, as before 2.6) still
  works, `app.router.routes.append(ws_route)` in the main module works at runtime but the
  tools do not see the socket.

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

- From the code of a write, use `bazis.contrib.ws.messages`; do not write a notifier of your
  own (a Redis client, `on_commit`, the language, the format of bazis-front):

  ```python
  from django.utils.translation import gettext_lazy as _

  from bazis.contrib.ws.messages import notification, notify, publish_changed

  # in hook_after_create / hook_after_update of the route, an action of a transit, save()
  notify(
      ticket.author,          # a user, an iterable of users (None and repeats skipped)
      lambda user: notification(
          _('New reply to ticket #%(number)s') % {'number': ticket.uniq_number},
          reply.body,         # the text, optional
          ticket,             # the item: "resource" and "id", optional
      ),
  )
  publish_changed(ticket)     # {"resource": "support.ticket"} to every user session
  ```

  Both publish after the commit of the current transaction (at once outside a transaction),
  robustly: a client that refetched before the commit would read the old data, a rolled
  back write publishes nothing, and Redis down does not fail a committed write (Django logs
  the error, the message is lost).
- `notify(users, message)` calls `message(user)` for each user and serializes the result
  inside `translation.override(user.language or settings.LANGUAGE_CODE)` (`language` of
  `UserLanguageMixin` of bazis-users; without the field, LANGUAGE_CODE): lazy strings, the
  `%` of a lazy string and translated fields read in the function are in the language of
  the recipient. The function is called at once, inside `notify` (only the publishing waits
  for the commit). The users need `UserWsMixin`;
  choose the recipients yourself (only the users who may see the item; skip the author of
  the change if he should not be told).
- `notification(title, text=None, item=None)` is the notification of bazis-front
  (`@/bazis/react/ws`): `{"action": "notification", "title", "text", "resource": "<JSON:API
  type>", "id": "<id>"}`; with an item the frontend also refetches it. Any other dict can
  be returned by the function: `user.ws_publish` delivers any JSON.
- `publish_changed(item)` (an instance or a model with `JsonApiMixin`) publishes
  `{"resource": "<JSON:API type>"}` on the common channel: the pages of bazis-front refetch
  the resource with their own permissions. It carries no id: the common channel reaches
  every user session (and every anonymous session with
  `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true`, enable it only if that is public). The ids,
  the notifications and the data of an item go only to the users who may see it.
- Not from `validate_item`: it may run more than once for one write.
- Low level: `user.ws_publish({...})` publishes at once (synchronous Redis, returns the
  number of receivers; wrap it in `transaction.on_commit(partial(...), robust=True)` from a
  write); `user.is_online` is true while a session of the user is open. To an anonymous
  client: publish to `get_anonymous_channel(token)` of `bazis.contrib.ws.utils`.
- Pub/sub is not stored: a message published while the client is not subscribed is lost.

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
