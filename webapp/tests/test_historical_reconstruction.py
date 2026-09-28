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
        "sociedades": [
            {
                "sociedad": "SOCIEDAD HISTÓRICA",
                "nit": "900.000.000-1",
                "rucom": "123",
                "municipio": "MEDELLÍN",
                "prefijo": "HIS",
                "consecutivo": 7,
            }
        ],
        "regalias": [{"mes": "ABRIL", "au": 1000, "ag": 50}],
        "boletin_settings": dict(data_store.DEFAULT_BOLETIN_SETTINGS),
        "entregas": [],
        "local_folders": [],
        "uploaded_files": [],
        "active_entrega_id": "",
    }


class HistoricalReconstructionTests(unittest.TestCase):
    def test_historical_delivery_keeps_date_and_own_parameters(self) -> None:
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
                entrega = data_store.create_historical_entrega(
                    {
                        "numero": "6",
                        "fecha": "2026-04-09",
                        "mes_regalias": "ABRIL",
                        "dolar": "4200",
                        "oz_au": "2300,50",
                        "oz_ag": "28.75",
                        "precio_negociacion_porcentaje": "96",
                        "retencion_porcentaje": "2,5",
                        "source_folder_id": "folder-6",
                    }
                )
                item = data_store.add_entrega_item(
                    {
                        "entrega_id": entrega["id"],
                        "proveedor": "SOCIEDAD HISTÓRICA",
                        "codigo": "HIS-OLD",
                        "peso_inicial": "1000",
                        "peso_post": "900",
                        "muestras": "0",
                    }
                )
                store = data_store.load_store()
                stored = store["entregas"][0]

                stored["items"][0]["ley_au"] = "800"
                stored["items"][0]["ley_ag"] = "20"
                data_store.save_store(store)
                boletin = data_store.boletines_for_entrega(stored)[0]

        self.assertEqual(entrega["fecha"], "2026-04-09")
        self.assertEqual(entrega["month"], "ABRIL")
        self.assertEqual(entrega["name"], "ENTREGA °6 - (2026-04-09)")
        self.assertEqual(entrega["parametros"]["dolar"], "4200")
        self.assertEqual(entrega["parametros"]["oz_au"], "2300,5")
        self.assertEqual(entrega["boletin_settings"]["precio_negociacion_porcentaje"], "96")
        self.assertEqual(entrega["reconstructed_from_folder_id"], "folder-6")
        self.assertEqual(item["codigo"], "HIS-OLD")
        self.assertEqual(store["sociedades"][0]["consecutivo"], 7)
        self.assertEqual(boletin["fecha"], "09/04/2026")
        self.assertEqual(boletin["precio_negociacion_porcentaje"], "96,00%")


if __name__ == "__main__":
    unittest.main()
