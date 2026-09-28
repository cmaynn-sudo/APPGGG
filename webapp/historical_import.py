from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any

import core
import data_store
import persistence


DELIVERY_RE = re.compile(r"^\s*ENTREGA\b.*?\((\d{4}-\d{2}-\d{2})\)\s*$", re.IGNORECASE)
DELIVERY_NUMBER_RE = re.compile(r"ENTREGA\s*[°º#Nn.]*\s*(\d+)", re.IGNORECASE)
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
MONTH_NAMES = {name.upper() for name in core.MESES_ES.values()}
MAX_EXTRACTED_BYTES = int(os.environ.get("MAX_HISTORICAL_IMPORT_MB", "100")) * 1024 * 1024
MAX_IMPORTED_FILES = int(os.environ.get("MAX_HISTORICAL_IMPORT_FILES", "5000"))


def legacy_folder_candidates(store: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    store = store if store is not None else data_store.load_store()
    uploads_by_folder: dict[str, list[dict[str, Any]]] = {}
    for file_info in store.get("uploaded_files", []):
        if file_info.get("folder_source") != "local":
            continue
        uploads_by_folder.setdefault(str(file_info.get("folder_id", "")), []).append(file_info)

    candidates = []
    for folder in store.get("local_folders", []):
        if folder.get("import_kind") in {"delivery", "general"}:
            continue
        folder_id = str(folder.get("id", ""))
        files = uploads_by_folder.get(folder_id, [])
        deliveries = set()
        for file_info in files:
            display_path = repair_text(str(file_info.get("display_path") or file_info.get("name") or ""))
            for part in PurePosixPath(display_path.replace("\\", "/")).parts:
                match = DELIVERY_RE.match(part)
                if match:
                    deliveries.add(normalized_key(f"{match.group(1)}/{part}"))
                    break
        if len(deliveries) < 2:
            continue
        candidates.append(
            {
                "id": folder_id,
                "name": folder.get("name", "Carpeta histórica"),
                "files": len(files),
                "deliveries": len(deliveries),
            }
        )
    return candidates


def reorganize_existing_folder(folder_id: str) -> dict[str, Any]:
    storage_error = persistence.write_block_reason()
    if storage_error:
        raise RuntimeError(storage_error)

    store = data_store.load_store()
    candidate = next((row for row in legacy_folder_candidates(store) if row["id"] == folder_id), None)
    if not candidate:
        raise ValueError("La carpeta no contiene varias entregas reconocibles para reorganizar.")

    files = []
    old_paths = []
    for file_info in store.get("uploaded_files", []):
        if file_info.get("folder_source") != "local" or str(file_info.get("folder_id", "")) != folder_id:
            continue
        relative_path = str(file_info.get("relative_path", "")).lstrip("/\\")
        path = (data_store.DATA_DIR / relative_path).resolve()
        if not str(path).startswith(str(data_store.DATA_DIR.resolve())) or not path.exists() or not path.is_file():
            raise ValueError(f"No se encontró el archivo {file_info.get('name', 'histórico')} para reorganizar.")
        old_paths.append(path)
        files.append(
            {
                "filename": file_info.get("display_path") or file_info.get("name") or path.name,
                "content": path.read_bytes(),
                "content_type": file_info.get("content_type", ""),
            }
        )

    summary = import_uploaded_history(files)

    final_store = data_store.load_store()
    final_store["local_folders"] = [
        folder for folder in final_store.get("local_folders", []) if str(folder.get("id", "")) != folder_id
    ]
    final_store["uploaded_files"] = [
        file_info
        for file_info in final_store.get("uploaded_files", [])
        if not (
            file_info.get("folder_source") == "local"
            and str(file_info.get("folder_id", "")) == folder_id
        )
    ]
    summary["reorganized_from"] = candidate["name"]
    final_store["last_historical_import"] = summary
    data_store.save_store(final_store, sync_backup=False)

    for path in old_paths:
        path.unlink(missing_ok=True)
    shutil.rmtree(data_store.UPLOADS_DIR / "local" / folder_id, ignore_errors=True)
    persistence.backup_state_or_raise(data_store.DATA_DIR)
    return summary


def import_uploaded_history(files: list[dict[str, object]]) -> dict[str, Any]:
    storage_error = persistence.write_block_reason()
    if storage_error:
        raise RuntimeError(storage_error)

    entries, ignored = uploaded_entries(files)
    groups, duplicate_count = group_entries(entries)
    if not groups:
        raise ValueError(
            "No se encontraron archivos para importar. Selecciona la carpeta CI GREEN GLOBAL o un ZIP que la contenga."
        )

    store = data_store.load_store()
    folders = store.setdefault("local_folders", [])
    uploaded = store.setdefault("uploaded_files", [])
    existing_by_key = {
        str(folder.get("import_key", "")): folder
        for folder in folders
        if str(folder.get("import_key", ""))
    }
    now = datetime.now().isoformat(timespec="seconds")
    created = 0
    updated = 0
    imported_files = 0
    delivery_count = 0
    general_count = 0
    boletin_count = 0

    staging_root = data_store.UPLOADS_DIR / f".historical-{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=True)
    staged_groups: list[dict[str, Any]] = []

    try:
        for group in groups:
            existing = existing_by_key.get(group["import_key"])
            if existing:
                folder_id = str(existing["id"])
                updated += 1
            else:
                folder_id = uuid.uuid4().hex
                existing = None
                created += 1

            group_stage = staging_root / folder_id
            group_stage.mkdir(parents=True, exist_ok=True)
            staged_files = []
            for entry in group["files"]:
                relative_path = data_store.safe_relative_upload_path(entry["relative_path"])
                target = data_store.unique_child_path(group_stage, relative_path)
                target.write_bytes(entry["content"])
                staged_files.append({**entry, "staged_path": target, "display_path": target.relative_to(group_stage).as_posix()})

            folder = {
                "id": folder_id,
                "name": group["name"],
                "year": group["year"],
                "month": group["month"],
                "date": group["date"],
                "delivery_number": group.get("delivery_number", ""),
                "source_relative_path": group["source_relative_path"],
                "import_key": group["import_key"],
                "import_kind": group["kind"],
                "created_at": existing.get("created_at", now) if existing else now,
                "imported_at": now,
                "files": [],
            }
            staged_groups.append({"folder": folder, "files": staged_files})
            imported_files += len(staged_files)
            boletin_count += sum(
                entry["name"].upper().startswith("BOLETIN") and entry["name"].lower().endswith(".pdf")
                for entry in staged_files
            )
            if group["kind"] == "delivery":
                delivery_count += 1
            else:
                general_count += 1

        replaced_ids = {item["folder"]["id"] for item in staged_groups}
        old_historical = [
            item
            for item in uploaded
            if item.get("folder_source") == "local"
            and item.get("folder_id") in replaced_ids
            and item.get("historical_import")
        ]
        old_paths = []
        for file_info in old_historical:
            rel = str(file_info.get("relative_path", "")).lstrip("/\\")
            path = (data_store.DATA_DIR / rel).resolve()
            if str(path).startswith(str(data_store.DATA_DIR.resolve())):
                old_paths.append(path)

        store["uploaded_files"] = [item for item in uploaded if item not in old_historical]
        folders_by_id = {str(folder.get("id", "")): folder for folder in folders}
        for staged in staged_groups:
            folder = staged["folder"]
            folders_by_id[folder["id"]] = folder

        for path in old_paths:
            path.unlink(missing_ok=True)

        for staged in staged_groups:
            folder = staged["folder"]
            final_root = data_store.UPLOADS_DIR / "local" / folder["id"]
            final_root.mkdir(parents=True, exist_ok=True)
            for entry in staged["files"]:
                target = data_store.unique_child_path(final_root, entry["display_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry["staged_path"]), str(target))
                display_path = target.relative_to(final_root).as_posix()
                store["uploaded_files"].append(
                    {
                        "id": uuid.uuid4().hex,
                        "folder_source": "local",
                        "folder_id": folder["id"],
                        "name": target.name,
                        "display_path": display_path,
                        "category": data_store.category_for_upload_path(display_path),
                        "relative_path": str(target.relative_to(data_store.DATA_DIR)),
                        "size": len(entry["content"]),
                        "content_type": entry["content_type"],
                        "uploaded_at": now,
                        "historical_import": True,
                        "sha256": entry["sha256"],
                    }
                )

        store["local_folders"] = sorted(
            folders_by_id.values(),
            key=lambda item: (str(item.get("date", "")), str(item.get("name", ""))),
            reverse=True,
        )
        summary = {
            "imported_at": now,
            "source_name": source_name(entries),
            "deliveries": delivery_count,
            "general_folders": general_count,
            "created": created,
            "updated": updated,
            "files": imported_files,
            "boletines": boletin_count,
            "ignored": ignored,
            "duplicates": duplicate_count,
        }
        store["last_historical_import"] = summary
        data_store.save_store(store, sync_backup=False)
        persistence.backup_state_or_raise(data_store.DATA_DIR)
        return summary
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def uploaded_entries(files: list[dict[str, object]]) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    ignored = 0
    total_size = 0

    for file_info in files:
        raw_name = repair_text(str(file_info.get("filename") or "")).strip()
        content = file_info.get("content")
        if not raw_name or not isinstance(content, bytes) or not content:
            ignored += 1
            continue
        if raw_name.lower().endswith(".zip"):
            archive_entries, archive_ignored = entries_from_zip(content)
            ignored += archive_ignored
            for entry in archive_entries:
                total_size += len(entry["content"])
                validate_limits(len(entries) + 1, total_size)
                entries.append(entry)
            continue

        normalized = normalize_source_path(raw_name)
        if should_ignore_path(normalized):
            ignored += 1
            continue
        total_size += len(content)
        validate_limits(len(entries) + 1, total_size)
        entries.append(make_entry(normalized, content, str(file_info.get("content_type") or "")))

    return entries, ignored


def entries_from_zip(content: bytes) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    ignored = 0
    total_size = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("El archivo ZIP no es válido.") from exc

    with archive:
        for member in archive.infolist():
            normalized = normalize_source_path(repair_text(member.filename))
            if member.is_dir() or should_ignore_path(normalized):
                ignored += 1
                continue
            if member.flag_bits & 0x1:
                raise ValueError("El ZIP está protegido con contraseña y no puede importarse.")
            total_size += member.file_size
            validate_limits(len(entries) + 1, total_size)
            payload = archive.read(member)
            entries.append(make_entry(normalized, payload, mimetypes.guess_type(normalized)[0] or ""))
    return entries, ignored


def group_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    groups: dict[str, dict[str, Any]] = {}
    duplicate_count = 0

    for entry in entries:
        parts = list(PurePosixPath(entry["source_path"]).parts)
        delivery_index = next((index for index, part in enumerate(parts) if DELIVERY_RE.match(part)), None)
        if delivery_index is not None:
            delivery_name = parts[delivery_index]
            match = DELIVERY_RE.match(delivery_name)
            delivery_date = match.group(1) if match else ""
            try:
                parsed_date = date.fromisoformat(delivery_date)
            except ValueError as exc:
                raise ValueError(f"La fecha de {delivery_name} no es válida.") from exc
            prefix = parts[:delivery_index]
            source_year = find_year(prefix) or str(parsed_date.year)
            source_month = find_month(prefix) or core.MESES_ES[parsed_date.month]
            relative_parts = parts[delivery_index + 1 :]
            if not relative_parts:
                continue
            source_relative_path = "/".join(parts[: delivery_index + 1])
            import_key = "delivery:" + normalized_key(f"{delivery_date}/{delivery_name}")
            number_match = DELIVERY_NUMBER_RE.search(delivery_name)
            group = groups.setdefault(
                import_key,
                {
                    "import_key": import_key,
                    "kind": "delivery",
                    "name": delivery_name,
                    "year": source_year,
                    "month": source_month,
                    "date": delivery_date,
                    "delivery_number": number_match.group(1) if number_match else "",
                    "source_relative_path": source_relative_path,
                    "files_by_path": {},
                },
            )
        else:
            source_year = find_year(parts)
            source_month = find_month(parts)
            relative_parts = trim_general_prefix(parts, source_year, source_month)
            if not relative_parts:
                continue
            period = " ".join(part for part in (source_month, source_year) if part).strip()
            name = f"DOCUMENTOS GENERALES - {period}" if period else "DOCUMENTOS GENERALES"
            import_key = "general:" + normalized_key(f"{source_year}/{source_month or 'SIN-MES'}")
            group = groups.setdefault(
                import_key,
                {
                    "import_key": import_key,
                    "kind": "general",
                    "name": name,
                    "year": source_year,
                    "month": source_month,
                    "date": f"{source_year}-{month_number(source_month):02d}-01" if source_year and source_month else "",
                    "delivery_number": "",
                    "source_relative_path": "/".join(parts[: -len(relative_parts)]) if len(parts) > len(relative_parts) else "",
                    "files_by_path": {},
                },
            )

        relative_path = "/".join(relative_parts)
        path_key = normalized_key(relative_path)
        if path_key in group["files_by_path"]:
            duplicate_count += 1
            if group["files_by_path"][path_key]["sha256"] == entry["sha256"]:
                continue
            relative_path = add_hash_suffix(relative_path, entry["sha256"][:8])
            path_key = normalized_key(relative_path)
        group["files_by_path"][path_key] = {**entry, "relative_path": relative_path}

    result = []
    for group in groups.values():
        group["files"] = sorted(group.pop("files_by_path").values(), key=lambda item: item["relative_path"])
        result.append(group)
    return sorted(result, key=lambda item: (item["date"], item["name"])), duplicate_count


def make_entry(source_path: str, content: bytes, content_type: str = "") -> dict[str, Any]:
    name = PurePosixPath(source_path).name
    return {
        "source_path": source_path,
        "name": name,
        "content": content,
        "content_type": content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def normalize_source_path(value: str) -> str:
    raw = re.sub(r"^[A-Za-z]:", "", value).replace("\\", "/")
    parts = []
    for part in raw.split("/"):
        part = repair_text(part).strip()
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("La carpeta contiene una ruta no segura.")
        parts.append(part)
    return "/".join(parts)


def should_ignore_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return True
    return any(part == ".DS_Store" or part == "__MACOSX" or part.startswith("._") for part in parts)


def repair_text(value: str) -> str:
    candidates = [value]
    for encoding in ("latin-1", "cp437"):
        try:
            candidate = value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return min(candidates, key=mojibake_score)


def mojibake_score(value: str) -> tuple[int, int]:
    suspicious = "ÂÃ┬├┤┼┌┐└┘░▒▓╣║╗╝╚╔"
    return (sum(value.count(char) for char in suspicious), len(value))


def validate_limits(file_count: int, total_size: int) -> None:
    if file_count > MAX_IMPORTED_FILES:
        raise ValueError(f"La importación supera el máximo de {MAX_IMPORTED_FILES} archivos.")
    if total_size > MAX_EXTRACTED_BYTES:
        limit_mb = MAX_EXTRACTED_BYTES // (1024 * 1024)
        raise ValueError(f"La importación descomprimida supera el máximo de {limit_mb} MB.")


def find_year(parts: list[str]) -> str:
    return next((part for part in reversed(parts) if YEAR_RE.match(part.strip())), "")


def find_month(parts: list[str]) -> str:
    return next((part.strip().upper() for part in reversed(parts) if part.strip().upper() in MONTH_NAMES), "")


def month_number(month: str) -> int:
    return next((number for number, name in core.MESES_ES.items() if name == month), 1)


def trim_general_prefix(parts: list[str], year: str, month: str) -> list[str]:
    month_index = next((index for index, part in enumerate(parts) if part.strip().upper() == month), None) if month else None
    if month_index is not None:
        return parts[month_index + 1 :]
    year_index = next((index for index, part in enumerate(parts) if part == year), None) if year else None
    if year_index is not None:
        return parts[year_index + 1 :]
    return parts[-1:]


def normalized_key(value: str) -> str:
    return re.sub(r"\s+", " ", repair_text(value).strip()).casefold()


def add_hash_suffix(path: str, suffix: str) -> str:
    pure = PurePosixPath(path)
    return str(pure.with_name(f"{pure.stem} ({suffix}){pure.suffix}"))


def source_name(entries: list[dict[str, Any]]) -> str:
    roots = {PurePosixPath(entry["source_path"]).parts[0] for entry in entries if PurePosixPath(entry["source_path"]).parts}
    return roots.pop() if len(roots) == 1 else "Archivo histórico"
