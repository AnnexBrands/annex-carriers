# UPS API SDK for Python

A lightweight, dependency-free Python SDK for UPS REST APIs.

The SDK handles OAuth token creation and caching, common headers (`transId`,
`transactionSrc`), JSON request encoding, UPS error responses, and stable
convenience methods for core APIs. UPS request schemas are large and change
over time, so API methods accept plain dictionaries that match the official
UPS JSON payloads.

Companion to the FedEx SDK in `../FedEx` — same structure and conventions.

## Install

```bash
pip install -e .
```

## Configure

```bash
export UPS_CLIENT_ID="your app client id"
export UPS_CLIENT_SECRET="your app client secret"
export UPS_ACCOUNT_NUMBER="your UPS shipper number"
export UPS_ENVIRONMENT="cie"  # UPS's test environment, or production
```

The SDK also accepts the shorter local aliases `UPS_CLIENT`, `UPS_SECRET`,
and `UPS_ACCOUNT` (`test`/`sandbox` map to `cie`), and can load them from an
env file:

```python
client = UPSClient.from_env(env_file="src/.env")
```

Then create a client:

```python
from ups_sdk import UPSClient

client = UPSClient.from_env()
```

You can also configure it directly:

```python
from ups_sdk import UPSClient, UPSConfig

client = UPSClient(
    UPSConfig(
        client_id="your app client id",
        client_secret="your app client secret",
        account_number="A1B2C3",
        environment="cie",
    )
)
```

OAuth uses the client-credentials grant with HTTP Basic auth; the account
number is sent as `x-merchant-id`. Tokens are cached and refreshed before
expiry.

## Tracking

```python
from ups_sdk import UPSClient

with UPSClient.from_env() as ups:
    response = ups.track("1Z12345E0291980793", return_milestones=True)

print(response.data)
```

## Rates

```python
rate_request = {
    "RateRequest": {
        "Shipment": {
            "Shipper": {
                "ShipperNumber": "A1B2C3",
                "Address": {"PostalCode": "21093", "CountryCode": "US"},
            },
            "ShipTo": {"Address": {"PostalCode": "30005", "CountryCode": "US"}},
            "Service": {"Code": "03"},
            "Package": [
                {
                    "PackagingType": {"Code": "02"},
                    "PackageWeight": {
                        "UnitOfMeasurement": {"Code": "LBS"},
                        "Weight": "5",
                    },
                }
            ],
        }
    }
}

with UPSClient.from_env() as ups:
    response = ups.rate(rate_request)                  # POST /api/rating/v2409/Rate
    shopped = ups.shop_rates(rate_request)             # POST /api/rating/v2409/Shop
```

To keep quoted == booked, derive the rate request from the exact payload you
will send to `create_shipment` (renames `PaymentInformation` →
`PaymentDetails`, `Packaging` → `PackagingType`, and strips booking-only
blocks), and flatten the reply for comparison:

```python
from ups_sdk import extract_rate_options

with UPSClient.from_env() as ups:
    response = ups.rate_from_ship_payload(shipment_payload)  # rate the pinned service
    shopped = ups.rate_from_ship_payload(shipment_payload, all_services=True)

for option in extract_rate_options(response.data):
    print(option["serviceCode"], option["serviceName"],
          option["totalCharges"], option["negotiatedCharges"], option["daysInTransit"])
```

Pass `negotiated_rates=True` to request account-negotiated rates
(`ShipmentRatingOptions.NegotiatedRatesIndicator`), and
`additional_info="timeintransit"` to combine rating with transit times.

## Shipments

```python
with UPSClient.from_env() as ups:
    response = ups.create_shipment(shipment_request)   # POST /api/shipments/v2409/ship
    label = ups.recover_label(label_recovery_request)  # POST /api/labels/v1/recovery
    voided = ups.void_shipment("1Z2220060290602143")   # DELETE .../void/cancel/{id}
    partial = ups.void_shipment(
        "1Z2220060290602143",
        tracking_numbers=["1Z2220060291994175"],       # void specific packages
    )
```

## Paperless Trade Documents

UPS's Paperless Documents API uploads customized trade documents (base64 in
JSON) to Forms History; the shipper account needs "Upload Forms Created
Offline" enabled. Uploaded DocumentIDs attach to a new shipment through
`InternationalForms` (FormType `07`), or to an existing shipment via the
image repository.

```python
from ups_sdk import UPSClient

with UPSClient.from_env() as ups:
    upload = ups.upload_commercial_invoice("commercial-invoice.pdf")
    document_id = ups.uploaded_document_id(upload)

    shipment_payload = ups.with_paperless_documents(shipment_payload, [document_id])
    response = ups.create_shipment(shipment_payload)
```

The resulting shipment payload includes:

```json
{
  "ShipmentRequest": {
    "Shipment": {
      "ShipmentServiceOptions": {
        "InternationalForms": {
          "FormType": "07",
          "UserCreatedForm": {
            "DocumentID": ["2016-01-18-11.01.07.589501"]
          }
        }
      }
    }
  }
}
```

For post-shipment association and housekeeping:

```python
ups.push_document_to_repository(
    document_ids=[document_id],
    shipment_identifier="1Z2220060290602143",
    shipment_date_and_time="2026-07-06-09.00.00",
    tracking_number="1Z2220060290602143",
)
ups.delete_paperless_document(document_id)
```

Other document types are available as constants (`PACKING_LIST`,
`DECLARATION`, ...) for `upload_paperless_document(document_type=...)`.

## Address Validation

```python
payload = {
    "XAVRequest": {
        "AddressKeyFormat": {
            "AddressLine": ["26601 ALISO CREEK ROAD"],
            "PoliticalDivision2": "ALISO VIEJO",
            "PoliticalDivision1": "CA",
            "PostcodePrimaryLow": "92656",
            "CountryCode": "US",
        }
    }
}

with UPSClient.from_env() as ups:
    response = ups.validate_addresses(payload)  # POST /api/addressvalidation/v2/3
```

Or validate a single Ship-shaped address and get a decision-ready summary
(street-level validation covers US and Puerto Rico; the CIE test environment
only returns results for NY and CA):

```python
from ups_sdk import extract_address_validation, first_candidate

with UPSClient.from_env() as ups:
    response = ups.validate_address(
        {"AddressLine": ["26601 Aliso Creek Rd"], "City": "Aliso Viejo",
         "StateProvinceCode": "CA", "PostalCode": "92656", "CountryCode": "US"}
    )

result = extract_address_validation(response.data)
print(result["valid"], result["classification"], first_candidate(response.data))
```

## Time in Transit

```python
tnt_request = {
    "originCountryCode": "US", "originPostalCode": "21093",
    "destinationCountryCode": "US", "destinationPostalCode": "30005",
    "weight": "5", "weightUnitOfMeasure": "LBS",
    "shipDate": "2026-07-06", "numberOfPackages": "1",
}

with UPSClient.from_env() as ups:
    response = ups.time_in_transit(tnt_request)  # POST /api/shipments/v1/transittimes
```

## Pickups

Pickup addresses use the Pickup API's own field names — `AddressLine` is a
single string and the state field is `StateProvince` — not the Ship API's
`Address` shape. Dates are `YYYYMMDD`, times 24-hour `HHMM`.

```python
with UPSClient.from_env() as ups:
    rates = ups.rate_pickup(pickup_rate_request)   # POST /api/shipments/v2409/pickup/oncall
    pickup = ups.create_pickup(pickup_request)     # POST /api/pickupcreation/v2409/pickup
```

Builder-backed conveniences:

```python
from ups_sdk import extract_pickup_confirmation

with UPSClient.from_env() as ups:
    rates = ups.check_pickup_rate(
        {"AddressLine": "1061 Triad Ct", "City": "Marietta", "StateProvince": "GA",
         "PostalCode": "30062", "CountryCode": "US", "ResidentialIndicator": "N"},
        pickup_date="20260706",
    )
    pickup = ups.schedule_pickup(
        pickup_address={"CompanyName": "Annex Brands", "ContactName": "Pickup Manager",
                        "AddressLine": "1061 Triad Ct", "City": "Marietta",
                        "StateProvince": "GA", "PostalCode": "30062", "CountryCode": "US",
                        "ResidentialIndicator": "N", "Phone": {"Number": "4049997225"}},
        pickup_date="20260706", ready_time="0900", close_time="1700",
        pieces=[{"ServiceCode": "001", "Quantity": "1",
                 "DestinationCountryCode": "US", "ContainerCode": "01"}],
        total_weight_lb=7,
    )
    confirmation = extract_pickup_confirmation(pickup.data)
    cancelled = ups.cancel_pickup(prn=confirmation["prn"])
    status = ups.pickup_pending_status()
```

## Generic Requests

For APIs that do not have a named helper yet, call any UPS endpoint directly:

```python
with UPSClient.from_env() as ups:
    response = ups.post("/api/rating/v2409/Rate", payload)
```

## Error Handling

UPS errors (`{"response": {"errors": [{"code", "message"}]}}`) are raised as
typed exceptions:

```python
from ups_sdk import UPSAPIError, UPSValidationError

try:
    UPSClient.from_env().rate(rate_request)
except UPSValidationError as exc:
    print(exc.status_code, exc.message, exc.transaction_id)
except UPSAPIError as exc:
    print(exc.status_code, exc.message)
```

## Supported Helpers

- `get_access_token(force_refresh=False)`
- `track(inquiry_number, ...)` / `track_by_reference(reference_number, ...)`
- `rate(payload, request_option=...)` / `shop_rates(payload)`
- `rate_from_ship_payload(ship_payload, all_services=False, negotiated_rates=None)`
- `time_in_transit(payload)`
- `create_shipment(payload)`
- `void_shipment(shipment_identification_number, tracking_numbers=None)`
- `recover_label(payload)`
- `validate_addresses(payload)` / `validate_address(address)`
- `rate_pickup(payload)` / `check_pickup_rate(address, ...)`
- `create_pickup(payload)` / `schedule_pickup(...)`
- `cancel_pickup(prn=...)` / `pickup_pending_status(...)`
- `upload_paperless_document(attachment, ...)` / `upload_commercial_invoice(attachment, ...)`
- `push_document_to_repository(...)` / `delete_paperless_document(document_id)`
- `uploaded_document_id(response)` / `uploaded_document_ids(response)`
- `with_paperless_documents(ship_payload, document_ids)`
- `get(path, query=...)`, `post(path, payload)`, `delete(path, ...)`, and `request(...)`

## Development

```bash
python -m unittest
python -m compileall src tests
```

## UPS Documentation

- UPS Developer Portal: https://developer.ups.com/
- API Catalog and Reference: https://developer.ups.com/api/reference
- OAuth Client Credentials: https://developer.ups.com/api/reference?loc=en_US&tag=OAuth-Client-Credentials
- OpenAPI specs: https://github.com/UPS-API/api-documentation
- Rating API: https://developer.ups.com/api/reference?loc=en_US&tag=Rating
- Shipping API: https://developer.ups.com/api/reference?loc=en_US&tag=Shipping
- Tracking API: https://developer.ups.com/api/reference?loc=en_US&tag=Tracking
- Address Validation API: https://developer.ups.com/api/reference?loc=en_US&tag=Address-Validation
- Pickup API: https://developer.ups.com/api/reference?loc=en_US&tag=Pickup
- Paperless Documents API: https://developer.ups.com/api/reference?loc=en_US&tag=Paperless-Documents
- Time in Transit API: https://developer.ups.com/api/reference?loc=en_US&tag=Time-In-Transit
