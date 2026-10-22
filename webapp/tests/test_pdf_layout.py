from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import data_store
import delivery_export
import renderer


class DownloadLayoutTests(unittest.TestCase):
    def test_direct_download_and_zip_use_the_layout_aware_renderer(self) -> None:
        handler = object.__new__(app.RecepcionHandler)
        handler.send_bytes = Mock()
        context = {"proveedor": "PROVEEDOR DE PRUEBA"}
        with patch.object(renderer, "render_print_pdf", return_value=b"%PDF-test") as render:
            handler.send_print("recibo-metales", context, download=True, filename="recibo.pdf")
        render.assert_called_once_with("recibo-metales", context)
        handler.send_bytes.assert_called_once_with(b"%PDF-test", "application/pdf", filename="recibo.pdf", attachment=True)

        entrega = {"id": "qa", "numero": 1, "fecha": "2026-01-12", "items": [
            {"id": "test", "proveedor": "PROVEEDOR DE PRUEBA", "codigo": "QA-1", "peso_ini": 1000, "peso_fin": 900},
        ]}
        with tempfile.TemporaryDirectory() as directory, patch.object(renderer, "render_print_pdf", return_value=b"%PDF-test") as render:
            entries = delivery_export.generated_documents(entrega, {})
            delivery_export.build_archive(Path(directory) / "entrega.zip", entries, {}, lambda *_: None)
        self.assertEqual([call.args[0] for call in render.call_args_list], ["preliminares", "recibo-metales"])
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(call.kwargs == {"store": {}} for call in render.call_args_list))

    @unittest.skipUnless(importlib.util.find_spec("weasyprint"), "Requiere el motor PDF de Render")
    def test_pdf_embeds_document_font_and_honors_saved_signature_and_grid(self) -> None:
        try:
            from weasyprint import HTML
        except OSError as exc:
            self.skipTest(str(exc))
        from pypdf import PdfReader

        layout = {"elements": {"image-2": {"x": 15, "y": 20, "scale": 1}, "column-B": {"width": 120}}}
        with patch.object(data_store, "load_store", return_value={}), patch.object(data_store, "get_template_layout", return_value=layout), patch.object(data_store, "get_template_assets", return_value={}):
            pdf = renderer.render_print_pdf("recibo-metales")
            html = renderer.absolutize_static_urls(renderer.render_print_html("recibo-metales", include_print_scale=False))
        reader = PdfReader(io.BytesIO(pdf))
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("RECIBO DE METALES", reader.pages[0].extract_text())
        descriptors = []
        for reference in reader.pages[0]["/Resources"]["/Font"].values():
            font = reference.get_object()
            descendants = font.get("/DescendantFonts", [reference])
            for descendant in descendants:
                descriptor = descendant.get_object().get("/FontDescriptor")
                if descriptor:
                    descriptors.append(descriptor.get_object())
        self.assertTrue(any("/FontFile2" in descriptor for descriptor in descriptors), "La fuente debe estar incrustada en el PDF")
        document = HTML(string=html, base_url=renderer.WEBAPP_DIR.as_uri()).render()
        boxes = list(document.pages[0]._page_box.descendants())
        signature = next(box for box in boxes if box.element is not None and box.element.get("data-layout-id") == "image-2")
        self.assertAlmostEqual(signature.transformation_matrix[2][0], 15)
        self.assertAlmostEqual(signature.transformation_matrix[2][1], 20)
        sheet = next(box for box in boxes if box.element is not None and box.element.get("class") == "doc-sheet")
        self.assertAlmostEqual(sheet.width, 1176)


if __name__ == "__main__":
    unittest.main()
