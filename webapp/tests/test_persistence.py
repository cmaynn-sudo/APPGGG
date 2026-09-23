from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


WEBAPP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBAPP_DIR))

import data_store  # noqa: E402
import persistence  # noqa: E402


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        persistence.LAST_BACKUP_ERROR = ""
        persistence.LAST_RESTORE_ERROR = ""
        persistence.LAST_BACKUP_AT = ""
        persistence.LAST_BACKUP_BYTES = 0

    def data_paths(self, root: Path):
        return (
            patch.object(data_store, "DATA_DIR", root),
            patch.object(data_store, "STORE_PATH", root / "recepcion_store.json"),
            patch.object(data_store, "UPLOADS_DIR", root / "uploads"),
        )

    def test_render_blocks_write_without_remote_storage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            data_dir, store_path, uploads_dir = self.data_paths(root)
            with (
                patch.dict(os.environ, {"RENDER": "true", "PERSISTENCE_REQUIRED": "true"}, clear=True),
                patch.object(persistence, "storage_backend", return_value=""),
                data_dir,
                store_path,
                uploads_dir,
            ):
                with self.assertRaisesRegex(RuntimeError, "almacenamiento persistente"):
                    data_store.save_store({"entregas": []})
                self.assertFalse((root / "recepcion_store.json").exists())

    def test_confirmed_backup_contains_latest_store(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            data_dir, store_path, uploads_dir = self.data_paths(root)
            captured: list[bytes] = []
            state = {
                "sociedades": [],
                "regalias": [],
                "boletin_settings": {},
                "entregas": [{"id": "persistente"}],
                "local_folders": [],
                "uploaded_files": [],
                "active_entrega_id": "persistente",
            }
            with (
                patch.dict(os.environ, {"RENDER": "true", "PERSISTENCE_REQUIRED": "true"}, clear=True),
                patch.object(persistence, "storage_backend", return_value="r2"),
                patch.object(persistence, "upload_backup", side_effect=captured.append),
                data_dir,
                store_path,
                uploads_dir,
            ):
                data_store.save_store(state)

            self.assertEqual(len(captured), 1)
            with zipfile.ZipFile(io.BytesIO(captured[0])) as archive:
                restored = json.loads(archive.read("recepcion_store.json"))
            self.assertEqual(restored["entregas"][0]["id"], "persistente")
            self.assertEqual(persistence.LAST_BACKUP_BYTES, len(captured[0]))


if __name__ == "__main__":
    unittest.main()
