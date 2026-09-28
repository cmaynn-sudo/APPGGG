from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import data_store  # noqa: E402
import historical_import  # noqa: E402
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


def upload(name: str, content: bytes = b"PDF") -> dict[str, object]:
    return {"filename": name, "content": content, "content_type": "application/pdf"}


class HistoricalImportTests(unittest.TestCase):
    def data_paths(self, root: Path):
        return (
            patch.object(data_store, "DATA_DIR", root),
            patch.object(data_store, "STORE_PATH", root / "recepcion_store.json"),
            patch.object(data_store, "UPLOADS_DIR", root / "uploads"),
            patch.object(data_store, "_empty_store", side_effect=minimal_store),
        )

    def test_groups_root_folder_into_deliveries_and_general_documents(self) -> None:
        entries, ignored = historical_import.uploaded_entries(
            [
                upload("CI GREEN GLOBAL/2026/ABRIL/ENTREGA °6 - (2026-04-09)/PRELIMINARES - 6.pdf"),
                upload("CI GREEN GLOBAL/2026/ABRIL/ENTREGA °6 - (2026-04-09)/BOLETINES/BOLETIN - MECA-3.pdf"),
                upload("CI GREEN GLOBAL/2026/ABRIL/CERTIFICADO DE REGALÍAS.pdf"),
                upload("CI GREEN GLOBAL/.DS_Store"),
            ]
        )
        groups, duplicates = historical_import.group_entries(entries)

        self.assertEqual(ignored, 1)
        self.assertEqual(duplicates, 0)
        self.assertEqual(len(groups), 2)
        delivery = next(group for group in groups if group["kind"] == "delivery")
        general = next(group for group in groups if group["kind"] == "general")
        self.assertEqual(delivery["date"], "2026-04-09")
        self.assertEqual(delivery["year"], "2026")
        self.assertEqual(delivery["month"], "ABRIL")
        self.assertEqual(delivery["delivery_number"], "6")
        self.assertEqual(
            [item["relative_path"] for item in delivery["files"]],
            ["BOLETINES/BOLETIN - MECA-3.pdf", "PRELIMINARES - 6.pdf"],
        )
        self.assertEqual(general["name"], "DOCUMENTOS GENERALES - ABRIL 2026")

    def test_repairs_macos_zip_filename_encoding(self) -> None:
        self.assertEqual(historical_import.repair_text("ENTREGA ┬░9"), "ENTREGA °9")
        self.assertEqual(historical_import.repair_text("CERTIFICADO DE REGAL├ìAS"), "CERTIFICADO DE REGALÍAS")

    def test_zip_and_folder_import_are_idempotent(self) -> None:
        paths = [
            "CI GREEN GLOBAL/2026/MAYO/ENTREGA °5 - (2026-05-07)/BOLETINES/BOLETIN - CORI-5.pdf",
            "CI GREEN GLOBAL/2026/MAYO/ENTREGA °5 - (2026-05-07)/LEYES/REPORTE LEYES - CORI-5.pdf",
        ]
        direct_files = [upload(path, f"data-{index}".encode()) for index, path in enumerate(paths)]
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            for index, path in enumerate(paths):
                archive.writestr(path, f"data-{index}".encode())

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            data_dir, store_path, uploads_dir, empty_store = self.data_paths(root)
            with (
                data_dir,
                store_path,
                uploads_dir,
                empty_store,
                patch.object(persistence, "restore_state_if_configured", return_value="disabled"),
                patch.object(persistence, "write_block_reason", return_value=""),
                patch.object(persistence, "backup_state_or_raise", return_value=True) as backup,
            ):
                first = historical_import.import_uploaded_history(direct_files)
                second = historical_import.import_uploaded_history(
                    [{"filename": "historico.zip", "content": zip_buffer.getvalue(), "content_type": "application/zip"}]
                )
                store = json.loads((root / "recepcion_store.json").read_text(encoding="utf-8"))

            self.assertEqual(first["created"], 1)
            self.assertEqual(second["created"], 0)
            self.assertEqual(second["updated"], 1)
            self.assertEqual(len(store["local_folders"]), 1)
            self.assertEqual(len(store["uploaded_files"]), 2)
            self.assertEqual(store["local_folders"][0]["date"], "2026-05-07")
            self.assertEqual(backup.call_count, 2)

    def test_zip_rejects_parent_directory_traversal(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../secreto.txt", "no")

        with self.assertRaisesRegex(ValueError, "ruta no segura"):
            historical_import.uploaded_entries(
                [{"filename": "historico.zip", "content": buffer.getvalue(), "content_type": "application/zip"}]
            )

    def test_reorganizes_legacy_combined_folder_without_reupload(self) -> None:
        paths = [
            "2026/ABRIL/ENTREGA °6 - (2026-04-09)/BOLETINES/BOLETIN - MECA-3.pdf",
            "2026/MAYO/ENTREGA °5 - (2026-05-07)/BOLETINES/BOLETIN - CORI-5.pdf",
        ]
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            data_dir, store_path, uploads_dir, empty_store = self.data_paths(root)
            with (
                data_dir,
                store_path,
                uploads_dir,
                empty_store,
                patch.object(persistence, "restore_state_if_configured", return_value="disabled"),
                patch.object(persistence, "write_block_reason", return_value=""),
                patch.object(persistence, "backup_state_or_raise", return_value=True),
            ):
                legacy = data_store.create_local_folder_from_upload("2026", [upload(path) for path in paths])
                candidates = historical_import.legacy_folder_candidates()
                summary = historical_import.reorganize_existing_folder(legacy["id"])
                store = data_store.load_store()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["deliveries"], 2)
        self.assertEqual(summary["deliveries"], 2)
        self.assertEqual(summary["reorganized_from"], "2026")
        self.assertEqual(len(store["local_folders"]), 2)
        self.assertEqual(len(store["uploaded_files"]), 2)
        self.assertNotIn(legacy["id"], {folder["id"] for folder in store["local_folders"]})


if __name__ == "__main__":
    unittest.main()
