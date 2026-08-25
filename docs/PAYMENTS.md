# GoDaddy Payments (Poynt) Integration

Developer reference for card payments in Popcorn-N-Such.

No real credentials appear in this document. Everything secret is supplied
through environment variables.

---

## 1. Architecture

Card data never touches Django. The browser talks to GoDaddy directly through
the Poynt Collect iframe and hands Django only a single-use **nonce**.

```
Browser                        Django                      GoDaddy / Poynt
───────                        ──────                      ───────────────
card fields (iframe) ─────────────────────────────────────▶ tokenize in-browser
        ◀───────────────────────────────────────────────── nonce
POST {nonce} + CSRF ─────────▶ recalculate total
                               from the database
                               claim idempotency key
                               sign JWT, get token ───────▶ POST /token
                                                   ◀─────── accessToken
                               tokenize the nonce ────────▶ POST .../cards/tokenize
                                                   ◀─────── paymentToken
                               charge the token ─────────▶ POST .../cards/tokenize/charge
                                                   ◀─────── transaction (CAPTURED)
                               create Order
        ◀───────────────────── redirect to receipt
```

The three properties that matter:

1. **Django never sees a PAN, CVV or expiry.** Only the nonce, and later a
   payment token, both of which are useless to an attacker without our
   credentials.
2. **Django decides the price.** The amount is recalculated from the cart at
   POST time. Anything the browser posts about totals is ignored.
3. **An order is created only after the processor confirms.** A declined or
   unknown charge produces no order.

### Files

| Path | Responsibility |
|---|---|
| [payments/gateways/poynt_auth.py](../payments/gateways/poynt_auth.py) | JWT signing, access-token cache, HTTP transport, error types |
| [payments/gateways/godaddy.py](../payments/gateways/godaddy.py) | Poynt endpoints: tokenize, charge, transaction lookup, refund, void |
| [payments/checkout.py](../payments/checkout.py) | Charge orchestration and the duplicate-charge guard |
| [payments/reconciliation.py](../payments/reconciliation.py) | Resolving charges whose outcome was never received |
| [payments/refunds.py](../payments/refunds.py) | Staff-authorised refunds |
| [payments/models.py](../payments/models.py) | `PaymentTransaction`, `PaymentRefund`, `PaymentEventLog` |
| [payments/log_filters.py](../payments/log_filters.py) | Redaction backstop for payment logs |
| [core/csp.py](../core/csp.py) | Content-Security-Policy including the Poynt origins |
| [orders/views.py](../orders/views.py) | `CheckoutReviewView` — the checkout endpoint |
| [templates/orders/checkout_review.html](../templates/orders/checkout_review.html) | Poynt Collect mount + submit handling |

---

## 2. Environment variables

Full list with comments in [.env.example](../.env.example).

### Required

| Variable | Notes |
|---|---|
| `GODADDY_POYNT_ENV` | `ote` (staging) or `prod`. **Defaults to `ote`.** |
| `GODADDY_POYNT_APPLICATION_ID` | From Poynt HQ. Also used by the browser SDK. |
| `GODADDY_POYNT_BUSINESS_ID` | From Poynt HQ. Also used by the browser SDK. |
| `GODADDY_POYNT_PRIVATE_KEY` *or* `GODADDY_POYNT_PRIVATE_KEY_PATH` | RSA private key (PEM). **Never commit.** |

### Optional

| Variable | Default | Notes |
|---|---|---|
| `GODADDY_POYNT_STORE_ID` | — | Recommended; sent as `context.storeId`. |
| `GODADDY_POYNT_API_HOST` | derived from env | Explicit override. |
| `GODADDY_POYNT_API_VERSION` | `1.2` | |
| `GODADDY_POYNT_TIMEOUT_SECONDS` | `20` | |
| `GODADDY_POYNT_TOKEN_LEEWAY_SECONDS` | `300` | Renew the token this long before expiry. |
| `GODADDY_PAYMENTS_CHARGE_ACTION` | `SALE` | `SALE` = auth+capture. `AUTHORIZE` = auth only. |
| `GODADDY_COLLECT_ENABLED` | `true` | Turns the card form on. |
| `GODADDY_COLLECT_SDK_URL` | follows env | Blank = auto (OTE vs prod host). |
| `GODADDY_PAYMENTS_WEBHOOK_SECRET` | — | Required for webhooks; absent ⇒ all webhooks rejected. |
| `CSP_ENFORCE` | `false` | Switch CSP from report-only to enforcing. |
| `PAYMENTS_LOG_LEVEL` | `INFO` | |
| `ALLOW_STUB_CHECKOUT_PAYMENT` | `false` | Dev only. **Must be false in production.** |

The private key may be given inline with newlines written as the two characters
`\n`, or as a path to a `.pem` file stored outside the repository. `*.pem`,
`*.key` and `secrets/` are gitignored.

> **Caution.** `core/runtime_settings.get_runtime_setting()` reads an environment
> variable *before* the database and Django settings. An env var therefore wins
> over anything set in the staff Operational Settings screen — and over
> `override_settings` in tests. The Poynt endpoint paths are deliberately pinned
> in `settings` and are *not* runtime-overridable, so an operator cannot
> redirect payment traffic.

---

## 3. Authentication

Poynt uses the OAuth 2.0 JWT bearer assertion grant.

```
Django
  ↓  JWT: iss = sub = applicationId, aud = api host, iat/exp/jti
  ↓  signed RS256 with the application private key
  ↓  POST /token   grantType=urn:ietf:params:oauth:grant-type:jwt-bearer
GoDaddy/Poynt
  ↓  accessToken (JWT, ~24h) + expiresIn
Django
  ↓  Authorization: Bearer <accessToken>  on every API call
```

Notes:

* The form field is `grantType`, **not** the RFC's `grant_type`.
* `api-version: 1.2` is required on every request.
* `Poynt-Request-Id` is sent on every request and is Poynt's **idempotency key**.
* Tokens are cached in Django's cache keyed by host + application id, expiring
  early by `GODADDY_POYNT_TOKEN_LEEWAY_SECONDS`. A `401` triggers exactly one
  retry with a freshly minted token.
* The private key is read only inside `poynt_auth.py`. It is never rendered into
  a template, returned in a response, or logged.

---

## 4. Checkout flow

`GET /orders/checkout/review/`
: Renders the summary and mounts Poynt Collect. Issues a **payment intent key**
  (a UUID) into the session and echoes it into the form.

`POST /orders/checkout/review/`
: 1. CSRF validated by Django middleware.
  2. Cart reloaded; totals recalculated server-side.
  3. Nonce read from `poynt_nonce`; rejected if absent.
  4. Intent key read **from the session**, not the POST body.
  5. `charge_checkout()` claims the key, calls Poynt, records the outcome.
  6. On approval, `create_confirmed_order()` writes the Order, decrements
     inventory under `SELECT FOR UPDATE`, and links the payment.
  7. Session checkout state is cleared and the customer is redirected.

Outcomes:

| Result | Customer sees | Order created? |
|---|---|---|
| Approved | `checkout_complete.html` | Yes |
| Declined | Review page + generic message | No |
| Timeout / unknown | `payment_pending.html` | No — pending reconciliation |
| Duplicate submit, first succeeded | Original receipt | No second order |
| Duplicate submit, first in flight | "already being processed" | No |

---

## 5. Duplicate-charge protection

Four independent layers:

1. **Session-issued intent key.** Minted on `GET`, stable across reloads. The
   browser cannot choose or rotate it.
2. **Database claim.** `PaymentTransaction` is created *before* the provider is
   called, under `UniqueConstraint(provider, idempotency_key)`. A concurrent
   second request loses the race and is refused.
3. **Provider idempotency.** The same key is sent as `Poynt-Request-Id`, so a
   genuine network-level replay returns the original transaction.
4. **Order-level constraint.** `UniqueConstraint(order)` where status is
   `confirmed`/`captured` makes two successful payments on one order
   impossible at the database level.

The Pay button is also disabled on submit, but that is a convenience — never the
mechanism.

---

## 6. Ambiguous outcomes

If Django sends a charge and the connection dies, the customer **may** have been
charged. Retrying would charge them twice.

Instead the attempt is stored as `AMBIGUOUS` with `requires_reconciliation=True`,
the customer is sent to a page that explicitly tells them not to retry, and
resolution happens by asking GoDaddy:

* If a provider transaction id was captured → `GET .../transactions/{id}`.
* Otherwise → search recent transactions for our `Poynt-Request-Id`.

Both lookups are read-only and safe to repeat. Only a positive match marks the
payment as taken. If nothing is found after `SETTLEMENT_GRACE` (30 minutes) the
charge is concluded never to have reached the processor.

Runs automatically every 2 minutes via Celery beat
(`payments.tasks.reconcile_ambiguous_payments`), or manually:

```bash
python manage.py reconcile_payments --limit 100
```

After `MAX_RECONCILIATION_ATTEMPTS` (12) the row is left flagged for a human and
logged at ERROR.

---

## 7. Database records

**PaymentTransaction** — one row per charge *attempt*, including failures.
`order` is nullable because the row is created before the order exists.

Stores: provider, status, amount_cents, currency, provider_transaction_id,
idempotency_key, card_brand, card_last4, avs_result, cvv_result, confirmed_at,
failure_code/message, reconciliation fields.

**Never stores** PAN, CVV, expiry, or track data. Provider payloads are scrubbed
by `_scrub()` before being persisted.

**PaymentRefund** — one row per refund, referencing the original payment. The
original charge row is never deleted or overwritten.

**PaymentEventLog** — raw inbound webhook events with signature-validity flag.

Statuses: `created`, `pending`, `authorized`, `captured`, `confirmed`, `failed`,
`refunded`, `cancelled`, `ambiguous`.

---

## 8. Refunds

```python
from payments.refunds import issue_refund

refund = issue_refund(
    payment=payment_transaction,
    actor=request.user,      # must be staff
    amount_cents=None,       # None = full remaining amount
    reason="customer request",
    request=request,
)
```

Enforced: staff-only; payment must be confirmed and have a provider transaction
id; the cumulative refunded amount can never exceed the amount captured. A full
refund omits the `amounts` block so the processor uses the original total.

Also available in the Django admin under **Payment refunds**.

A refund timeout leaves the row `PENDING` and raises — verify at the processor
before retrying, never issue a second refund blindly.

Under the hood: `POST /businesses/{id}/transactions` with
`{"action": "REFUND", "parentId": "<original id>"}`. Voiding an unsettled
authorization instead uses `POST .../transactions/{id}/void`.

---

## 9. Testing

```bash
python manage.py test payments.tests_poynt      # 55 tests, all mocked
python manage.py check_payments_ready           # config audit
python manage.py check_payments_ready --live    # also authenticates
```

No test performs a real charge. Coverage includes successful checkout, declines,
invalid/missing nonce, amount-manipulation attempts, duplicate POSTs, API errors
and timeouts, reconciliation, refund authorization, CSRF enforcement, and
assertions that no secret reaches the page or the logs.

### Staging (OTE) checklist

Set `GODADDY_POYNT_ENV=ote` with staging credentials, then verify in order:

- [ ] `python manage.py check_payments_ready --live` passes
- [ ] Checkout review page loads
- [ ] Poynt Collect iframe renders the card fields
- [ ] Browser console shows no CSP violations
- [ ] Entering a test card produces a nonce (watch the status text)
- [ ] Django receives the nonce; a `PaymentTransaction` row appears
- [ ] Logs show a token obtained, then tokenize, then charge
- [ ] `provider_transaction_id` is stored
- [ ] Order is created with the correct server-side total
- [ ] Success page displays
- [ ] Confirmation email sends

Then the failure paths:

- [ ] Decline test card → no order, generic message, row is `failed`
- [ ] Double-click Pay → exactly one order, one transaction
- [ ] Refresh and resubmit the review page → no second charge
- [ ] Tamper with a posted `total_cents` → server total is charged
- [ ] Set `GODADDY_POYNT_TIMEOUT_SECONDS=1` → pending page, row `ambiguous`
- [ ] `python manage.py reconcile_payments` resolves that row correctly
- [ ] Refund a staging payment as staff → `PaymentRefund` row, original intact
- [ ] Attempt a refund as a non-staff user → refused

---

## 10. Production cutover

Only these change:

| Item | Staging | Production |
|---|---|---|
| `GODADDY_POYNT_ENV` | `ote` | `prod` |
| API host (derived) | `services-ote.poynt.net` | `services.poynt.net` |
| `GODADDY_POYNT_APPLICATION_ID` | staging app | **production app** |
| `GODADDY_POYNT_BUSINESS_ID` | staging business | **production business** |
| `GODADDY_POYNT_STORE_ID` | staging store | **production store** |
| `GODADDY_POYNT_PRIVATE_KEY` | staging key | **production key** |
| `GODADDY_PAYMENTS_WEBHOOK_SECRET` | staging secret | production secret |
| `DJANGO_DEBUG` | may be true | **must be false** |
| `ALLOW_STUB_CHECKOUT_PAYMENT` | may be true | **must be false/absent** |

Also changes automatically: the Collect SDK host (`collect.commerce.ote-godaddy.com`
→ `collect.commerce.godaddy.com`), unless you pinned `GODADDY_COLLECT_SDK_URL`.

Unchanged: all
endpoint paths, the charge action, application code, database schema, and the
CSP (it already lists both hosts).

Staging configuration is kept, not deleted — the two are separated by
environment variables, so you can point a staging deployment back at `ote` at any
time.

Procedure:

1. Complete the staging checklist above with zero failures.
2. Set the production env vars in the deployment platform (never in the repo).
3. Deploy.
4. `python manage.py check_payments_ready --live` → expect all-pass.
5. Place one small **real** order with a real card.
6. Confirm the transaction in Poynt HQ and the `PaymentTransaction` row.
7. Refund that order through the admin; confirm both sides.
8. Watch `payments.*` logs and the reconciliation task for the first day.

---

## 11. Troubleshooting

**`PoyntAuthError: Poynt rejected the application credentials (HTTP 401)`**
Application ID and key belong to different environments, or the key is not the
one issued with that application. Staging keys do not work against production.

**`PoyntConfigurationError: Could not sign the Poynt authentication assertion`**
The key is not a valid PEM RSA private key. Inline values need newlines written
as `\n`; check they were not collapsed into spaces.

**Card form does not appear**
`GODADDY_COLLECT_ENABLED`, the SDK URL, and both IDs must be set — and the
server credentials must also be complete, since the page hides the form when a
charge could not possibly succeed. Check the browser console for CSP violations.

**Charge returns HTTP 404**
Usually a Business ID that does not exist in the selected environment.

**Everything becomes `ambiguous`**
Network egress to `services*.poynt.net` is blocked, or the timeout is too low.
These rows are safe — reconciliation resolves them; nothing is double-charged.

**Webhooks all rejected**
`GODADDY_PAYMENTS_WEBHOOK_SECRET` is unset. Verification fails closed by design.

**Tests cannot override a payment setting**
An env var from your real `.env` is winning. Patch `os.environ` as well — see
`WebhookSignatureTests`.

---

## 12. Security invariants

Do not weaken these:

* No PAN, CVV, expiry or track data in the database, logs, or any response.
* The amount charged always comes from the database, never from the request.
* No order is created before the processor confirms.
* An ambiguous charge is never retried automatically.
* Webhook signature verification fails closed.
* CSRF protection is never disabled on checkout. `csrf_exempt` appears only on
  the webhook route, which is a signed server-to-server callback.
* Poynt endpoint paths stay pinned in settings, never runtime-editable.
* The private key never leaves the server process.
