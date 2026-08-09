# Extracting a module into its own service

This is the procedure the whole architecture exists to make cheap. Chat is used
as the worked example because it is the usual first candidate: WebSocket-heavy,
different scaling curve from the rest of the platform, and a self-contained data
set.

## Before you start

Confirm the module is actually extractable:

```bash
python manage.py check_boundaries --module chat
python manage.py service_map --methods
```

`check_boundaries` must be clean, and `service_map` tells you exactly what chat
depends on:

```
chat  depends on: accounts, matches, moderation, reports, subscriptions
```

Those five must be reachable from the new deployment. Nothing else.

## 1. Split the data

Chat owns four tables, all prefixed `chat_`:

```
chat_conversation
chat_conversation_member
chat_message
chat_message_reaction
```

There are no foreign keys out of that set except to `accounts_user`, and
`Conversation.match_id` is a `ServiceReference` — a bare UUID, not an FK. So the
tables move with a plain dump and restore:

```bash
pg_dump --table='chat_*' zynora | psql zynora_chat
```

The user FK is the only thing that needs a decision. Two options:

- **Shared identity database** (simplest): the chat service keeps read-only
  access to `accounts_user`.
- **Local user mirror** (fully independent): chat keeps its own `user_id` UUID
  column and resolves names through `services.accounts.get_user_ref()`, caching
  the result. The interface already returns exactly the fields needed for this.

## 2. Stand up the new deployment

The new service runs the same codebase with a reduced `INSTALLED_APPS`:

```python
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",   # if you chose the shared-identity option
    "apps.chat",
    "apps.api",        # serves /internal/
]

REMOTE_SERVICES = {
    "matches":       {"base_url": "http://core.internal:8000", "token": TOKEN},
    "moderation":    {"base_url": "http://core.internal:8000", "token": TOKEN},
    "reports":       {"base_url": "http://core.internal:8000", "token": TOKEN},
    "subscriptions": {"base_url": "http://core.internal:8000", "token": TOKEN},
}
```

Set `INTERNAL_SERVICE_TOKEN` on both sides. It is the only credential the RPC
layer accepts.

## 3. Point the core at the new service

In the core deployment, remove `apps.chat` from `INSTALLED_APPS` and add:

```python
REMOTE_SERVICES = {
    "chat": {"base_url": "http://chat.internal:8000", "token": TOKEN},
}
```

**No call site changes.** `services.chat.count_unread_conversations(user_id)`
still resolves — the registry now returns a `RemoteServiceClient` that POSTs to
`/internal/chat/count_unread_conversations/` and unwraps the result.

## 4. Move the WebSocket route

Delete the chat line from `config/routing.py` in the core and point nginx at the
new service:

```nginx
location /ws/chat/ {
    proxy_pass http://chat_service;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## 5. Bridge the event bus

This is the one step that needs real work. Today `publish()` dispatches
in-process; across a network it must reach both deployments.

Replace the dispatcher in `apps/common/events.py`:

```python
def publish(name, payload=None, actor_id=None):
    envelope = EventEnvelope(name=name, payload=payload or {}, actor_id=...)
    _dispatch_local(envelope)          # handlers in this deployment
    _broker.publish(name, envelope.to_dict())   # RabbitMQ / Kafka / SNS
    return envelope
```

Each deployment runs a consumer that feeds received envelopes back into
`_dispatch_local`. Producers and subscribers are untouched: `EventEnvelope` is
already a flat, JSON-serialisable dict, which is why the bus was written that
way from the start.

Chat subscribes to `MATCH_CREATED`, `MATCH_ENDED`, `USER_BANNED` and
`USER_DELETED`, and publishes `MESSAGE_SENT`, `MESSAGE_READ` and
`CONVERSATION_STARTED`. Those seven events are the full asynchronous contract.

## 6. Verify

```bash
python manage.py test tests.test_flows
```

The flow tests assert only through public contracts, so they pass unchanged
against the split deployment. If one fails, a boundary was violated somewhere the
static checker could not see it — that is the signal to look for.

## Recommended extraction order

Least entangled first:

1. **chat** — different scaling profile, clean data boundary
2. **notifications** — pure event consumer, depends on almost nothing
3. **payments** — regulatory isolation is worth having on its own
4. **matching** — CPU-bound, stateless, already pure functions
5. **recommendation** — read model, rebuildable from scratch at any time
6. **analytics** — read-only aggregates
7. **media** — object storage and CDN concerns

Keep `accounts`, `authentication` and `subscriptions` in the core the longest.
They are the shared kernel: identity and entitlement are on nearly every request
path, and a network hop there costs you everywhere at once.

## What not to do

- **Don't extract a module with a failing boundary check.** The checker is
  cheaper than the incident.
- **Don't add a synchronous dependency to break a cycle.** If two services need
  each other, one of them should be publishing an event instead.
- **Don't let a leaf service acquire dependencies.** `accounts`,
  `subscriptions`, `moderation` and `audit` must keep answering when the rest of
  the platform is down. `tests/test_boundaries.py` asserts this.
