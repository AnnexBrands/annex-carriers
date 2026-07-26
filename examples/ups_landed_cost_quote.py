"""Quote landed cost for an international shipment.

Usage:
    python examples/ups_landed_cost_quote.py

Landed Cost is one of the eleven UPS families the SDK did not reach before
0.2. Nothing here books anything — it is a quote.
"""

from __future__ import annotations

import json

from carriers.ups import UPSClient, extract_landed_cost_totals


def main() -> int:
    client = UPSClient.from_env(env_file="src/.env")

    response = client.trade.landed_cost(
        shipment_id="EXAMPLE-1",
        import_country_code="GB",
        export_country_code="US",
        currency_code="GBP",
        items=[
            {
                "hsCode": "400932",
                "priceEach": "125",
                "quantity": 24,
                "UOM": "Each",
                "originCountryCode": "US",
                "description": "Rubber tubing",
            }
        ],
    )

    totals = extract_landed_cost_totals(response.data)
    print(json.dumps(totals, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
