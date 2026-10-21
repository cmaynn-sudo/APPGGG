from __future__ import annotations

import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import data_store  # noqa: E402
import renderer  # noqa: E402


class LayoutEditorTests(unittest.TestCase):
    def test_leaf_texts_are_individually_editable_with_stable_ids(self) -> None:
        body = (
            '<div data-layout-id="block-provider"><dl>'
            '<dt>PROVEEDOR:</dt><dd>Ángel &amp; Asociados</dd></dl></div>'
            '<h1 data-layout-id="block-title">REPORTE</h1>'
        )
        prepared = renderer.prepare_template_layout(body)
        changed = renderer.prepare_template_layout(body.replace("Ángel &amp; Asociados", "Otro proveedor"))

        self.assertIn('data-layout-id="text-block-provider-dl1-dt1-1"', prepared)
        self.assertIn('data-layout-id="text-block-provider-dl1-dd1-1"', prepared)
        self.assertIn('data-layout-id="text-block-provider-dl1-dd1-1"', changed)
        self.assertIn("Ángel &amp; Asociados", prepared)
        self.assertNotIn("&amp;amp;", prepared)
        self.assertNotIn("text-block-title", prepared)
        self.assertEqual(renderer.prepare_template_layout(prepared), prepared)

    def test_individual_character_text_and_position_persist(self) -> None:
        store = {"template_layouts": {}}
        with (
            patch.object(data_store, "load_store", return_value=store),
            patch.object(data_store, "save_store") as save_store,
        ):
            layout = data_store.update_template_layout(
                "boletin",
                json.dumps({
                    "text-block-provider-2": {"x": 5, "text_override": "Ángel"},
                    "char-text-block-provider-2-0": {"x": 12, "y": -3, "font_size": 18, "text_override": "A"},
                    "char-text-block-provider-2-1": {"hidden": True},
                }),
            )

        character = layout["elements"]["char-text-block-provider-2-0"]
        self.assertEqual(character["x"], 12)
        self.assertEqual(character["y"], -3)
        self.assertEqual(character["text_override"], "A")
        self.assertTrue(layout["elements"]["char-text-block-provider-2-1"]["hidden"])
        css = renderer.template_layout_css("boletin", layout)
        self.assertIn('[data-layout-id="char-text-block-provider-2-0"]', css)
        self.assertIn("translate(12.00px, -3.00px)", css)
        save_store.assert_called_once_with(store)

    def test_character_overrides_apply_after_parent_text_and_escape_html(self) -> None:
        body = '<p data-layout-id="block-title">Texto original</p>'
        result = renderer.apply_template_content_overrides(
            body,
            {"elements": {
                "block-title": {"text_override": "Á😀 oro"},
                "char-block-title-0": {"text_override": "<A>"},
                "char-block-title-1": {"hidden": True},
                "char-block-title-3": {"x": 10},
            }},
            {},
        )

        self.assertIn('data-layout-id="char-block-title-0"', result)
        self.assertIn("&lt;A&gt;", result)
        self.assertIn('data-layout-id="char-block-title-1"', result)
        self.assertIn('data-layout-id="char-block-title-3"', result)
        self.assertIn("data-layout-word", result)
        self.assertNotIn("Texto original", result)

    def test_character_indexes_preserve_line_breaks(self) -> None:
        for line_break in ("<br>", "<br/>"):
            with self.subTest(line_break=line_break):
                result = renderer.apply_template_content_overrides(
                    f'<p data-layout-id="block-title">AB{line_break}CD</p>',
                    {"elements": {"char-block-title-3": {"text_override": "X"}}},
                    {},
                )
                self.assertIn(line_break, result)
                self.assertIn('data-layout-id="char-block-title-3" data-layout-character data-layout-parent="block-title">X</span>', result)
                self.assertIn('data-layout-id="char-block-title-4"', result)

    def test_template_element_ids_remain_unique_and_idempotent(self) -> None:
        class ElementIds(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.ids: list[str] = []

            def handle_starttag(self, tag, attrs) -> None:
                element_id = dict(attrs).get("data-layout-id")
                if element_id:
                    self.ids.append(element_id)

        for slug, template in renderer.TEMPLATE_BY_SLUG.items():
            with self.subTest(slug=slug):
                body = renderer.env.get_template(template.render_template_name).render(
                    **renderer.template_sample_context(slug),
                )
                prepared = renderer.prepare_template_layout(body)
                parser = ElementIds()
                parser.feed(prepared)
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                self.assertEqual(renderer.prepare_template_layout(prepared), prepared)
                characters = renderer.apply_template_content_overrides(
                    prepared, {"elements": {f"char-{parser.ids[-1]}-0": {"x": 1}}}, {},
                )
                final_parser = ElementIds()
                final_parser.feed(characters)
                self.assertEqual(len(final_parser.ids), len(set(final_parser.ids)))

    def test_print_wraps_characters_only_for_edited_texts(self) -> None:
        with (
            patch.object(data_store, "get_template_layout", return_value={"elements": {
                "char-block-title-0": {"x": 9, "text_override": "R"},
            }}),
            patch.object(data_store, "get_template_assets", return_value={}),
        ):
            html = renderer.render_print_html("boletin")

        self.assertIn('data-layout-id="char-block-title-0"', html)
        self.assertIn('data-layout-id="text-block-provider-dl1-dt1-1"', html)
        self.assertNotIn('data-layout-id="char-text-block-provider-dl1-dt1-1-0"', html)
        self.assertIn("translate(9.00px, 0.00px)", html)

    def test_empty_fields_keep_the_same_id_when_values_become_available(self) -> None:
        empty = renderer.prepare_template_layout('<div data-layout-id="block-totals"><strong></strong><strong>OTRO</strong></div>')
        filled = renderer.prepare_template_layout('<div data-layout-id="block-totals"><strong>100</strong><strong>OTRO</strong></div>')
        for field in ("text-block-totals-strong1-1", "text-block-totals-strong2-1"):
            self.assertIn(f'data-layout-id="{field}"', empty)
            self.assertIn(f'data-layout-id="{field}"', filled)

    def test_bulletin_sample_includes_calculated_fields_for_the_editor(self) -> None:
        sample = renderer.template_sample_context("boletin")
        for key in ("fino_oro", "fino_plata", "valor_a_pagar", "regalia_oro_total", "regalia_plata_total", "periodo_regalias"):
            self.assertTrue(sample[key], key)

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
        row_rule = next(rule for rule in css.splitlines() if "tr:nth-of-type(6){" in rule)
        self.assertIn("height:48.00px", row_rule)
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

    def test_explicit_grid_dimensions_override_legacy_cell_sizes(self) -> None:
        store = {"template_layouts": {}}
        with patch.object(data_store, "load_store", return_value=store), patch.object(data_store, "save_store"):
            layout = data_store.update_template_layout("preliminares", json.dumps({
                "cell-B6": {"width": 250, "height": 30},
                "column-B": {"width": 320},
                "row-6": {"height": 48},
                "column-evil selector": {"width": 100},
            }))
        self.assertEqual(layout["elements"]["column-B"]["width"], 320)
        self.assertEqual(layout["elements"]["row-6"]["height"], 48)
        self.assertNotIn("column-evil selector", layout["elements"])
        css = renderer.template_layout_css("preliminares", layout)
        self.assertIn(".doc-sheet{width:1236.00px", css)
        self.assertIn("col:nth-child(2){width:320.00px", css)
        cell_rule = next(rule for rule in css.splitlines() if "tr:nth-of-type(6) > td:nth-child(2){" in rule)
        self.assertIn("width:320.00px", cell_rule)
        self.assertIn("height:48.00px", cell_rule)
        self.assertIn('[data-layout-id="image-1"]{left:373.00px', css)

    def test_grid_parser_tracks_merged_cells_without_shifting_following_cells(self) -> None:
        parser = renderer.TableGeometryParser()
        parser.feed('<table><col style="width:100px"><col style="width:80px">'
                    '<tr style="height:30px"><td rowspan="2">A</td><td>B</td></tr>'
                    '<tr style="height:25px"><td>C</td></tr></table>')
        self.assertEqual(parser.columns, [100, 80])
        self.assertEqual(parser.rows, [30, 25])
        self.assertEqual([(cell.row, cell.column, cell.rowspan) for cell in parser.cells], [(0, 0, 2), (0, 1, 1), (1, 1, 1)])

    def test_receipt_keeps_signature_transform_and_reserves_space_before_footer(self) -> None:
        css = renderer.template_layout_css("recibo-metales", {"elements": {
            "image-2": {"x": -21.2, "y": 96.4, "scale": 1.27},
        }})
        self.assertIn("translate(-21.20px, 96.40px) scale(1.270)", css)
        footer = next(rule for rule in css.splitlines() if "tr:nth-of-type(48){" in rule)
        self.assertIn("top:1042.57px", footer)

    def test_preliminares_use_uniform_body_rows_and_font_files_are_bundled(self) -> None:
        _columns, rows, _cells, _images = renderer.template_table_geometry("preliminares")
        self.assertEqual(rows[5:13], (40,) * 8)
        css = (renderer.STATIC_DIR / "print.css").read_text()
        self.assertIn('font-size: 14.7px !important', css)
        for variant in ("Regular", "Bold", "Italic", "BoldItalic"):
            name = f"LiberationSans-{variant}.ttf"
            self.assertTrue((renderer.STATIC_DIR / "fonts" / name).is_file())
            self.assertIn(name, css)
        self.assertTrue((renderer.STATIC_DIR / "fonts" / "LICENSE_LIBERATION").is_file())

    def test_wide_columns_fit_the_download_page_with_the_same_web_print_scale(self) -> None:
        layout = {"elements": {"column-B": {"width": 600}}}
        zoom = renderer.pdf_zoom("preliminares", layout)
        self.assertLess(zoom, 0.62)
        columns, _rows, _cells, _images = renderer.template_table_geometry("preliminares")
        width = sum(renderer.resized_column_widths(columns, layout["elements"]))
        self.assertAlmostEqual(width * zoom, 190 * 96 / 25.4)
        self.assertIn(f"scale({zoom})", renderer.print_scale_css("preliminares", layout))

    def test_pdf_failure_does_not_silently_discard_saved_design(self) -> None:
        with (
            patch.object(renderer, "render_weasy_pdf", side_effect=ImportError("motor no disponible")),
            patch.object(data_store, "get_template_layout", return_value={"elements": {"image-2": {"y": 20}}}),
            patch.object(data_store, "get_template_assets", return_value={}),
            patch.object(renderer, "render_recibo_pdf") as simplified,
        ):
            with self.assertRaisesRegex(RuntimeError, "No se pudo exportar el diseño guardado"):
                renderer.render_print_pdf("recibo-metales")
        simplified.assert_not_called()

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
