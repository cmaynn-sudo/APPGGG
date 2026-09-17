from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import calculations
import core
import persistence
from template_catalog import WEBAPP_DIR


DATA_DIR = Path(os.environ.get("DATA_DIR", str(WEBAPP_DIR / "data")))
STORE_PATH = DATA_DIR / "recepcion_store.json"
UPLOADS_DIR = DATA_DIR / "uploads"
DEFAULT_BOLETIN_SETTINGS = {
    "precio_negociacion_porcentaje": "97,5",
    "retencion_porcentaje": "2,5",
}


def _empty_store() -> dict[str, Any]:
    return {
        "sociedades": core.read_sociedades(),
        "regalias": core.read_regalias(),
        "boletin_settings": dict(DEFAULT_BOLETIN_SETTINGS),
        "entregas": [],
        "local_folders": [],
        "uploaded_files": [],
        "active_entrega_id": "",
    }


def normalize_store(store: dict[str, Any], sync_backup: bool = True) -> dict[str, Any]:
    defaults = _empty_store()
    changed = False
    for key, value in defaults.items():
        if key not in store:
            store[key] = value
            changed = True
    settings = store.get("boletin_settings")
    if not isinstance(settings, dict):
        settings = {}
        store["boletin_settings"] = settings
        changed = True
    for key, value in DEFAULT_BOLETIN_SETTINGS.items():
        if key not in settings or settings.get(key) in (None, ""):
            settings[key] = value
            changed = True
    for entrega in store.get("entregas", []):
        if "items" not in entrega:
            entrega["items"] = []
            changed = True
        if "parametros" not in entrega:
            entrega["parametros"] = {
                "mes_regalias": entrega.get("month", core.mes_actual_es()),
                "dolar": "",
                "oz_au": "",
                "oz_ag": "",
            }
            changed = True
    for folder in store.get("local_folders", []):
        if "files" not in folder:
            folder["files"] = []
            changed = True
    if changed:
        save_store(store, sync_backup=sync_backup)
    return store


def load_store() -> dict[str, Any]:
    restore_status = persistence.restore_state_if_configured(
        DATA_DIR,
        force=persistence.should_restore_on_start(),
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        save_store(_empty_store(), sync_backup=False)
        created_empty = True
    else:
        created_empty = False
    should_sync_backup = not created_empty and restore_status not in {"failed", "remote-empty"}
    return normalize_store(json.loads(STORE_PATH.read_text(encoding="utf-8")), sync_backup=should_sync_backup)


def save_store(store: dict[str, Any], sync_backup: bool = True) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(STORE_PATH)
    if sync_backup:
        persistence.backup_state_if_configured(DATA_DIR)


def get_sociedad(store: dict[str, Any], nombre: str) -> dict[str, Any] | None:
    target = nombre.strip()
    for row in store.get("sociedades", []):
        if row.get("sociedad", "").strip() == target:
            return row
    return None


def get_regalias_for_month(store: dict[str, Any], mes: str) -> dict[str, Any]:
    target = mes.strip().lower()
    for row in store.get("regalias", []):
        if row.get("mes", "").strip().lower() == target:
            return row
    return {"mes": mes, "au": 0, "ag": 0}


def get_boletin_settings(store: dict[str, Any] | None = None) -> dict[str, Any]:
    data = store or load_store()
    settings = dict(DEFAULT_BOLETIN_SETTINGS)
    saved = data.get("boletin_settings") or {}
    if isinstance(saved, dict):
        settings.update(saved)
    return settings


def update_boletin_settings(form: dict[str, str]) -> dict[str, Any]:
    settings = {
        "precio_negociacion_porcentaje": normalize_percent_field(form.get("precio_negociacion_porcentaje", ""), "97,5"),
        "retencion_porcentaje": normalize_percent_field(form.get("retencion_porcentaje", ""), "2,5"),
    }
    store = load_store()
    store["boletin_settings"] = settings
    save_store(store)
    return settings


def normalize_percent_field(raw: str, fallback: str) -> str:
    value = str(raw or fallback).strip()
    try:
        number = core.parse_decimal_input(value)
    except ValueError as exc:
        raise ValueError("El porcentaje debe ser numérico.") from exc
    if number < 0:
        raise ValueError("El porcentaje no puede ser negativo.")
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def create_entrega(numero: str) -> dict[str, Any]:
    if not numero.strip():
        raise ValueError("Ingresa un número de entrega.")
    store = load_store()
    today = date.today()
    entrega = {
        "id": uuid.uuid4().hex,
        "numero": numero.strip(),
        "fecha": today.isoformat(),
        "year": str(today.year),
        "month": core.MESES_ES[today.month],
        "name": f"ENTREGA °{numero.strip()} - ({today.isoformat()})",
        "items": [],
        "parametros": {
            "mes_regalias": core.MESES_ES[today.month],
            "dolar": "",
            "oz_au": "",
            "oz_ag": "",
        },
    }
    store.setdefault("entregas", []).append(entrega)
    store["active_entrega_id"] = entrega["id"]
    save_store(store)
    return entrega


def set_active_entrega(entrega_id: str) -> None:
    store = load_store()
    if not any(entrega.get("id") == entrega_id for entrega in store.get("entregas", [])):
        raise ValueError("Entrega no encontrada.")
    store["active_entrega_id"] = entrega_id
    save_store(store)


def delete_entrega(entrega_id: str) -> None:
    store = load_store()
    entregas = store.get("entregas", [])
    if not any(entrega.get("id") == entrega_id for entrega in entregas):
        raise ValueError("Entrega no encontrada.")
    store["entregas"] = [entrega for entrega in entregas if entrega.get("id") != entrega_id]
    store["uploaded_files"] = [
        file_info
        for file_info in store.get("uploaded_files", [])
        if not (file_info.get("folder_source") == "web" and file_info.get("folder_id") == entrega_id)
    ]
    upload_dir = UPLOADS_DIR / "web" / entrega_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    store["active_entrega_id"] = store["entregas"][-1]["id"] if store.get("entregas") else ""
    save_store(store)


def get_entrega(entrega_id: str | None = None) -> dict[str, Any] | None:
    store = load_store()
    target = entrega_id or store.get("active_entrega_id")
    for entrega in store.get("entregas", []):
        if entrega.get("id") == target:
            return entrega
    return store.get("entregas", [])[-1] if store.get("entregas") else None


def list_entregas() -> list[dict[str, Any]]:
    store = load_store()
    return sorted(store.get("entregas", []), key=lambda item: item.get("fecha", ""), reverse=True)


def add_entrega_item(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega_id = form.get("entrega_id") or store.get("active_entrega_id")
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Primero crea una entrega.")
    if len(entrega.get("items", [])) >= 8:
        raise ValueError("La plantilla de preliminares permite máximo 8 sociedades por entrega.")

    sociedad = get_sociedad(store, form.get("proveedor", ""))
    if not sociedad:
        raise ValueError("Selecciona una sociedad válida.")

    consecutivo = int(sociedad.get("consecutivo") or 0) + 1
    sociedad["consecutivo"] = consecutivo
    codigo = f"{sociedad.get('prefijo')}-{consecutivo}"
    raw = {
        "id": uuid.uuid4().hex,
        "proveedor": sociedad.get("sociedad", ""),
        "sociedad": sociedad.get("sociedad", ""),
        "nit": sociedad.get("nit", ""),
        "rucom": sociedad.get("rucom", ""),
        "municipio": sociedad.get("municipio", ""),
        "prefijo": sociedad.get("prefijo", ""),
        "codigo": codigo,
        "barra": codigo,
        "peso_inicial": form.get("peso_inicial", ""),
        "peso_post": form.get("peso_post", ""),
        "peso_final": form.get("peso_post", ""),
        "muestras": form.get("muestras", "0"),
        "ley_estimada": form.get("ley_estimada", "0.7") or "0.7",
        "ley_au": "",
        "ley_ag": "",
        "estado": "recibo",
    }
    item = calculations.preliminar_item(raw)
    entrega.setdefault("items", []).append(item)
    save_store(store)
    return item


def update_entrega_item(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == form.get("entrega_id")), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    idx = next((idx for idx, item in enumerate(entrega.get("items", [])) if item.get("id") == form.get("item_id")), None)
    if idx is None:
        raise ValueError("Sociedad no encontrada en la entrega.")
    item = dict(entrega["items"][idx])
    for key in ["peso_inicial", "peso_post", "muestras", "ley_estimada", "ley_au", "ley_ag"]:
        if key in form:
            item[key] = form.get(key, "")
    item["peso_final"] = item.get("peso_post", "")
    recalculated = calculations.preliminar_item(item)
    recalculated["ley_au"] = item.get("ley_au", "")
    recalculated["ley_ag"] = item.get("ley_ag", "")
    recalculated["ley_estimada"] = item.get("ley_estimada", "")
    recalculated["estado"] = "leyes" if recalculated.get("ley_au") and recalculated.get("ley_ag") else "recibo"
    entrega["items"][idx] = recalculated
    save_store(store)
    return recalculated


def delete_entrega_item(entrega_id: str, item_id: str) -> None:
    store = load_store()
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    original_count = len(entrega.get("items", []))
    entrega["items"] = [item for item in entrega.get("items", []) if item.get("id") != item_id]
    if len(entrega["items"]) == original_count:
        raise ValueError("Sociedad no encontrada en la entrega.")
    save_store(store)


def update_ley(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == form.get("entrega_id")), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    item = next((i for i in entrega.get("items", []) if i.get("id") == form.get("item_id")), None)
    if not item:
        raise ValueError("Sociedad no encontrada en la entrega.")
    item["ley_au"] = form.get("ley_au", "")
    item["ley_ag"] = form.get("ley_ag", "")
    item["estado"] = "leyes"
    save_store(store)
    return item


def clear_ley(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == form.get("entrega_id")), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    item = next((i for i in entrega.get("items", []) if i.get("id") == form.get("item_id")), None)
    if not item:
        raise ValueError("Sociedad no encontrada en la entrega.")
    item["ley_au"] = ""
    item["ley_ag"] = ""
    item["estado"] = "recibo"
    save_store(store)
    return item


def update_parametros(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == form.get("entrega_id")), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    entrega["parametros"] = {
        "mes_regalias": form.get("mes_regalias", ""),
        "dolar": form.get("dolar", ""),
        "oz_au": form.get("oz_au", ""),
        "oz_ag": form.get("oz_ag", ""),
    }
    save_store(store)
    return entrega["parametros"]


def clear_parametros(entrega_id: str) -> dict[str, Any]:
    store = load_store()
    entrega = next((e for e in store.get("entregas", []) if e.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    entrega["parametros"] = {
        "mes_regalias": entrega.get("month", core.mes_actual_es()),
        "dolar": "",
        "oz_au": "",
        "oz_ag": "",
    }
    save_store(store)
    return entrega["parametros"]


def upsert_regalia(form: dict[str, str]) -> dict[str, Any]:
    mes = form.get("mes", "").strip().upper()
    if not mes:
        raise ValueError("Selecciona un mes.")
    if mes not in core.MESES_ORDEN:
        raise ValueError("Mes inválido.")

    def parse_optional(name: str) -> float | None:
        raw = form.get(name, "").strip()
        return core.parse_decimal_input(raw) if raw else None

    row = {
        "mes": mes,
        "au": parse_optional("au"),
        "ag": parse_optional("ag"),
    }
    store = load_store()
    regalias = store.setdefault("regalias", [])
    for idx, existing in enumerate(regalias):
        if existing.get("mes", "").strip().upper() == mes:
            regalias[idx] = row
            break
    else:
        regalias.append(row)
    store["regalias"] = sorted(regalias, key=lambda item: core.MESES_ORDEN.index(item.get("mes", "DICIEMBRE")) if item.get("mes") in core.MESES_ORDEN else 99)
    save_store(store)
    return row


def delete_regalia(mes: str) -> None:
    target = mes.strip().upper()
    store = load_store()
    regalias = store.get("regalias", [])
    if not any(row.get("mes", "").strip().upper() == target for row in regalias):
        raise ValueError("Regalía no encontrada.")
    store["regalias"] = [row for row in regalias if row.get("mes", "").strip().upper() != target]
    save_store(store)


def upsert_sociedad(form: dict[str, str]) -> dict[str, Any]:
    original = form.get("original_sociedad", "").strip()
    sociedad = form.get("sociedad", "").strip().upper()
    prefijo = form.get("prefijo", "").strip().upper()
    if not sociedad:
        raise ValueError("Ingresa el nombre de la sociedad.")
    if not prefijo:
        raise ValueError("Ingresa el prefijo.")
    consecutivo_raw = form.get("consecutivo", "0").strip() or "0"
    try:
        consecutivo = int(core.parse_decimal_input(consecutivo_raw))
    except ValueError as exc:
        raise ValueError("El consecutivo debe ser numérico.") from exc
    row = {
        "sociedad": sociedad,
        "nit": form.get("nit", "").strip(),
        "rucom": form.get("rucom", "").strip(),
        "municipio": form.get("municipio", "").strip().upper(),
        "prefijo": prefijo,
        "consecutivo": consecutivo,
    }
    store = load_store()
    sociedades = store.setdefault("sociedades", [])
    if original:
        for idx, existing in enumerate(sociedades):
            if existing.get("sociedad", "").strip() == original:
                sociedades[idx] = row
                break
        else:
            raise ValueError("Sociedad no encontrada.")
    else:
        if any(existing.get("sociedad", "").strip().upper() == sociedad for existing in sociedades):
            raise ValueError("Ya existe una sociedad con ese nombre.")
        sociedades.append(row)
    store["sociedades"] = sorted(sociedades, key=lambda item: item.get("sociedad", ""))
    save_store(store)
    return row


def delete_sociedad(nombre: str) -> None:
    target = nombre.strip()
    store = load_store()
    sociedades = store.get("sociedades", [])
    if not any(row.get("sociedad", "").strip() == target for row in sociedades):
        raise ValueError("Sociedad no encontrada.")
    store["sociedades"] = [row for row in sociedades if row.get("sociedad", "").strip() != target]
    save_store(store)


def safe_filename(name: str) -> str:
    clean = Path(name or "archivo").name.strip()
    clean = re.sub(r'[\\/:*?"<>|]', "-", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean or f"archivo-{uuid.uuid4().hex[:8]}"


def safe_path_parts(name: str) -> list[str]:
    raw = re.sub(r"^[A-Za-z]:", "", str(name or "")).replace("\\", "/")
    parts = []
    for part in raw.split("/"):
        if part.strip() in {"", ".", ".."}:
            continue
        clean = safe_filename(part)
        if clean in {"", ".", ".."}:
            continue
        parts.append(clean)
    return parts or [f"archivo-{uuid.uuid4().hex[:8]}"]


def safe_relative_upload_path(name: str) -> str:
    return "/".join(safe_path_parts(name))


def infer_folder_name(files: list[dict[str, object]], fallback: str = "") -> str:
    if fallback.strip():
        return safe_filename(fallback.strip())
    for file_info in files:
        parts = safe_path_parts(str(file_info.get("filename") or ""))
        if len(parts) > 1:
            return parts[0]
    today = date.today().isoformat()
    return f"CARPETA LOCAL - {today}"


def category_for_upload_path(relative_path: str) -> str:
    parts = [part.upper() for part in safe_path_parts(relative_path)]
    filename = parts[-1] if parts else ""
    if "LEYES" in parts or filename.startswith("REPORTE LEYES"):
        return "Leyes"
    if "BOLETINES" in parts or filename.startswith("BOLETIN"):
        return "Boletines"
    if filename.startswith("PRELIMINARES"):
        return "Preliminares"
    if filename.startswith("CERTIFICADO"):
        return "Certificados"
    if filename.endswith(".PDF"):
        return "Recibos de metales"
    return "Archivos"


def unique_child_path(root: Path, relative_path: str) -> Path:
    parts = safe_path_parts(relative_path)
    target_dir = root.joinpath(*parts[:-1])
    filename = parts[-1]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10_000):
        candidate = target_dir / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return target_dir / f"{uuid.uuid4().hex}-{filename}"


def list_local_folders() -> list[dict[str, Any]]:
    store = load_store()
    return sorted(store.get("local_folders", []), key=lambda item: item.get("created_at", ""), reverse=True)


def get_local_folder(folder_id: str) -> dict[str, Any] | None:
    store = load_store()
    return next((folder for folder in store.get("local_folders", []) if folder.get("id") == folder_id), None)


def create_local_folder_from_upload(folder_name: str, files: list[dict[str, object]]) -> dict[str, Any]:
    valid_files = [
        file_info
        for file_info in files
        if str(file_info.get("filename") or "").strip() and isinstance(file_info.get("content"), bytes) and file_info.get("content")
    ]
    if not valid_files:
        raise ValueError("Selecciona una carpeta con archivos.")
    folder_id = uuid.uuid4().hex
    today = date.today()
    folder = {
        "id": folder_id,
        "name": infer_folder_name(valid_files, folder_name),
        "year": str(today.year),
        "month": core.MESES_ES[today.month],
        "date": today.isoformat(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    store = load_store()
    store.setdefault("local_folders", []).append(folder)
    save_store(store, sync_backup=False)
    try:
        for file_info in valid_files:
            filename = str(file_info.get("filename") or "")
            save_uploaded_file(
                "local",
                folder_id,
                filename,
                file_info.get("content") or b"",
                str(file_info.get("content_type") or ""),
                preserve_path=True,
                category=category_for_upload_path(filename),
                sync_backup=False,
            )
    except Exception:
        delete_local_folder(folder_id)
        raise
    persistence.backup_state_if_configured(DATA_DIR)
    return get_local_folder(folder_id) or folder


def delete_local_folder(folder_id: str) -> None:
    store = load_store()
    folders = store.get("local_folders", [])
    if not any(folder.get("id") == folder_id for folder in folders):
        raise ValueError("Carpeta local no encontrada.")
    store["local_folders"] = [folder for folder in folders if folder.get("id") != folder_id]
    save_store(store)
    delete_uploaded_files_for("local", folder_id)
    folder_dir = UPLOADS_DIR / "local" / folder_id
    if folder_dir.exists():
        shutil.rmtree(folder_dir)


def uploaded_files_for(folder_source: str, folder_id: str) -> list[dict[str, Any]]:
    store = load_store()
    return [
        file_info
        for file_info in store.get("uploaded_files", [])
        if file_info.get("folder_source") == folder_source and file_info.get("folder_id") == folder_id
    ]


def save_uploaded_file(
    folder_source: str,
    folder_id: str,
    filename: str,
    content: bytes,
    content_type: str = "",
    preserve_path: bool = False,
    category: str = "",
    sync_backup: bool = True,
) -> dict[str, Any]:
    if not content:
        raise ValueError("El archivo está vacío.")
    file_id = uuid.uuid4().hex
    clean_name = safe_filename(filename)
    folder_root = UPLOADS_DIR / folder_source / folder_id
    if preserve_path:
        display_path = safe_relative_upload_path(filename)
        target = unique_child_path(folder_root, display_path)
        clean_name = target.name
    else:
        display_path = clean_name
        folder_root.mkdir(parents=True, exist_ok=True)
        target = folder_root / f"{file_id}-{clean_name}"
    target.write_bytes(content)
    file_info = {
        "id": file_id,
        "folder_source": folder_source,
        "folder_id": folder_id,
        "name": clean_name,
        "display_path": display_path,
        "category": category,
        "relative_path": str(target.relative_to(DATA_DIR)),
        "size": len(content),
        "content_type": content_type,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    store = load_store()
    store.setdefault("uploaded_files", []).append(file_info)
    save_store(store, sync_backup=sync_backup)
    return file_info


def find_uploaded_file(file_id: str) -> tuple[dict[str, Any], Path] | tuple[None, None]:
    store = load_store()
    for file_info in store.get("uploaded_files", []):
        if file_info.get("id") != file_id:
            continue
        rel = str(file_info.get("relative_path", "")).lstrip("/\\")
        path = (DATA_DIR / rel).resolve()
        if not str(path).startswith(str(DATA_DIR.resolve())) or not path.exists() or not path.is_file():
            return None, None
        return file_info, path
    return None, None


def delete_uploaded_file(file_id: str) -> dict[str, Any]:
    store = load_store()
    target = None
    remaining = []
    for file_info in store.get("uploaded_files", []):
        if file_info.get("id") == file_id:
            target = file_info
        else:
            remaining.append(file_info)
    if not target:
        raise ValueError("Archivo no encontrado.")
    _file, path = find_uploaded_file(file_id)
    if path:
        path.unlink(missing_ok=True)
    store["uploaded_files"] = remaining
    save_store(store)
    return target


def delete_uploaded_files_for(folder_source: str, folder_id: str) -> None:
    store = load_store()
    remaining = []
    for file_info in store.get("uploaded_files", []):
        if file_info.get("folder_source") == folder_source and file_info.get("folder_id") == folder_id:
            rel = str(file_info.get("relative_path", "")).lstrip("/\\")
            path = (DATA_DIR / rel).resolve()
            if str(path).startswith(str(DATA_DIR.resolve())):
                path.unlink(missing_ok=True)
        else:
            remaining.append(file_info)
    store["uploaded_files"] = remaining
    save_store(store)


def boletines_for_entrega(entrega: dict[str, Any]) -> list[dict[str, Any]]:
    store = load_store()
    parametros = entrega.get("parametros", {})
    regalias = get_regalias_for_month(store, parametros.get("mes_regalias", entrega.get("month", "")))
    settings = get_boletin_settings(store)
    rows = []
    for item in entrega.get("items", []):
        if item.get("ley_au") in ("", None) or item.get("ley_ag") in ("", None):
            continue
        rows.append(calculations.boletin_context(item, parametros, regalias, settings))
    return rows


def certificado_groups(year: str | None = None, month: str | None = None) -> list[dict[str, Any]]:
    store = load_store()
    groups: dict[str, dict[str, Any]] = {}
    for entrega in store.get("entregas", []):
        if year and entrega.get("year") != year:
            continue
        if month and entrega.get("month") != month:
            continue
        for boletin in boletines_for_entrega(entrega):
            key = boletin.get("sociedad") or boletin.get("proveedor")
            if not key:
                continue
            group = groups.setdefault(
                key,
                {
                    "key": slugify(key),
                    "sociedad": key,
                    "nit": boletin.get("nit", ""),
                    "boletines": [],
                },
            )
            group["boletines"].append(
                {
                    "documento": boletin.get("barra", boletin.get("codigo", "")),
                    "fecha": entrega.get("fecha", ""),
                    "mes": entrega.get("month", ""),
                    "finos_oro": boletin.get("finos_oro", ""),
                    "finos_plata": boletin.get("finos_plata", ""),
                    "regalia_oro": boletin.get("regalia_oro", ""),
                    "regalia_plata": boletin.get("regalia_plata", ""),
                }
            )
    return sorted(groups.values(), key=lambda item: item["sociedad"])


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9ñ]+", "-", text)
    return text.strip("-") or "sociedad"
