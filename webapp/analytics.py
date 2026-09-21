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
MONTH_NUMBER = {name: number for number, name in core.MESES_ES.items()}


def dashboard_summary(requested_year: str = "") -> dict[str, Any]:
    store = data_store.load_store()
    folders = document_library.all_folders()
    records = structured_billing_records(store)
    read_errors = 0

    known_keys = {record_key(record) for record in records}
    for record, parsed in historical_billing_records(folders):
        if not parsed:
            read_errors += 1
            continue
        key = record_key(record)
        if key in known_keys:
            continue
        known_keys.add(key)
        records.append(record)

    current_year = str(date.today().year)
    years = sorted({str(record.get("year")) for record in records if record.get("year")}, reverse=True)
    selected_year = requested_year if requested_year in years else current_year if current_year in years else (years[0] if years else current_year)
    if selected_year not in years:
        years.insert(0, selected_year)

    selected = [record for record in records if str(record.get("year")) == selected_year]
    months = []
    for number, month_name in core.MESES_ES.items():
        rows = [record for record in selected if record.get("month_number") == number]
        months.append(
            {
                "number": number,
                "name": month_name.capitalize(),
                "facturacion": sum(record.get("facturacion", 0.0) for record in rows),
                "transferido": sum(record.get("transferido", 0.0) for record in rows),
                "peso_inicial": sum(record.get("peso_inicial", 0.0) for record in rows),
                "peso_final": sum(record.get("peso_final", 0.0) for record in rows),
                "boletines": len(rows),
            }
        )

    totals = summarize_rows(selected)
    max_facturacion = max((month["facturacion"] for month in months), default=0.0)
    for month in months:
        month["bar_percent"] = round(month["facturacion"] / max_facturacion * 100, 2) if max_facturacion else 0
        format_summary(month)
    format_summary(totals)

    recent = sorted(selected, key=lambda row: (row.get("date", ""), row.get("documento", "")), reverse=True)[:6]
    for record in recent:
        record["facturacion_display"] = calculations.fmt_money(record.get("facturacion", 0.0))
        record["peso_final_display"] = calculations.fmt_number(record.get("peso_final", 0.0))

    return {
        "year": selected_year,
        "years": years,
        "months": months,
        "totals": totals,
        "records": selected,
        "recent": recent,
        "read_errors": read_errors,
        "has_historical": any(record.get("source") != "web" for record in selected),
    }


def structured_billing_records(store: dict[str, Any]) -> list[dict[str, Any]]:
    settings = data_store.get_boletin_settings(store)
    records = []
    for entrega in store.get("entregas", []):
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
                    "documento": item.get("barra") or item.get("codigo", ""),
                    "sociedad": item.get("sociedad") or item.get("proveedor", ""),
                    "date": entrega.get("fecha", ""),
                    "year": year,
                    "month_number": month_number,
                    "facturacion": calculations.as_float(boletin.get("valor_total_metales_value")),
                    "transferido": calculations.as_float(boletin.get("valor_transferir_value")),
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
                    "sociedad": parsed.get("sociedad", ""),
                }
            )
            if not parsed.get("date"):
                parsed["date"] = folder.get("date", "")
            parsed_date = parse_iso_date(parsed.get("date", ""))
            parsed["year"] = str(parsed_date.year if parsed_date else folder.get("year", ""))
            parsed["month_number"] = parsed_date.month if parsed_date else MONTH_NUMBER.get(str(folder.get("month", "")).upper())
            yield parsed, True


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
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
    if cache_key in PDF_CACHE:
        return PDF_CACHE[cache_key]

    try:
        text = " ".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    except Exception:
        PDF_CACHE[cache_key] = None
        return None
    text = re.sub(r"\s+", " ", text)

    received = re.search(
        r"PESO\s+RECIBIDO\s+PESO\s+FUNDIDO.*?([0-9][0-9.,]*)\s*G\s+([0-9][0-9.,]*)\s*G",
        text,
        flags=re.IGNORECASE,
    )
    billed = find_number(text, r"VALOR\s+TOTAL\s+METALES\s*\(COP\)\s*\$?\s*([0-9][0-9.,]*)")
    if not received or billed is None:
        PDF_CACHE[cache_key] = None
        return None

    raw_date = find_text(text, r"FECHA\s+DE\s+LIQUIDACI[ÓO]N:\s*(\d{1,2}/\d{1,2}/\d{4})")
    parsed_date = ""
    if raw_date:
        try:
            parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
        except ValueError:
            parsed_date = ""
    result = {
        "documento": find_text(text, r"DOCUMENTO:\s*([A-Z0-9Ñ._-]+)"),
        "sociedad": find_text(text, r"PROVEEDOR:\s*(.*?)\s+NIT:"),
        "date": parsed_date,
        "facturacion": billed,
        "transferido": find_number(text, r"VALOR\s+A\s+TRANSFERIR\s*\$?\s*([0-9][0-9.,]*)") or 0.0,
        "peso_inicial": parse_number(received.group(1)),
        "peso_final": parse_number(received.group(2)),
    }
    PDF_CACHE[cache_key] = result
    return result


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
        round(calculations.as_float(record.get("facturacion"))),
        round(calculations.as_float(record.get("peso_inicial")) * 100),
        round(calculations.as_float(record.get("peso_final")) * 100),
    )


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "facturacion": sum(record.get("facturacion", 0.0) for record in rows),
        "transferido": sum(record.get("transferido", 0.0) for record in rows),
        "peso_inicial": sum(record.get("peso_inicial", 0.0) for record in rows),
        "peso_final": sum(record.get("peso_final", 0.0) for record in rows),
        "boletines": len(rows),
        "entregas": len({record.get("delivery_id") for record in rows if record.get("delivery_id")}),
    }


def format_summary(summary: dict[str, Any]) -> None:
    summary["facturacion_display"] = calculations.fmt_money(summary.get("facturacion", 0.0))
    summary["transferido_display"] = calculations.fmt_money(summary.get("transferido", 0.0))
    summary["peso_inicial_display"] = calculations.fmt_number(summary.get("peso_inicial", 0.0))
    summary["peso_final_display"] = calculations.fmt_number(summary.get("peso_final", 0.0))
