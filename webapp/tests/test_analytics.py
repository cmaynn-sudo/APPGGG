from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import analytics  # noqa: E402


class DashboardSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_load_store = analytics.data_store.load_store
        self.original_all_folders = analytics.document_library.all_folders
        self.original_structured = analytics.structured_billing_records
        self.original_historical = analytics.historical_billing_records

        self.records = [
            {
                "source": "web",
                "source_label": "Web",
                "delivery_id": "e1",
                "delivery_label": "ENTREGA 1",
                "documento": "A-1",
                "sociedad": "ALFA",
                "date": "2026-01-02",
                "year": "2026",
                "month_number": 1,
                "subtotal": 1000.0,
                "valor_a_pagar": 900.0,
                "regalia_oro": 50.0,
                "regalia_plata": 10.0,
                "valor_pagado": 840.0,
                "peso_inicial": 100.0,
                "peso_final": 95.0,
            },
            {
                "source": "web",
                "source_label": "Web",
                "delivery_id": "e2",
                "delivery_label": "ENTREGA 2",
                "documento": "B-1",
                "sociedad": "BETA",
                "date": "2026-02-03",
                "year": "2026",
                "month_number": 2,
                "subtotal": 2000.0,
                "valor_a_pagar": 1800.0,
                "regalia_oro": 100.0,
                "regalia_plata": 20.0,
                "valor_pagado": 1680.0,
                "peso_inicial": 200.0,
                "peso_final": 190.0,
            },
        ]
        analytics.data_store.load_store = lambda: {}
        analytics.document_library.all_folders = lambda: []
        analytics.structured_billing_records = lambda _store: [dict(row) for row in self.records]
        analytics.historical_billing_records = lambda _folders: iter(())

    def tearDown(self) -> None:
        analytics.data_store.load_store = self.original_load_store
        analytics.document_library.all_folders = self.original_all_folders
        analytics.structured_billing_records = self.original_structured
        analytics.historical_billing_records = self.original_historical

    def test_totals_use_boletin_financial_fields(self) -> None:
        result = analytics.dashboard_summary({"year": "2026"})

        self.assertEqual(result["totals"]["subtotal"], 3000.0)
        self.assertEqual(result["totals"]["valor_a_pagar"], 2700.0)
        self.assertEqual(result["totals"]["regalia_oro"], 150.0)
        self.assertEqual(result["totals"]["regalia_plata"], 30.0)
        self.assertEqual(result["totals"]["valor_pagado"], 2520.0)
        self.assertEqual(result["totals"]["peso_inicial"], 300.0)
        self.assertEqual(result["totals"]["peso_final"], 285.0)
        self.assertEqual(result["totals"]["peso_diferencia"], -15.0)
        self.assertEqual(result["totals"]["peso_diferencia_porcentaje"], -0.05)
        self.assertEqual(result["totals"]["peso_diferencia_porcentaje_display"], "-5,00%")

    def test_money_and_weight_charts_use_independent_scales(self) -> None:
        result = analytics.dashboard_summary({"year": "2026"})
        january, february = result["months"][:2]

        self.assertEqual(january["subtotal_bar_percent"], 50.0)
        self.assertEqual(february["subtotal_bar_percent"], 100.0)
        self.assertEqual(january["peso_inicial_bar_percent"], 50.0)
        self.assertEqual(january["peso_final_bar_percent"], 47.5)
        self.assertEqual(february["peso_inicial_bar_percent"], 100.0)
        self.assertEqual(february["peso_final_bar_percent"], 95.0)

    def test_month_delivery_and_provider_filters_combine(self) -> None:
        result = analytics.dashboard_summary(
            {"year": "2026", "month": "1", "entrega": "e1", "proveedor": "ALFA"}
        )

        self.assertEqual(result["active_filter_count"], 3)
        self.assertEqual(result["totals"]["subtotal"], 1000.0)
        self.assertEqual(result["totals"]["entregas"], 1)
        self.assertEqual(len(result["months"]), 1)
        self.assertEqual(result["months"][0]["number"], 1)

    def test_duplicate_documents_do_not_double_totals_but_delivery_remains_filterable(self) -> None:
        duplicate = dict(self.records[0])
        duplicate.update({"delivery_id": "e3", "delivery_label": "ENTREGA 3", "source": "local"})
        self.records.append(duplicate)

        complete = analytics.dashboard_summary({"year": "2026"})
        filtered = analytics.dashboard_summary({"year": "2026", "entrega": "e3"})

        self.assertEqual(complete["totals"]["subtotal"], 3000.0)
        self.assertEqual(len(complete["delivery_options"]), 3)
        self.assertEqual(filtered["totals"]["subtotal"], 1000.0)
        self.assertEqual(filtered["totals"]["entregas"], 1)

    def test_diagnostics_identify_pdf_without_extractable_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            path = Path(raw_root) / "BOLETIN - MANUAL.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with path.open("wb") as target:
                writer.write(target)

            folder = {
                "id": "historica-1",
                "source": "local",
                "name": "ENTREGA °4 - (2026-02-12)",
                "href": "/entregas/local/historica-1",
                "year": "2026",
                "month": "FEBRERO",
                "date": "2026-02-12",
                "folder": {"delivery_number": "4"},
            }
            detail = {
                "docs": [
                    {
                        "id": "pdf-1",
                        "name": path.name,
                        "category": "Boletines",
                        "view_url": "/archivos/subido/pdf-1",
                        "download_url": "/archivos/subido/pdf-1?download=1",
                    }
                ]
            }
            analytics.PDF_CACHE.clear()
            analytics.PDF_ERROR_CACHE.clear()
            with (
                patch.object(analytics.document_library, "folder_detail", return_value=detail),
                patch.object(analytics, "document_path", return_value=path),
            ):
                result = analytics.historical_pdf_diagnostics([folder], {"entregas": []})

        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["readable"], 0)
        self.assertEqual(result["unreadable"], 1)
        self.assertEqual(result["groups"][0]["delivery_number"], "4")
        self.assertIn("no contiene texto", result["groups"][0]["documents"][0]["reason"])

    def test_old_regalizas_label_is_read_without_losing_royalties(self) -> None:
        text = """
        DOCUMENTO: CORI-4 PROVEEDOR: COMERCIAL RIO VERDE S.A.S NIT: 900.534.616-3
        FECHA DE LIQUIDACION: 12/03/2026
        PESO RECIBIDO PESO FUNDIDO 1.000 G 920 G
        FINO (G) 895,25 24,75
        VALOR TOTAL METALES (COP) $ 100.000.000
        VALOR A PAGAR (COP) $ 97.500.000
        REGALIZAS ADEUDADAS POR EL PROVEEDOR ORO PLATA $ 474.135 $ 7.785,95
        VALOR PAGADO $ 97.018.079
        """

        result, reason = analytics.parse_billing_text(text)

        self.assertEqual(reason, "")
        self.assertIsNotNone(result)
        self.assertEqual(result["regalia_oro"], 474135.0)
        self.assertEqual(result["regalia_plata"], 7785.95)
        self.assertEqual(result["nit"], "900.534.616-3")
        self.assertEqual(result["finos_oro"], 895.25)
        self.assertEqual(result["finos_plata"], 24.75)
        self.assertEqual(result["_missing_fields"], [])
        self.assertEqual(result["_certificate_missing_fields"], [])

    def test_manual_override_fills_only_dashboard_missing_fields(self) -> None:
        record = {
            "documento": "CORI-4",
            "date": "2026-03-12",
            "regalia_oro": 0.0,
            "regalia_plata": 0.0,
            "_missing_fields": ["regalia_oro", "regalia_plata"],
            "_certificate_missing_fields": ["finos_oro", "finos_plata"],
        }
        override = {
            "values": {
                "regalia_oro": 474135.0,
                "regalia_plata": 7785.95,
                "finos_oro": 895.25,
                "finos_plata": 24.75,
            }
        }

        corrected = analytics.apply_dashboard_override(record, override)

        self.assertEqual(corrected["regalia_oro"], 474135.0)
        self.assertEqual(corrected["regalia_plata"], 7785.95)
        self.assertEqual(corrected["finos_oro"], 895.25)
        self.assertEqual(corrected["_missing_fields"], [])
        self.assertEqual(corrected["_certificate_missing_fields"], [])
        self.assertTrue(corrected["_manual_override"])

    def test_web_bulletin_columns_and_royalty_totals_are_read(self) -> None:
        text = """
        DOCUMENTO: TEST-1 FECHA DE LIQUIDACIÓN: 2026-10-07
        PROVEEDOR: PRUEBA SAS NIT: 900.000.000-1
        PESO RECIBIDO 1.000 G PESO FUNDIDO 920 G
        VARIABLES LEY % FINO (G) PRECIO (COP) VALOR METAL (COP)
        ORO 850 782 $ 288.392 $ 225.522.544
        PLATA 120 110,4 $ 1.929 $ 212.962
        VALOR TOTAL METALES (COP) RETEFUENTE (COP) VALOR A PAGAR (COP)
        $ 225.735.506 $ -5.643.388 $ 220.092.118
        REGALÍAS ADEUDADAS POR EL PROVEEDOR OCTUBRE 2026
        ORO PLATA $ 20.000 $ 300,00 $ 15.640.000 $ 33.120
        VALOR A TRANSFERIR $ 204.418.998
        """
        result, reason = analytics.parse_billing_text(text)
        self.assertEqual(reason, "")
        self.assertEqual(result["peso_inicial"], 1000)
        self.assertEqual(result["finos_oro"], 782)
        self.assertEqual(result["finos_plata"], 110.4)
        self.assertEqual(result["subtotal"], 225735506)
        self.assertEqual(result["valor_a_pagar"], 220092118)
        self.assertEqual(result["regalia_oro"], 15640000)
        self.assertEqual(result["regalia_plata"], 33120)
        self.assertEqual(result["_certificate_missing_fields"], [])


if __name__ == "__main__":
    unittest.main()
