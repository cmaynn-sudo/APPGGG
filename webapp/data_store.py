from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import calculations
import core
from template_catalog import WEBAPP_DIR


DATA_DIR = Path(os.environ.get("DATA_DIR", str(WEBAPP_DIR / "data")))
STORE_PATH = DATA_DIR / "recepcion_store.json"


def _empty_store() -> dict[str, Any]:
    return {
        "sociedades": core.read_sociedades(),
        "regalias": core.read_regalias(),
        "entregas": [],
        "active_entrega_id": "",
    }


def load_store() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        save_store(_empty_store())
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def save_store(store: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(STORE_PATH)


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


def create_entrega(numero: str) -> dict[str, Any]:
    if not numero.strip():
        raise ValueError("Ingresa un numero de entrega.")
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

    sociedad = get_sociedad(store, form.get("proveedor", ""))
    if not sociedad:
        raise ValueError("Selecciona una sociedad valida.")

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


def boletines_for_entrega(entrega: dict[str, Any]) -> list[dict[str, Any]]:
    store = load_store()
    parametros = entrega.get("parametros", {})
    regalias = get_regalias_for_month(store, parametros.get("mes_regalias", entrega.get("month", "")))
    rows = []
    for item in entrega.get("items", []):
        if item.get("ley_au") in ("", None) or item.get("ley_ag") in ("", None):
            continue
        rows.append(calculations.boletin_context(item, parametros, regalias))
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
