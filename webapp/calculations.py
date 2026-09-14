from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from core import MESES_ES, parse_decimal_input


def as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(parse_decimal_input(str(value)))
    except ValueError:
        return default


def as_percent_rate(value: Any, default_percent: float) -> float:
    number = as_float(value, default_percent)
    return number if abs(number) <= 1 else number / 100


def excel_round(value: float, places: int = 0) -> float:
    quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    rounded = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(rounded)


def fmt_number(value: Any, places: int = 2, blank_zero: bool = False) -> str:
    if value in (None, ""):
        return ""
    number = as_float(value)
    if blank_zero and number == 0:
        return ""
    text = locale_number(number, places)
    return text.rstrip("0").rstrip(",") if places > 0 else text


def fmt_percent(value: Any, places: int = 2) -> str:
    if value in (None, ""):
        return ""
    return f"{locale_number(as_float(value) * 100, places)}%"


def fmt_money(value: Any, places: int = 0) -> str:
    if value in (None, ""):
        return ""
    return f"$ {locale_number(as_float(value), places)}"


def locale_number(value: float, places: int = 2) -> str:
    text = f"{value:,.{places}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def today_iso(current: date | None = None) -> str:
    return (current or date.today()).isoformat()


def today_ddmmyyyy(current: date | None = None) -> str:
    return (current or date.today()).strftime("%d/%m/%Y")


def today_long_es(current: date | None = None) -> str:
    current = current or date.today()
    return f"{current.day:02d} de {MESES_ES[current.month].lower()} de {current.year}"


def current_period_label(current: date | None = None) -> str:
    current = current or date.today()
    return f"{MESES_ES[current.month]} {current.year}"


def preliminar_item(raw: dict[str, Any]) -> dict[str, Any]:
    peso_inicial = as_float(raw.get("peso_inicial"))
    peso_post = as_float(raw.get("peso_post"))
    muestras = as_float(raw.get("muestras"))
    merma = peso_inicial - peso_post
    porcentaje_merma = merma / peso_inicial if peso_inicial else ""
    peso_final = peso_post - muestras
    item = dict(raw)
    item.update(
        {
            "peso_inicial_value": peso_inicial,
            "peso_post_value": peso_post,
            "muestras_value": muestras,
            "merma_value": merma,
            "porcentaje_merma_value": porcentaje_merma if porcentaje_merma != "" else 0,
            "peso_final_value": peso_final,
            "peso_inicial": fmt_number(peso_inicial),
            "peso_post": fmt_number(peso_post),
            "muestras": fmt_number(muestras),
            "merma": fmt_number(merma),
            "porcentaje_merma": fmt_percent(porcentaje_merma) if porcentaje_merma != "" else "",
            "peso_final": fmt_number(peso_final),
        }
    )
    return item


def preliminares_context(items: list[dict[str, Any]], current: date | None = None) -> dict[str, Any]:
    calculated = [preliminar_item(item) for item in items]
    total_peso_inicial = sum(item["peso_inicial_value"] for item in calculated)
    total_peso_post = sum(item["peso_post_value"] for item in calculated)
    total_muestras = sum(item["muestras_value"] for item in calculated)
    total_merma = sum(item["merma_value"] for item in calculated)
    total_porcentaje_merma = sum(item["porcentaje_merma_value"] for item in calculated)
    total_peso_final = sum(item["peso_final_value"] for item in calculated)
    return {
        "fecha": today_iso(current),
        "preliminares": calculated,
        "preliminares_totales": {
            "peso_inicial": fmt_number(total_peso_inicial),
            "peso_post": fmt_number(total_peso_post),
            "muestras": fmt_number(total_muestras),
            "merma": fmt_number(total_merma),
            "porcentaje_merma": fmt_percent(total_porcentaje_merma),
            "peso_final": fmt_number(total_peso_final),
        },
    }


def recibo_context(raw: dict[str, Any], current: date | None = None) -> dict[str, Any]:
    item = preliminar_item(raw)
    ley_estimada = as_float(raw.get("ley_estimada", 0.7))
    oro_fino_estimado = item["peso_post_value"] * ley_estimada
    item.update(
        {
            "fecha_larga": today_long_es(current),
            "ley_estimada": fmt_number(ley_estimada),
            "oro_fino_estimado": fmt_number(oro_fino_estimado),
        }
    )
    return item


def reporte_analisis_context(raw: dict[str, Any], current: date | None = None) -> dict[str, Any]:
    peso_final = as_float(raw.get("peso_final", raw.get("peso_post")))
    ley_au = as_float(raw.get("ley_au"))
    ley_ag = as_float(raw.get("ley_ag"))
    data = dict(raw)
    data.update(
        {
            "fecha_larga": today_long_es(current),
            "peso_inicial": fmt_number(raw.get("peso_inicial")),
            "peso_final": fmt_number(peso_final),
            "ley_au": fmt_number(ley_au),
            "ley_ag": fmt_number(ley_ag),
            "gramos_au": fmt_number(peso_final * ley_au / 1000),
            "gramos_ag": fmt_number(peso_final * ley_ag / 1000),
        }
    )
    return data


def boletin_context(
    raw: dict[str, Any],
    parametros: dict[str, Any],
    regalias: dict[str, Any],
    settings: dict[str, Any] | None = None,
    current: date | None = None,
) -> dict[str, Any]:
    current = current or date.today()
    settings = settings or {}
    peso_ini = as_float(raw.get("peso_ini", raw.get("peso_inicial")))
    peso_fin = as_float(raw.get("peso_fin", raw.get("peso_final", raw.get("peso_post"))))
    ley_au = as_float(raw.get("ley_au"))
    ley_ag = as_float(raw.get("ley_ag"))
    dolar = as_float(parametros.get("dolar"))
    oz_au = as_float(parametros.get("oz_au"))
    oz_ag = as_float(parametros.get("oz_ag"))
    regalia_au = as_float(regalias.get("au"))
    regalia_ag = as_float(regalias.get("ag"))
    mes_regalias = (parametros.get("mes_regalias") or regalias.get("mes") or MESES_ES[current.month]).strip().upper()
    precio_negociacion_rate = as_percent_rate(settings.get("precio_negociacion_porcentaje"), 97.5)
    retencion_rate = as_percent_rate(settings.get("retencion_porcentaje"), 2.5)

    perdida = peso_ini - peso_fin
    porcentaje_perdida = perdida / peso_ini if peso_ini else ""
    fino_oro = excel_round(peso_fin * ley_au / 1000, 2)
    fino_plata = excel_round(peso_fin * ley_ag / 1000, 2)
    precio_oro = excel_round(((oz_au / 31.10347) * dolar) * precio_negociacion_rate, 0)
    precio_plata = excel_round(((oz_ag / 31.10347) * dolar) / 2, 0)
    valor_oro = fino_oro * precio_oro
    valor_plata = fino_plata * precio_plata
    valor_total = valor_oro + valor_plata
    retefuente = valor_total * -retencion_rate
    valor_pagar = valor_total + retefuente
    regalia_oro_4 = regalia_au * 0.04
    regalia_plata_4 = regalia_ag * 0.04
    regalia_oro_total = regalia_oro_4 * fino_oro
    regalia_plata_total = regalia_plata_4 * fino_plata
    valor_transferir = valor_pagar - regalia_oro_total - regalia_plata_total

    data = dict(raw)
    data.update(
        {
            "fecha": today_ddmmyyyy(current),
            "fecha_iso": today_iso(current),
            "periodo_regalias": f"{mes_regalias} {current.year}",
            "peso_ini": fmt_number(peso_ini),
            "peso_fin": fmt_number(peso_fin),
            "ley_au": fmt_number(ley_au),
            "ley_ag": fmt_number(ley_ag),
            "regalia_au": fmt_money(regalia_au),
            "regalia_ag": fmt_money(regalia_ag, 2),
            "dolar": fmt_money(dolar),
            "oz_au": fmt_money(oz_au),
            "oz_ag": fmt_money(oz_ag),
            "precio_negociacion_porcentaje": fmt_percent(precio_negociacion_rate),
            "retencion_porcentaje": fmt_percent(retencion_rate),
            "perdida": fmt_number(perdida),
            "porcentaje_perdida": fmt_percent(porcentaje_perdida) if porcentaje_perdida != "" else "",
            "fino_oro": fmt_number(fino_oro),
            "fino_plata": fmt_number(fino_plata),
            "precio_oro_cop": fmt_money(precio_oro),
            "precio_plata_cop": fmt_money(precio_plata),
            "valor_oro": fmt_money(valor_oro),
            "valor_plata": fmt_money(valor_plata),
            "valor_total_metales": fmt_money(valor_total),
            "retefuente": fmt_money(retefuente),
            "valor_a_pagar": fmt_money(valor_pagar),
            "regalia_oro_4": fmt_money(regalia_oro_4, 2),
            "regalia_plata_4": fmt_money(regalia_plata_4, 2),
            "regalia_oro_total": fmt_money(regalia_oro_total),
            "regalia_plata_total": fmt_money(regalia_plata_total),
            "valor_transferir": fmt_money(valor_transferir),
            "finos_oro": fmt_number(fino_oro),
            "finos_plata": fmt_number(fino_plata),
            "regalia_oro": fmt_number(regalia_oro_total),
            "regalia_plata": fmt_number(regalia_plata_total),
        }
    )
    return data


def certificado_context(sociedad: str, nit: str, boletines: list[dict[str, Any]], current: date | None = None) -> dict[str, Any]:
    rows = list(boletines)
    totals = {
        "finos_oro": sum(as_float(row.get("finos_oro")) for row in rows),
        "finos_plata": sum(as_float(row.get("finos_plata")) for row in rows),
        "regalia_oro": sum(as_float(row.get("regalia_oro")) for row in rows),
        "regalia_plata": sum(as_float(row.get("regalia_plata")) for row in rows),
    }
    formatted_rows = []
    for row in rows:
        formatted = dict(row)
        formatted["finos_oro"] = fmt_number(row.get("finos_oro"))
        formatted["finos_plata"] = fmt_number(row.get("finos_plata"))
        formatted["regalia_oro"] = fmt_money(row.get("regalia_oro"))
        formatted["regalia_plata"] = fmt_money(row.get("regalia_plata"))
        formatted_rows.append(formatted)
    return {
        "fecha_larga": today_long_es(current),
        "sociedad": sociedad,
        "nit": nit,
        "boletines": formatted_rows,
        "totales": {
            "finos_oro": fmt_number(totals["finos_oro"]),
            "finos_plata": fmt_number(totals["finos_plata"]),
            "regalia_oro": fmt_money(totals["regalia_oro"]),
            "regalia_plata": fmt_money(totals["regalia_plata"]),
        },
    }
