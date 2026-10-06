from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import data_store  # noqa: E402
import persistence  # noqa: E402


def minimal_store() -> dict:
    return {
        "sociedades": [],
        "regalias": [],
        "boletin_settings": dict(data_store.DEFAULT_BOLETIN_SETTINGS),
        "entregas": [],
        "local_folders": [],
        "uploaded_files": [],
        "active_entrega_id": "",
    }


class DeliveryLifecycleTests(unittest.TestCase):
    def test_finalize_selects_an_open_delivery_and_reopen_restores_editing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with (
                patch.object(data_store, "DATA_DIR", root),
                patch.object(data_store, "STORE_PATH", root / "recepcion_store.json"),
                patch.object(data_store, "UPLOADS_DIR", root / "uploads"),
                patch.object(data_store, "_empty_store", side_effect=minimal_store),
                patch.object(persistence, "restore_state_if_configured", return_value="disabled"),
                patch.object(persistence, "write_block_reason", return_value=""),
                patch.object(persistence, "backup_state_or_raise", return_value=True),
            ):
                first = data_store.create_entrega("1", fecha="2026-01-12")
                second = data_store.create_entrega("2", fecha="2026-02-12")

                data_store.finalize_entrega(second["id"])
                self.assertEqual(data_store.get_entrega()["id"], first["id"])
                self.assertEqual(
                    [row["id"] for row in data_store.list_entregas(include_finalized=False)],
                    [first["id"]],
                )
                with self.assertRaisesRegex(ValueError, "finalizada"):
                    data_store.set_active_entrega(second["id"])

                data_store.finalize_entrega(first["id"])
                self.assertIsNone(data_store.get_entrega())
                with self.assertRaisesRegex(ValueError, "finalizada"):
                    data_store.add_entrega_item({"entrega_id": first["id"], "proveedor": ""})

                reopened = data_store.reopen_entrega(first["id"])
                self.assertFalse(reopened["finalizada"])
                self.assertEqual(data_store.get_entrega()["id"], first["id"])

    def test_annual_certificate_group_includes_every_month_for_the_society(self) -> None:
        store = {
            "entregas": [
                {"id": "e1", "year": "2026", "month": "ENERO", "fecha": "2026-01-12"},
                {"id": "e2", "year": "2026", "month": "FEBRERO", "fecha": "2026-02-12"},
                {"id": "e3", "year": "2025", "month": "DICIEMBRE", "fecha": "2025-12-12"},
            ]
        }

        def boletines(entrega: dict) -> list[dict]:
            return [
                {
                    "sociedad": "SOCIEDAD ANUAL",
                    "nit": "900.000.000-1",
                    "barra": f"BAR-{entrega['id']}",
                    "finos_oro": "10",
                    "finos_plata": "2",
                    "regalia_oro": "100",
                    "regalia_plata": "20",
                }
            ]

        with (
            patch.object(data_store, "load_store", return_value=store),
            patch.object(data_store, "boletines_for_entrega", side_effect=boletines),
        ):
            annual = data_store.certificado_groups("2026")
            monthly = data_store.certificado_groups("2026", "ENERO")

        self.assertEqual(len(annual), 1)
        self.assertEqual([row["documento"] for row in annual[0]["boletines"]], ["BAR-e1", "BAR-e2"])
        self.assertEqual([row["mes"] for row in annual[0]["boletines"]], ["ENERO", "FEBRERO"])
        self.assertEqual(len(monthly[0]["boletines"]), 1)


if __name__ == "__main__":
    unittest.main()
