from __future__ import annotations

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


def dashboard_summary(requested_filters: dict[str, str] | None = None) -> dict[str, Any]:
    filters = {key: str(value or "").strip() for key, value in (requested_filters or {}).items()}
    store = data_store.load_store()
    folders = document_library.all_folders()
    records = structured_billing_records(store)
    read_errors = 0

    for record, parsed in historical_billing_records(folders):
        if not parsed:
            read_errors += 1
            continue
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
    for month in months:
        month["bar_percent"] = round(month["subtotal"] / max_subtotal * 100, 2) if max_subtotal else 0
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
            path = document_path(document)
            parsed = parse_billing_pdf(path) if path else None
            if not parsed:
                yield {}, False
                continue
            parsed.update(
                {
                    "source": source,
                    "source_label": "Carpeta subida" if source == "local" else "Histórico importado",
                    "folder_id": folder.get("id", ""),
                    "delivery_id": folder.get("id", ""),
                    "delivery_label": folder.get("name", "Entrega importada"),
                    "sociedad": parsed.get("sociedad", ""),
                }
            )
            if not parsed.get("date"):
                parsed["date"] = folder.get("date", "")
            parsed_date = parse_iso_date(parsed.get("date", ""))
            parsed["year"] = str(parsed_date.year if parsed_date else folder.get("year", ""))
            parsed["month_number"] = (
                parsed_date.month
                if parsed_date
                else MONTH_NUMBER.get(str(folder.get("month", "")).upper())
            )
            yield parsed, True


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
    text = re.sub(r"\s+", " ", text)
    if not text.strip():
        PDF_CACHE[cache_key] = None
        PDF_ERROR_CACHE[cache_key] = "El PDF no contiene texto extraíble; puede ser una imagen escaneada."
        return None, PDF_ERROR_CACHE[cache_key]

    received = re.search(
        r"PESO\s+RECIBIDO\s+PESO\s+FUNDIDO.*?([0-9][0-9.,]*)\s*G\s+([0-9][0-9.,]*)\s*G",
        text,
        flags=re.IGNORECASE,
    )
    subtotal = find_number(text, r"VALOR\s+TOTAL\s+METALES\s*\(COP\)\s*\$?\s*([0-9][0-9.,]*)")
    if not received or subtotal is None:
        PDF_CACHE[cache_key] = None
        if not received and subtotal is None:
            reason = "No se reconocieron los pesos ni el valor total; el formato del boletín es diferente."
        elif not received:
            reason = "No se reconocieron los pesos recibido y fundido del boletín."
        else:
            reason = "No se reconoció el valor total de metales del boletín."
        PDF_ERROR_CACHE[cache_key] = reason
        return None, reason

    raw_date = find_text(text, r"FECHA\s+DE\s+LIQUIDACI[ÓO]N:\s*(\d{1,2}/\d{1,2}/\d{4})")
    parsed_date = ""
    if raw_date:
        try:
            parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
        except ValueError:
            parsed_date = ""

    royalties = re.search(
        r"REGALIAS\s+ADEUDADAS\s+POR\s+EL\s+PROVEEDOR.*?ORO\s+PLATA\s+\$\s*([0-9][0-9.,]*)\s+\$\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    result = {
        "documento": find_text(text, r"DOCUMENTO:\s*([A-Z0-9Ñ._-]+)"),
        "sociedad": find_text(text, r"PROVEEDOR:\s*(.*?)\s+NIT:"),
        "date": parsed_date,
        "subtotal": subtotal,
        "valor_a_pagar": find_number(text, r"VALOR\s+A\s+PAGAR\s*\(COP\)\s*\$?\s*([0-9][0-9.,]*)") or 0.0,
        "regalia_oro": parse_number(royalties.group(1)) if royalties else 0.0,
        "regalia_plata": parse_number(royalties.group(2)) if royalties else 0.0,
        "valor_pagado": find_number(
            text,
            r"VALOR\s+(?:A\s+TRANSFERIR|PAGADO)\s*\$?\s*([0-9][0-9.,]*)",
        )
        or 0.0,
        "peso_inicial": parse_number(received.group(1)),
        "peso_final": parse_number(received.group(2)),
    }
    PDF_CACHE[cache_key] = result
    PDF_ERROR_CACHE[cache_key] = ""
    return result, ""


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
    return {
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


def format_summary(summary: dict[str, Any]) -> None:
    for key in ("subtotal", "valor_a_pagar", "regalia_oro", "regalia_plata", "valor_pagado"):
        summary[f"{key}_display"] = calculations.fmt_money(summary.get(key, 0.0))
    summary["peso_inicial_display"] = calculations.fmt_number(summary.get("peso_inicial", 0.0))
    summary["peso_final_display"] = calculations.fmt_number(summary.get("peso_final", 0.0))
