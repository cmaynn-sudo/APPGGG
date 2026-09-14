from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WEBAPP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = WEBAPP_DIR.parent
TEMPLATE_DIR = WEBAPP_DIR / "templates"
GENERATED_TEMPLATE_DIR = TEMPLATE_DIR / "generated"
STATIC_DIR = WEBAPP_DIR / "static"
GENERATED_ASSET_DIR = STATIC_DIR / "generated"


@dataclass(frozen=True)
class TemplateSpec:
    slug: str
    title: str
    workbook: Path
    preferred_sheet: str
    current_script: str
    purpose: str
    output_name: str
    fields: dict[str, str]
    body_template: str | None = None
    page_size: str = "A4"
    page_margin: str = "10mm"

    @property
    def generated_template_name(self) -> str:
        return f"generated/{self.slug}.html"

    @property
    def render_template_name(self) -> str:
        return self.body_template or self.generated_template_name


def row_fields(prefix: str, cells: list[str]) -> dict[str, str]:
    return {cell: f"{prefix}_{idx}" for idx, cell in enumerate(cells, start=1)}


PRELIMINARES_FIELDS: dict[str, str] = {}
for row in range(6, 14):
    idx = row - 5
    PRELIMINARES_FIELDS.update(
        {
            f"B{row}": f"preliminares[{idx - 1}].proveedor|default('')",
            f"C{row}": f"preliminares[{idx - 1}].codigo|default('')",
            f"D{row}": f"preliminares[{idx - 1}].peso_inicial|default('')",
            f"E{row}": f"preliminares[{idx - 1}].peso_post|default('')",
            f"F{row}": f"preliminares[{idx - 1}].merma|default('')",
            f"G{row}": f"preliminares[{idx - 1}].porcentaje_merma|default('')",
            f"H{row}": f"preliminares[{idx - 1}].muestras|default('')",
            f"I{row}": f"preliminares[{idx - 1}].peso_final|default('')",
        }
    )
PRELIMINARES_FIELDS.update(
    {
        "D14": "preliminares_totales.peso_inicial|default('')",
        "E14": "preliminares_totales.peso_post|default('')",
        "F14": "preliminares_totales.merma|default('')",
        "G14": "preliminares_totales.porcentaje_merma|default('')",
        "H14": "preliminares_totales.muestras|default('')",
        "I14": "preliminares_totales.peso_final|default('')",
        "I16": "fecha",
    }
)


CERTIFICADO_FIELDS: dict[str, str] = {
    "A10": "sociedad",
    "E10": "nit",
}
for row in range(15, 19):
    idx = row - 15
    CERTIFICADO_FIELDS.update(
        {
            f"A{row}": f"boletines[{idx}].documento|default('')",
            f"B{row}": f"boletines[{idx}].fecha|default('')",
            f"C{row}": f"boletines[{idx}].mes|default('')",
            f"D{row}": f"boletines[{idx}].finos_oro|default('')",
            f"E{row}": f"boletines[{idx}].finos_plata|default('')",
            f"F{row}": f"boletines[{idx}].regalia_oro|default('')",
            f"G{row}": f"boletines[{idx}].regalia_plata|default('')",
        }
    )
CERTIFICADO_FIELDS.update(
    {
        "B2": "fecha_larga",
        "D21": "totales.finos_oro|default('')",
        "E21": "totales.finos_plata|default('')",
        "F21": "totales.regalia_oro|default('')",
        "G21": "totales.regalia_plata|default('')",
    }
)


TEMPLATES: list[TemplateSpec] = [
    TemplateSpec(
        slug="preliminares",
        title="Preliminares",
        workbook=PROJECT_DIR / "PRELIMINARES.xlsx",
        preferred_sheet="PRELIMINARES",
        current_script="DOCUMENTOS.py",
        purpose="Resumen de sociedades, barras y pesos de una entrega.",
        output_name="PRELIMINARES - {entrega} ({fecha}).pdf",
        fields=PRELIMINARES_FIELDS,
    ),
    TemplateSpec(
        slug="recibo-metales",
        title="Recibo de metales",
        workbook=PROJECT_DIR / "RECIBO DE METALES.xlsx",
        preferred_sheet="RECIBO DE METALES",
        current_script="DOCUMENTOS.py",
        purpose="Recibo individual generado por sociedad y barra.",
        output_name="{proveedor} ({codigo}).pdf",
        fields={
            "I7": "proveedor",
            "I9": "nit",
            "I11": "rucom",
            "I13": "municipio",
            "B14": "fecha_larga",
            "B16": "codigo",
            "A25": "peso_inicial",
            "C25": "peso_post",
            "G25": "oro_fino_estimado",
        },
    ),
    TemplateSpec(
        slug="reporte-analisis",
        title="Reporte de analisis",
        workbook=PROJECT_DIR / "REPORTE DE ANALISIS.xlsx",
        preferred_sheet="Hoja1",
        current_script="LEYES.py",
        purpose="Reporte de leyes AU/AG por barra.",
        output_name="REPORTE LEYES - {barra}.pdf",
        fields={
            "I7": "sociedad",
            "I9": "nit",
            "I11": "rucom",
            "I13": "municipio",
            "B14": "fecha_larga",
            "B16": "barra",
            "B21": "barra",
            "A28": "peso_inicial",
            "C28": "peso_final",
            "E28": "ley_au",
            "G28": "ley_ag",
            "I28": "gramos_au",
            "K28": "gramos_ag",
        },
    ),
    TemplateSpec(
        slug="boletin",
        title="Boletin",
        workbook=PROJECT_DIR / "REPORTE DE LIQUIDACION.xlsx",
        preferred_sheet="Hoja2",
        current_script="BOLETINES.py",
        purpose="Liquidacion y cierre de venta por barra.",
        output_name="BOLETIN - {barra}.pdf",
        fields={
            "C16": "barra",
            "C18": "fecha",
            "I12": "sociedad",
            "I14": "nit",
            "C24": "peso_ini",
            "G24": "peso_fin",
            "K24": "perdida",
            "L24": "porcentaje_perdida",
            "H32": "ley_au",
            "L32": "ley_ag",
            "H34": "fino_oro",
            "L34": "fino_plata",
            "H36": "precio_oro_cop",
            "L36": "precio_plata_cop",
            "H38": "valor_oro",
            "L38": "valor_plata",
            "H44": "valor_total_metales",
            "H46": "retefuente",
            "H48": "valor_a_pagar",
            "P51": "regalia_oro_4",
            "P52": "regalia_plata_4",
            "B53": "periodo_regalias",
            "C53": "regalia_au",
            "E53": "regalia_ag",
            "H52": "regalia_oro_total",
            "L52": "regalia_plata_total",
            "H58": "valor_transferir",
            "C73": "dolar",
            "G73": "oz_au",
            "J73": "oz_ag",
        },
        body_template="manual/boletin.html",
        page_size="letter",
        page_margin="0",
    ),
    TemplateSpec(
        slug="certificado-regalias",
        title="Certificado de regalias",
        workbook=PROJECT_DIR / "PAGO DE REGALIAS.xlsx",
        preferred_sheet="MES",
        current_script="PAGO DE REGALIAS.py",
        purpose="Certificado mensual agrupado por sociedad.",
        output_name="CERTIFICADO DE REGALIAS {sociedad} - {mes}.pdf",
        fields=CERTIFICADO_FIELDS,
    ),
]


TEMPLATE_BY_SLUG = {template.slug: template for template in TEMPLATES}


SAMPLE_CONTEXT = {
    "entrega": "8",
    "fecha": "2026-08-06",
    "proveedor": "COMERCIAL RIO VERDE S.A.S",
    "sociedad": "COMERCIAL RIO VERDE S.A.S",
    "nit": "900.534.616-3",
    "rucom": "2024072928005",
    "municipio": "NEIVA",
    "codigo": "CORI-9",
    "barra": "CORI-9",
    "peso_inicial": "1250.50",
    "peso_post": "1244.20",
    "peso_final": "1244.20",
    "peso_ini": "1250.50",
    "peso_fin": "1244.20",
    "muestras": "15.00",
    "ley_au": "85.32",
    "ley_ag": "12.48",
    "regalia_au": "419835.44",
    "regalia_ag": "6309.32",
    "dolar": "4010.25",
    "oz_au": "2340.10",
    "oz_ag": "27.85",
    "precio_negociacion_porcentaje": "97,50%",
    "retencion_porcentaje": "2,50%",
    "mes": "AGOSTO",
    "preliminares": [
        {
            "proveedor": "COMERCIAL RIO VERDE S.A.S",
            "codigo": "CORI-9",
            "peso_inicial": "1250.50",
            "peso_post": "1244.20",
            "muestras": "15.00",
        },
        {
            "proveedor": "INVERSIONES LIZAMA SAS",
            "codigo": "INLI-9",
            "peso_inicial": "980.00",
            "peso_post": "975.35",
            "muestras": "10.00",
        },
    ],
    "boletines": [
        {
            "documento": "CORI-9",
            "fecha": "06/08/2026",
            "mes": "AGOSTO",
            "finos_oro": "1062.81",
            "finos_plata": "155.28",
            "regalia_oro": "419835.44",
            "regalia_plata": "6309.32",
        },
        {
            "documento": "CORI-10",
            "fecha": "18/08/2026",
            "mes": "AGOSTO",
            "finos_oro": "844.16",
            "finos_plata": "98.42",
            "regalia_oro": "419835.44",
            "regalia_plata": "6309.32",
        },
    ],
    "totales": {
        "finos_oro": "1906.97",
        "finos_plata": "253.70",
        "regalia_oro": "839670.88",
        "regalia_plata": "12618.64",
    },
}
