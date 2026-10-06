from __future__ import annotations

import json
import math
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
from template_catalog import TEMPLATE_BY_SLUG, WEBAPP_DIR


DATA_DIR = Path(os.environ.get("DATA_DIR", str(WEBAPP_DIR / "data")))
STORE_PATH = DATA_DIR / "recepcion_store.json"
UPLOADS_DIR = DATA_DIR / "uploads"
DEFAULT_BOLETIN_SETTINGS = {
    "precio_negociacion_porcentaje": "97,5",
    "retencion_porcentaje": "2,5",
}
DASHBOARD_OVERRIDE_TEXT_FIELDS = ("documento", "sociedad", "date")
DASHBOARD_OVERRIDE_NUMBER_FIELDS = (
    "subtotal",
    "valor_a_pagar",
    "regalia_oro",
    "regalia_plata",
    "valor_pagado",
    "peso_inicial",
    "peso_final",
)
LAYOUT_ELEMENT_ID_RE = re.compile(r"^(?:cell-[A-Z]{1,3}\d+|image-\d+|block-[a-z0-9-]+)$")
LAYOUT_ALIGNMENTS = {"", "left", "center", "right"}


def _empty_store() -> dict[str, Any]:
    return {
        "sociedades": core.read_sociedades(),
        "regalias": core.read_regalias(),
        "boletin_settings": dict(DEFAULT_BOLETIN_SETTINGS),
        "entregas": [],
        "local_folders": [],
        "uploaded_files": [],
        "dashboard_overrides": {},
        "template_layouts": {},
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
        if "finalizada" not in entrega:
            entrega["finalizada"] = False
            changed = True
        if "finalizada_at" not in entrega:
            entrega["finalizada_at"] = ""
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
    if not isinstance(store.get("dashboard_overrides"), dict):
        store["dashboard_overrides"] = {}
        changed = True
    if not isinstance(store.get("template_layouts"), dict):
        store["template_layouts"] = {}
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
    should_sync_backup = (
        persistence.is_configured()
        and not created_empty
        and restore_status not in {"failed", "remote-empty"}
    )
    return normalize_store(json.loads(STORE_PATH.read_text(encoding="utf-8")), sync_backup=should_sync_backup)


def save_store(store: dict[str, Any], sync_backup: bool = True) -> None:
    if sync_backup:
        storage_error = persistence.write_block_reason()
        if storage_error:
            raise RuntimeError(storage_error)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(STORE_PATH)
    if sync_backup:
        persistence.backup_state_or_raise(DATA_DIR)


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


def get_entrega_boletin_settings(entrega: dict[str, Any], store: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_boletin_settings(store)
    saved = entrega.get("boletin_settings") or {}
    if isinstance(saved, dict):
        settings.update({key: value for key, value in saved.items() if value not in (None, "")})
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


def upsert_dashboard_override(form: dict[str, str]) -> dict[str, Any]:
    quality_id = str(form.get("quality_id", "")).strip()
    if not quality_id or len(quality_id) > 180:
        raise ValueError("No se pudo identificar el boletín que se va a corregir.")

    values: dict[str, Any] = {}
    for field in DASHBOARD_OVERRIDE_TEXT_FIELDS:
        raw = str(form.get(field, "")).strip()
        if not raw:
            continue
        if field == "date":
            try:
                date.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError("La fecha informativa no es válida.") from exc
        values[field] = raw

    for field in DASHBOARD_OVERRIDE_NUMBER_FIELDS:
        raw = str(form.get(field, "")).strip()
        if not raw:
            continue
        try:
            values[field] = core.parse_decimal_input(raw)
        except ValueError as exc:
            raise ValueError("Todos los valores del dashboard deben ser numéricos.") from exc

    if not values:
        raise ValueError("Ingresa al menos un dato para guardar la corrección informativa.")

    override = {
        "quality_id": quality_id,
        "document_name": str(form.get("document_name", "")).strip(),
        "folder_name": str(form.get("folder_name", "")).strip(),
        "values": values,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    store = load_store()
    store.setdefault("dashboard_overrides", {})[quality_id] = override
    save_store(store)
    return override


def delete_dashboard_override(quality_id: str) -> None:
    target = str(quality_id or "").strip()
    store = load_store()
    overrides = store.setdefault("dashboard_overrides", {})
    if target not in overrides:
        raise ValueError("La corrección informativa no existe.")
    del overrides[target]
    save_store(store)


def get_template_layout(slug: str, store: dict[str, Any] | None = None) -> dict[str, Any]:
    if slug not in TEMPLATE_BY_SLUG:
        return {"elements": {}}
    data = store or load_store()
    layout = data.get("template_layouts", {}).get(slug, {})
    if not isinstance(layout, dict):
        return {"elements": {}}
    elements = layout.get("elements", {})
    return {
        "elements": elements if isinstance(elements, dict) else {},
        "updated_at": str(layout.get("updated_at", "")),
    }


def update_template_layout(slug: str, raw_layout: str) -> dict[str, Any]:
    if slug not in TEMPLATE_BY_SLUG:
        raise ValueError("La plantilla seleccionada no existe.")
    try:
        submitted = json.loads(raw_layout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Los ajustes visuales no tienen un formato válido.") from exc
    if not isinstance(submitted, dict):
        raise ValueError("Los ajustes visuales no tienen un formato válido.")
    if len(submitted) > 400:
        raise ValueError("La plantilla contiene demasiados ajustes individuales.")

    elements: dict[str, dict[str, Any]] = {}
    for element_id, raw_settings in submitted.items():
        if not isinstance(element_id, str) or not LAYOUT_ELEMENT_ID_RE.fullmatch(element_id):
            continue
        if not isinstance(raw_settings, dict):
            continue
        settings: dict[str, Any] = {}
        for name, fallback, lower, upper in (
            ("x", 0.0, -500.0, 500.0),
            ("y", 0.0, -500.0, 500.0),
            ("scale", 1.0, 0.4, 2.5),
            ("font_size", 0.0, 0.0, 72.0),
        ):
            try:
                value = float(raw_settings.get(name, fallback))
            except (TypeError, ValueError):
                value = fallback
            if not math.isfinite(value):
                value = fallback
            value = min(upper, max(lower, value))
            if name in {"x", "y"} and abs(value) < 0.01:
                value = 0.0
            if name == "scale" and abs(value - 1.0) < 0.001:
                value = 1.0
            if name == "font_size" and value < 1:
                value = 0.0
            settings[name] = round(value, 2)
        settings["nowrap"] = bool(raw_settings.get("nowrap", False))
        alignment = str(raw_settings.get("text_align", "")).strip().lower()
        settings["text_align"] = alignment if alignment in LAYOUT_ALIGNMENTS else ""
        elements[element_id] = settings

    layout = {
        "elements": elements,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    store = load_store()
    store.setdefault("template_layouts", {})[slug] = layout
    save_store(store)
    return layout


def reset_template_layout(slug: str) -> None:
    if slug not in TEMPLATE_BY_SLUG:
        raise ValueError("La plantilla seleccionada no existe.")
    store = load_store()
    layouts = store.setdefault("template_layouts", {})
    if slug in layouts:
        del layouts[slug]
        save_store(store)


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


def normalize_optional_number(raw: str, label: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    try:
        number = core.parse_decimal_input(value)
    except ValueError as exc:
        raise ValueError(f"{label} debe ser numérico.") from exc
    text = f"{number:.8f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def create_entrega(
    numero: str,
    fecha: str = "",
    parametros: dict[str, str] | None = None,
    boletin_settings: dict[str, str] | None = None,
    reconstructed_from_folder_id: str = "",
) -> dict[str, Any]:
    if not numero.strip():
        raise ValueError("Ingresa un número de entrega.")
    raw_date = str(fecha or "").strip()
    try:
        delivery_date = date.fromisoformat(raw_date) if raw_date else date.today()
    except ValueError as exc:
        raise ValueError("La fecha de la entrega no es válida.") from exc

    store = load_store()
    month = core.MESES_ES[delivery_date.month]
    raw_parameters = parametros or {}
    royalty_month = str(raw_parameters.get("mes_regalias") or month).strip().upper()
    if royalty_month not in core.MESES_ORDEN:
        raise ValueError("El mes de regalías no es válido.")
    entrega = {
        "id": uuid.uuid4().hex,
        "numero": numero.strip(),
        "fecha": delivery_date.isoformat(),
        "year": str(delivery_date.year),
        "month": month,
        "name": f"ENTREGA °{numero.strip()} - ({delivery_date.isoformat()})",
        "finalizada": False,
        "finalizada_at": "",
        "items": [],
        "parametros": {
            "mes_regalias": royalty_month,
            "dolar": normalize_optional_number(raw_parameters.get("dolar", ""), "El dólar"),
            "oz_au": normalize_optional_number(raw_parameters.get("oz_au", ""), "La onza de oro"),
            "oz_ag": normalize_optional_number(raw_parameters.get("oz_ag", ""), "La onza de plata"),
        },
    }
    if boletin_settings is not None:
        entrega["boletin_settings"] = {
            "precio_negociacion_porcentaje": normalize_percent_field(
                boletin_settings.get("precio_negociacion_porcentaje", ""),
                get_boletin_settings(store)["precio_negociacion_porcentaje"],
            ),
            "retencion_porcentaje": normalize_percent_field(
                boletin_settings.get("retencion_porcentaje", ""),
                get_boletin_settings(store)["retencion_porcentaje"],
            ),
        }
    if reconstructed_from_folder_id:
        entrega["historical_reconstruction"] = True
        entrega["reconstructed_from_folder_id"] = reconstructed_from_folder_id
    store.setdefault("entregas", []).append(entrega)
    store["active_entrega_id"] = entrega["id"]
    save_store(store)
    return entrega


def create_historical_entrega(form: dict[str, str]) -> dict[str, Any]:
    return create_entrega(
        form.get("numero", ""),
        form.get("fecha", ""),
        parametros={
            "mes_regalias": form.get("mes_regalias", ""),
            "dolar": form.get("dolar", ""),
            "oz_au": form.get("oz_au", ""),
            "oz_ag": form.get("oz_ag", ""),
        },
        boletin_settings={
            "precio_negociacion_porcentaje": form.get("precio_negociacion_porcentaje", ""),
            "retencion_porcentaje": form.get("retencion_porcentaje", ""),
        },
        reconstructed_from_folder_id=form.get("source_folder_id", ""),
    )


def set_active_entrega(entrega_id: str) -> None:
    store = load_store()
    entrega = next((row for row in store.get("entregas", []) if row.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    if entrega.get("finalizada"):
        raise ValueError("La entrega está finalizada. Reábrela antes de continuar trabajando en ella.")
    store["active_entrega_id"] = entrega_id
    save_store(store)


def finalize_entrega(entrega_id: str) -> dict[str, Any]:
    store = load_store()
    entrega = next((row for row in store.get("entregas", []) if row.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    entrega["finalizada"] = True
    entrega["finalizada_at"] = datetime.now().isoformat(timespec="seconds")
    if store.get("active_entrega_id") == entrega_id:
        store["active_entrega_id"] = next(
            (
                row.get("id", "")
                for row in reversed(store.get("entregas", []))
                if not row.get("finalizada") and row.get("id") != entrega_id
            ),
            "",
        )
    save_store(store)
    return entrega


def reopen_entrega(entrega_id: str) -> dict[str, Any]:
    store = load_store()
    entrega = next((row for row in store.get("entregas", []) if row.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    entrega["finalizada"] = False
    entrega["finalizada_at"] = ""
    store["active_entrega_id"] = entrega_id
    save_store(store)
    return entrega


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
    store["active_entrega_id"] = next(
        (
            entrega.get("id", "")
            for entrega in reversed(store.get("entregas", []))
            if not entrega.get("finalizada")
        ),
        "",
    )
    save_store(store)


def get_entrega(entrega_id: str | None = None) -> dict[str, Any] | None:
    store = load_store()
    if entrega_id:
        return next(
            (entrega for entrega in store.get("entregas", []) if entrega.get("id") == entrega_id),
            None,
        )
    target = store.get("active_entrega_id")
    active = next(
        (
            entrega
            for entrega in store.get("entregas", [])
            if entrega.get("id") == target and not entrega.get("finalizada")
        ),
        None,
    )
    if active:
        return active
    return next(
        (entrega for entrega in reversed(store.get("entregas", [])) if not entrega.get("finalizada")),
        None,
    )


def list_entregas(include_finalized: bool = True) -> list[dict[str, Any]]:
    store = load_store()
    entregas = store.get("entregas", [])
    if not include_finalized:
        entregas = [entrega for entrega in entregas if not entrega.get("finalizada")]
    return sorted(entregas, key=lambda item: item.get("fecha", ""), reverse=True)


def editable_entrega(store: dict[str, Any], entrega_id: str) -> dict[str, Any]:
    entrega = next((row for row in store.get("entregas", []) if row.get("id") == entrega_id), None)
    if not entrega:
        raise ValueError("Entrega no encontrada.")
    if entrega.get("finalizada"):
        raise ValueError("La entrega está finalizada. Reábrela para modificar sus datos.")
    return entrega


def add_entrega_item(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega_id = form.get("entrega_id") or store.get("active_entrega_id")
    if not entrega_id:
        raise ValueError("Primero crea una entrega.")
    entrega = editable_entrega(store, entrega_id)
    if len(entrega.get("items", [])) >= 8:
        raise ValueError("La plantilla de preliminares permite máximo 8 sociedades por entrega.")

    sociedad = get_sociedad(store, form.get("proveedor", ""))
    if not sociedad:
        raise ValueError("Selecciona una sociedad válida.")

    manual_code = form.get("codigo", "").strip().upper()
    if manual_code:
        if any(
            str(existing.get("codigo", "")).strip().upper() == manual_code
            for existing in entrega.get("items", [])
        ):
            raise ValueError("Ese código ya existe en la entrega.")
        codigo = manual_code
    else:
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
    entrega = editable_entrega(store, form.get("entrega_id", ""))
    idx = next((idx for idx, item in enumerate(entrega.get("items", [])) if item.get("id") == form.get("item_id")), None)
    if idx is None:
        raise ValueError("Sociedad no encontrada en la entrega.")
    item = dict(entrega["items"][idx])
    for key in ["peso_inicial", "peso_post", "muestras", "ley_estimada", "ley_au", "ley_ag"]:
        if key in form:
            item[key] = form.get(key, "")
    if "codigo" in form:
        codigo = form.get("codigo", "").strip().upper()
        if not codigo:
            raise ValueError("El código no puede quedar vacío.")
        if any(
            existing.get("id") != item.get("id")
            and str(existing.get("codigo", "")).strip().upper() == codigo
            for existing in entrega.get("items", [])
        ):
            raise ValueError("Ese código ya existe en la entrega.")
        item["codigo"] = codigo
        item["barra"] = codigo
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
    entrega = editable_entrega(store, entrega_id)
    original_count = len(entrega.get("items", []))
    entrega["items"] = [item for item in entrega.get("items", []) if item.get("id") != item_id]
    if len(entrega["items"]) == original_count:
        raise ValueError("Sociedad no encontrada en la entrega.")
    save_store(store)


def update_ley(form: dict[str, str]) -> dict[str, Any]:
    store = load_store()
    entrega = editable_entrega(store, form.get("entrega_id", ""))
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
    entrega = editable_entrega(store, form.get("entrega_id", ""))
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
    entrega = editable_entrega(store, form.get("entrega_id", ""))
    royalty_month = form.get("mes_regalias", "").strip().upper()
    if royalty_month not in core.MESES_ORDEN:
        raise ValueError("El mes de regalías no es válido.")
    entrega["parametros"] = {
        "mes_regalias": royalty_month,
        "dolar": normalize_optional_number(form.get("dolar", ""), "El dólar"),
        "oz_au": normalize_optional_number(form.get("oz_au", ""), "La onza de oro"),
        "oz_ag": normalize_optional_number(form.get("oz_ag", ""), "La onza de plata"),
    }
    if "precio_negociacion_porcentaje" in form or "retencion_porcentaje" in form:
        current_settings = get_entrega_boletin_settings(entrega, store)
        entrega["boletin_settings"] = {
            "precio_negociacion_porcentaje": normalize_percent_field(
                form.get("precio_negociacion_porcentaje", ""),
                current_settings["precio_negociacion_porcentaje"],
            ),
            "retencion_porcentaje": normalize_percent_field(
                form.get("retencion_porcentaje", ""),
                current_settings["retencion_porcentaje"],
            ),
        }
    save_store(store)
    return entrega["parametros"]


def clear_parametros(entrega_id: str) -> dict[str, Any]:
    store = load_store()
    entrega = editable_entrega(store, entrega_id)
    entrega["parametros"] = {
        "mes_regalias": entrega.get("month", core.mes_actual_es()),
        "dolar": "",
        "oz_au": "",
        "oz_ag": "",
    }
    entrega.pop("boletin_settings", None)
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
    storage_error = persistence.write_block_reason()
    if storage_error:
        raise RuntimeError(storage_error)
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
    persistence.backup_state_or_raise(DATA_DIR)
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
    if sync_backup:
        storage_error = persistence.write_block_reason()
        if storage_error:
            raise RuntimeError(storage_error)
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
    settings = get_entrega_boletin_settings(entrega, store)
    try:
        delivery_date = date.fromisoformat(str(entrega.get("fecha", "")))
    except ValueError:
        delivery_date = date.today()
    rows = []
    for item in entrega.get("items", []):
        if item.get("ley_au") in ("", None) or item.get("ley_ag") in ("", None):
            continue
        rows.append(calculations.boletin_context(item, parametros, regalias, settings, current=delivery_date))
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
