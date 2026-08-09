<img width="1366" height="625" alt="Screenshot From 2026-08-03 21-12-24" src="https://github.com/user-attachments/assets/22e6e902-1730-4f7d-94ad-b5b511b2db5e" />
# Zynora

A dating platform built as **21 independent service modules** inside one Django
repository. Each module owns its data, exposes a single public contract, and can
be lifted into its own deployment without rewriting call sites or migrations.

Compatibility scoring, verification, moderation, mobile-money payments and
real-time chat are all implemented not stubbed.

---

## Quick start

```bash
make install          # virtualenv + dependencies
cp .env.example .env  # defaults run with no external services
make migrate
make seed             # 30 demo members with profiles, likes and matches
make run              # http://localhost:8000
```

Demo accounts are printed by `make seed`; they all share one password.

Nothing above needs PostgreSQL, Redis or a mail server. SQLite, in-memory cache,
in-memory channel layer and console email are the defaults, so the whole platform
boots on a laptop. Set `DB_ENGINE=postgres` and `REDIS_URL=...` to switch.

---

## Architecture

### The rule

> A module's only public surface is `apps/<module>/interface.py`.
> Nothing else in it may be imported from outside.

That single rule is what makes the modules extractable. It is enforced, not
documented:

```bash
make boundaries
```

```
✓ 19 service modules checked — all boundaries clean.
```

`check_boundaries` fails the build if a module imports another module's
`models`, `services`, `forms`, `tasks`, `admin`, `serializers`, `views` or
`consumers`, or declares a ForeignKey across a service boundary.

### How modules talk

| Need | Mechanism | Example |
|------|-----------|---------|
| Read another module's data | Registry → interface | `services.profiles.get_match_payloads(ids)` |
| Tell the platform something happened | Event bus | `publish(Event.MATCH_CREATED, {...})` |
| Reference another module's record | `ServiceReference` UUID column | `match_id = ServiceReference("matches")` |

```python
from apps.common.registry import services

ref = services.accounts.get_user_ref(user_id)   # a dict, never an ORM object
```

Three properties follow from this:

1. **No cross-module foreign keys.** `AUTH_USER_MODEL` is the one shared kernel;
   everything else is a bare UUID. A module's tables can move to their own
   database without touching a migration.
2. **Wire-safe contracts.** Interface methods take and return primitives, UUIDs
   and plain dicts, so the same call works locally or over HTTP.
3. **Failure isolation.** A broken event subscriber is logged, never raised into
   the producer. A payment cannot fail because a notification handler threw.

### Extracting a module

Add it to `REMOTE_SERVICES` and deploy it separately:

```python
REMOTE_SERVICES = {
    "chat": {"base_url": "http://chat.internal:8000", "token": "..."},
}
```

The registry now returns a `RemoteServiceClient` instead of the local interface.
Every existing call site — `services.chat.count_unread_conversations(user_id)` —
is unchanged. The receiving deployment serves `/internal/<service>/<method>/`
(see `apps/api/internal.py`), which applies the arguments and returns the result.

### The dependency graph

```
make boundaries
```

```
accounts         depends on: —          ← identity, the root
subscriptions    depends on: —          ← entitlements resolve without anyone
moderation       depends on: —          ← screening works when all else is down
audit            depends on: —          ← listens to events only

authentication   depends on: accounts, notifications
profiles         depends on: accounts, moderation
onboarding       depends on: accounts, profiles
matching         depends on: profiles, accounts
matches          depends on: accounts, matching, chat
likes            depends on: accounts, matching, matches, subscriptions, reports
chat             depends on: accounts, matches, moderation, reports, subscriptions
discovery        depends on: accounts, profiles, matching, likes, matches, reports
recommendation   depends on: accounts, profiles, matching, likes, matches, reports
notifications    depends on: accounts, chat, subscriptions
payments         depends on: accounts
verification     depends on: accounts, authentication, moderation, notifications
reports          depends on: accounts, moderation, subscriptions
security         depends on: authentication, profiles, notifications
analytics        depends on: (everything — read-only aggregates)
```

The four leaf services are deliberate: they are the ones that must keep working
when something else is down.

---

## The modules

| Module | Owns |
|--------|------|
| `accounts` | Identity, devices, account settings |
| `authentication` | Credentials, sessions, JWT, TOTP MFA, social login |
| `profiles` | Profile data, photos, interests, match preferences |
| `onboarding` | Six-step signup wizard |
| `discovery` | The candidate feed (owns no tables) |
| `matching` | Compatibility engine — pure functions, no ORM |
| `likes` | Swipe intents and daily quotas |
| `matches` | Mutual connections |
| `chat` | Conversations, messages, WebSockets |
| `notifications` | In-app, email, push, SMS delivery |
| `subscriptions` | Plans, entitlements, coupons |
| `payments` | Providers, webhooks, invoices, refunds |
| `verification` | Email, phone, selfie, government ID |
| `moderation` | Content screening, trust scores, review queue |
| `reports` | Abuse reports, blocks, support tickets |
| `analytics` | Daily metrics, funnels, dashboard |
| `recommendation` | Precomputed ranked picks |
| `security` | Anomaly detection, rate limits, IP reputation |
| `audit` | Immutable action log |
| `api` | REST gateway + internal RPC |
| `common` | Shared kernel: base models, events, registry |

---

## The matching engine

`apps/matching/engine.py` is pure functions over dicts — no Django, no ORM, no
other module. Six weighted dimensions produce a 0–100 score:

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Distance | 0.25 | Square-root decay to the seeker's stated maximum |
| Interests | 0.25 | Jaccard overlap, with a bonus for any overlap |
| Age | 0.15 | Peaks mid-band, degrades outside it |
| Lifestyle | 0.15 | Smoking, drinking, children, religion, languages |
| Goals | 0.12 | Relationship intent; `unsure` is not a mismatch |
| Activity | 0.08 | Completeness, photos, recency |

Weights live in `settings.ZYNORA["MATCH_SCORE_WEIGHTS"]` and are tunable without
a deploy. Every score is explainable — `/matching/explain/<user_id>/` shows the
per-dimension breakdown a member actually sees.

Hard filters (gender, age band, distance, photos, verification) run *before*
scoring and are separate from it, so an excluded candidate is never "almost" a
match.

---

## Roles and access control

Access is **capability-based**, never a role check scattered through views and
templates. The vocabulary lives in `apps/common/constants.Capability`; the
policy — who holds what — lives in one table in `apps/accounts/roles.py`.

| Role | Capabilities |
|------|--------------|
| `member` | none |
| `support` | handle support, review reports, view member detail |
| `analyst` | view analytics |
| `moderator` | moderate content, review reports + verifications, shadow ban, suspend, support |
| `admin` | everything, including audit trail, security ops, role management, refunds, Django admin |

A Django superuser holds every capability — that is what superuser means, and
pretending otherwise only pushes people to bypass the module.

```bash
python manage.py set_role alice@example.com moderator
python manage.py set_role --list     # who has what
python manage.py set_role --roles    # the full matrix
```

Three properties this buys:

- **The sidebar cannot leak a link.** `staff_nav` is computed from the
  requester's capabilities in a context processor; the template just loops over
  a list that is empty for an ordinary member. There is no role logic in any
  template.
- **A new staff screen cannot be added without declaring who may see it** —
  `STAFF_NAVIGATION` pairs every entry with its required capability, and a test
  asserts every entry resolves to a real URL.
- **Role changes are audited.** `set_role` publishes `ROLE_CHANGED`, which the
  audit service records like any other privileged action.

Enforcement is at three layers and tested at all three: `CapabilityRequiredMixin`
on pages, capability permission classes on the API, and the computed navigation
in the UI. `tests/test_roles.py` asserts each role reaches exactly its own
surface and 403s on every other — 200 where allowed, 403 where not, for every
role against every staff URL and endpoint.

## Security

Built in from the first commit, not added later:

- **MFA** — RFC 6238 TOTP implemented on the standard library
  (`apps/authentication/totp.py`), with hashed single-use recovery codes and
  replay rejection inside the 30-second window.
- **Tokens** — every verification and reset token is stored SHA-256 hashed. A
  database disclosure yields nothing replayable.
- **Breached passwords** — k-anonymity check against HIBP; only five characters
  of the hash leave the server, and it fails *open* so the API can never take
  registration down.
- **Device fingerprinting** — session pinned to a browser signature; a mismatch
  raises a session-hijack event.
- **Anomaly detection** — new device, new IP, impossible travel, brute force and
  credential stuffing, each scored and escalated.
- **Rate limiting** — global and per-endpoint, with IP reputation that decays.
- **User-enumeration defence** — identical timing and identical responses whether
  or not an account exists.
- **CSP, HSTS, frame-deny, no-store on authenticated pages.**
- **Audit trail** — append-only; `save()` on an existing row raises, `delete()`
  raises, and the admin blocks add/change/delete.
- **Data minimisation** — ID documents are deleted once a decision is made;
  coordinates are quantised to ~110 m before storage.

---

## Payments

Eight providers behind one four-method contract
(`charge`, `verify`, `refund`, `parse_webhook`):

Stripe · PayPal · Flutterwave · Pesapal · M-Pesa · Airtel Money · Mixx by Yas
(Tigo Pesa) · HaloPesa

Adding a provider means adding one file and one registry entry. Nothing else
changes.

Two properties matter more than the provider list:

- **Payments never grants a feature.** It publishes `PAYMENT_SUCCEEDED`;
  `subscriptions` decides what that buys. Money movement and entitlement are
  separable concerns.
- **A lost webhook cannot lose a sale.** Callbacks are persisted *before*
  processing, and `reconcile_open_payments` polls the provider for anything
  still open after ten minutes.

---

## Icons

No emoji anywhere in the interface. Emoji render differently on every OS, cannot
be styled or coloured, and misalign with text. Zynora ships a **58-icon subset of
Bootstrap Icons** as a self-hosted SVG sprite (`static/img/icons.svg`, 23 KB) —
one cached request for the whole site, no CDN (the CSP blocks external hosts),
and every icon inherits `currentColor` so it themes itself.

```django
{% load icons %}
{% icon "patch-check-fill" size=18 label="Verified member" %}
```

Icon *names* are stored in Python (staff navigation, notification kinds), never
glyphs — so the data layer stays free of presentation.

```bash
python manage.py check_icons
```

Fails the build on a missing `{% load icons %}`, an unknown icon name, drift
between the sprite and the tag's whitelist, or any emoji that creeps back into a
template. Wired into `make boundaries`.

## Search

An icon beside Discover opens `/discover/search/` — find anyone by **name,
region, country, job title or interests**, with scope chips to narrow the field.

Search is composed across two contracts, not one query: `accounts` owns names,
`profiles` owns location, work and interests, and `discovery` unions the two.
Neither module reads the other's tables.

It deliberately **ignores your match preferences by default**. Looking someone up
is a different intent from browsing a feed, and silently hiding results you asked
for is worse than showing someone outside your usual range. A checkbox turns
preference filtering on. Blocks always apply.

## Why a feed is never empty

Filters are correct but arithmetic is unforgiving: gender halves a pool, an age
band halves it again, and a 50 km radius across a sparse region can finish the
job. One member's pool of 51 became 2.

So when a feed comes back under `MIN_FEED_SIZE`, discovery **widens the radius**
(3×, 10×, then unrestricted) and marks the results that fell outside the stated
distance. Only distance is relaxed — gender, age and the photo/verified
requirements are choices, not geography — and stored preferences are never
modified. Feeds went from 1–5 results to 11–20.

`manage.py diagnose_feed <email>` shows the pool, the exclusions and the
per-filter rejection counts when you want to know exactly what happened.

## Liking someone does not hide them

A like keeps the person in your feed, now marked **Liked**, and the like reaches
them immediately. Removing someone the moment you like them hides the people you
were most interested in and drains the feed fastest for your most active members.

| Action | Card |
|--------|------|
| Like / Super like | stays, marked liked |
| Match | leaves — it belongs on Matches |
| Block | leaves, both directions |

`likes.get_passed_ids()` is what discovery excludes; `get_swiped_ids()` still
exists for anything that needs the full picture.

## Chat

Messages only flow between matches, so the message button on a card does not
pretend otherwise. It opens a **separate browser window** (`?popup=1`, chromeless
layout) which either:

- hands you the existing conversation if you already matched, or
- lets you attach a note to a Super Like — the one sanctioned way to say
  something before a mutual like.

A real window rather than a modal: it survives navigation on the feed, can sit
beside it, and keeps its own history. One reusable window, so repeated clicks
refocus instead of stacking, with a new-tab fallback when a popup blocker
intervenes.

## Notifications

The inbox carries **engagement only** — likes, super likes, matches, messages.
Operational records (security alerts, receipts, verification decisions) are still
written and still emailed, but they live on the pages that own them:

| Kind | Where it lives |
|------|----------------|
| security | `/security/` — with full sign-in history |
| payment | `/payments/history/` — with invoices |
| verification | `/verification/` |
| subscription | `/subscriptions/mine/` |

`INBOX_KINDS` in `apps/notifications/services.py` is the single switch. Rows keep
an `in_inbox` flag rather than being discarded, so support can still see
everything while the member's badge counts only what they can act on.

## MVT discipline

Templates are **plain HTML**. All computation happens in views and services:

- No calculations, no business logic, no template-tag chains
- Labels, percentages, distances, badges and grouping are prepared in the view
- CSS and JS live in `static/`, never inline (email HTML is the one exception —
  mail clients strip external stylesheets)
- Progress-bar widths come from `data-progress` attributes applied by JS, which
  also keeps the CSP free of `unsafe-inline` scripts

A view hands the template a list of dicts it only has to print.

---

## Commands

```bash
make run          # ASGI dev server
make worker       # Celery worker
make beat         # Celery scheduler
make test         # 39 tests
make lint         # ruff
make boundaries   # architecture check + service graph

python manage.py service_map --events --methods   # full contract + event wiring
python manage.py check_boundaries --strict        # CI gate
python manage.py seed_demo --users 50

# Roles
python manage.py set_role you@example.com admin
python manage.py set_role --roles

# When Discover looks empty
python manage.py diagnose_feed --platform         # pool health
python manage.py diagnose_feed alice@example.com  # one member, filter by filter
python manage.py backfill_photos                  # generated avatars for members with none
```

### Why Discover can look empty

`with_photos_only` is **on by default** — a member with no approved photo does
not appear for anyone. That is deliberate, but on a fresh install where nobody
has uploaded anything it empties every feed at once. `seed_demo` now generates
avatars so a seeded system works; run `backfill_photos` if you imported members
some other way.

`diagnose_feed` reports the pool, the exclusions and the per-filter rejection
counts, and the empty state in the UI shows the member the same reasons with a
link to fix each one.

## Deployment

```bash
cd docker && docker compose up --build
```

Brings up PostgreSQL, Redis, the ASGI app, a Celery worker, the scheduler and
nginx. `/internal/` is denied at the nginx layer — service RPC must never be
reachable from outside the mesh.

---

## Testing

```
Ran 39 tests — OK
```

- `tests/test_boundaries.py` — the architecture tests. Every module exposes a
  contract, declares real dependencies, the leaf services stay leaves, the
  registry can be overridden, and the event bus survives a broken handler.
- `tests/test_matching_engine.py` — the scorer, with no database at all.
- `tests/test_flows.py` — registration, mutual matching, blocking, discovery
  filtering, entitlement granting, moderation, and a render check on every page.

Every assertion goes through a public contract, so the suite keeps passing after
a module is extracted.
