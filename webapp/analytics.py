from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

import calculations
import core
import data_store
import document_library


PDF_CACHE: dict[tuple[str, int, int], dict[str, Any] | None] = {}
PDF_ERROR_CACHE: dict[tuple[str, int, int], str] = {}
MONTH_NUMBER = {name: number for number, name in core.MESES_ES.items()}
DASHBOARD_FIELDS = (
    "documento",
    "sociedad",
    "date",
    "subtotal",
    "valor_a_pagar",
    "regalia_oro",
    "regalia_plata",
    "valor_pagado",
    "peso_inicial",
    "peso_final",
)
DASHBOARD_NUMBER_FIELDS = DASHBOARD_FIELDS[3:]
CERTIFICATE_FIELDS = ("nit", "finos_oro", "finos_plata")
QUALITY_FIELDS = DASHBOARD_FIELDS + CERTIFICATE_FIELDS
QUALITY_NUMBER_FIELDS = DASHBOARD_NUMBER_FIELDS + ("finos_oro", "finos_plata")
DASHBOARD_FIELD_LABELS = {
    "documento": "Documento",
    "sociedad": "Proveedor",
    "date": "Fecha",
    "subtotal": "Subtotal",
    "valor_a_pagar": "Valor a pagar",
    "regalia_oro": "Regalías oro",
    "regalia_plata": "Regalías plata",
    "valor_pagado": "Valor pagado",
    "peso_inicial": "Gramos iniciales",
    "peso_final": "Gramos finales",
    "nit": "NIT",
    "finos_oro": "Finos de oro",
    "finos_plata": "Finos de plata",
}


def dashboard_summary(requested_filters: dict[str, str] | None = None) -> dict[str, Any]:
    filters = {key: str(value or "").strip() for key, value in (requested_filters or {}).items()}
    store = data_store.load_store()
    folders = document_library.all_folders()
    records = structured_billing_records(store)
    read_errors = 0
    incomplete_records = 0

    for record, parsed in historical_billing_records(folders):
        if not parsed:
            read_errors += 1
            continue
        if record.get("_missing_fields"):
            incomplete_records += 1
        records.append(record)

    current_year = str(date.today().year)
    years = sorted({str(record.get("year")) for record in records if record.get("year")}, reverse=True)
    selected_year = filters.get("year", "")
    if selected_year not in years:
        selected_year = current_year if current_year in years else (years[0] if years else current_year)
    if selected_year not in years:
        years.insert(0, selected_year)

    year_records = [record for record in records if str(record.get("year")) == selected_year]
    delivery_options = unique_options(year_records, "delivery_id", "delivery_label")
    provider_options = sorted(
        {str(record.get("sociedad", "")).strip() for record in year_records if str(record.get("sociedad", "")).strip()}
    )

    selected_month = filters.get("month", "")
    if selected_month not in {str(number) for number in core.MESES_ES}:
        selected_month = ""
    selected_delivery = filters.get("entrega", "")
    if selected_delivery not in {option["value"] for option in delivery_options}:
        selected_delivery = ""
    selected_provider = filters.get("proveedor", "")
    if selected_provider not in provider_options:
        selected_provider = ""

    selected = list(year_records)
    if selected_month:
        selected = [record for record in selected if record.get("month_number") == int(selected_month)]
    if selected_delivery:
        selected = [record for record in selected if str(record.get("delivery_id", "")) == selected_delivery]
    if selected_provider:
        selected = [record for record in selected if str(record.get("sociedad", "")) == selected_provider]
    selected = unique_records(selected)

    month_numbers = [int(selected_month)] if selected_month else list(core.MESES_ES)
    months = []
    for number in month_numbers:
        rows = [record for record in selected if record.get("month_number") == number]
        summary = summarize_rows(rows)
        summary.update({"number": number, "name": core.MESES_ES[number].capitalize()})
        months.append(summary)

    totals = summarize_rows(selected)
    max_subtotal = max((month["subtotal"] for month in months), default=0.0)
    max_weight = max(
        (max(month["peso_inicial"], month["peso_final"]) for month in months),
        default=0.0,
    )
    for month in months:
        month["subtotal_bar_percent"] = (
            round(month["subtotal"] / max_subtotal * 100, 2) if max_subtotal else 0
        )
        month["peso_inicial_bar_percent"] = (
            round(month["peso_inicial"] / max_weight * 100, 2) if max_weight else 0
        )
        month["peso_final_bar_percent"] = (
            round(month["peso_final"] / max_weight * 100, 2) if max_weight else 0
        )
        month["bar_percent"] = month["subtotal_bar_percent"]
        format_summary(month)
    format_summary(totals)

    recent = sorted(selected, key=lambda row: (row.get("date", ""), row.get("documento", "")), reverse=True)[:6]
    for record in recent:
        record["subtotal_display"] = calculations.fmt_money(record.get("subtotal", 0.0))
        record["valor_pagado_display"] = calculations.fmt_money(record.get("valor_pagado", 0.0))
        record["peso_final_display"] = calculations.fmt_number(record.get("peso_final", 0.0))

    active_filter_count = sum(bool(value) for value in (selected_month, selected_delivery, selected_provider))
    return {
        "year": selected_year,
        "years": years,
        "months": months,
        "month_options": [
            {"value": str(number), "label": month_name.capitalize()}
            for number, month_name in core.MESES_ES.items()
        ],
        "delivery_options": delivery_options,
        "provider_options": provider_options,
        "filters": {
            "year": selected_year,
            "month": selected_month,
            "entrega": selected_delivery,
            "proveedor": selected_provider,
        },
        "active_filter_count": active_filter_count,
        "totals": totals,
        "records": selected,
        "recent": recent,
        "read_errors": read_errors,
        "incomplete_records": incomplete_records,
        "quality_issue_count": read_errors + incomplete_records,
        "has_historical": any(record.get("source") != "web" for record in selected),
    }


def structured_billing_records(store: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for entrega in store.get("entregas", []):
        settings = data_store.get_entrega_boletin_settings(entrega, store)
        parametros = entrega.get("parametros", {})
        regalias = data_store.get_regalias_for_month(
            store,
            parametros.get("mes_regalias", entrega.get("month", "")),
        )
        delivery_date = parse_iso_date(entrega.get("fecha", ""))
        year = str(entrega.get("year") or (delivery_date.year if delivery_date else ""))
        month_number = MONTH_NUMBER.get(str(entrega.get("month", "")).upper())
        if not month_number and delivery_date:
            month_number = delivery_date.month

        for item in entrega.get("items", []):
            if item.get("ley_au") in ("", None) or item.get("ley_ag") in ("", None):
                continue
            boletin = calculations.boletin_context(item, parametros, regalias, settings, current=delivery_date)
            records.append(
                {
                    "source": "web",
                    "source_label": "Web",
                    "folder_id": entrega.get("id", ""),
                    "delivery_id": entrega.get("id", ""),
                    "delivery_label": entrega.get("name") or f"Entrega {entrega.get('numero', '')}",
                    "documento": item.get("barra") or item.get("codigo", ""),
                    "sociedad": item.get("sociedad") or item.get("proveedor", ""),
                    "date": entrega.get("fecha", ""),
                    "year": year,
                    "month_number": month_number,
                    "subtotal": calculations.as_float(boletin.get("valor_total_metales_value")),
                    "valor_a_pagar": calculations.as_float(boletin.get("valor_a_pagar_value")),
                    "regalia_oro": calculations.as_float(boletin.get("regalia_oro_total_value")),
                    "regalia_plata": calculations.as_float(boletin.get("regalia_plata_total_value")),
                    "valor_pagado": calculations.as_float(boletin.get("valor_transferir_value")),
                    "peso_inicial": calculations.as_float(boletin.get("peso_ini_value")),
                    "peso_final": calculations.as_float(boletin.get("peso_fin_value")),
                }
            )
    return records


def historical_billing_records(folders: list[dict[str, Any]]):
    store = data_store.load_store()
    overrides = store.get("dashboard_overrides", {})
    for folder in folders:
        source = folder.get("source")
        if source not in {"local", "imported"}:
            continue
        detail_source = "importadas" if source == "imported" else "local"
        detail = document_library.folder_detail(detail_source, folder.get("id", ""))
        if not detail:
            continue
        for document in detail.get("docs", []):
            name = str(document.get("name", ""))
            if document.get("category") != "Boletines" and not name.upper().startswith("BOLETIN"):
                continue
            if not name.lower().endswith(".pdf"):
                continue
            path = document_path(document)
            parsed = parse_billing_pdf(path) if path else None
            quality_id = dashboard_quality_id(document, folder)
            override = overrides.get(quality_id, {}) if isinstance(overrides, dict) else {}
            if not parsed:
                inferred_code = document_code_from_name(name)
                fallback_date = folder.get("date", "")
                parsed = {
                    "documento": inferred_code,
                    "sociedad": "",
                    "date": fallback_date,
                    **{field: 0.0 for field in DASHBOARD_NUMBER_FIELDS},
                    "_missing_fields": [
                        field
                        for field in DASHBOARD_FIELDS
                        if not (field == "documento" and inferred_code)
                        and not (field == "date" and fallback_date)
                    ],
                }
                parsed = apply_dashboard_override(parsed, override)
                if not manual_dashboard_record_ready(parsed):
                    yield {}, False
                    continue
            else:
                parsed = apply_dashboard_override(dict(parsed), override)
            parsed.update(
                {
                    "source": source,
                    "source_label": "Carpeta subida" if source == "local" else "Histórico importado",
                    "folder_id": folder.get("id", ""),
                    "delivery_id": folder.get("id", ""),
                    "delivery_label": folder.get("name", "Entrega importada"),
                    "sociedad": parsed.get("sociedad", ""),
                    "_quality_id": quality_id,
                    "_view_url": document.get("view_url", ""),
                }
            )
            if not parsed.get("date"):
                parsed["date"] = folder.get("date", "")
                if parsed["date"]:
                    parsed["_missing_fields"] = [
                        field for field in parsed.get("_missing_fields", []) if field != "date"
                    ]
            parsed_date = parse_iso_date(parsed.get("date", ""))
            parsed["year"] = str(parsed_date.year if parsed_date else folder.get("year", ""))
            parsed["month_number"] = (
                parsed_date.month
                if parsed_date
                else MONTH_NUMBER.get(str(folder.get("month", "")).upper())
            )
            yield parsed, True


def dashboard_quality_id(document: dict[str, Any], folder: dict[str, Any]) -> str:
    kind = str(document.get("kind") or folder.get("source") or "historical").strip().lower()
    document_id = str(document.get("id", "")).strip()
    if document_id:
        return f"{kind}:{document_id}"
    identity = "|".join(
        (
            str(folder.get("id", "")),
            str(document.get("display_path") or document.get("name") or ""),
        )
    )
    return f"{kind}:{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:24]}"


def document_code_from_name(name: str) -> str:
    match = re.search(r"BOLET[IÍ]N\s*-?\s*([A-Z0-9Ñ._-]+)", str(name or ""), flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def apply_dashboard_override(record: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(record)
    values = (override or {}).get("values", {})
    if not isinstance(values, dict):
        values = {}
    applied = set()
    for field in QUALITY_FIELDS:
        if field not in values or values[field] in (None, ""):
            continue
        result[field] = values[field]
        applied.add(field)
    result["_missing_fields"] = [
        field for field in result.get("_missing_fields", []) if field not in applied
    ]
    result["_certificate_missing_fields"] = [
        field for field in result.get("_certificate_missing_fields", []) if field not in applied
    ]
    result["_manual_override"] = bool(applied)
    return result


def manual_dashboard_record_ready(record: dict[str, Any]) -> bool:
    if not parse_iso_date(record.get("date", "")):
        return False
    return not any(field in set(record.get("_missing_fields", [])) for field in DASHBOARD_NUMBER_FIELDS)


def dashboard_data_quality(
    folders: list[dict[str, Any]] | None = None,
    store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    folders = folders if folders is not None else document_library.all_folders()
    store = store or data_store.load_store()
    overrides = store.get("dashboard_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}

    items = []
    scanned = 0
    readable = 0
    incomplete = 0
    unreadable = 0
    corrected = 0

    for folder in folders:
        source = folder.get("source")
        if source not in {"local", "imported"}:
            continue
        detail_source = "importadas" if source == "imported" else "local"
        detail = document_library.folder_detail(detail_source, folder.get("id", ""))
        if not detail:
            continue
        for document in detail.get("docs", []):
            name = str(document.get("name", ""))
            if document.get("category") != "Boletines" and not name.upper().startswith("BOLETIN"):
                continue
            if not name.lower().endswith(".pdf"):
                continue

            scanned += 1
            quality_id = dashboard_quality_id(document, folder)
            override = overrides.get(quality_id, {})
            path = document_path(document)
            parsed, reason = inspect_billing_pdf(path) if path else (
                None,
                "El archivo no está disponible en el almacenamiento.",
            )
            if parsed:
                readable += 1
                record = dict(parsed)
            else:
                unreadable += 1
                inferred_code = document_code_from_name(name)
                record = {
                    "documento": inferred_code,
                    "sociedad": "",
                    "nit": "",
                    "date": "",
                    **{field: 0.0 for field in QUALITY_NUMBER_FIELDS},
                    "_missing_fields": [
                        field for field in DASHBOARD_FIELDS if not (field == "documento" and inferred_code)
                    ],
                    "_certificate_missing_fields": list(CERTIFICATE_FIELDS),
                }

            if not record.get("date") and folder.get("date"):
                record["date"] = folder.get("date", "")
                record["_missing_fields"] = [
                    field for field in record.get("_missing_fields", []) if field != "date"
                ]
                record["_certificate_missing_fields"] = [
                    field for field in record.get("_certificate_missing_fields", []) if field != "date"
                ]
            record = apply_dashboard_override(record, override)
            missing_fields = list(
                dict.fromkeys(
                    record.get("_missing_fields", [])
                    + record.get("_certificate_missing_fields", [])
                )
            )
            has_override = bool(override and override.get("values"))
            if parsed and missing_fields:
                incomplete += 1
            if has_override and not missing_fields:
                corrected += 1
            if not missing_fields and not has_override:
                continue

            display_values = {
                field: (
                    ""
                    if field in missing_fields
                    else calculations.fmt_number(record.get(field, ""), places=2)
                    if field in QUALITY_NUMBER_FIELDS
                    else record.get(field, "")
                )
                for field in QUALITY_FIELDS
            }
            items.append(
                {
                    "quality_id": quality_id,
                    "document_name": name,
                    "folder_name": folder.get("name", "Entrega histórica"),
                    "folder_href": folder.get("href", ""),
                    "view_url": document.get("view_url", ""),
                    "download_url": document.get("download_url", ""),
                    "values": display_values,
                    "missing_fields": missing_fields,
                    "missing_labels": [DASHBOARD_FIELD_LABELS[field] for field in missing_fields],
                    "reason": reason,
                    "readable": bool(parsed),
                    "corrected": has_override,
                    "complete": not missing_fields,
                    "updated_at": override.get("updated_at", "") if isinstance(override, dict) else "",
                }
            )

    pending = sum(not item["complete"] for item in items)
    items.sort(key=lambda item: (item["complete"], item["folder_name"], item["document_name"]))
    return {
        "scanned": scanned,
        "readable": readable,
        "incomplete": incomplete,
        "unreadable": unreadable,
        "corrected": corrected,
        "pending": pending,
        "items": items,
    }


def historical_pdf_diagnostics(
    folders: list[dict[str, Any]] | None = None,
    store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    folders = folders if folders is not None else document_library.all_folders()
    store = store or data_store.load_store()
    reconstructed = {
        str(entrega.get("reconstructed_from_folder_id", "")): entrega
        for entrega in store.get("entregas", [])
        if str(entrega.get("reconstructed_from_folder_id", ""))
    }
    groups = []
    scanned = 0
    readable = 0

    for folder in folders:
        source = folder.get("source")
        if source not in {"local", "imported"}:
            continue
        detail_source = "importadas" if source == "imported" else "local"
        detail = document_library.folder_detail(detail_source, folder.get("id", ""))
        if not detail:
            continue
        issues = []
        for document in detail.get("docs", []):
            name = str(document.get("name", ""))
            if document.get("category") != "Boletines" and not name.upper().startswith("BOLETIN"):
                continue
            if not name.lower().endswith(".pdf"):
                continue
            scanned += 1
            path = document_path(document)
            parsed, reason = inspect_billing_pdf(path) if path else (None, "El archivo no está disponible en el almacenamiento.")
            if parsed:
                readable += 1
                continue
            issues.append(
                {
                    "id": document.get("id", ""),
                    "name": name,
                    "reason": reason,
                    "view_url": document.get("view_url", ""),
                    "download_url": document.get("download_url", ""),
                }
            )
        if not issues:
            continue

        folder_id = str(folder.get("id", ""))
        linked = reconstructed.get(folder_id)
        folder_data = folder.get("folder") or {}
        delivery_number = str(folder_data.get("delivery_number", ""))
        if not delivery_number:
            match = re.search(r"ENTREGA\s*[°º#Nn.]*\s*(\d+)", str(folder.get("name", "")), re.IGNORECASE)
            delivery_number = match.group(1) if match else ""
        groups.append(
            {
                "folder_id": folder_id,
                "folder_name": folder.get("name", "Entrega histórica"),
                "folder_href": folder.get("href", ""),
                "date": folder.get("date", ""),
                "year": folder.get("year", ""),
                "month": folder.get("month", ""),
                "delivery_number": delivery_number,
                "documents": issues,
                "reconstructed": bool(linked),
                "web_delivery_id": linked.get("id", "") if linked else "",
                "web_delivery_name": linked.get("name", "") if linked else "",
            }
        )

    unreadable = sum(len(group["documents"]) for group in groups)
    return {
        "scanned": scanned,
        "readable": readable,
        "unreadable": unreadable,
        "pending_groups": sum(not group["reconstructed"] for group in groups),
        "groups": groups,
    }


def document_path(document: dict[str, Any]) -> Path | None:
    kind = document.get("kind")
    if kind == "uploaded":
        _file, path = data_store.find_uploaded_file(document.get("id", ""))
        return path
    if kind == "imported":
        _file, path = document_library.find_imported_file(document.get("id", ""))
        return path
    return None


def parse_billing_pdf(path: Path) -> dict[str, Any] | None:
    result, _reason = inspect_billing_pdf(path)
    return result


def inspect_billing_pdf(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        stat = path.stat()
    except OSError:
        return None, "El archivo no está disponible en el almacenamiento."
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
    if cache_key in PDF_CACHE:
        return PDF_CACHE[cache_key], PDF_ERROR_CACHE.get(cache_key, "")

    try:
        text = " ".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    except Exception as exc:
        PDF_CACHE[cache_key] = None
        PDF_ERROR_CACHE[cache_key] = f"El PDF está dañado, protegido o no se puede abrir ({type(exc).__name__})."
        return None, PDF_ERROR_CACHE[cache_key]
    result, reason = parse_billing_text(text)
    if not result:
        PDF_CACHE[cache_key] = None
        PDF_ERROR_CACHE[cache_key] = reason
        return None, reason

    PDF_CACHE[cache_key] = result
    PDF_ERROR_CACHE[cache_key] = ""
    return result, ""


def parse_billing_text(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    text = re.sub(r"\s+", " ", str(raw_text or ""))
    if not text.strip():
        return None, "El PDF no contiene texto extraíble; puede ser una imagen escaneada."

    received = re.search(
        r"PESO\s+RECIBIDO\s+PESO\s+FUNDIDO.*?([0-9][0-9.,]*)\s*G\s+([0-9][0-9.,]*)\s*G",
        text,
        flags=re.IGNORECASE,
    )
    if not received:
        received = re.search(
            r"PESO\s+RECIBIDO\s+([0-9][0-9.,]*)\s*G\s+PESO\s+FUNDIDO\s+([0-9][0-9.,]*)\s*G",
            text,
            flags=re.IGNORECASE,
        )
    web_totals = re.search(
        r"VALOR\s+TOTAL\s+METALES\s*\(COP\)\s+RETEFUENTE\s*\(COP\)\s+VALOR\s+A\s+PAGAR\s*\(COP\)\s*\$?\s*([0-9][0-9.,]*)\s*\$?\s*-?[0-9][0-9.,]*\s*\$?\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    subtotal = find_number(text, r"VALOR\s+TOTAL(?:\s+DE)?\s+METALES\s*\(COP\)\s*\$?\s*([0-9][0-9.,]*)")
    if subtotal is None and web_totals:
        subtotal = parse_number(web_totals.group(1))
    if not received or subtotal is None:
        if not received and subtotal is None:
            reason = "No se reconocieron los pesos ni el valor total; el formato del boletín es diferente."
        elif not received:
            reason = "No se reconocieron los pesos recibido y fundido del boletín."
        else:
            reason = "No se reconoció el valor total de metales del boletín."
        return None, reason

    raw_date = find_text(
        text,
        r"FECHA\s+DE\s+LIQUIDACI[ÓO]N\s*:\s*([0-9]{1,4}[/-][0-9]{1,2}[/-][0-9]{1,4})",
    )
    parsed_date = parse_document_date(raw_date)

    royalties = re.search(
        r"REGAL[IÍ](?:A|ZA)S\s+ADEUDADAS\s+POR\s+EL\s+PROVEEDOR.*?ORO\s+PLATA\s+\$\s*([0-9][0-9.,]*)\s+\$\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    web_royalties = re.search(
        r"REGAL[IÍ]AS\s+ADEUDADAS\s+POR\s+EL\s+PROVEEDOR.*?ORO\s+PLATA\s*\$?\s*[0-9][0-9.,]*\s*\$?\s*[0-9][0-9.,]*\s*\$\s*([0-9][0-9.,]*)\s*\$\s*([0-9][0-9.,]*)\s+VALOR\s+A\s+TRANSFERIR",
        text,
        flags=re.IGNORECASE,
    )
    if web_royalties:
        royalties = web_royalties
    documento = find_text(text, r"DOCUMENTO:\s*([A-Z0-9Ñ._-]+)")
    sociedad = find_text(text, r"PROVEEDOR:\s*(.*?)\s+NIT:")
    nits = re.findall(r"\bNIT\s*:\s*([0-9][0-9.\-]+)", text, flags=re.IGNORECASE)
    provider_nit = nits[-1] if nits else ""
    fine_values = re.search(
        r"FINO\s*\(\s*G\s*\)\s*\$?\s*([0-9][0-9.,]*)\s+\$?\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    web_metals = re.search(
        r"VALOR\s+METAL\s*\(COP\)\s+ORO\s+[0-9][0-9.,]*\s+([0-9][0-9.,]*)\s*\$\s*[0-9][0-9.,]*\s*\$\s*[0-9][0-9.,]*\s+PLATA\s+[0-9][0-9.,]*\s+([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    if not fine_values and web_metals:
        fine_values = web_metals
    law_values = re.search(
        r"LEY\s*%\s*\$?\s*([0-9][0-9.,]*)\s+\$?\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    peso_final = parse_number(received.group(2))
    if fine_values:
        finos_oro = parse_number(fine_values.group(1))
        finos_plata = parse_number(fine_values.group(2))
    elif law_values:
        finos_oro = calculations.excel_round(peso_final * parse_number(law_values.group(1)) / 1000, 2)
        finos_plata = calculations.excel_round(peso_final * parse_number(law_values.group(2)) / 1000, 2)
    else:
        finos_oro = None
        finos_plata = None
    valor_a_pagar = find_number(text, r"VALOR\s+A\s+PAGAR\s*\(COP\)\s*\$?\s*([0-9][0-9.,]*)")
    if web_totals:
        valor_a_pagar = parse_number(web_totals.group(2))
    valor_pagado = find_number(
        text,
        r"VALOR\s+(?:A\s+TRANSFERIR|PAGADO)\s*(?:\(COP\))?\s*\$?\s*([0-9][0-9.,]*)",
    )
    result = {
        "documento": documento,
        "sociedad": sociedad,
        "nit": provider_nit,
        "date": parsed_date,
        "subtotal": subtotal,
        "valor_a_pagar": valor_a_pagar if valor_a_pagar is not None else 0.0,
        "regalia_oro": parse_number(royalties.group(1)) if royalties else 0.0,
        "regalia_plata": parse_number(royalties.group(2)) if royalties else 0.0,
        "valor_pagado": valor_pagado if valor_pagado is not None else 0.0,
        "peso_inicial": parse_number(received.group(1)),
        "peso_final": peso_final,
        "finos_oro": finos_oro,
        "finos_plata": finos_plata,
    }
    missing_fields = []
    if not documento:
        missing_fields.append("documento")
    if not sociedad:
        missing_fields.append("sociedad")
    if not parsed_date:
        missing_fields.append("date")
    if valor_a_pagar is None:
        missing_fields.append("valor_a_pagar")
    if not royalties:
        missing_fields.extend(("regalia_oro", "regalia_plata"))
    if valor_pagado is None:
        missing_fields.append("valor_pagado")
    result["_missing_fields"] = missing_fields
    result["_certificate_missing_fields"] = [
        field
        for field, value in (
            ("documento", documento),
            ("sociedad", sociedad),
            ("nit", provider_nit),
            ("date", parsed_date),
            ("finos_oro", finos_oro),
            ("finos_plata", finos_plata),
            ("regalia_oro", result["regalia_oro"] if royalties else None),
            ("regalia_plata", result["regalia_plata"] if royalties else None),
        )
        if value in (None, "")
    ]
    return result, ""


def parse_document_date(raw: str) -> str:
    value = str(raw or "").strip()
    for format_string in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, format_string).date().isoformat()
        except ValueError:
            continue
    return ""


def historical_certificate_records(
    folders: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
):
    store = store or data_store.load_store()
    overrides = store.get("dashboard_overrides", {})
    societies = store.get("sociedades", [])
    for folder in folders:
        source = folder.get("source")
        if source not in {"local", "imported"}:
            continue
        detail_source = "importadas" if source == "imported" else "local"
        detail = document_library.folder_detail(detail_source, folder.get("id", ""))
        if not detail:
            continue
        for document in detail.get("docs", []):
            name = str(document.get("name", ""))
            if document.get("category") != "Boletines" and not name.upper().startswith("BOLETIN"):
                continue
            if not name.lower().endswith(".pdf"):
                continue
            path = document_path(document)
            quality_id = dashboard_quality_id(document, folder)
            override = overrides.get(quality_id, {}) if isinstance(overrides, dict) else {}
            parsed = parse_billing_pdf(path) if path else None
            if parsed:
                parsed = dict(parsed)
            else:
                inferred_code = document_code_from_name(name)
                fallback_date = str(folder.get("date", ""))
                parsed = {
                    "documento": inferred_code,
                    "sociedad": "",
                    "nit": "",
                    "date": fallback_date,
                    "finos_oro": 0.0,
                    "finos_plata": 0.0,
                    "regalia_oro": 0.0,
                    "regalia_plata": 0.0,
                    "_certificate_missing_fields": [
                        field
                        for field in (
                            "documento",
                            "sociedad",
                            "nit",
                            "date",
                            "finos_oro",
                            "finos_plata",
                            "regalia_oro",
                            "regalia_plata",
                        )
                        if not (field == "documento" and inferred_code)
                        and not (field == "date" and fallback_date)
                    ],
                }
            parsed = apply_dashboard_override(dict(parsed), override)
            parsed["documento"] = parsed.get("documento") or document_code_from_name(name)
            parsed["date"] = parsed.get("date") or folder.get("date", "")

            society = matching_society(parsed, societies)
            society_name = parsed.get("sociedad") or (society or {}).get("sociedad", "")
            if not society_name:
                continue
            if not parsed.get("nit") and society:
                parsed["nit"] = society.get("nit", "")
            recovered_fields = {
                field
                for field in ("documento", "sociedad", "nit", "date")
                if (
                    bool(society_name)
                    if field == "sociedad"
                    else parsed.get(field) not in (None, "")
                )
            }
            certificate_missing = [
                field
                for field in parsed.get("_certificate_missing_fields", [])
                if field not in recovered_fields
            ]
            if certificate_missing:
                continue
            parsed_date = parse_iso_date(parsed.get("date", ""))
            record_year = str(parsed_date.year if parsed_date else folder.get("year", ""))
            record_month = str(folder.get("month", "")).strip().upper()
            if not record_month and parsed_date:
                record_month = core.MESES_ES[parsed_date.month]
            yield {
                "source": source,
                "sociedad": society_name,
                "nit": parsed.get("nit", ""),
                "documento": parsed.get("documento", ""),
                "fecha": parsed.get("date", ""),
                "year": record_year,
                "mes": record_month,
                "finos_oro": parsed.get("finos_oro", 0.0),
                "finos_plata": parsed.get("finos_plata", 0.0),
                "regalia_oro": parsed.get("regalia_oro", 0.0),
                "regalia_plata": parsed.get("regalia_plata", 0.0),
                "certificate_missing_fields": [],
            }


def matching_society(parsed: dict[str, Any], societies: list[dict[str, Any]]) -> dict[str, Any] | None:
    name = normalize_identity(parsed.get("sociedad", ""))
    document_code = normalize_identity(str(parsed.get("documento", "")).split("-", 1)[0])
    for society in societies:
        if name and normalize_identity(society.get("sociedad", "")) == name:
            return society
    for society in societies:
        code = normalize_identity(str(society.get("codigo", "")).split("-", 1)[0])
        if code and document_code == code:
            return society
    return None


def normalize_identity(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def find_text(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def find_number(text: str, pattern: str) -> float | None:
    raw = find_text(text, pattern)
    return parse_number(raw) if raw else None


def parse_number(raw: str) -> float:
    try:
        return core.parse_decimal_input(raw)
    except ValueError:
        return 0.0


def parse_iso_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def record_key(record: dict[str, Any]) -> tuple[str, str, int, int, int]:
    return (
        str(record.get("documento", "")).strip().upper(),
        str(record.get("date", "")),
        round(calculations.as_float(record.get("subtotal"))),
        round(calculations.as_float(record.get("peso_inicial")) * 100),
        round(calculations.as_float(record.get("peso_final")) * 100),
    )


def unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    known = set()
    for record in records:
        key = record_key(record)
        if key in known:
            continue
        known.add(key)
        rows.append(record)
    return rows


def unique_options(records: list[dict[str, Any]], value_key: str, label_key: str) -> list[dict[str, str]]:
    options: dict[str, str] = {}
    for record in records:
        value = str(record.get(value_key, "")).strip()
        if not value:
            continue
        options[value] = str(record.get(label_key, "")).strip() or value
    return [
        {"value": value, "label": label}
        for value, label in sorted(options.items(), key=lambda item: item[1], reverse=True)
    ]


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "subtotal": sum(record.get("subtotal", 0.0) for record in rows),
        "valor_a_pagar": sum(record.get("valor_a_pagar", 0.0) for record in rows),
        "regalia_oro": sum(record.get("regalia_oro", 0.0) for record in rows),
        "regalia_plata": sum(record.get("regalia_plata", 0.0) for record in rows),
        "valor_pagado": sum(record.get("valor_pagado", 0.0) for record in rows),
        "peso_inicial": sum(record.get("peso_inicial", 0.0) for record in rows),
        "peso_final": sum(record.get("peso_final", 0.0) for record in rows),
        "boletines": len(rows),
        "entregas": len({record.get("delivery_id") for record in rows if record.get("delivery_id")}),
    }
    summary["peso_diferencia"] = summary["peso_final"] - summary["peso_inicial"]
    summary["peso_diferencia_porcentaje"] = (
        summary["peso_diferencia"] / summary["peso_inicial"]
        if summary["peso_inicial"]
        else 0.0
    )
    return summary


def format_summary(summary: dict[str, Any]) -> None:
    for key in ("subtotal", "valor_a_pagar", "regalia_oro", "regalia_plata", "valor_pagado"):
        summary[f"{key}_display"] = calculations.fmt_money(summary.get(key, 0.0))
    summary["peso_inicial_display"] = calculations.fmt_number(summary.get("peso_inicial", 0.0))
    summary["peso_final_display"] = calculations.fmt_number(summary.get("peso_final", 0.0))
    difference = calculations.as_float(summary.get("peso_diferencia", 0.0))
    percentage = calculations.as_float(summary.get("peso_diferencia_porcentaje", 0.0))
    difference_display = calculations.fmt_number(difference)
    percentage_display = calculations.fmt_percent(percentage)
    summary["peso_diferencia_display"] = f"+{difference_display}" if difference > 0 else difference_display
    summary["peso_diferencia_porcentaje_display"] = (
        f"+{percentage_display}" if percentage > 0 else percentage_display
    )
    summary["peso_diferencia_descripcion"] = (
        "más que el peso inicial"
        if difference > 0
        else "menos que el peso inicial"
        if difference < 0
        else "sin variación"
    )
