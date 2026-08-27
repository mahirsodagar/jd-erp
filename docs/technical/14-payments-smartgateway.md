# 14. Payments — HDFC SmartGateway

Online collection of the **application fee** that a lead pays before the
application form unlocks. Everything lives in `apps/payments`.

Student course-fee installments are **not** covered here — they are still
collected offline and keyed in by HR as `FeeReceipt` rows (chapter 6).

Reference: <https://smartgateway.hdfcbank.com/docs/smartgateway-api-ref-basicauth/>
(the Basic-auth flavour of the API — see §14.3 for why, not the
JWE/JWS-signed flavour that the Juspay Java SDK in the repo root uses).

---

## 14.1 What problem this solves

Before the gateway, the fee step was manual end to end:

```
Counsellor clicks "Send fee link"
   → SMS/WhatsApp/email carrying a static per-institute short URL
     (settings.FEE_LINK_URLS) + UPI QR + bank details
   → student pays into the bank
   → someone spots it on a statement
   → counsellor clicks "Mark fee paid" and types the reference by hand
   → only now does "Send application link" unlock
```

Two things were expensive there: the reconciliation lag (hours to days),
and the typing, which is where wrong references come from. With
SmartGateway the middle three steps collapse:

```
Counsellor clicks "Send fee link"
   → a PaymentRequest is raised for this lead and its pay URL goes out
     on the same SMS/WhatsApp/email legs as before
   → student taps the link, lands on the HDFC hosted payment page,
     pays by UPI / card / netbanking
   → SmartGateway POSTs ORDER_SUCCEEDED to our webhook
   → we re-read the order, then stamp the lead's application_fee_* fields
   → "Send application link" unlocks
```

The gate itself did not move. `send_application_link` still refuses to
send while `Lead.application_fee_paid_at` is null — the webhook just
became another thing that can set it, alongside a human.

---

## 14.2 Why the link points at us, not at the bank

This is the one structural decision worth understanding before reading
the code.

SmartGateway's `/session` API mints a **payment page session**, and
`payment_links.web` comes back with an **expiry**. That is fine for a
checkout button clicked seconds later. It is wrong for our flow, where
the URL goes out by SMS and a lead may pay two days later — a URL minted
at send time would be dead on arrival.

So the SMS carries our own URL, and the bank is only contacted when the
student actually taps it:

```
SMS  →  GET /api/public/pay/<token>/     (ours, never expires)
             │
             ├─ reuses the current session if it's still good
             └─ otherwise POSTs /session for a fresh order
                       │
                       └─ 302 → HDFC hosted payment page (expires)
```

That is what the two-table split models:

| Table | One row per | Lifetime |
|---|---|---|
| `PaymentRequest` | "this lead owes this fee" — carries the public `token` | Until paid or cancelled |
| `PaymentOrder` | one trip to the payment page | Until its session expires |

A request accumulates several orders when a student opens the link,
wanders off, and comes back tomorrow. Only one ever reaches `CHARGED`.

**`order_id` constraints.** SmartGateway caps it at 20 characters and
rejects special characters, so orders are named `AF{request_pk}N{attempt}`
— alphanumeric, and keyed on the request rather than the lead so two
requests for one lead can't collide. `attempt_count` is bumped *before*
the session call, not after: a failed session still burns that order_id
as far as the bank is concerned.

---

## 14.3 Authentication — three separate things

Easy to conflate, so they are named apart everywhere in the code:

| Direction | Mechanism | Setting |
|---|---|---|
| Us → bank | `Authorization: Basic base64(api_key + ":")` — API key as username, empty password | `SMARTGATEWAY_API_KEY` |
| Bank → us (webhook) | A **different** username/password pair set in the dashboard, replayed as an ordinary Basic header | `SMARTGATEWAY_WEBHOOK_USERNAME` / `_PASSWORD` |
| Bank → us (return_url) | HMAC-SHA256 over the redirect params, keyed by a **third** secret | `SMARTGATEWAY_RESPONSE_KEY` |
| Student → us (pay link) | The UUID token in the URL | — |

Three different secrets, and mixing them up is the most likely
integration mistake. The dashboard `config.json` writes the API key with
a trailing colon (`"API_KEY": "…E5:"`) precisely because it is a Basic
username with an empty password.

### The return_url signature

SmartGateway redirects the payer back with signed parameters:

```
?order_id=AF1N01&status=CHARGED&status_id=21
&signature=euKz…%3D&signature_algorithm=HMAC-SHA256
```

`verify_return_signature` reproduces the reference PHP exactly:

1. Drop `signature` and `signature_algorithm` from the set.
2. Sort the remaining params by key.
3. Percent-encode each key and value, join as `k=v` with `&`.
4. **Percent-encode that whole joined string again.**
5. HMAC-SHA256 it with the RESPONSE_KEY, base64 the digest.
6. Compare, url-decoding both sides as the reference does.

Step 4 is the one people miss — an implementation without it looks right
and never validates. `signature_payload()` is unit-tested against a
hand-built expectation for that reason, and the round-trip test signs
with an independent implementation so a bug in ours can't cancel itself
out.

Encoding matches PHP's `urlencode()`, not Python's `quote_plus()`
defaults: space is `+` and `~` **is** escaped.

The Juspay Java SDK bundled in the repo root uses a third scheme entirely
(JWE/JWS signing with a keypair on disk). We use the Basic-auth flavour
because it needs no key material deployed and the two calls we make are
identical either way.

### The webhook is not evidence

**SmartGateway does not sign webhook bodies.** The shared credentials are
the entire authentication, which means anyone who learns them could
otherwise assert that a fee was paid. So by default a webhook is treated
as a *nudge*: `process_webhook_event` re-reads the order from
`/orders/{order_id}` and applies **that** answer, not the payload's.

There is a test pinning exactly this — a webhook claiming `CHARGED` over
an order the API reports as `AUTHORIZATION_FAILED` leaves the lead
unpaid. Set `SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD=True` to skip the
re-fetch, and accept the consequence.

The `return_url` is different — it *is* signed (see above), so it can be
trusted. Even so `PayReturnView` prefers a fresh read of the order, since
a signed `CHARGED` can still be followed by a failed capture. The
signature earns its keep as the fallback: if the API read fails, an
authenticated `CHARGED` shows the student success instead of an unhelpful
"still confirming", while an *unsigned* claim of the same thing does not.
A signature that arrives but fails to validate is logged loudly — in a
healthy integration it should never happen.

---

## 14.4 Order statuses

SmartGateway has a wide vocabulary; `PaymentOrder` mirrors it and sorts
it into two frozensets that the rest of the code reads:

* `PAID_STATUSES` — **`CHARGED` only.** `AUTHORIZED` is deliberately
  excluded: it is a hold, not a capture. If you ever switch the
  application fee to manual capture, that decision has to be revisited.
* `TERMINAL_STATUSES` — nothing further will happen; the reconcile
  command skips these.

Everything else (`NEW`, `PENDING_VBV`, `AUTHORIZING`, …) is non-terminal
and gets polled.

### Manual reconciliation never loses

`_mark_lead_fee_paid` refuses to touch a lead whose
`application_fee_paid_at` is already set. If accounts reconciled a bank
transfer by hand and the webhook lands afterwards, their reference stays.
The order and request still settle — only the lead's fields are held.

---

## 14.5 The fallback is the point

`SMARTGATEWAY_ENABLED` is a per-environment kill switch, and
`leads.send_links._fee_link_url` degrades rather than fails:

| Situation | What the student receives |
|---|---|
| Gateway on, request raised | Our per-lead pay URL |
| Gateway on, request can't be raised | The static short URL + UPI/bank instructions |
| Gateway off | The static short URL + UPI/bank instructions |

A gateway outage therefore never blocks a counsellor from sending
payment instructions. Note that raising a request makes **no** network
call, so the only failure modes here are misconfiguration and a missing
fee amount — the bank being down surfaces later, when the student taps
the link, and shows them a "try again shortly" page.

`send_fee_link` reports which happened (`gateway: "smartgateway" |
"manual"`), and the UI keys its wording off that.

---

## 14.6 When a webhook never arrives

Two escape hatches, both routed through the same `apply_order_body` so
they cannot drift from the webhook path:

* **Per request, from the UI** — "Check payment status" on the lead's
  *Online payments* card
  (`POST /api/payments/requests/<id>/reconcile/`). Requires
  `leads.application_fee.record`, since it can mark a lead paid. Returns
  409 if the student never opened the link, because there is no order to
  check.
* **In bulk, from cron** —
  `python manage.py reconcile_smartgateway --days 30`. Idempotent, and
  skips terminal orders. `--dry-run` lists what it would check.

---

## 14.7 Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/public/pay/<token>/` | token in URL | What the SMS points at. Mints/reuses a session, 302s to the bank |
| `GET,POST /api/public/pay/<token>/return/` | token in URL | SmartGateway's `return_url`. Re-reads the order, redirects to the SPA result page |
| `POST /api/public/smartgateway/webhook/` | dashboard Basic creds | Settlement |
| `GET /api/payments/requests/?lead=<id>` | `leads.application_fee.record` / `leads.send.fee_link` / `leads.lead.view*` | Lead's payment history |
| `POST /api/payments/requests/<id>/reconcile/` | `leads.application_fee.record` | Force a status check |
| `GET /api/payments/smartgateway/status/` | any authenticated user | Drives the sandbox banner in the UI |

The webhook answers **200 for anything it durably recorded**, including
events it skipped and events that failed to apply — SmartGateway retries
until it sees a 2xx, and retrying will not fix a payload referencing an
order we don't have. Only bad credentials (401) or an unparseable body
(400) get a non-2xx.

Subscribe to these events in the dashboard: `ORDER_SUCCEEDED`,
`ORDER_FAILED`, `TXN_CHARGED`, `TXN_FAILED`, `ORDER_REFUNDED`,
`AUTO_REFUND_SUCCEEDED`. Anything else is recorded `SKIPPED` and ignored.

**No new permission keys** were minted — new keys only take effect after
`manage.py seed_permissions`, which resets customised role grants, and
nothing here is a genuinely new capability.

---

## 14.8 Configuration

All keys documented in `.env.example`. The minimum to go live:

```
SMARTGATEWAY_ENABLED=True
SMARTGATEWAY_SANDBOX=True              # False for the real bank
SMARTGATEWAY_API_KEY=...
SMARTGATEWAY_MERCHANT_ID=...
SMARTGATEWAY_CLIENT_ID=hdfcmaster      # your merchant id in production
SMARTGATEWAY_RESPONSE_KEY=...          # signs the return_url params
SMARTGATEWAY_PUBLIC_BASE_URL=https://api.jdinstitute.example
SMARTGATEWAY_WEBHOOK_USERNAME=...
SMARTGATEWAY_WEBHOOK_PASSWORD=...
```

`SMARTGATEWAY_PUBLIC_BASE_URL` must be the origin of **this API** as the
bank's servers and the student's phone reach it — both the pay link and
the `return_url` are built from it, and SmartGateway requires
`return_url` to be a reachable HTTPS endpoint. It cannot be localhost in
any environment that actually takes money.

`is_enabled()` requires the switch **and** the API key, merchant id and
client id, so a half-filled `.env` behaves as "off" rather than erroring
at send time.

### Amount resolution

The charged amount comes from `_application_fee_for_lead`, unchanged from
the manual flow:

1. `FeeTemplate.application_fee` for the lead's (campus, program), most
   recent academic year first.
2. `INSTITUTE_PAYMENT_DETAILS[institute]["default_amount"]`.
3. Nothing → the request is refused (the manual flow tolerated a blank
   amount because the student typed it into their UPI app; a hosted
   payment page cannot).

`format_amount` refuses a value that isn't a whole number of paise rather
than rounding it, because rounding here means charging a student the
wrong amount.

### Auto-sending the application link

`SMARTGATEWAY_AUTOSEND_APPLICATION_LINK` (default **False**) sends the
application-form link the instant the fee settles. It is off by default
because it messages a real lead with no human in the loop. Failures are
logged and swallowed — a flaky SMS gateway must not un-settle a payment
that already happened.

---

## 14.9 Testing

`apps/payments/tests_smartgateway.py` — 49 tests, no network (the two
gateway calls are patched). They pin the things that fail silently rather
than loudly: webhook credentials, redelivery not double-settling, the
payload not being trusted on its own word, `order_id` staying inside the
20-char alphanumeric limit, session expiry forcing a fresh order, the
return-URL signature's double encoding, and manual mark-paid surviving a
late webhook.

```bash
python manage.py test apps.payments
```

### End-to-end against sandbox

1. Set the env vars above with sandbox credentials
   (`SMARTGATEWAY_SANDBOX=True`, `CLIENT_ID=hdfcmaster`).
2. Expose the API over HTTPS — the bank must reach both the webhook and
   the `return_url`. A tunnel (`ssh -R 80:localhost:8000 serveo.net`,
   ngrok) or the real staging host; set `SMARTGATEWAY_PUBLIC_BASE_URL` to
   whatever that origin is.
3. Register `https://<host>/api/public/smartgateway/webhook/` in the
   dashboard with the events listed in §14.7, and set the webhook
   username/password to match your `.env`.
4. Open a lead with a campus/program whose `FeeTemplate.application_fee`
   is set, and click **Send fee link**.
5. Open the pay URL and complete a sandbox payment.
6. The lead's application fee should flip to paid on its own, and
   **Send application link** should unlock.

If it doesn't, check in this order:

* `SmartGatewayWebhookEvent` in Django admin — a row with status `ERROR`
  carries the reason.
* **No row at all** means the delivery never passed the credentials
  check, almost always `SMARTGATEWAY_WEBHOOK_*` not matching the
  dashboard, or the API key having been pasted there by mistake.
* A row marked `PROCESSED` with the lead still unpaid means the re-read
  from `/orders/{id}` disagreed with the webhook — look at
  `PaymentOrder.status` and `bank_error_message`.
