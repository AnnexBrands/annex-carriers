"""Upload a pre-shipment commercial invoice and attach it to a shipment payload.

Usage:
    python examples/fedex_preshipment_commercial_invoice.py invoice.pdf

This example prints the shipment payload with the FedEx ETD reference attached.
Uncomment the final create_shipment call only when you are ready to create a
real shipment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from carriers.fedex import COMMERCIAL_INVOICE, FedExClient


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python examples/fedex_preshipment_commercial_invoice.py invoice.pdf")
        return 2

    invoice_path = Path(sys.argv[1])
    client = FedExClient.from_env(env_file="src/.env")

    upload = client.documents.upload_pre_shipment(
        invoice_path,
        origin_country_code="US",
        destination_country_code="CA",
        carrier_code="FDXE",
        transaction_id=f"commercial-invoice-{invoice_path.stem}",
    )
    document_id = client.documents.document_id(upload)
    if not document_id:
        raise RuntimeError(f"FedEx upload response did not contain a docId: {upload.data!r}")

    document_reference = client.documents.reference(
        document_id,
        document_reference=invoice_path.stem,
        description="Commercial Invoice",
    )

    shipment_payload = {
        "labelResponseOptions": "URL_ONLY",
        "requestedShipment": {
            "shipper": {},
            "recipients": [],
            "shippingChargesPayment": {},
            "customsClearanceDetail": {},
            "labelSpecification": {},
            "requestedPackageLineItems": [],
        },
        "accountNumber": {"value": client.config.account_number},
    }
    shipment_payload = client.documents.attach_to_shipment(
        shipment_payload,
        [document_reference],
        requested_document_types=[COMMERCIAL_INVOICE],
    )

    print(json.dumps(shipment_payload, indent=2))

    # response = client.ship.create(shipment_payload)
    # print(json.dumps(response.data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
