# Bazis WS

[![PyPI version](https://img.shields.io/pypi/v/bazis-ws.svg)](https://pypi.org/project/bazis-ws/)
[![Python Versions](https://img.shields.io/pypi/pyversions/bazis-ws.svg)](https://pypi.org/project/bazis-ws/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Extension package for Bazis, providing WebSocket connections with authentication support, Redis pub/sub, and user online status tracking.

## Quick Start

```bash
uv add bazis-ws
```

```python
# Add mixin to user model
from django.contrib.auth.models import AbstractUser
from bazis.contrib.ws.models_abstract import UserWsMixin
from bazis.core.models_abstract import JsonApiMixin

class User(UserWsMixin, JsonApiMixin, AbstractUser):
    """User with WebSocket support"""
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

# Register the WebSocket route in the router module of the project (BS_BAZIS_ROUTER_MODULE)
from bazis.contrib.ws.ws import ws_route
from bazis.core.routing import BazisRouter

router = BazisRouter(prefix='/api/v1')
router.routes.append(ws_route)  # appended as it is, the route keeps its path: /ws
```

## Table of Contents

- [Description](#description)
- [Requirements](#requirements)
- [Installation](#installation)
- [Core Components](#core-components)
  - [UserWsMixin](#userwsmixin)
  - [WsEndpoint](#wsendpoint)
  - [Architecture](#architecture)
- [Usage](#usage)
  - [Project Setup](#project-setup)
  - [Connecting to WebSocket](#connecting-to-websocket)
  - [Sending Messages to Users](#sending-messages-to-users)
  - [Checking Online Status](#checking-online-status)
- [WebSocket Protocol](#websocket-protocol)
- [Examples](#examples)
- [License](#license)
- [Links](#links)

## Description

**Bazis WS** is an extension package for the Bazis framework that provides a fully-featured WebSocket communication system. The package includes:

- **UserWsMixin** — mixin for user model with WebSocket support
- **WsEndpoint** — ready-to-use WebSocket endpoint with JWT authentication
- **Redis Pub/Sub** — messaging system between servers and clients
- **Online Status Tracking** — automatic detection of online/offline users
- **Personal Channels** — each user has their own channel for receiving messages
- **Common Channel** — for broadcasting messages to all connected users (not to anonymous
  sessions unless `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true`)

**This package requires installation of `bazis` and a running Redis server.**

## Requirements

- **Python**: 3.12+
- **bazis**: latest version
- **PostgreSQL**: 12+
- **Redis**: For pub/sub and caching
- **Additional libraries**:
  - `PyJWT` — for JWT handling
  - `psycopg[binary]` — for asynchronous PostgreSQL access
  - `redis` — for Redis operations

## Installation

### Using uv (recommended)

```bash
uv add bazis-ws
```

### Using pip

```bash
pip install bazis-ws
```

## Core Components

### UserWsMixin

Mixin for user model that adds WebSocket support.

**Location**: `bazis.contrib.ws.models_abstract.UserWsMixin`

**Properties**:

- `user_channel` — user's personal channel in Redis (format: `user_ws::{user_id}`)
- `ws_session` — WebSocket session key in Redis (format: `user_ws::{user_id}:session`)
- `is_online` — boolean property indicating whether the user is connected to WebSocket

**Methods**:

- `ws_publish(data: dict) -> int` — send message to user via their personal channel

**Usage Example**:

```python
from django.contrib.auth.models import AbstractUser
from bazis.contrib.ws.models_abstract import UserWsMixin
from bazis.core.models_abstract import JsonApiMixin

class User(UserWsMixin, JsonApiMixin, AbstractUser):
    """User with WebSocket support"""
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
```

### WsEndpoint

WebSocket endpoint with authentication and session management support.

**Location**: `bazis.contrib.ws.ws.WsEndpoint`

**Based on**: `starlette.endpoints.WebSocketEndpoint`

**Key Features**:

1. **JWT Token Authentication**:
   - On connection: `ws://api.example.com/ws?token=<jwt_token>`
   - During session: sending `{"token": "<jwt_token>"}`
   - The token must be a valid, unexpired session token (`exp` and `sub` are required)
     of an active user.

   **Anonymous clients** send a token they generate themselves instead of a JWT:
   16–128 characters `A-Z a-z 0-9 _ -` (e.g. a random UUID). The token is the only
   secret protecting the channel, so it must be random. It subscribes to the channel
   `user_ws:anon:<token>`, which can never be the channel of a user or the common channel.
   Anybody can open an anonymous session, so by default it does not receive the common
   channel (see [Common Channel](#common-channel)).

2. **Automatic Online Status Tracking**:
   - Status update every 5 seconds
   - Redis entry TTL: 10 seconds

3. **Channel Subscription**:
   - User's personal channel (or the channel of the anonymous token)
   - Common channel: user sessions; anonymous sessions only with
     `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true`
   - `{"type": "subscribed"}` is sent once the subscription is active: the messages
     published from then on are delivered (pub/sub keeps nothing published before)

4. **Ping/Pong**:
   - Client sends `{"type": "ping"}`
   - Server responds `{"type": "pong"}`

**Connection Lifecycle**:

```python
1. on_connect()      → accept connection
2. session_start()   → authenticate and start background tasks
   ├─ task_online_update()    → update online status
   └─ task_listen_queue()     → listen to Redis channels
3. on_receive()      → handle incoming messages
4. on_disconnect()   → cleanup resources
5. session_stop()    → stop background tasks
```

### Architecture

```
┌─────────────┐                    ┌──────────────┐
│   Client    │◄──WebSocket───────►│  WsEndpoint  │
│ (Browser/   │                    │              │
│  Mobile)    │                    │  Starlette   │
└─────────────┘                    └───────┬──────┘
                                           │
                                           │ JWT Auth
                                           ▼
                                    ┌──────────────┐
                                    │  PostgreSQL  │
                                    │  (User DB)   │
                                    └──────────────┘
                                           │
                                           │
                                           ▼
┌─────────────┐                    ┌──────────────┐
│   Backend   │────publish────────►│    Redis     │
│   Service   │                    │   Pub/Sub    │
└─────────────┘                    └───────┬──────┘
                                           │
                                           │ subscribe
                                           ▼
                                    ┌──────────────┐
                                    │  WsEndpoint  │
                                    │              │
                                    └───────┬──────┘
                                           │
                                           │ send_json
                                           ▼
                                    ┌──────────────┐
                                    │   Client     │
                                    └──────────────┘
```

**Redis Channels**:

- `user_ws::{user_id}` — user's personal channel
- `user_ws:common` — common channel of the user sessions (and of the anonymous sessions
  with `BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true`)
- `user_ws::{user_id}:session` — active session key (TTL: 10 seconds)
- `user_ws:anon:{token}` — channel of an anonymous client (and `...:session`, its session key)

A session that cannot run closes the socket (see [Close Codes](#close-codes)): code `1008`
after a refused token, code `1011` when the server fails (the session start, or Redis
while the session is running) so that the client reconnects.

## Usage

### Project Setup

**1. Add mixin to user model**:

```python
# models.py
from django.contrib.auth.models import AbstractUser
from bazis.contrib.ws.models_abstract import UserWsMixin
from bazis.core.models_abstract import JsonApiMixin

class User(UserWsMixin, JsonApiMixin, AbstractUser):
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
```

**2. Add `is_online` field to user routes**:

```python
# routes.py
from bazis.contrib.ws.routes_abstract import UserWsRouteSet
from django.apps import apps

class UserRouteSet(UserWsRouteSet):
    model = apps.get_model('myapp.User')
```

**3. Register WebSocket route** in the router module of the project, the module of
`BS_BAZIS_ROUTER_MODULE`:

```python
# router.py
from bazis.contrib.ws.ws import ws_route
from bazis.core.routing import BazisRouter

router = BazisRouter(prefix='/api/v1')
router.routes.append(ws_route)  # appended as it is, the route keeps its path: /ws

router.register('myapp.router')
```

`ws_route` is a Starlette `WebSocketRoute`, not a `BazisRouter` route: appended to the
routes of the root router, it keeps its path `/ws` (the prefix of the router is not applied),
and `bazis.core.app` includes it with the router. Tools import the router module, not the
main module of the project: the contract export of bazis-front finds the socket there.
Appending the route to `app.router.routes` in the main module also works at runtime, but
the tools do not see it.

### Connecting to WebSocket

#### JavaScript Client

```javascript
class WebSocketClient {
  constructor(url, token) {
    this.url = url;
    this.token = token;
    this.ws = null;
    this.reconnectInterval = 5000;
    this.pingInterval = 30000;
    this.pingTimer = null;
  }

  connect() {
    this.ws = new WebSocket(`${this.url}?token=${this.token}`);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.startPing();
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = (event) => {
      console.log('WebSocket disconnected');
      this.stopPing();
      // 1008: the token was refused, the same token would be refused again
      if (event.code === 1008) return;
      // Reconnect (use a growing delay in production)
      setTimeout(() => this.connect(), this.reconnectInterval);
    };
  }

  handleMessage(data) {
    switch (data.type) {
      case 'pong':
        console.log('Received pong');
        break;
      case 'subscribed':
        // the messages published from now on are delivered: refetch what may have changed
        console.log('Subscribed');
        break;
      case 'data':
        console.log('Received data:', data.data);
        // Process received data
        this.onData(data.data);
        break;
      case 'error':
        // the server closes the socket after it: 1008 (a refused token) or 1011
        console.error('Error:', data.code, data.detail);
        break;
      default:
        console.log('Unknown message type:', data);
    }
  }

  startPing() {
    this.pingTimer = setInterval(() => {
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, this.pingInterval);
  }

  stopPing() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  onData(data) {
    // Override this method to handle data
    console.log('Data received:', data);
  }

  disconnect() {
    this.stopPing();
    if (this.ws) {
      this.ws.close();
    }
  }
}

// Usage
const ws = new WebSocketClient('ws://api.example.com/ws', jwtToken);
ws.onData = (data) => {
  console.log('Processing data:', data);
  // Your processing logic
};
ws.connect();
```

#### Python Client

```python
import asyncio
import json
import websockets

async def websocket_client(url, token):
    uri = f"{url}?token={token}"
    
    async with websockets.connect(uri) as websocket:
        print("WebSocket connected")
        
        # Background task for ping
        async def send_ping():
            while True:
                await asyncio.sleep(30)
                await websocket.send(json.dumps({"type": "ping"}))
        
        ping_task = asyncio.create_task(send_ping())
        
        try:
            async for message in websocket:
                data = json.loads(message)
                
                if data['type'] == 'pong':
                    print("Received pong")
                elif data['type'] == 'subscribed':
                    print("Subscribed")
                elif data['type'] == 'data':
                    print(f"Received data: {data['data']}")
                elif data['type'] == 'error':
                    print(f"Error: {data['code']} - {data['detail']}")
        finally:
            ping_task.cancel()

# Usage
asyncio.run(websocket_client('ws://api.example.com/ws', jwt_token))
```

### Sending Messages to Users

#### From Django View or API Endpoint

```python
from django.contrib.auth import get_user_model

User = get_user_model()

def send_notification_to_user(user_id, message):
    """Send notification to specific user"""
    user = User.objects.get(id=user_id)
    
    if user.is_online:
        user.ws_publish({
            'type': 'notification',
            'title': 'New Notification',
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        return True
    return False
```

#### From Celery Task

```python
from celery import shared_task
from django.contrib.auth import get_user_model

User = get_user_model()

@shared_task
def notify_user_async(user_id, notification_data):
    """Asynchronously send notification to user"""
    try:
        user = User.objects.get(id=user_id)
        user.ws_publish({
            'type': 'task_completed',
            'data': notification_data
        })
    except User.DoesNotExist:
        pass
```

#### Common Channel

The common channel `user_ws:common` (`bazis.contrib.ws.COMMON_CHANNEL`) reaches every user
session, whatever the user may see. Publish there only what every user may know: that a
resource changed, `{"resource": "<JSON:API type>"}`, without the id of the item (the format
of bazis-front, whose pages then refetch the resource with their own permissions). Send the
ids, the notifications and any data of an item only to the users who may see it,
with `user.ws_publish(...)`.

```python
import json

from django.conf import settings

from redis import Redis

from bazis.contrib.ws import COMMON_CHANNEL

redis = Redis.from_url(settings.CACHES['default']['LOCATION'])

def resource_changed(resource: str):
    """Tell all user sessions that a resource changed"""
    redis.publish(COMMON_CHANNEL, json.dumps({'resource': resource}))
```

Anonymous sessions do not receive the common channel: an anonymous token is generated by
the client, so anybody can open such a session. Set
`BS_BAZIS_WS_ANONYMOUS_COMMON_CHANNEL=true` only if what the project publishes on the
common channel is public (for example, pages that anonymous visitors see refresh on the
`{"resource"}` messages).

### Checking Online Status

#### In Django Template

```python
from django.contrib.auth import get_user_model

User = get_user_model()

def user_list_view(request):
    users = User.objects.all()
    
    online_users = [user for user in users if user.is_online]
    offline_users = [user for user in users if not user.is_online]
    
    return render(request, 'users.html', {
        'online_users': online_users,
        'offline_users': offline_users
    })
```

#### Via API (using UserWsRouteSet)

```bash
GET /api/v1/<app>/<resource>/
Authorization: Bearer <token>
```

**Response**:
```json
{
  "data": [
    {
      "type": "app.user",
      "id": "123",
      "attributes": {
        "username": "john_doe",
        "email": "john@example.com",
        "is_online": true
      }
    }
  ]
}
```

## WebSocket Protocol

### Messages from Client

#### Ping

```json
{
  "type": "ping"
}
```

#### Authentication During Session

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### Messages from Server

#### Subscribed

Sent once the subscription of the session is active (after each accepted token): the
messages published from then on are delivered.

```json
{
  "type": "subscribed"
}
```

#### Pong

```json
{
  "type": "pong"
}
```

#### Data

```json
{
  "type": "data",
  "data": {
    "type": "notification",
    "title": "New Message",
    "message": "You have a new message from admin"
  }
}
```

#### Error

```json
{
  "type": "error",
  "code": "expired_token",
  "detail": "Token expired"
}
```

**Error Codes**:

- `expired_token` — JWT token has expired
- `invalid_token` — the JWT is invalid, or the anonymous token does not match the format
- `user_not_found` — user not found in database or inactive
- `internal_error` — the session could not be started

### Close Codes

The server closes the socket of a session that cannot run, after the error message if
there is one:

- `1008` (policy violation) — the token was refused (`expired_token`, `invalid_token`,
  `user_not_found`): connect again only with another token (a refreshed session token).
- `1011` (internal error) — the session could not be started (`internal_error`), or Redis
  failed while it was running: reconnect with a growing delay.

The messages that the client sends after the server closed the socket are ignored.

## Examples

### Real-time Chat Example

**Backend (sending message)**:

```python
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json

User = get_user_model()

@require_POST
def send_message(request):
    data = json.loads(request.body)
    recipient_id = data.get('recipient_id')
    message = data.get('message')
    
    try:
        recipient = User.objects.get(id=recipient_id)
        
        # Send message via WebSocket
        if recipient.is_online:
            recipient.ws_publish({
                'type': 'chat_message',
                'sender': {
                    'id': str(request.user.id),
                    'username': request.user.username
                },
                'message': message,
                'timestamp': datetime.now().isoformat()
            })
            return JsonResponse({'status': 'sent'})
        else:
            # Save offline message
            return JsonResponse({'status': 'saved_offline'})
            
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
```

**Frontend (receiving message)**:

```javascript
class ChatClient extends WebSocketClient {
  onData(data) {
    if (data.type === 'chat_message') {
      this.displayMessage(data.sender, data.message, data.timestamp);
    }
  }

  displayMessage(sender, message, timestamp) {
    const messageElement = document.createElement('div');
    messageElement.className = 'chat-message';
    messageElement.innerHTML = `
      <div class="sender">${sender.username}</div>
      <div class="message">${message}</div>
      <div class="timestamp">${new Date(timestamp).toLocaleString()}</div>
    `;
    document.getElementById('chat-messages').appendChild(messageElement);
  }
}

const chat = new ChatClient('ws://api.example.com/ws', jwtToken);
chat.connect();
```

### Task Notification Example

**Celery Task**:

```python
from celery import shared_task
from django.contrib.auth import get_user_model

User = get_user_model()

@shared_task
def process_long_running_task(user_id, task_data):
    """Long-running task with user notification"""
    user = User.objects.get(id=user_id)
    
    # Notify about start
    user.ws_publish({
        'type': 'task_started',
        'task_id': process_long_running_task.request.id,
        'message': 'Processing started...'
    })
    
    try:
        # Execute task
        result = perform_processing(task_data)
        
        # Notify about success
        user.ws_publish({
            'type': 'task_completed',
            'task_id': process_long_running_task.request.id,
            'result': result,
            'message': 'Processing completed successfully'
        })
        
    except Exception as e:
        # Notify about error
        user.ws_publish({
            'type': 'task_failed',
            'task_id': process_long_running_task.request.id,
            'error': str(e),
            'message': 'An error occurred during processing'
        })
```

### Online Indicator Example

**JavaScript Component**:

```javascript
class OnlineIndicator {
  constructor(userId) {
    this.userId = userId;
    this.indicator = document.getElementById(`user-${userId}-status`);
  }

  async checkStatus() {
    const response = await fetch(`/api/v1/users/user/${this.userId}/`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });
    
    const data = await response.json();
    const isOnline = data.data.attributes.is_online;
    
    this.updateIndicator(isOnline);
  }

  updateIndicator(isOnline) {
    if (isOnline) {
      this.indicator.classList.add('online');
      this.indicator.classList.remove('offline');
      this.indicator.textContent = 'Online';
    } else {
      this.indicator.classList.add('offline');
      this.indicator.classList.remove('online');
      this.indicator.textContent = 'Offline';
    }
  }
}

// Periodic status check
const indicator = new OnlineIndicator('user-123');
setInterval(() => indicator.checkStatus(), 10000);
```

## License

Apache License 2.0

See [LICENSE](LICENSE) file for details.

## Links

- [Bazis Documentation](https://github.com/ecofuture-tech/bazis) — main repository
- [Bazis WS Repository](https://github.com/ecofuture-tech/bazis-ws) — package repository
- [Issue Tracker](https://github.com/ecofuture-tech/bazis-ws/issues) — report bugs or request features
- [Starlette WebSockets](https://www.starlette.io/websockets/) — Starlette WebSocket documentation
- [Redis Pub/Sub](https://redis.io/docs/manual/pubsub/) — Redis Pub/Sub documentation

## Support

If you have questions or issues:
- Check the [Bazis documentation](https://github.com/ecofuture-tech/bazis)
- Search through [existing issues](https://github.com/ecofuture-tech/bazis-ws/issues)
- Create a [new issue](https://github.com/ecofuture-tech/bazis-ws/issues/new) with detailed information

---

Made with ❤️ by Bazis team
