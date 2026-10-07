from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import data_store  # noqa: E402
import renderer  # noqa: E402


class LayoutEditorTests(unittest.TestCase):
    def test_layout_values_are_validated_before_persisting(self) -> None:
        store = {"template_layouts": {}}
        submitted = json.dumps(
            {
                "cell-I15": {
                    "x": 900,
                    "y": -12.5,
                    "scale": 1.2,
                    "font_size": 0.5,
                    "width": 1600,
                    "height": 0.5,
                    "nowrap": True,
                    "hidden": True,
                    "text_align": "justify",
                    "text_override": "Representante legal actualizado",
                },
                "image-1": {"x": "nan", "scale": "infinity"},
                "bad selector": {"x": 10},
            }
        )

        with (
            patch.object(data_store, "load_store", return_value=store),
            patch.object(data_store, "save_store") as save_store,
        ):
            layout = data_store.update_template_layout("recibo-metales", submitted)

        settings = layout["elements"]["cell-I15"]
        self.assertEqual(settings["x"], 500.0)
        self.assertEqual(settings["y"], -12.5)
        self.assertEqual(settings["font_size"], 0.0)
        self.assertEqual(settings["width"], 1200.0)
        self.assertEqual(settings["height"], 0.0)
        self.assertEqual(settings["text_align"], "")
        self.assertTrue(settings["nowrap"])
        self.assertTrue(settings["hidden"])
        self.assertEqual(settings["text_override"], "Representante legal actualizado")
        self.assertEqual(layout["elements"]["image-1"]["x"], 0.0)
        self.assertEqual(layout["elements"]["image-1"]["scale"], 1.0)
        self.assertNotIn("bad selector", layout["elements"])
        save_store.assert_called_once_with(store)

    def test_saved_layout_css_is_included_in_print_html(self) -> None:
        layout = {
            "elements": {
                "cell-I15": {
                    "x": 12,
                    "y": -4,
                    "scale": 1.1,
                    "font_size": 16,
                    "nowrap": True,
                    "text_align": "center",
                }
            }
        }

        with (
            patch.object(data_store, "get_template_layout", return_value=layout),
            patch.object(data_store, "get_template_assets", return_value={}),
        ):
            html = renderer.render_print_html("recibo-metales")

        self.assertIn('[data-layout-id="cell-I15"]', html)
        self.assertIn("translate(12.00px, -4.00px) scale(1.100)", html)
        self.assertIn("font-size:16.00px", html)
        self.assertIn("white-space:nowrap", html)
        self.assertIn("text-align:center", html)

    def test_corrupt_saved_numbers_fall_back_to_safe_css(self) -> None:
        css = renderer.template_layout_css(
            "recibo-metales",
            {
                "elements": {
                    "cell-I15": {
                        "x": "not-a-number",
                        "y": float("nan"),
                        "scale": float("inf"),
                        "font_size": "broken",
                    }
                }
            },
        )

        self.assertIn("translate(0.00px, 0.00px) scale(1.000)", css)
        self.assertNotIn("font-size", css)

    def test_cell_dimensions_resize_its_excel_column_and_row(self) -> None:
        css = renderer.template_layout_css(
            "preliminares",
            {
                "elements": {
                    "cell-B6": {
                        "width": 260,
                        "height": 48,
                        "hidden": True,
                    }
                }
            },
        )

        self.assertIn("col:nth-child(2){width:260.00px", css)
        self.assertIn("tr:nth-of-type(6){height:48.00px", css)
        self.assertIn('[data-layout-id="cell-B6"]{', css)
        self.assertIn("display:none !important", css)
        self.assertNotIn("display:block !important", css)

    def test_custom_text_is_escaped_and_preserves_line_breaks(self) -> None:
        body = '<p data-layout-id="block-legal-name">Texto original</p>'
        result = renderer.apply_template_content_overrides(
            body,
            {
                "elements": {
                    "block-legal-name": {"text_override": "Ángel & Asociados\nRepresentante <Legal>"}
                }
            },
            {},
        )

        self.assertIn("Ángel &amp; Asociados<br>Representante &lt;Legal&gt;", result)
        self.assertNotIn("Texto original", result)

    def test_signature_asset_is_saved_inside_persistent_uploads(self) -> None:
        store = {"template_assets": {}}
        with tempfile.TemporaryDirectory() as raw_root:
            uploads = Path(raw_root) / "uploads"
            with (
                patch.object(data_store, "UPLOADS_DIR", uploads),
                patch.object(data_store, "TEMPLATE_ASSET_DIR", uploads / "template-assets"),
                patch.object(data_store, "load_store", return_value=store),
                patch.object(data_store, "save_store") as save_store,
            ):
                metadata = data_store.save_template_asset(
                    "certificado-anual",
                    "image-signature",
                    "firma nueva.png",
                    b"\x89PNG\r\n\x1a\ncontenido",
                )
                found_metadata, path = data_store.template_asset_path(
                    "certificado-anual",
                    "image-signature",
                    store,
                )

        self.assertEqual(metadata["content_type"], "image/png")
        self.assertEqual(found_metadata, metadata)
        self.assertEqual(path.name, "image-signature.png")
        save_store.assert_called_once_with(store)


if __name__ == "__main__":
    unittest.main()
