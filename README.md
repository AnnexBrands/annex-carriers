# annex-carriers

Carrier REST API SDKs for UPS and FedEx over one shared, dependency-free core.

Formerly two repositories (`ups-api-sdk` and `fedex-api-sdk`) that were clones
of each other and had already drifted: UPS had a careful gzip/deflate decoding
fix that FedEx never received, so a compressed FedEx response raised
`UnicodeDecodeError` from inside the transport. About 350 lines of transport,
token lifecycle, error classification and config resolution were maintained
twice — 100% of the layer where bugs are subtle and silent.

They are now one repository with an internal core and one adapter per carrier.

```
src/carriers/
  _core/     transport · retry · multipart · token · error base · config base
  ups/       UPS OAuth, versioned URL map, payload builders   (19 API families)
  fedex/     FedEx OAuth, URL map, ETD workflows              (8 API families)
```

The leading underscore is the contract: `_core` is internal and free to change
without a deprecation cycle. Adapters never import each other, and never learn
anything about a caller's domain — `carriers.fedex` does not know what an
ABConnect job id is.

## Install

```bash
pip install -e .
```

Python 3.11+. No runtime dependencies.

## Quick start

```python
from carriers.ups import UPSClient
from carriers.fedex import FedExClient

with UPSClient.from_env() as ups:
    quote = ups.rating.shop(payload)
    label = ups.shipping.create(ship_payload)

with FedExClient.from_env() as fedex:
    doc = fedex.documents.upload_post_shipment(
        "invoice.pdf",
        origin_country_code="US",
        destination_country_code="GB",
        tracking_number=tracking,
        shipment_date="2026-07-24",
    )
```

### Configure

```bash
export UPS_CLIENT_ID="..."      export FEDEX_CLIENT_ID="..."
export UPS_CLIENT_SECRET="..."  export FEDEX_CLIENT_SECRET="..."
export UPS_ACCOUNT_NUMBER="..." export FEDEX_ACCOUNT_NUMBER="..."
export UPS_ENVIRONMENT="cie"    export FEDEX_ENVIRONMENT="sandbox"
```

UPS also accepts the shorter aliases `UPS_CLIENT`, `UPS_SECRET`, `UPS_ACCOUNT`
(`test`/`sandbox` map to `cie`); FedEx accepts `FEDEX_CLIENT`, `FEDEX_SECRET`,
`FEDEX_ACCOUNT` (`test`/`cie` map to `sandbox`). Both can read an env file:

```python
client = UPSClient.from_env(env_file="src/.env")
```

The process environment always wins over the file, so exporting a variable
overrides a checked-in value.

Or build the config directly:

```python
from carriers.ups import UPSClient, UPSConfig

client = UPSClient(UPSConfig(
    client_id="...", client_secret="...", account_number="A1B2C3",
    environment="cie",
))
```

Tokens are cached in memory behind a lock and refreshed 60s before expiry.
**Nothing is ever written to disk** — no token cache file to leak into a repo.

## API surface

Every method takes the plain dictionaries the carrier documents and returns a
parsed response (`.data`, `.status_code`, `.headers`, `.transaction_id`), so a
schema change on the carrier's side does not require a release here.

### UPS — 65 methods across 11 namespaces

All nineteen Postman collections in `docs/postman/ups/` are reachable.

| Namespace | Covers | Key methods |
|---|---|---|
| `client.oauth` | OAuth auth-code grant | `authorization_url`, `exchange_authorization_code`, `refresh` |
| `client.tracking` | Tracking, Track Alert | `track`, `track_by_reference`, `subscribe` |
| `client.rating` | Rating, Time in Transit | `rate`, `shop`, `from_ship_payload`, `rate_with_time_in_transit`, `time_in_transit` |
| `client.shipping` | Shipping, Label Recovery | `create`, `void`, `recover_label` |
| `client.addresses` | Address Validation (XAV) | `validate`, `validate_payload` |
| `client.pickups` | Pickup | `rate`, `schedule`, `cancel`, `pending_status`, `political_divisions`, `service_centers` |
| `client.paperless` | Paperless Documents | `upload`, `push_to_repository`, `delete`, `attach`, `document_ids` |
| `client.trade` | Landed Cost, Customs Detail, Export Assure ×2 | `landed_cost`, `customs_detail_fields`, `submit_customs_detail`, `export_assure_compliance`, `export_assure_interactive` |
| `client.visibility` | Quantum View, Delivery Intercept, DeliveryDefense | `quantum_view_events`, `intercept_charges`, `address_confidence` |
| `client.dangerous_goods` | Pre-Notification | `pre_notification` |
| `client.forwarding` | Forwarding (23 endpoints) | `create_order`, `create_shipment`, `freight_rates`, `milestones`, `create_quote`, `cities`, `service_types`, … |

The client-credentials grant is automatic — every authenticated call fetches
and caches its own token. `client.oauth` is only for the interactive flow.

### FedEx — 33 methods across 8 namespaces

| Namespace | Covers | Key methods |
|---|---|---|
| `client.ship` | Ship API | `create`, `cancel`, `validate`, `results`, `create_tag`, `cancel_tag` |
| `client.rate` | Rate API | `quotes`, `freight_quotes` |
| `client.track` | Track API | `by_tracking_numbers`, `by_reference`, `by_tcn`, `documents`, `notifications` |
| `client.documents` | Trade Documents Upload (ETD) | `upload_pre_shipment`, `upload_post_shipment`, `upload_images`, `reference`, `attach_to_shipment` |
| `client.addresses` | Address Validation | `resolve`, `validate_postal` |
| `client.locations` | Location API | `search` |
| `client.pickups` | Pickup API | `availability`, `create`, `cancel` |
| `client.availability` | Service Availability | `service_options`, `transit_times` |

**Endpoint provenance.** `carriers/fedex/endpoints.py` tags every path: `[spec]`
verified against an OpenAPI document in `docs/specs/fedex/`, `[live]` already
exercised against FedEx, `[portal]` taken from FedEx's published catalog but
**not verified here**. The `[portal]` set is exported as
`endpoints.UNVERIFIED` — confirm those against your developer portal account
before production use. Correcting one is a single-line change with no
call-site churn.

Two `[spec]` corrections landed in 0.2, both previously untested:

| | 0.1 | 0.2 (per `docs/specs/fedex/ship.json`) |
|---|---|---|
| Cancel shipment | `POST /ship/v1/shipments/cancel` | `PUT /ship/v1/shipments/cancel` |
| Validate shipment | `POST /ship/v1/shipments/validate` | `POST /ship/v1/shipments/packages/validate` |

### ETD: pre-shipment vs post-shipment

The distinction is easy to lose and expensive to get wrong, so the two
workflows have separate methods rather than a flag:

- **Pre-shipment** — upload first, then reference the returned `docId` on the
  shipment payload. Use `upload_pre_shipment` + `attach_to_shipment`.
- **Post-shipment** — the label already exists, so the document is lodged
  after the fact and *must* carry `trackingNumber` and `shipmentDate`. Use
  `upload_post_shipment`.

If something else books your label (a TMS, a broker, ABConnect), your
integration is structurally **post-shipment**.

## What the core gives you

**Retry with `Retry-After`.** Both SDKs previously raised on 429 and stopped,
and neither read the header. The policy now lives in one place:

```python
from carriers import RetryPolicy
client = UPSClient.from_env(retry_policy=RetryPolicy(attempts=5, max_backoff=60))
client = UPSClient.from_env(retry_policy=RetryPolicy.disabled())
```

A carrier-supplied `Retry-After` beats the computed backoff, clamped to
`max_backoff`. Backoff is exponential with full jitter.

**POST is not retried on 5xx by default.** A 500 from `POST /ship` may mean the
label was bought and the response lost; retrying would double-book. Only 408
and 429 — where the carrier told us it did not process the request — retry on
non-idempotent methods. Opt in with `RetryPolicy(retry_non_idempotent=True)`
if a duplicate is acceptable for your call.

**Logging.** Both packages had zero `logger` calls, so a failed booking left no
trace beyond the exception. Every client now logs to `carriers.ups` /
`carriers.fedex`: `debug` per request, `warning` per retry, `error` with the
carrier's own message and transaction id on failure.

```python
import logging
logging.getLogger("carriers").setLevel(logging.DEBUG)
```

**Content decoding.** Gzip and deflate, with a magic-byte sniff backing up the
`Content-Encoding` header so mislabeled bodies still decode. FedEx now has this
too.

**Error taxonomy.** Each carrier's errors subclass both a carrier-specific
class and a shared base, so you can narrow or generalise:

```python
from carriers import CarrierRateLimitError      # either carrier
from carriers.ups import UPSValidationError     # UPS only
```

`CarrierTransportError` is raised when the request never reached the carrier at
all, which is a different problem from the carrier saying no.

**Swappable transport.** `Transport` is a Protocol; the default is urllib. The
entire test suite runs without a network by passing a fake.

## Payload builders

Thin wrappers are not always enough, so each adapter ships builders for the
shapes that are tedious or easy to get wrong:

```python
from carriers.ups import (
    rate_request_from_ship_payload,  # quoted == booked: derive the rate
                                     # request from the exact ship payload
    build_landed_cost_request,       # fills commodityId positionally
    build_track_alert_subscription,
    extract_rate_options,            # flatten RatedShipment into comparable dicts
    extract_package_status,
    extract_candidates,              # XAV suggested corrections
)
```

The extractors handle UPS's single-object collapse, where a one-element array
arrives as a bare object.

## Compatibility

`ups_sdk` and `fedex_sdk` still import and re-export everything, with a
`DeprecationWarning`. The flat client methods (`client.rate`, `client.track`,
`client.create_shipment`, …) are unchanged and delegate to the namespaces.

New code should use `carriers.ups` / `carriers.fedex` and the namespaced
surface. The shims come out once nothing references them.

## Tests

```bash
python -m unittest discover -s tests -t . -p "test_*.py"
# or
pytest
```

133 tests, no network. `tests/core/` covers the shared layer once — content
decoding, retry policy, error mapping, token caching, multipart, config
resolution — which is the point of the merge.

## Layout

```
src/carriers/_core/     internal infrastructure (no carrier knowledge)
src/carriers/ups/       UPS adapter
src/carriers/fedex/     FedEx adapter
src/{ups_sdk,fedex_sdk}.py   deprecated import shims
tests/core/             the shared layer, tested once
tests/{ups,fedex}/      per-carrier suites
docs/postman/ups/       19 UPS Postman collections (endpoint provenance)
docs/specs/fedex/       FedEx OpenAPI documents (endpoint provenance)
examples/
```

## Not in scope here

This package is layer 1: one external system's wire format, auth flow and
error mapping, and nothing else. It deliberately does not own:

- the correlation between a job, a label and a trade document — that belongs
  to a domain layer above these adapters;
- retry policy for *business* steps (as opposed to HTTP);
- anything ABConnect-, database- or job-shaped.

A carrier package that grows one of those has taken on someone else's concern.
