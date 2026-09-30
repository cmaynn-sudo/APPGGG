from __future__ import annotations

import sys
import unittest
from pathlib import Path


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import app  # noqa: E402


class TemplateRenderingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
