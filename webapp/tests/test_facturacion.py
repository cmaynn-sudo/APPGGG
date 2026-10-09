from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import app  # noqa: E402
import calculations  # noqa: E402
import data_store  # noqa: E402


def example_boletin() -> dict:
    return {
        "sociedad": "NEGOCIOS VALLE DEL ABURRA",
        "barra": "ABUR-78-LI",
        "peso_fin_value": 311.2,
        "fino_oro_value": 220.86,
        "fino_plata_value": 36.06,
        "precio_oro_cop_value": 414176,
        "valor_total_metales_value": 91580675.34,
        "valor_a_pagar_value": 89291158.46,
        "regalia_oro_total_value": 3000000,
        "regalia_plata_total_value": 134100.14,
        "valor_transferir_value": 86157058.32,
    }


def example_store() -> dict:
    return {
        "boletin_settings": dict(data_store.DEFAULT_BOLETIN_SETTINGS),
        "regalias": [{"mes": "ENERO", "au": 5000, "ag": 50}],
        "active_entrega_id": "otra-entrega",
        "entregas": [
            {
                "id": "entrega-solicitada",
                "name": "ENTREGA 1",
                "fecha": "2026-01-12",
                "month": "ENERO",
                "parametros": {
                    "mes_regalias": "ENERO",
                    "dolar": 1000,
                    "oz_au": 31.10347,
                    "oz_ag": 31.10347,
                },
                "items": [
                    {
                        "id": "item-1",
                        "proveedor": "COMERCIALIZADORA TEST",
                        "codigo": "TEST-1",
                        "peso_ini": 1100,
                        "peso_fin": 1000,
                        "ley_au": 750,
                        "ley_ag": 100,
                    },
                    {
                        "id": "item-incompleto",
                        "proveedor": "SIN LEYES",
                        "codigo": "PENDIENTE-1",
                        "ley_au": "",
                        "ley_ag": "",
                    },
                ],
            },
            {
                "id": "otra-entrega",
                "fecha": "2026-02-12",
                "items": [{"proveedor": "OTRA ENTREGA", "ley_au": 750, "ley_ag": 100}],
            },
        ],
    }


class FacturacionTextTests(unittest.TestCase):
    def test_preserves_sample_structure_and_uses_amount_payable(self) -> None:
        boletin = example_boletin()
        original = copy.deepcopy(boletin)
        text = calculations.facturacion_text([boletin])

        self.assertEqual(
            text,
            "C.I. GREEN GLOBAL GROUP S.A.S.\r\n"
            "NEGOCIOS VALLE DEL ABURRA\r\n"
            "ABUR-78-LI\r\n"
            "Peso final: 311,20\r\n"
            "Gramos oro: 220,86\r\n"
            "Gramos plata: 36,06\r\n"
            "Subtotal: 91.580.675,34\r\n"
            "Regalias: 3.134.100,14\r\n"
            "Valor total: 89.291.158,46\r\n"
            "\r\n"
            "Valor de negociación por gramo:  $414.176,00\r\n"
            "\r\n"
            "ORO EN DESUSO BOLETIN #ABUR-78-LI FINAL: 311,20 GR\r\n"
            "VTA JOYERIA ORO EN DESUSO PUROS AU:220,86 GR AG:36,06 GR "
            "FINAL:311,20 GR BOLETIN #ABUR-78-LI\r\n"
            "------------------------------------\r\n",
        )
        self.assertEqual(boletin, original)

    def test_includes_all_bulletins_in_order_with_separate_blocks(self) -> None:
        second = {**example_boletin(), "sociedad": "ALEXANDRA RAMÍREZ", "barra": "ALRA-16-LI"}
        text = calculations.facturacion_text([example_boletin(), second])

        self.assertEqual(text.count("C.I. GREEN GLOBAL GROUP S.A.S."), 2)
        self.assertEqual(text.count("------------------------------------"), 2)
        self.assertLess(text.index("ABUR-78-LI"), text.index("ALRA-16-LI"))
        self.assertIn("------------------------------------\r\n\r\n\r\nC.I.", text)
        self.assertIn("ALEXANDRA RAMÍREZ", text)

    def test_uses_existing_bulletin_calculations_and_excludes_pending_items(self) -> None:
        store = example_store()
        entrega = store["entregas"][0]
        with patch.object(data_store, "load_store", return_value=store):
            boletines = data_store.boletines_for_entrega(entrega)
        text = calculations.facturacion_text(boletines)

        self.assertEqual(len(boletines), 1)
        self.assertIn("Peso final: 1.000,00", text)
        self.assertIn("Gramos oro: 750,00", text)
        self.assertIn("Gramos plata: 100,00", text)
        self.assertIn("Subtotal: 781.250,00", text)
        self.assertIn("Regalias: 150.200,00", text)
        self.assertIn("Valor total: 761.718,75", text)
        self.assertIn("Valor de negociación por gramo:  $975,00", text)
        self.assertNotIn("611.518,75", text)
        self.assertNotIn("PENDIENTE-1", text)

    def test_honors_delivery_specific_negotiation_and_withholding(self) -> None:
        store = example_store()
        entrega = store["entregas"][0]
        entrega["boletin_settings"] = {"precio_negociacion_porcentaje": 90, "retencion_porcentaje": 0}
        entrega["items"].append(
            {"codigo": "PLATA-1", "proveedor": "SOLO PLATA", "peso_fin": 100, "ley_au": 0, "ley_ag": 100}
        )
        with patch.object(data_store, "load_store", return_value=store):
            boletines = data_store.boletines_for_entrega(entrega)
        text = calculations.facturacion_text(boletines)

        self.assertEqual(len(boletines), 2)
        self.assertIn("Valor total: 725.000,00", text)
        self.assertIn("Valor de negociación por gramo:  $900,00", text)
        self.assertIn("PUROS AU:0,00 GR AG:10,00 GR FINAL:100,00 GR BOLETIN #PLATA-1", text)


class FacturacionDownloadTests(unittest.TestCase):
    def handler(self, path: str, logged_in: bool = True) -> app.RecepcionHandler:
        handler = object.__new__(app.RecepcionHandler)
        handler.path = path
        handler.require_login = Mock(return_value=logged_in)
        handler.send_bytes = Mock()
        handler.send_error = Mock()
        return handler

    def test_download_uses_requested_delivery_not_active_delivery(self) -> None:
        handler = self.handler("/boletines/entrega-solicitada/facturacion.txt")
        with patch.object(data_store, "load_store", return_value=example_store()):
            handler.do_GET()

        handler.send_error.assert_not_called()
        body, content_type = handler.send_bytes.call_args.args
        self.assertEqual(content_type, "text/plain; charset=utf-8")
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        text = body.decode("utf-8-sig")
        self.assertIn("COMERCIALIZADORA TEST", text)
        self.assertNotIn("OTRA ENTREGA", text)
        self.assertIn("negociación", text)
        self.assertEqual(handler.send_bytes.call_args.kwargs, {"filename": "FACTURACION.txt", "attachment": True})

    def test_download_requires_existing_login_without_extra_authorization(self) -> None:
        handler = self.handler("/boletines/entrega-solicitada/facturacion.txt", logged_in=False)
        with patch.object(data_store, "get_entrega") as get_entrega:
            handler.do_GET()

        get_entrega.assert_not_called()
        handler.send_bytes.assert_not_called()

    def test_missing_delivery_or_empty_bulletins_returns_not_found(self) -> None:
        for entrega in (None, {"id": "entrega-solicitada", "items": []}):
            with self.subTest(entrega=entrega):
                handler = self.handler("/boletines/entrega-solicitada/facturacion.txt")
                with (
                    patch.object(data_store, "get_entrega", return_value=entrega),
                    patch.object(data_store, "boletines_for_entrega", return_value=[]),
                ):
                    handler.do_GET()

                self.assertEqual(handler.send_error.call_args.args[0], 404)
                handler.send_bytes.assert_not_called()

    def test_module_offers_one_discreet_button_only_when_bulletins_are_ready(self) -> None:
        entrega = example_store()["entregas"][0]
        for boletines in ([], [example_boletin()]):
            with self.subTest(ready=bool(boletines)):
                html = app.env.get_template("boletines.html").render(
                    entrega=entrega,
                    boletines=boletines,
                    settings=data_store.DEFAULT_BOLETIN_SETTINGS,
                    months=["ENERO"],
                    public=False,
                    user={"username": "admin", "role": "SUPERUSER"},
                    request_path="/boletines",
                    asset_version="test",
                    backup_status={"required": False, "enabled": True, "write_ready": True},
                )

                self.assertEqual(html.count('download="FACTURACION.txt"'), int(bool(boletines)))
                if boletines:
                    self.assertIn('/boletines/entrega-solicitada/facturacion.txt', html)
                    self.assertIn('data-tooltip="Descargar resumen de facturación de esta entrega (TXT)"', html)


if __name__ == "__main__":
    unittest.main()
