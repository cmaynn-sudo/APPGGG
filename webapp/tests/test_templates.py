from __future__ import annotations

import sys
import unittest
from pathlib import Path


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import app  # noqa: E402


class TemplateRenderingTests(unittest.TestCase):
    def base_context(self, request_path: str) -> dict:
        return {
            "public": False,
            "user": {"username": "admin", "role": "SUPERUSER"},
            "request_path": request_path,
            "asset_version": "test",
            "backup_status": {"required": False, "enabled": True, "write_ready": True},
        }

    def test_data_quality_renders_issue_values_without_dict_method_collision(self) -> None:
        fields = {
            "documento": "CORI-4",
            "sociedad": "COMERCIAL RIO VERDE S.A.S",
            "date": "2026-03-12",
            "subtotal": "100.000.000",
            "valor_a_pagar": "97.500.000",
            "regalia_oro": "474.135",
            "regalia_plata": "7.785,95",
            "valor_pagado": "97.018.079",
            "peso_inicial": "1.000",
            "peso_final": "920",
        }
        quality = {
            "scanned": 1,
            "incomplete": 1,
            "unreadable": 0,
            "corrected": 0,
            "items": [
                {
                    "quality_id": "uploaded:abc",
                    "document_name": "BOLETIN - CORI-4.pdf",
                    "folder_name": "ENTREGA 4",
                    "folder_href": "/entregas/local/abc",
                    "view_url": "/archivos/subido/abc",
                    "values": fields,
                    "missing_fields": ["regalia_oro"],
                    "missing_labels": ["Regalías oro"],
                    "reason": "",
                    "readable": True,
                    "corrected": False,
                    "complete": False,
                }
            ],
        }

        html = app.env.get_template("data_quality.html").render(
            quality=quality,
            message="",
            public=False,
            user={"username": "admin", "role": "SUPERUSER"},
            request_path="/control-datos",
            asset_version="test",
            backup_status={"required": False, "enabled": True, "write_ready": True},
        )

        self.assertIn("BOLETIN - CORI-4.pdf", html)
        self.assertIn('value="474.135"', html)
        self.assertIn("Guardar corrección", html)

    def test_layout_editor_renders_selectable_template_and_controls(self) -> None:
        template = app.TEMPLATE_BY_SLUG["recibo-metales"]
        html = app.env.get_template("layout_editor.html").render(
            templates=app.TEMPLATES,
            template=template,
            generated_template=template.render_template_name,
            layout={"elements": {}, "updated_at": ""},
            layout_css="",
            message="",
            public=False,
            user={"username": "admin", "role": "SUPERUSER"},
            request_path="/editor-plantillas",
            asset_version="test",
            backup_status={"required": False, "enabled": True, "write_ready": True},
            **app.SAMPLE_CONTEXT,
        )

        self.assertIn("Diseño de planillas", html)
        self.assertIn('data-layout-editor', html)
        self.assertIn('data-layout-element-select', html)
        self.assertIn('data-layout-control="scale"', html)
        self.assertIn('data-layout-id="cell-I15"', html)

    def test_annual_certificate_renders_all_rows_without_monthly_limit(self) -> None:
        boletines = [
            {
                "documento": f"BAR-{index}",
                "fecha": f"2026-0{min(index, 9)}-12",
                "mes": "ENERO",
                "finos_oro": "10,00",
                "finos_plata": "2,00",
                "regalia_oro": "$ 100",
                "regalia_plata": "$ 20",
            }
            for index in range(1, 7)
        ]
        html = app.env.get_template("manual/certificado-anual.html").render(
            sociedad="SOCIEDAD ANUAL",
            nit="900.000.000-1",
            periodo_label="Año 2026",
            fecha_larga="6 de octubre de 2026",
            boletines=boletines,
            totales={
                "finos_oro": "60,00",
                "finos_plata": "12,00",
                "regalia_oro": "$ 600",
                "regalia_plata": "$ 120",
            },
        )

        self.assertIn("Certificado anual de regalías", html)
        self.assertIn("BAR-6", html)
        self.assertIn("Total anual", html)

    def test_certificates_keep_monthly_mode_and_offer_annual_mode(self) -> None:
        html = app.env.get_template("certificados.html").render(
            period="annual",
            year="2026",
            month="",
            years=["2026"],
            months=["ENERO"],
            groups=[
                {
                    "key": "sociedad-anual",
                    "sociedad": "SOCIEDAD ANUAL",
                    "nit": "900.000.000-1",
                    "boletines": [{"documento": "BAR-1"}],
                }
            ],
            **self.base_context("/certificados?period=annual&year=2026"),
        )

        self.assertIn("Mensuales", html)
        self.assertIn("Anuales", html)
        self.assertIn("/print/certificado-anual/2026/sociedad-anual", html)

    def test_application_signature_is_present_in_authenticated_layout(self) -> None:
        html = app.env.get_template("base.html").render(
            **self.base_context("/"),
        )

        self.assertIn("ANGEL SISTEMS", html)

    def test_login_keeps_authentication_form_without_workspace_navigation(self) -> None:
        html = app.env.get_template("login.html").render(
            public=True,
            user=None,
            request_path="/login",
            asset_version="test",
            next="/entregas",
            error="Credenciales incorrectas",
        )

        self.assertIn("Software de operaciones", html)
        self.assertIn("C.I. Green Global Group", html)
        self.assertIn('method="post" action="/login"', html)
        self.assertIn('name="next" value="/entregas"', html)
        self.assertIn('name="username" autocomplete="username"', html)
        self.assertIn('name="password" type="password"', html)
        self.assertIn('role="alert">Credenciales incorrectas', html)
        self.assertNotIn('class="sidebar"', html)


if __name__ == "__main__":
    unittest.main()
