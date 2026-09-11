from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import data_store
from template_catalog import WEBAPP_DIR


IMPORTED_DOCS_DIR = WEBAPP_DIR / "imported_docs"
IMPORTED_COPY_ROOT = IMPORTED_DOCS_DIR / "ci_green_global"
MANIFEST_PATH = IMPORTED_DOCS_DIR / "manifest.json"


def _hash_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def file_size_label(size: int | None) -> str:
    if size is None:
        return ""
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"deliveries": [], "loose_files": [], "source": "CI GREEN GLOBAL"}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(manifest: dict[str, Any]) -> None:
    IMPORTED_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def delivery_date_from_name(name: str) -> str:
    match = re.search(r"\((\d{4}-\d{2}-\d{2})\)", name)
    return match.group(1) if match else ""


def category_for_path(parts: list[str], filename: str) -> str:
    upper = filename.upper()
    if "LEYES" in {part.upper() for part in parts} or upper.startswith("REPORTE LEYES"):
        return "Leyes"
    if "BOLETINES" in {part.upper() for part in parts} or upper.startswith("BOLETIN"):
        return "Boletines"
    if upper.startswith("PRELIMINARES"):
        return "Preliminares"
    if upper.startswith("CERTIFICADO"):
        return "Certificados"
    if filename.lower().endswith(".pdf"):
        return "Recibos de metales"
    return "Archivos"


def enrich_imported_file(file_info: dict[str, Any]) -> dict[str, Any]:
    item = dict(file_info)
    item["kind"] = "imported"
    item["size_label"] = file_size_label(item.get("size"))
    item["content_type"] = mimetypes.guess_type(item.get("name", ""))[0] or "application/octet-stream"
    item["view_url"] = f"/archivos/importado/{quote(item['id'])}"
    item["download_url"] = f"/archivos/importado/{quote(item['id'])}?download=1"
    item["deletable"] = True
    return item


def imported_deliveries() -> list[dict[str, Any]]:
    manifest = load_manifest()
    rows = []
    for delivery in manifest.get("deliveries", []):
        files = [enrich_imported_file(file_info) for file_info in delivery.get("files", [])]
        row = dict(delivery)
        row["source"] = "imported"
        row["source_label"] = "Local importada"
        row["href"] = f"/entregas/importadas/{quote(row['id'])}"
        row["document_count"] = len(files)
        row["file_count"] = len(files)
        row["date"] = row.get("date") or delivery_date_from_name(row.get("name", ""))
        row["files"] = files
        rows.append(row)
    return sorted(rows, key=lambda item: (item.get("year", ""), item.get("date", ""), item.get("name", "")), reverse=True)


def loose_folder() -> dict[str, Any] | None:
    manifest = load_manifest()
    loose = [enrich_imported_file(file_info) for file_info in manifest.get("loose_files", [])]
    if not loose:
        return None
    return {
        "id": "archivos-sueltos",
        "source": "loose",
        "source_label": "Local importada",
        "name": "Certificados y archivos sueltos",
        "year": "",
        "month": "",
        "date": "",
        "document_count": len(loose),
        "file_count": len(loose),
        "href": "/entregas/importadas/archivos-sueltos",
        "files": loose,
    }


def imported_delivery(folder_id: str) -> dict[str, Any] | None:
    if folder_id == "archivos-sueltos":
        return loose_folder()
    return next((folder for folder in imported_deliveries() if folder.get("id") == folder_id), None)


def find_imported_file(file_id: str) -> tuple[dict[str, Any], Path] | tuple[None, None]:
    manifest = load_manifest()
    candidates = list(manifest.get("loose_files", []))
    for delivery in manifest.get("deliveries", []):
        candidates.extend(delivery.get("files", []))
    for file_info in candidates:
        if file_info.get("id") != file_id:
            continue
        rel = str(file_info.get("relative_path", "")).lstrip("/\\")
        path = (IMPORTED_COPY_ROOT / rel).resolve()
        root = IMPORTED_COPY_ROOT.resolve()
        if not str(path).startswith(str(root)) or not path.exists() or not path.is_file():
            return None, None
        return enrich_imported_file(file_info), path
    return None, None


def remove_imported_file(file_id: str) -> bool:
    manifest = load_manifest()
    removed = False

    def keep_file(file_info: dict[str, Any]) -> bool:
        nonlocal removed
        if file_info.get("id") == file_id:
            _file, path = find_imported_file(file_id)
            if path:
                path.unlink(missing_ok=True)
            removed = True
            return False
        return True

    manifest["loose_files"] = [file_info for file_info in manifest.get("loose_files", []) if keep_file(file_info)]
    for delivery in manifest.get("deliveries", []):
        delivery["files"] = [file_info for file_info in delivery.get("files", []) if keep_file(file_info)]
    manifest["deliveries"] = [delivery for delivery in manifest.get("deliveries", []) if delivery.get("files")]
    if removed:
        save_manifest(manifest)
    return removed


def remove_imported_delivery(folder_id: str) -> bool:
    manifest = load_manifest()
    remaining = []
    removed = False
    for delivery in manifest.get("deliveries", []):
        if delivery.get("id") != folder_id:
            remaining.append(delivery)
            continue
        removed = True
        for file_info in delivery.get("files", []):
            _file, path = find_imported_file(file_info.get("id", ""))
            if path:
                path.unlink(missing_ok=True)
    if removed:
        manifest["deliveries"] = remaining
        save_manifest(manifest)
    return removed


def generated_documents_for_entrega(entrega: dict[str, Any]) -> list[dict[str, Any]]:
    entrega_id = quote(entrega.get("id", ""))
    numero = entrega.get("numero", "")
    fecha = entrega.get("fecha", "")
    docs: list[dict[str, Any]] = []
    if entrega.get("items"):
        view_url = f"/print/preliminares/{entrega_id}"
        docs.append(
            {
                "kind": "generated",
                "category": "Preliminares",
                "title": f"Preliminares entrega {numero}",
                "name": f"PRELIMINARES - {numero} ({fecha}).pdf",
                "meta": f"{len(entrega.get('items', []))} sociedad(es)",
                "view_url": view_url,
                "download_url": f"{view_url}?download=1",
                "deletable": False,
            }
        )
    for item in entrega.get("items", []):
        item_id = quote(item.get("id", ""))
        barra = item.get("barra") or item.get("codigo", "")
        proveedor = item.get("proveedor", "")
        recibo_url = f"/print/recibo/{entrega_id}/{item_id}"
        docs.append(
            {
                "kind": "generated",
                "category": "Recibos de metales",
                "title": f"Recibo de metales {barra}",
                "name": f"{proveedor} ({barra}).pdf",
                "meta": proveedor,
                "view_url": recibo_url,
                "download_url": f"{recibo_url}?download=1",
                "deletable": False,
            }
        )
        if item.get("ley_au") not in ("", None) and item.get("ley_ag") not in ("", None):
            leyes_url = f"/print/reporte-analisis/{entrega_id}/{item_id}"
            boletin_url = f"/print/boletin/{entrega_id}/{item_id}"
            docs.append(
                {
                    "kind": "generated",
                    "category": "Leyes",
                    "title": f"Reporte de leyes {barra}",
                    "name": f"REPORTE LEYES - {barra}.pdf",
                    "meta": proveedor,
                    "view_url": leyes_url,
                    "download_url": f"{leyes_url}?download=1",
                    "deletable": False,
                }
            )
            docs.append(
                {
                    "kind": "generated",
                    "category": "Boletines",
                    "title": f"Boletin {barra}",
                    "name": f"BOLETIN - {barra}.pdf",
                    "meta": proveedor,
                    "view_url": boletin_url,
                    "download_url": f"{boletin_url}?download=1",
                    "deletable": False,
                }
            )
    return docs


def uploaded_documents_for_folder(source: str, folder_id: str) -> list[dict[str, Any]]:
    rows = []
    for file_info in data_store.uploaded_files_for(source, folder_id):
        item = dict(file_info)
        item["kind"] = "uploaded"
        item["category"] = item.get("category") or "Archivos agregados"
        display_path = item.get("display_path") or item.get("name", "Archivo")
        item["title"] = display_path
        item["meta"] = "Subido al aplicativo" if source != "local" else "Carpeta local"
        item["size_label"] = file_size_label(item.get("size"))
        item["view_url"] = f"/archivos/subido/{quote(item['id'])}"
        item["download_url"] = f"/archivos/subido/{quote(item['id'])}?download=1"
        item["archive_path"] = display_path
        item["deletable"] = True
        rows.append(item)
    return rows


def local_uploaded_folders() -> list[dict[str, Any]]:
    folders = []
    for folder in data_store.list_local_folders():
        uploads = uploaded_documents_for_folder("local", folder.get("id", ""))
        folders.append(
            {
                "id": folder.get("id", ""),
                "source": "local",
                "source_label": "Carpeta local",
                "name": folder.get("name", ""),
                "year": folder.get("year", ""),
                "month": folder.get("month", ""),
                "date": folder.get("date", ""),
                "document_count": len(uploads),
                "file_count": len(uploads),
                "href": f"/entregas/local/{quote(folder.get('id', ''))}",
                "folder": folder,
            }
        )
    return folders


def web_folders() -> list[dict[str, Any]]:
    folders = []
    for entrega in data_store.list_entregas():
        docs = generated_documents_for_entrega(entrega)
        uploads = uploaded_documents_for_folder("web", entrega.get("id", ""))
        folders.append(
            {
                "id": entrega.get("id", ""),
                "source": "web",
                "source_label": "Web",
                "name": entrega.get("name", ""),
                "year": entrega.get("year", ""),
                "month": entrega.get("month", ""),
                "date": entrega.get("fecha", ""),
                "document_count": len(docs) + len(uploads),
                "file_count": len(docs) + len(uploads),
                "item_count": len(entrega.get("items", [])),
                "href": f"/entregas/web/{quote(entrega.get('id', ''))}",
                "entrega": entrega,
            }
        )
    return folders


def all_folders() -> list[dict[str, Any]]:
    rows = web_folders() + local_uploaded_folders() + imported_deliveries()
    loose = loose_folder()
    if loose:
        rows.append(loose)
    return sorted(rows, key=lambda item: (item.get("year", ""), item.get("date", ""), item.get("name", "")), reverse=True)


def folder_detail(source: str, folder_id: str) -> dict[str, Any] | None:
    if source == "web":
        entrega = data_store.get_entrega(folder_id)
        if not entrega:
            return None
        docs = generated_documents_for_entrega(entrega) + uploaded_documents_for_folder("web", folder_id)
        return {
            "id": folder_id,
            "source": "web",
            "source_label": "Web",
            "name": entrega.get("name", ""),
            "year": entrega.get("year", ""),
            "month": entrega.get("month", ""),
            "date": entrega.get("fecha", ""),
            "docs": docs,
            "entrega": entrega,
            "can_delete_folder": True,
            "zip_url": f"/entregas/web/{quote(folder_id)}/descargar",
        }
    if source == "local":
        folder = data_store.get_local_folder(folder_id)
        if not folder:
            return None
        docs = uploaded_documents_for_folder("local", folder_id)
        return {
            "id": folder_id,
            "source": "local",
            "source_label": "Carpeta local",
            "name": folder.get("name", ""),
            "year": folder.get("year", ""),
            "month": folder.get("month", ""),
            "date": folder.get("date", ""),
            "docs": docs,
            "can_delete_folder": True,
            "zip_url": f"/entregas/local/{quote(folder_id)}/descargar",
        }
    if source == "importadas":
        folder = imported_delivery(folder_id)
        if not folder:
            return None
        docs = list(folder.get("files", [])) + uploaded_documents_for_folder("imported", folder_id)
        return {
            "id": folder_id,
            "source": "imported",
            "source_label": "Local importada",
            "name": folder.get("name", ""),
            "year": folder.get("year", ""),
            "month": folder.get("month", ""),
            "date": folder.get("date", ""),
            "docs": docs,
            "can_delete_folder": folder_id != "archivos-sueltos",
            "zip_url": f"/entregas/importadas/{quote(folder_id)}/descargar",
        }
    return None


def grouped_documents(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        groups.setdefault(doc.get("category") or "Archivos", []).append(doc)
    order = ["Preliminares", "Recibos de metales", "Leyes", "Boletines", "Certificados", "Archivos agregados", "Archivos"]
    return [
        {"category": category, "docs": groups[category]}
        for category in sorted(groups, key=lambda value: (order.index(value) if value in order else 99, value))
    ]


def exported_at_label() -> str:
    manifest = load_manifest()
    raw = manifest.get("generated_at", "")
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw
