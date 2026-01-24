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

# Register WebSocket route
from bazis.core.app import app
from bazis.contrib.ws.ws import ws_route

app.router.routes.append(ws_route)
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
- **Common Channel** — for broadcasting messages to all connected users

**This package requires installation of `bazis` and a running Redis server.**

## Requirements

- **Python**: 3.12+
- **bazis**: latest version
- **PostgreSQL**: 12+
- **Redis**: For pub/sub and caching
- **Additional libraries**:
  - `python-jose` — for JWT handling
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

- `user_channel` — user's personal channel in Redis (format: `user_ws:{user_id}`)
- `ws_session` — WebSocket session key in Redis (format: `user_ws:{user_id}:session`)
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

2. **Automatic Online Status Tracking**:
   - Status update every 5 seconds
   - Redis entry TTL: 10 seconds

3. **Channel Subscription**:
   - User's personal channel
   - Common channel for all users

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

- `user_ws:{user_id}` — user's personal channel
- `user_ws:common` — common channel for all users
- `user_ws:{user_id}:session` — active session key (TTL: 10 seconds)

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

**3. Register WebSocket route**:

```python
# main.py or app.py
from bazis.core.app import app
from bazis.contrib.ws.ws import ws_route

app.router.routes.append(ws_route)
```

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

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      this.stopPing();
      // Reconnect
      setTimeout(() => this.connect(), this.reconnectInterval);
    };
  }

  handleMessage(data) {
    switch (data.type) {
      case 'pong':
        console.log('Received pong');
        break;
      case 'data':
        console.log('Received data:', data.data);
        // Process received data
        this.onData(data.data);
        break;
      case 'error':
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

#### Broadcasting to All Online Users

```python
from redis import Redis
from django.conf import settings
import json

redis = Redis.from_url(settings.CACHES['default']['LOCATION'])

def broadcast_message(message):
    """Send message to all connected users"""
    from bazis.contrib.ws import COMMON_CHANNEL
    
    redis.publish(COMMON_CHANNEL, json.dumps({
        'type': 'broadcast',
        'message': message
    }))
```

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
- `user_not_found` — user not found in database

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
