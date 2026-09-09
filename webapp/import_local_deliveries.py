from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import document_library


SOURCE_ROOT = Path.home() / "Documents" / "CI GREEN GLOBAL"
TARGET_ROOT = document_library.IMPORTED_COPY_ROOT
MANIFEST_PATH = document_library.MANIFEST_PATH


def _hash_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def _file_record(source_file: Path, rel_path: Path) -> dict:
    stat = source_file.stat()
    parts = list(rel_path.parts)
    return {
        "id": _hash_id(rel_path.as_posix()),
        "name": source_file.name,
        "relative_path": rel_path.as_posix(),
        "category": document_library.category_for_path(parts, source_file.name),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def import_local_deliveries(source_root: Path = SOURCE_ROOT, target_root: Path = TARGET_ROOT) -> dict:
    if not source_root.exists():
        raise FileNotFoundError(f"No existe la carpeta local: {source_root}")

    target_root.mkdir(parents=True, exist_ok=True)
    delivery_map: dict[str, dict] = {}
    loose_files: list[dict] = []

    for source_file in sorted(source_root.rglob("*")):
        if not source_file.is_file() or source_file.name == ".DS_Store":
            continue
        rel_path = source_file.relative_to(source_root)
        target_file = target_root / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)

        record = _file_record(source_file, rel_path)
        parts = list(rel_path.parts)
        if len(parts) >= 3 and parts[2].upper().startswith("ENTREGA"):
            delivery_rel = "/".join(parts[:3])
            delivery = delivery_map.setdefault(
                delivery_rel,
                {
                    "id": _hash_id(delivery_rel),
                    "name": parts[2],
                    "year": parts[0],
                    "month": parts[1].upper(),
                    "date": document_library.delivery_date_from_name(parts[2]),
                    "relative_path": delivery_rel,
                    "files": [],
                },
            )
            delivery["files"].append(record)
        else:
            loose_files.append(record)

    manifest = {
        "source": str(source_root),
        "target": str(target_root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "deliveries": sorted(delivery_map.values(), key=lambda item: (item["year"], item["date"], item["name"])),
        "loose_files": sorted(loose_files, key=lambda item: item["relative_path"]),
    }
    document_library.save_manifest(manifest)
    return manifest


if __name__ == "__main__":
    manifest = import_local_deliveries()
    total_files = sum(len(delivery["files"]) for delivery in manifest["deliveries"]) + len(manifest["loose_files"])
    print(f"Importadas {len(manifest['deliveries'])} entregas y {total_files} archivo(s).")
