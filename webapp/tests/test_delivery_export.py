from __future__ import annotations

import io
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import data_store
import delivery_export as exports
import renderer


def delivery() -> dict:
    return {
        "id": "qa", "numero": 10, "fecha": "2026-10-21", "month": "OCTUBRE",
        "name": "ENTREGA 10", "parametros": {"dolar": "3400", "oz_au": "4520", "oz_ag": "40", "mes_regalias": "OCTUBRE"},
        "items": [
            {"id": str(i), "proveedor": f"SOCIEDAD {i}", "codigo": f"QA-{i}", "barra": f"QA-{i}", "peso_inicial": "1000", "peso_post": "920", "peso_final": "920", "muestras": "2", "ley_au": "700", "ley_ag": "122"}
            for i in range(5)
        ],
    }


class ExportTests(unittest.TestCase):
    def test_all_generated_documents_use_original_contexts(self):
        entries = exports.generated_documents(delivery(), {})
        self.assertEqual(len(entries), 16)
        self.assertEqual([entry.slug for entry in entries].count("boletin"), 5)
        self.assertEqual(entries[0].context["fecha"], "2026-10-21")
        self.assertEqual(entries[1].context["fecha_larga"], "21 de octubre de 2026")
        self.assertEqual(entries[2].context["fecha_larga"], "21 de octubre de 2026")
        self.assertEqual(entries[3].context["fecha"], "21/10/2026")
        pending = delivery()
        pending["items"][0]["ley_ag"] = ""
        self.assertEqual(len(exports.generated_documents(pending, {})), 14)

    def test_zip_contains_pdfs_and_original_nested_files_without_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.txt"
            source.write_text("Original", encoding="utf-8")
            entries = [exports.PdfEntry("Boletines/QA.pdf", "boletin", {}), exports.FileEntry("Boletines/QA.pdf", source), exports.FileEntry("Anexos/2025/enero/archivo.txt", source)]
            progress = Mock()
            with patch.object(renderer, "render_print_pdf", return_value=b"%PDF-test") as render:
                exports.build_archive(root / "test.zip", entries, {"template_layouts": {}}, progress)
            render.assert_called_once_with("boletin", {}, store={"template_layouts": {}})
            with zipfile.ZipFile(root / "test.zip") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.namelist(), ["Boletines/QA.pdf", "Boletines/QA (2).pdf", "Anexos/2025/enero/archivo.txt"])
                self.assertEqual(archive.read("Anexos/2025/enero/archivo.txt"), b"Original")
            self.assertEqual(progress.call_args.args[0], 3)

    def test_missing_attachment_is_an_error_not_a_silently_incomplete_zip(self):
        with patch.object(exports.document_library, "find_imported_file", return_value=(None, None)):
            with self.assertRaisesRegex(ValueError, "No se encuentra.*original.pdf"):
                exports.export_entries("importadas", {"docs": [{"kind": "imported", "name": "original.pdf", "id": "missing"}]}, {})

    def test_path_names_are_safe(self):
        self.assertEqual(exports.archive_name("../../Boletines/../archivo.pdf", set()), "Boletines/archivo.pdf")
        self.assertEqual(exports.archive_name("/Boletines/archivo.pdf", set()), "Boletines/archivo.pdf")

    def test_job_returns_immediately_deduplicates_and_is_owner_scoped(self):
        manager = exports.ExportManager()
        release = threading.Event()
        started = threading.Event()
        def build(path, entries, store, progress):
            started.set()
            release.wait(5)
            path.write_bytes(b"ZIP")
        try:
            with patch.object(exports, "build_archive", side_effect=build):
                detail = {"name": "Entrega", "docs": []}
                start = time.monotonic()
                first = manager.start("admin", "local", "qa", detail, {})
                self.assertLess(time.monotonic() - start, 1)
                self.assertTrue(started.wait(1))
                second = manager.start("admin", "local", "qa", detail, {})
                self.assertEqual(first["id"], second["id"])
                self.assertIsNone(manager.get(first["id"], "otro"))
                self.assertIsNone(manager.open_result(first["id"], "otro"))
                release.set()
                manager.executor.shutdown(wait=True)
            self.assertEqual(manager.get(first["id"], "admin")["status"], "ready")
            with manager.open_result(first["id"], "admin") as result:
                self.assertEqual(result.read(), b"ZIP")
        finally:
            release.set()
            manager.close()

    def test_saved_edits_invalidate_cached_zip_and_snapshot_is_not_mutated(self):
        manager = exports.ExportManager()
        captured = []
        def build(path, entries, store, progress):
            captured.append(store)
            path.write_bytes(b"ZIP")
        store = {"template_layouts": {"recibo-metales": {"elements": {"image-2": {"y": 20}}}}}
        try:
            with patch.object(exports, "build_archive", side_effect=build):
                first = manager.start("admin", "local", "qa", {"docs": []}, store)
                store["template_layouts"]["recibo-metales"]["elements"]["image-2"]["y"] = 50
                second = manager.start("admin", "local", "qa", {"docs": []}, store)
                self.assertNotEqual(first["id"], second["id"])
                manager.executor.shutdown(wait=True)
            self.assertEqual(captured[0]["template_layouts"]["recibo-metales"]["elements"]["image-2"]["y"], 20)
            self.assertEqual(captured[1]["template_layouts"]["recibo-metales"]["elements"]["image-2"]["y"], 50)
        finally:
            manager.close()

    def test_failure_removes_partial_zip_and_can_be_retried(self):
        manager = exports.ExportManager()
        try:
            with patch.object(exports, "build_archive", side_effect=RuntimeError("Firma inválida")), self.assertLogs(level="ERROR"):
                job = manager.start("admin", "local", "qa", {"docs": []}, {})
                manager.executor.shutdown(wait=True)
            result = manager.get(job["id"], "admin")
            self.assertEqual(result["status"], "error")
            self.assertIn("Firma inválida", result["error"])
            self.assertIsNone(manager.open_result(job["id"], "admin"))
            self.assertFalse((Path(manager.directory.name) / f"{job['id']}.zip").exists())
        finally:
            manager.close()

    def test_queue_and_completed_files_are_bounded_and_expire(self):
        manager = exports.ExportManager(ttl=0.01, max_pending=1)
        release = threading.Event()
        def build(path, *_args):
            release.wait(5)
            path.write_bytes(b"ZIP")
        try:
            with patch.object(exports, "build_archive", side_effect=build):
                first = manager.start("admin", "local", "qa", {"docs": []}, {})
                with self.assertRaisesRegex(ValueError, "varias descargas"):
                    manager.start("admin", "local", "otra", {"docs": []}, {})
                release.set()
                manager.executor.shutdown(wait=True)
            time.sleep(0.02)
            self.assertIsNone(manager.get(first["id"], "admin"))
            self.assertEqual(list(Path(manager.directory.name).iterdir()), [])
        finally:
            release.set()
            manager.close()

    def test_start_route_redirects_without_waiting_for_archive(self):
        handler = object.__new__(app.RecepcionHandler)
        handler.current_user = Mock(return_value={"username": "admin"})
        handler.redirect = Mock()
        detail = {"docs": [], "name": "Entrega"}
        with patch.object(app.document_library, "folder_detail", return_value=detail), patch.object(data_store, "load_store", return_value={}), patch.object(exports.manager, "start", return_value={"id": "job"}) as start:
            handler.download_folder_zip("web", "qa")
        start.assert_called_once_with("admin", "web", "qa", detail, {})
        handler.redirect.assert_called_once_with("/descargas/job")

    def test_ready_download_streams_file_and_status_is_not_cacheable(self):
        handler = object.__new__(app.RecepcionHandler)
        handler.current_user = Mock(return_value={"username": "admin"})
        handler.send_json = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        job = {"id": "qa", "status": "ready", "name": "ENTREGA 10"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entrega.zip"
            path.write_bytes(b"ZIP-content")
            with patch.object(exports.manager, "get", return_value=job), patch.object(exports.manager, "open_result", side_effect=lambda *_: path.open("rb")):
                handler.serve_delivery_export("/descargas/qa/estado")
                handler.send_json.assert_called_once_with(job)
                handler.serve_delivery_export("/descargas/qa/archivo")
        self.assertEqual(handler.wfile.getvalue(), b"ZIP-content")
        handler.send_header.assert_any_call("Cache-Control", "no-store")
        handler.send_header.assert_any_call("Content-Length", "11")

    def test_normalization_does_not_reopen_excel_catalogs_for_existing_data(self):
        store = data_store._empty_store(include_catalogs=False)
        with patch.object(data_store.core, "read_sociedades") as sociedades, patch.object(data_store.core, "read_regalias") as regalias, patch.object(data_store, "save_store"):
            data_store.normalize_store(store)
        sociedades.assert_not_called()
        regalias.assert_not_called()

    def test_renderer_uses_supplied_snapshot_without_loading_store(self):
        with patch.object(data_store, "load_store", side_effect=AssertionError("No volver a leer los datos")):
            html = renderer.render_print_html("recibo-metales", store={"template_layouts": {"recibo-metales": {"elements": {"image-2": {"y": 30}}}}})
        self.assertIn("translate(0.00px, 30.00px)", html)


if __name__ == "__main__":
    unittest.main()
