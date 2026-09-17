from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.sax.saxutils import escape

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

from template_catalog import SAMPLE_CONTEXT, STATIC_DIR, TEMPLATE_BY_SLUG, TEMPLATE_DIR, WEBAPP_DIR


env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=ChainableUndefined,
)


def render_print_html(
    slug: str,
    context: dict | None = None,
    *,
    include_print_scale: bool = True,
    page_size: str | None = None,
    page_margin: str | None = None,
) -> str:
    spec = TEMPLATE_BY_SLUG[slug]
    data = dict(SAMPLE_CONTEXT)
    if context:
        data.update(context)
    body = env.get_template(spec.render_template_name).render(**data)
    print_css = (STATIC_DIR / "print.css").read_text(encoding="utf-8")
    scale_css = print_scale_css(slug) if include_print_scale else ""
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{spec.title}</title>
  <style>
    @page {{ size: {page_size or spec.page_size}; margin: {page_margin or spec.page_margin}; }}
    body {{ margin: 0; background: white; }}
    {print_css}
    .doc-sheet {{ box-shadow: none; margin: 0 auto; }}
    {scale_css}
  </style>
</head>
<body class="print-export print-{slug}">
{body}
</body>
</html>
"""


def save_print_html(slug: str, output_path: Path, context: dict | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_print_html(slug, context), encoding="utf-8")
    return output_path


def render_print_pdf(slug: str, context: dict | None = None) -> bytes:
    spec = TEMPLATE_BY_SLUG[slug]
    data = dict(SAMPLE_CONTEXT)
    if context:
        data.update(context)
    try:
        return render_weasy_pdf(slug, data)
    except ImportError:
        print("[recepción] WeasyPrint no está instalado; usando PDF simplificado.")
    except Exception as exc:
        print(f"[recepción] No se pudo generar PDF desde HTML; usando PDF simplificado: {exc}")
    reportlab_renderers = {
        "preliminares": render_preliminares_pdf,
        "recibo-metales": render_recibo_pdf,
        "reporte-analisis": render_reporte_analisis_pdf,
        "boletin": render_boletin_pdf,
        "certificado-regalias": render_certificado_pdf,
    }
    if slug in reportlab_renderers:
        return reportlab_renderers[slug](data, spec.title)
    raise RuntimeError("No hay motor PDF disponible para este documento.")


def render_weasy_pdf(slug: str, context: dict | None = None) -> bytes:
    from weasyprint import HTML

    zoom = pdf_zoom(slug)
    page_size, page_margin = pdf_page_box(slug, zoom)
    html = absolutize_static_urls(
        render_print_html(
            slug,
            context,
            include_print_scale=False,
            page_size=page_size,
            page_margin=page_margin,
        )
    )
    return HTML(string=html, base_url=WEBAPP_DIR.as_uri()).write_pdf(zoom=zoom)


def pdf_zoom(slug: str) -> float:
    return {
        "preliminares": 0.62,
        "recibo-metales": 0.62,
        "reporte-analisis": 0.62,
        "certificado-regalias": 0.89,
    }.get(slug, 1.0)


def pdf_page_box(slug: str, zoom: float) -> tuple[str, str]:
    spec = TEMPLATE_BY_SLUG[slug]
    if zoom == 1:
        return spec.page_size, spec.page_margin

    page_sizes_mm = {
        "a4": (210.0, 297.0),
        "letter": (215.9, 279.4),
    }
    size = page_sizes_mm.get(spec.page_size.lower())
    if not size:
        return spec.page_size, spec.page_margin

    width_mm, height_mm = size
    page_size = f"{width_mm / zoom:.4f}mm {height_mm / zoom:.4f}mm"
    margin = scaled_margin(spec.page_margin, zoom)
    return page_size, margin


def scaled_margin(margin: str, zoom: float) -> str:
    value = margin.strip().lower()
    if value in {"0", "0mm"}:
        return "0"
    if value.endswith("mm"):
        return f"{float(value[:-2]) / zoom:.4f}mm"
    return margin


def print_scale_css(slug: str) -> str:
    scales = {
        "preliminares": "0.62",
        "recibo-metales": "0.62",
        "reporte-analisis": "0.62",
        "certificado-regalias": "0.89",
    }
    scale = scales.get(slug)
    if not scale:
        return ""
    inverse = f"{1 / float(scale):.4f}"
    return f"""
    .print-export .print-document {{
      transform: scale({scale});
      transform-origin: top left;
      width: calc(100% * {inverse});
    }}
    .print-export .doc-sheet {{
      margin: 0 !important;
    }}
    """


def absolutize_static_urls(html: str) -> str:
    static_uri = STATIC_DIR.as_uri().rstrip("/")
    return (
        html.replace('src="/static/', f'src="{static_uri}/')
        .replace("src='/static/", f"src='{static_uri}/")
        .replace("url(/static/", f"url({static_uri}/")
        .replace("url('/static/", f"url('{static_uri}/")
        .replace('url("/static/', f'url("{static_uri}/')
    )


def render_preliminares_pdf(data: dict, title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    styles = pdf_styles()
    rows = [["Proveedor", "Código", "Peso inicial", "Peso post", "Merma", "% merma", "Muestras", "Peso final"]]
    for item in data.get("preliminares", []):
        rows.append(
            [
                cell(item.get("proveedor"), styles["Cell"]),
                cell(item.get("codigo"), styles["Cell"]),
                cell(item.get("peso_inicial"), styles["RightCell"]),
                cell(item.get("peso_post"), styles["RightCell"]),
                cell(item.get("merma"), styles["RightCell"]),
                cell(item.get("porcentaje_merma"), styles["RightCell"]),
                cell(item.get("muestras"), styles["RightCell"]),
                cell(item.get("peso_final"), styles["RightCell"]),
            ]
        )
    totals = data.get("preliminares_totales", {})
    rows.append(
        [
            "",
            "TOTAL",
            cell(totals.get("peso_inicial"), styles["RightCell"]),
            cell(totals.get("peso_post"), styles["RightCell"]),
            cell(totals.get("merma"), styles["RightCell"]),
            cell(totals.get("porcentaje_merma"), styles["RightCell"]),
            cell(totals.get("muestras"), styles["RightCell"]),
            cell(totals.get("peso_final"), styles["RightCell"]),
        ]
    )
    table = Table(rows, colWidths=[56 * mm, 24 * mm, 28 * mm, 28 * mm, 26 * mm, 26 * mm, 26 * mm, 28 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d5c63")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7a1")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e5e7eb")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f7faf8")]),
            ]
        )
    )
    story = [
        header_block(title, data.get("fecha")),
        Paragraph(f"Entrega {safe_text(data.get('entrega'))}", styles["Subtitle"]),
        Spacer(1, 10),
        table,
    ]
    return story_pdf(story, pagesize=landscape(A4), title=title, margins=(18 * mm, 18 * mm, 16 * mm, 16 * mm))


def render_recibo_pdf(data: dict, title: str) -> bytes:
    story = [
        header_block(title, data.get("fecha_larga")),
        details_table(
            [
                ("Proveedor", data.get("proveedor")),
                ("NIT", data.get("nit")),
                ("RUCOM", data.get("rucom")),
                ("Municipio", data.get("municipio")),
                ("Documento", data.get("codigo")),
            ]
        ),
        section_title("Pesos recibidos"),
        metric_table(
            [
                ("Peso inicial", f"{safe_text(data.get('peso_inicial'))} G"),
                ("Peso post fundición", f"{safe_text(data.get('peso_post'))} G"),
                ("Ley estimada", data.get("ley_estimada")),
                ("Oro fino estimado", f"{safe_text(data.get('oro_fino_estimado'))} G"),
            ]
        ),
    ]
    return story_pdf(story, title=title)


def render_reporte_analisis_pdf(data: dict, title: str) -> bytes:
    story = [
        header_block(title, data.get("fecha_larga")),
        details_table(
            [
                ("Sociedad", data.get("sociedad")),
                ("NIT", data.get("nit")),
                ("RUCOM", data.get("rucom")),
                ("Municipio", data.get("municipio")),
                ("Barra", data.get("barra")),
            ]
        ),
        section_title("Resultado de análisis"),
        metric_table(
            [
                ("Peso inicial", f"{safe_text(data.get('peso_inicial'))} G"),
                ("Peso final", f"{safe_text(data.get('peso_final'))} G"),
                ("Ley AU", data.get("ley_au")),
                ("Ley AG", data.get("ley_ag")),
                ("Gramos AU", data.get("gramos_au")),
                ("Gramos AG", data.get("gramos_ag")),
            ]
        ),
    ]
    return story_pdf(story, title=title)


def render_certificado_pdf(data: dict, title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    styles = pdf_styles()
    rows = [["Documento", "Fecha", "Mes", "Finos oro", "Finos plata", "Regalía oro", "Regalía plata"]]
    for item in data.get("boletines", []):
        rows.append(
            [
                cell(item.get("documento"), styles["Cell"]),
                cell(item.get("fecha"), styles["Cell"]),
                cell(item.get("mes"), styles["Cell"]),
                cell(item.get("finos_oro"), styles["RightCell"]),
                cell(item.get("finos_plata"), styles["RightCell"]),
                cell(item.get("regalia_oro"), styles["RightCell"]),
                cell(item.get("regalia_plata"), styles["RightCell"]),
            ]
        )
    totals = data.get("totales", {})
    rows.append(
        [
            "",
            "",
            "TOTAL",
            cell(totals.get("finos_oro"), styles["RightCell"]),
            cell(totals.get("finos_plata"), styles["RightCell"]),
            cell(totals.get("regalia_oro"), styles["RightCell"]),
            cell(totals.get("regalia_plata"), styles["RightCell"]),
        ]
    )
    table = Table(rows, colWidths=[27 * mm, 25 * mm, 25 * mm, 26 * mm, 26 * mm, 31 * mm, 31 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d5c63")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7a1")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e5e7eb")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    body = (
        "C.I Green Global Group S.A.S certifica que al proveedor relacionado se le tramitó "
        "y pagó las correspondientes regalías a la ANM."
    )
    story = [
        header_block(title, data.get("fecha_larga")),
        Paragraph(safe_text(body), styles["Body"]),
        Spacer(1, 10),
        details_table([("Sociedad", data.get("sociedad")), ("NIT", data.get("nit"))]),
        section_title("Boletines del período"),
        table,
    ]
    return story_pdf(story, pagesize=A4, title=title, margins=(16 * mm, 16 * mm, 16 * mm, 16 * mm))


def render_boletin_pdf(data: dict, title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=letter)
    page.setTitle(title)
    width, height = letter
    margin = 54
    top = height - 54
    grey = colors.HexColor("#d9d9d9")
    ink = colors.black

    def text(x: float, y: float, value: object, size: int = 9, bold: bool = False, align: str = "left") -> None:
        page.setFillColor(ink)
        page.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        content = safe_text(value)
        if align == "center":
            page.drawCentredString(x, y, content)
        elif align == "right":
            page.drawRightString(x, y, content)
        else:
            page.drawString(x, y, content)

    def rect(x: float, y: float, w: float, h: float, fill=grey) -> None:
        page.setFillColor(fill)
        page.setStrokeColor(colors.black)
        page.rect(x, y, w, h, fill=1, stroke=0)

    text(margin + 166, top, "REPORTE DE LIQUIDACIÓN", 18, True, "center")
    draw_logo(page, width - margin - 105, top - 20, 105, 55)
    line_y = top - 28
    page.setStrokeColor(colors.black)
    page.line(margin, line_y, width - margin, line_y)

    left_x = margin
    right_x = margin + 300
    y = line_y - 28
    text(left_x, y, "C.I GREEN GLOBAL GROUP S.A.S", 9, True)
    text(right_x, y, "PROVEEDOR:", 9)
    text(right_x + 83, y, data.get("sociedad"), 9, True)
    y -= 18
    text(left_x, y, "NIT:", 9)
    text(left_x + 76, y, "901.640.887-1", 9, True)
    text(right_x, y, "NIT:", 9)
    text(right_x + 83, y, data.get("nit"), 9, True)
    y -= 18
    text(left_x, y, "DOCUMENTO:", 9)
    text(left_x + 76, y, data.get("barra"), 9, True)
    text(right_x, y, "TIPO DE PROVEEDOR:", 9)
    text(right_x + 112, y, "RECICLADO", 9, True)
    y -= 18
    text(left_x, y, "FECHA DE LIQUIDACIÓN:", 9)
    text(left_x + 126, y, data.get("fecha"), 9, True)
    text(right_x, y, "TIPO DE ORO:", 9)
    text(right_x + 83, y, "RECICLADO", 9, True)

    y -= 20
    page.line(margin, y, width - margin, y)
    y -= 56
    rect(margin, y, width - margin * 2, 42)
    thirds = (width - margin * 2) / 3
    text(margin + thirds * 0.5, y + 25, "PESO RECIBIDO", 8, False, "center")
    text(margin + thirds * 0.5, y + 10, f"{safe_text(data.get('peso_ini'))} G", 10, True, "center")
    text(margin + thirds * 1.5, y + 25, "PESO FUNDIDO", 8, False, "center")
    text(margin + thirds * 1.5, y + 10, f"{safe_text(data.get('peso_fin'))} G", 10, True, "center")
    text(margin + thirds * 2.5, y + 25, "PÉRDIDA", 8, False, "center")
    text(margin + thirds * 2.32, y + 10, data.get("perdida"), 10, True, "center")
    text(margin + thirds * 2.68, y + 10, data.get("porcentaje_perdida"), 10, True, "center")

    y -= 42
    col_w = [230, 115, 115]
    gap = 20
    x0 = margin
    x1 = x0 + col_w[0] + gap
    x2 = x1 + col_w[1] + gap
    text(x0 + col_w[0] / 2, y + 18, "VARIABLES", 10, True, "center")
    text(x1 + col_w[1] / 2, y + 18, "ORO", 10, True, "center")
    text(x2 + col_w[2] / 2, y + 18, "PLATA", 10, True, "center")
    y -= 98
    rect(x0, y, col_w[0], 92)
    rect(x1, y, col_w[1], 92)
    rect(x2, y, col_w[2], 92)
    labels = ["LEY %", "FINO (G)", "PRECIO (COP)", "VALOR METAL (COP)"]
    oro = [data.get("ley_au"), data.get("fino_oro"), data.get("precio_oro_cop"), data.get("valor_oro")]
    plata = [data.get("ley_ag"), data.get("fino_plata"), data.get("precio_plata_cop"), data.get("valor_plata")]
    for index, label in enumerate(labels):
        row_y = y + 72 - index * 20
        text(x0 + 12, row_y, label, 9, True)
        text(x1 + col_w[1] / 2, row_y, oro[index], 9, True, "center")
        text(x2 + col_w[2] / 2, row_y, plata[index], 9, True, "center")

    y -= 86
    labels = ["VALOR TOTAL METALES (COP)", "RETEFUENTE (COP)", "VALOR A PAGAR (COP)"]
    values = [data.get("valor_total_metales"), data.get("retefuente"), data.get("valor_a_pagar")]
    for index, label in enumerate(labels):
        row_y = y + 58 - index * 22
        text(x0, row_y, label, 9, True)
    rect(x1, y + 4, col_w[1], 72)
    for index, value in enumerate(values):
        text(x1 + col_w[1] / 2, y + 58 - index * 22, value, 9, True, "center")

    y -= 104
    text(x0, y + 82, "REGALIAS ADEUDADAS POR EL PROVEEDOR", 7, True)
    text(x0, y + 48, data.get("periodo_regalias"), 8, True)
    text(x1 + 42, y + 82, "ORO", 7, False, "center")
    text(x1 + 92, y + 82, "PLATA", 7, False, "center")
    text(x1 + 42, y + 66, data.get("regalia_au"), 7, True, "center")
    text(x1 + 92, y + 66, data.get("regalia_ag"), 7, True, "center")
    rect(x2 - 8, y + 38, 80, 28)
    rect(x2 + 82, y + 38, 80, 28)
    text(x2 + 32, y + 49, data.get("regalia_oro_total"), 8, True, "center")
    text(x2 + 122, y + 49, data.get("regalia_plata_total"), 8, True, "center")

    y -= 8
    text(x0, y, "VALOR A TRANSFERIR", 10, True)
    rect(x1, y - 12, col_w[1], 28)
    text(x1 + col_w[1] / 2, y - 2, data.get("valor_transferir"), 10, True, "center")
    y -= 32
    page.line(margin, y, width - margin, y)
    text(width - margin - 140, y + 5, f"RUCOM: {safe_text(data.get('rucom'))}", 7, False)

    y -= 66
    text(x0, y + 46, "PARÁMETROS", 9, True)
    rows = [
        ("TC", data.get("dolar"), "1 USD"),
        ("XAU", data.get("oz_au"), "1 OZ"),
        ("XAG", data.get("oz_ag"), "1 OZ"),
    ]
    for index, (label, value, unit) in enumerate(rows):
        row_y = y + 24 - index * 17
        text(x0, row_y, label, 8, True)
        text(x0 + 55, row_y, value, 8, False)
        text(x0 + 132, row_y, unit, 8, False)
    text(x2, y + 24, f"Negociación: {safe_text(data.get('precio_negociacion_porcentaje'))}", 7, False)
    text(x2, y + 8, f"Retención: {safe_text(data.get('retencion_porcentaje'))}", 7, False)

    page.showPage()
    page.save()
    return buffer.getvalue()


def story_pdf(story: list, pagesize=None, title: str = "", margins: tuple[float, float, float, float] | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buffer = io.BytesIO()
    left, right, top, bottom = margins or (42, 42, 36, 36)
    doc = SimpleDocTemplate(buffer, pagesize=pagesize or A4, title=title, leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom)
    doc.build(story)
    return buffer.getvalue()


def pdf_styles() -> dict:
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle

    return {
        "Title": ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=16, leading=19, spaceAfter=4),
        "Subtitle": ParagraphStyle("Subtitle", fontName="Helvetica", fontSize=9, leading=12, textColor="#4b5563"),
        "Section": ParagraphStyle("Section", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=14, spaceAfter=8),
        "Body": ParagraphStyle("Body", fontName="Helvetica", fontSize=9, leading=12, spaceAfter=8),
        "Cell": ParagraphStyle("Cell", fontName="Helvetica", fontSize=8, leading=9),
        "RightCell": ParagraphStyle("RightCell", fontName="Helvetica", fontSize=8, leading=9, alignment=TA_RIGHT),
        "Label": ParagraphStyle("Label", fontName="Helvetica-Bold", fontSize=8, leading=10),
    }


def header_block(title: str, subtitle: object = ""):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Table, TableStyle

    styles = pdf_styles()
    logo = logo_path()
    left = [Paragraph(escape(title.upper()), styles["Title"])]
    if subtitle:
        left.append(Paragraph(escape(safe_text(subtitle)), styles["Subtitle"]))
    right = ""
    if logo:
        right = Image(str(logo), width=36 * mm, height=22 * mm, kind="proportional")
    table = Table([[left, right]], colWidths=[None, 42 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    return table


def details_table(rows: list[tuple[object, object]]):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    styles = pdf_styles()
    table = Table(
        [[cell(label, styles["Label"]), cell(value, styles["Cell"])] for label, value in rows],
        colWidths=[42 * mm, 116 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e5e7eb")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7a1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def metric_table(rows: list[tuple[object, object]]):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    styles = pdf_styles()
    table = Table(
        [[cell(label, styles["Label"]), cell(value, styles["RightCell"])] for label, value in rows],
        colWidths=[78 * mm, 46 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7a1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7faf8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def section_title(value: str):
    from reportlab.platypus import Paragraph

    return Paragraph(escape(value), pdf_styles()["Section"])


def cell(value: object, style):
    from reportlab.platypus import Paragraph

    return Paragraph(escape(safe_text(value)), style)


def draw_logo(page, x: float, y: float, w: float, h: float) -> None:
    logo = logo_path()
    if logo:
        page.drawImage(str(logo), x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")


def logo_path() -> Path | None:
    path = STATIC_DIR / "generated" / "logo.png"
    return path if path.exists() else None


def safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def asset_path(uri: str, _rel: str = "") -> str:
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path or uri)
    if raw_path.startswith("/static/"):
        candidate = (WEBAPP_DIR / raw_path.lstrip("/")).resolve()
        if str(candidate).startswith(str(WEBAPP_DIR.resolve())):
            return str(candidate)
    return uri
