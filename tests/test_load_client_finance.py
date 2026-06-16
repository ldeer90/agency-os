from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "load_client_finance.py"
SPEC = importlib.util.spec_from_file_location("load_client_finance", SCRIPT_PATH)
load_client_finance = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(load_client_finance)


class LoadClientFinanceTests(unittest.TestCase):
    def test_monday_client_board_overlays_future_retainers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board_path = Path(tmp) / "client_board.json"
            board_path.write_text(
                json.dumps(
                    {
                        "name": "Client Board",
                        "items_page": {
                            "items": [
                                {
                                    "id": "1",
                                    "name": "TravelKon",
                                    "group": {"title": "Current Clients"},
                                    "column_values": [
                                        {"id": "date4", "text": "2026-03-02"},
                                        {"id": "numeric_mm0tfsvq", "text": "14200"},
                                        {"id": "text_mm0z9mb9", "text": "Beginning of Month"},
                                    ],
                                },
                                {
                                    "id": "2",
                                    "name": "Old Client",
                                    "group": {"title": "Lost Clients"},
                                    "column_values": [{"id": "numeric_mm0tfsvq", "text": "9999"}],
                                },
                                {
                                    "id": "3",
                                    "name": "Shop rongrong",
                                    "group": {"title": "Current Clients"},
                                    "column_values": [
                                        {"id": "numeric_mm0tfsvq", "text": "800"},
                                        {"id": "text_mm2tew4n", "text": "Additional $1000"},
                                    ],
                                },
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            base_rows = [
                {
                    "period_id": "2026-05",
                    "client_slug": "travelkon",
                    "billing_status": "issued",
                    "expense_amount_aud": 0,
                },
                {
                    "period_id": "2026-08",
                    "client_slug": "travelkon",
                    "billing_status": "planned",
                    "expense_amount_aud": 0,
                },
            ]

            rows = load_client_finance.parse_monday_client_board_rows(
                board_path,
                run_id="test",
                ingested_at="2026-06-14T00:00:00+10:00",
                periods=["2026-05", "2026-08"],
                base_rows=base_rows,
            )

        self.assertFalse(any(row["client_slug"] == "old-client" for row in rows))
        travelkon_aug = next(row for row in rows if row["client_slug"] == "travelkon" and row["period_id"] == "2026-08")
        self.assertEqual(travelkon_aug["retainer_amount_aud"], 14200)
        self.assertEqual(travelkon_aug["source_id"], "monday_client_board")
        shop_aug = next(row for row in rows if row["client_slug"] == "shop-rongrong" and row["period_id"] == "2026-08")
        self.assertEqual(shop_aug["retainer_amount_aud"], 1800)


if __name__ == "__main__":
    unittest.main()
