from __future__ import annotations

import base64
import html as html_lib
import io
import math
import re
import threading
from datetime import date
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse
from xml.sax.saxutils import escape

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

from template_catalog import SAMPLE_CONTEXT, STATIC_DIR, TEMPLATE_BY_SLUG, TEMPLATE_DIR, WEBAPP_DIR


env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=ChainableUndefined,
)

PDF_RENDER_LOCK = threading.Lock()


def template_sample_context(slug: str) -> dict:
    data = dict(SAMPLE_CONTEXT)
    if slug == "boletin":
        import calculations

        data.update(calculations.boletin_context(
            data,
            {key: data[key] for key in ("dolar", "oz_au", "oz_ag")},
            {"au": data["regalia_au"], "ag": data["regalia_ag"], "mes": data["mes"]},
            {key: data[key] for key in ("precio_negociacion_porcentaje", "retencion_porcentaje")},
            current=date.fromisoformat(data["fecha"]),
        ))
    return data


def render_print_html(
    slug: str,
    context: dict | None = None,
    *,
    include_print_scale: bool = True,
    page_size: str | None = None,
    page_margin: str | None = None,
    store: dict | None = None,
) -> str:
    spec = TEMPLATE_BY_SLUG[slug]
    data = template_sample_context(slug)
    if context:
        data.update(context)
    body = prepare_template_layout(env.get_template(spec.render_template_name).render(**data))
    import data_store

    layout = data_store.get_template_layout(slug, store=store)
    assets = data_store.get_template_assets(slug, store=store)
    body = apply_template_content_overrides(body, layout, assets)
    print_css = (STATIC_DIR / "print.css").read_text(encoding="utf-8")
    scale_css = print_scale_css(slug, layout) if include_print_scale else ""
    saved_layout_css = template_layout_css(slug, layout)
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
    {saved_layout_css}
  </style>
</head>
<body class="print-export print-{slug}">
{body}
</body>
</html>
"""


def template_layout_css(slug: str, layout: dict | None = None) -> str:
    if layout is None:
        import data_store

        layout = data_store.get_template_layout(slug)
    elements = (layout or {}).get("elements", {})
    if not isinstance(elements, dict):
        return ""

    rules = []
    for element_id, settings in elements.items():
        if isinstance(element_id, str) and element_id.startswith(("column-", "row-")):
            continue
        if not isinstance(element_id, str) or not re.fullmatch(
            r"(?:cell-[A-Z]{1,3}\d+|image-[a-z0-9-]+|block-[a-z0-9-]+|(?:text|char)-[A-Za-z0-9-]+)",
            element_id,
        ):
            continue
        if not isinstance(settings, dict):
            continue
        x = layout_number(settings.get("x"), 0.0, -500.0, 500.0)
        y = layout_number(settings.get("y"), 0.0, -500.0, 500.0)
        scale = layout_number(settings.get("scale"), 1.0, 0.4, 2.5)
        declarations = [
            f"transform:translate({x:.2f}px, {y:.2f}px) scale({scale:.3f}) !important",
            "transform-origin:center center !important",
        ]
        font_size = layout_number(settings.get("font_size"), 0.0, 0.0, 72.0)
        width = layout_number(settings.get("width"), 0.0, 0.0, 1200.0)
        height = layout_number(settings.get("height"), 0.0, 0.0, 1200.0)
        if font_size > 0:
            declarations.append(f"font-size:{font_size:.2f}px !important")
        if settings.get("text_override") is not None:
            declarations.append("white-space:pre-wrap !important")
        if settings.get("nowrap"):
            declarations.extend(
                (
                    "white-space:nowrap !important",
                    "overflow-wrap:normal !important",
                    "word-break:normal !important",
                )
            )
        text_align = str(settings.get("text_align", ""))
        if text_align in {"left", "center", "right"}:
            declarations.append(f"text-align:{text_align} !important")
        if settings.get("hidden"):
            declarations.append("display:none !important")
        if not element_id.startswith("cell-"):
            if width > 0:
                declarations.append(f"width:{width:.2f}px !important")
            if height > 0:
                declarations.append(f"height:{height:.2f}px !important")
        rules.append(
            f'[data-layout-id="{element_id}"]' + "{" + ";".join(declarations) + "}"
        )
    rules.extend(table_dimension_css(slug, elements))
    return "\n".join(rules)


class TableCellGeometry(NamedTuple):
    row: int
    index: int
    column: int
    rowspan: int
    colspan: int
    vertical: str


class TableImageGeometry(NamedTuple):
    id: str
    left: float
    top: float
    height: float


def grid_anchor_shift(offset: float, original: tuple, resized: list) -> float:
    boundary = 0.0
    for index, size in enumerate(original):
        if offset < boundary + size:
            return sum(resized[:index]) - boundary
        boundary += size
    return 0.0


class TableGeometryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.columns: list[float] = []
        self.rows: list[float] = []
        self.cells: list[TableCellGeometry] = []
        self.occupied: set[tuple[int, int]] = set()
        self.next_column = 0
        self.cell_index = 0
        self.images: list[TableImageGeometry] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "img" and attributes.get("data-layout-id"):
            style = attributes.get("style") or ""
            top = re.search(r"(?:^|;)top:([\d.]+)px", style)
            left = re.search(r"(?:^|;)left:([\d.]+)px", style)
            height = re.search(r"(?:^|;)height:([\d.]+)px", style)
            if top and left and height:
                self.images.append(TableImageGeometry(attributes["data-layout-id"], float(left[1]), float(top[1]), float(height[1])))
            return
        if tag == "td":
            row = len(self.rows) - 1
            while (row, self.next_column) in self.occupied:
                self.next_column += 1
            rowspan = int(attributes.get("rowspan") or 1)
            colspan = int(attributes.get("colspan") or 1)
            align = re.search(r"vertical-align:(top|middle|bottom)", attributes.get("style") or "")
            self.cells.append(TableCellGeometry(row, self.cell_index, self.next_column, rowspan, colspan, align[1] if align else "middle"))
            for r in range(row, row + rowspan):
                for c in range(self.next_column, self.next_column + colspan):
                    self.occupied.add((r, c))
            self.next_column += colspan
            self.cell_index += 1
            return
        if tag not in {"col", "tr"}:
            return
        dimension = "width" if tag == "col" else "height"
        match = re.search(rf"(?:^|;)\s*{dimension}\s*:\s*([\d.]+)px", dict(attrs).get("style") or "")
        target = self.columns if tag == "col" else self.rows
        target.append(float(match.group(1)) if match else 20.0)
        if tag == "tr":
            self.next_column = 0
            self.cell_index = 0


@lru_cache(maxsize=16)
def template_table_geometry(slug: str) -> tuple:
    spec = TEMPLATE_BY_SLUG[slug]
    source, _filename, _uptodate = env.loader.get_source(env, spec.render_template_name)
    parser = TableGeometryParser()
    parser.feed(source)
    if slug == "preliminares":
        parser.rows[4] = 88.0
        parser.rows[5:13] = [40.0] * 8
        parser.rows[13] = 28.0
    return tuple(parser.columns), tuple(parser.rows), tuple(parser.cells), tuple(parser.images)


def table_dimension_css(slug: str, elements: dict) -> list[str]:
    base_columns, base_rows, cells, images = template_table_geometry(slug)
    if not base_columns:
        return []
    rows = {}
    # Keep existing cell-based sizes; explicit ruler sizes take precedence.
    for element_id, settings in elements.items():
        if not isinstance(settings, dict) or not isinstance(element_id, str):
            continue
        cell_match = re.fullmatch(r"cell-([A-Z]{1,3})(\d+)", element_id)
        if cell_match:
            height = layout_number(settings.get("height"), 0, 0, 1200)
            if height:
                rows[int(cell_match[2])] = height
    for element_id, settings in elements.items():
        if not isinstance(settings, dict) or not isinstance(element_id, str):
            continue
        row = re.fullmatch(r"row-([1-9]\d{0,3})", element_id)
        if row:
            value = layout_number(settings.get("height"), 0, 0, 1200)
            if value:
                rows[int(row[1])] = max(18, value)
    scope = f'[data-template="{slug}"]'
    widths = resized_column_widths(base_columns, elements)
    heights = list(base_rows)
    rules = []
    for index, width in enumerate(widths):
        if width != base_columns[index]:
            rules.append(f'{scope} .excel-sheet col:nth-child({index + 1}){{width:{width:.2f}px !important}}')
    total_width = sum(widths)
    for row, height in rows.items():
        if not 1 <= row <= len(base_rows):
            continue
        heights[row - 1] = height
    if slug == "recibo-metales" and 47 not in rows:
        signature = next((image for image in images if image.id == "image-2"), None)
        settings = elements.get("image-2", {})
        if signature and isinstance(settings, dict) and not settings.get("hidden"):
            top = signature.top + grid_anchor_shift(signature.top, base_rows, heights)
            height = layout_number(settings.get("height"), 0, 0, 1200) or signature.height
            scale = layout_number(settings.get("scale"), 1, 0.4, 2.5)
            bottom = top + layout_number(settings.get("y"), 0, -500, 500) + height * (1 + scale) / 2
            # Reserve space before the identity lines without changing the saved signature.
            heights[46] += max(0, bottom + 8 - sum(heights[:47]))
    total_height = sum(heights)
    rules.extend((
        f'{scope} .doc-sheet{{width:{total_width:.2f}px !important}}',
        f'{scope} .excel-sheet{{display:block;position:relative;width:{total_width:.2f}px !important;height:{total_height:.2f}px}}',
        f'{scope} .excel-sheet colgroup{{display:none}}',
        f'{scope} .excel-sheet > tbody{{display:block}}',
    ))
    for image in images:
        left = image.left + grid_anchor_shift(image.left, base_columns, widths)
        top = image.top + grid_anchor_shift(image.top, base_rows, heights)
        rules.append(f'{scope} [data-layout-id="{image.id}"]{{left:{left:.2f}px !important;top:{top:.2f}px !important}}')
    for index, height in enumerate(heights):
        selector = f'{scope} .excel-sheet tr:nth-of-type({index + 1})'
        rules.append(f'{selector}{{display:block;position:absolute;left:0;top:{sum(heights[:index]):.2f}px;width:100%;height:{height:.2f}px !important}}')
    for cell in cells:
        selector = f'{scope} .excel-sheet tr:nth-of-type({cell.row + 1}) > td:nth-child({cell.index + 1})'
        width = sum(widths[cell.column:cell.column + cell.colspan])
        height = sum(heights[cell.row:cell.row + cell.rowspan])
        justify = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}[cell.vertical]
        rules.append(
            f'{selector}{{display:flex;flex-direction:column;justify-content:{justify};position:absolute !important;'
            f'left:{sum(widths[:cell.column]):.2f}px;top:0;width:{width:.2f}px !important;height:{height:.2f}px !important;min-width:0;min-height:0}}'
        )
        if cell.rowspan == 1 and cell.row + 1 in rows:
            rules.append(f'{selector} > .excel-cell-content{{max-height:{max(0, height - 5):.2f}px !important;overflow:hidden}}')
    return rules


def resized_column_widths(original: tuple, elements: dict) -> list[float]:
    widths = list(original)
    for pattern in (r"cell-([A-Z]{1,3})\d+", r"column-([A-Z]{1,3})"):
        for element_id, settings in elements.items():
            if not isinstance(element_id, str) or not isinstance(settings, dict):
                continue
            match = re.fullmatch(pattern, element_id)
            if not match:
                continue
            column = excel_column_number(match[1]) - 1
            width = layout_number(settings.get("width"), 0, 0, 1200)
            if width and 0 <= column < len(widths):
                widths[column] = max(18, width) if element_id.startswith("column-") else width
    return widths


def excel_column_number(column: str) -> int:
    number = 0
    for character in column:
        number = number * 26 + (ord(character) - ord("A") + 1)
    return number


def apply_template_content_overrides(
    body: str,
    layout: dict | None,
    assets: dict[str, dict[str, str]] | None,
) -> str:
    elements = (layout or {}).get("elements", {})
    text_overrides = {
        element_id: settings.get("text_override")
        for element_id, settings in elements.items()
        if isinstance(settings, dict) and isinstance(settings.get("text_override"), str)
    }
    asset_sources: dict[str, str] = {}
    if assets:
        import data_store

        uploads_root = data_store.UPLOADS_DIR.resolve()
        for element_id, metadata in assets.items():
            if not isinstance(metadata, dict):
                continue
            path = (data_store.UPLOADS_DIR / str(metadata.get("stored_path", ""))).resolve()
            if not path.is_relative_to(uploads_root) or not path.is_file():
                continue
            content_type = str(metadata.get("content_type") or "image/png")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            asset_sources[element_id] = f"data:{content_type};base64,{encoded}"
    if text_overrides or asset_sources:
        parser = TemplateOverrideParser(text_overrides, asset_sources)
        parser.feed(body)
        parser.close()
        body = parser.rendered
    character_parents = set()
    for element_id in elements:
        match = re.fullmatch(r"char-(.+)-(\d+)", element_id)
        if match:
            character_parents.add(match.group(1))
    if character_parents:
        characters = CharacterLayoutParser(character_parents)
        characters.feed(body)
        characters.close()
        parser = TemplateOverrideParser(
            {key: value for key, value in text_overrides.items() if key.startswith("char-")},
            {},
        )
        parser.feed(characters.rendered)
        parser.close()
        body = parser.rendered
    return body


def prepare_template_layout(body: str) -> str:
    parser = LayoutTextParser()
    parser.feed(body)
    parser.close()
    return parser.rendered


class LayoutTextParser(HTMLParser):
    VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    SKIP_ELEMENTS = {"script", "style", "svg", "textarea"}
    TEXT_ELEMENTS = {"span", "strong", "b", "em", "i", "p", "dt", "dd", "td", "th", "h1", "h2", "h3", "small"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[dict] = []
        self.root_children: dict[str, int] = {}
        self.offsets: dict[str, int] = {}
        self.annotate_empty = True

    @property
    def rendered(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self.get_starttag_text())
        parent = self.stack[-1] if self.stack else None
        siblings = parent["children"] if parent else self.root_children
        siblings[tag] = siblings.get(tag, 0) + 1
        anchor = parent["id"] or parent["path"] if parent else "document"
        if tag not in self.VOID_ELEMENTS:
            self.stack.append({
                "tag": tag,
                "id": dict(attrs).get("data-layout-id") or "",
                "path": f"{anchor}-{tag}{siblings[tag]}",
                "children": {},
                "texts": 0,
            })

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if self.stack:
            node = self.stack[-1]
            if (self.annotate_empty and node["tag"] == tag and tag in self.TEXT_ELEMENTS and not node["id"]
                    and not node["children"] and not node["texts"]):
                self.parts.append(
                    f'<span data-layout-id="text-{node["path"]}-1" '
                    'data-layout-label="Texto" data-layout-text></span>'
                )
        self.parts.append(f"</{tag}>")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(node["tag"] in self.SKIP_ELEMENTS for node in self.stack):
            self.parts.append(data)
            return
        text = html_lib.escape(data)
        if data.strip() and self.stack and not self.stack[-1]["id"]:
            node = self.stack[-1]
            node["texts"] += 1
            element_id = f'text-{node["path"]}-{node["texts"]}'
            text = f'<span data-layout-id="{element_id}" data-layout-label="Texto" data-layout-text>{text}</span>'
        self.parts.append(text)

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")


class CharacterLayoutParser(LayoutTextParser):
    def __init__(self, parents: set[str]) -> None:
        super().__init__()
        self.parents = parents
        self.annotate_empty = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self.stack and self.stack[-1]["id"] in self.parents:
            parent = self.stack[-1]["id"]
            self.offsets[parent] = self.offsets.get(parent, 0) + 1
        super().handle_starttag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self.stack and self.stack[-1]["id"] in self.parents:
            parent = self.stack[-1]["id"]
            self.offsets[parent] = self.offsets.get(parent, 0) + 1
        super().handle_startendtag(tag, attrs)

    def handle_data(self, data: str) -> None:
        parent = self.stack[-1]["id"] if self.stack else ""
        if parent not in self.parents:
            self.parts.append(html_lib.escape(data))
            return
        for word in re.split(r"(\s+)", data):
            grouped = bool(word and not word.isspace())
            if grouped:
                self.parts.append("<span data-layout-word>")
            for character in word:
                index = self.offsets.get(parent, 0)
                self.offsets[parent] = index + 1
                self.parts.append(
                    f'<span data-layout-id="char-{parent}-{index}" data-layout-character '
                    f'data-layout-parent="{parent}">{html_lib.escape(character)}</span>'
                )
            if grouped:
                self.parts.append("</span>")


class TemplateOverrideParser(HTMLParser):
    VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, text_overrides: dict[str, str], asset_sources: dict[str, str]) -> None:
        super().__init__(convert_charrefs=False)
        self.text_overrides = text_overrides
        self.asset_sources = asset_sources
        self.parts: list[str] = []
        self.suppressed_depth = 0
        self.replacement_text = ""

    @property
    def rendered(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.suppressed_depth:
            if tag not in self.VOID_ELEMENTS:
                self.suppressed_depth += 1
            return
        raw = self.get_starttag_text()
        attributes = dict(attrs)
        element_id = attributes.get("data-layout-id", "") or ""
        if tag == "img" and element_id in self.asset_sources:
            raw = replace_html_attribute(raw, "src", self.asset_sources[element_id])
        self.parts.append(raw)
        if tag not in self.VOID_ELEMENTS and element_id in self.text_overrides:
            self.suppressed_depth = 1
            self.replacement_text = self.text_overrides[element_id]

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.suppressed_depth:
            return
        raw = self.get_starttag_text()
        attributes = dict(attrs)
        element_id = attributes.get("data-layout-id", "") or ""
        if tag == "img" and element_id in self.asset_sources:
            raw = replace_html_attribute(raw, "src", self.asset_sources[element_id])
        self.parts.append(raw)

    def handle_endtag(self, tag: str) -> None:
        if self.suppressed_depth:
            self.suppressed_depth -= 1
            if self.suppressed_depth == 0:
                text = html_lib.escape(self.replacement_text).replace("\r\n", "\n").replace("\r", "\n")
                self.parts.append(text.replace("\n", "<br>"))
                self.parts.append(f"</{tag}>")
                self.replacement_text = ""
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(f"<?{data}>")


def replace_html_attribute(tag: str, name: str, value: str) -> str:
    escaped = html_lib.escape(value, quote=True)
    pattern = re.compile(rf"(\s{name}\s*=\s*)([\"']).*?\2", re.IGNORECASE | re.DOTALL)
    if pattern.search(tag):
        return pattern.sub(lambda match: f'{match.group(1)}"{escaped}"', tag, count=1)
    closing = "/>" if tag.rstrip().endswith("/>") else ">"
    return tag.rstrip()[: -len(closing)] + f' {name}="{escaped}"' + closing


def layout_number(value: object, fallback: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return min(upper, max(lower, number))


def save_print_html(slug: str, output_path: Path, context: dict | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_print_html(slug, context), encoding="utf-8")
    return output_path


def render_print_pdf(slug: str, context: dict | None = None, *, store: dict | None = None) -> bytes:
    # The free server must not render several font/image-heavy PDFs concurrently.
    with PDF_RENDER_LOCK:
        return _render_print_pdf(slug, context, store=store)


def _render_print_pdf(slug: str, context: dict | None = None, *, store: dict | None = None) -> bytes:
    spec = TEMPLATE_BY_SLUG[slug]
    data = template_sample_context(slug)
    if context:
        data.update(context)
    try:
        return render_weasy_pdf(slug, data, store=store)
    except ImportError:
        pdf_error = "WeasyPrint no está instalado."
    except Exception as exc:
        pdf_error = str(exc)
    import data_store

    if data_store.get_template_layout(slug, store=store).get("elements") or data_store.get_template_assets(slug, store=store):
        raise RuntimeError(
            "No se pudo exportar el diseño guardado. Verifica el motor WeasyPrint y sus "
            "bibliotecas en Render (despliegue Docker). No se generó un PDF simplificado "
            "porque perdería tus ajustes. Detalle: " + pdf_error
        )
    print(f"[recepción] Usando PDF simplificado: {pdf_error}")
    reportlab_renderers = {
        "preliminares": render_preliminares_pdf,
        "recibo-metales": render_recibo_pdf,
        "reporte-analisis": render_reporte_analisis_pdf,
        "boletin": render_boletin_pdf,
        "certificado-regalias": render_certificado_pdf,
        "certificado-anual": render_certificado_pdf,
    }
    if slug in reportlab_renderers:
        return reportlab_renderers[slug](data, spec.title)
    raise RuntimeError("No hay motor PDF disponible para este documento.")


def render_weasy_pdf(slug: str, context: dict | None = None, *, store: dict | None = None) -> bytes:
    from weasyprint import HTML
    import data_store

    if store is None:
        store = data_store.load_store()
    layout = data_store.get_template_layout(slug, store=store)
    zoom = pdf_zoom(slug, layout)
    page_size, page_margin = pdf_page_box(slug, zoom)
    html = absolutize_static_urls(
        render_print_html(
            slug,
            context,
            include_print_scale=False,
            page_size=page_size,
            page_margin=page_margin,
            store=store,
        )
    )
    return HTML(string=html, base_url=WEBAPP_DIR.as_uri()).write_pdf(zoom=zoom)


def pdf_zoom(slug: str, layout: dict | None = None) -> float:
    zoom = {
        "preliminares": 0.62,
        "recibo-metales": 0.62,
        "reporte-analisis": 0.62,
        "certificado-regalias": 0.89,
    }.get(slug, 1.0)
    original, _rows, _cells, _images = template_table_geometry(slug)
    if not original:
        return zoom
    if layout is None:
        import data_store

        layout = data_store.get_template_layout(slug)
    width = sum(resized_column_widths(original, (layout or {}).get("elements", {})))
    spec = TEMPLATE_BY_SLUG[slug]
    page_width = 215.9 if spec.page_size.lower() == "letter" else 210.0
    margin = float(spec.page_margin.removesuffix("mm"))
    available_width = (page_width - margin * 2) * 96 / 25.4
    return min(zoom, available_width / width)


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


def print_scale_css(slug: str, layout: dict | None = None) -> str:
    scale = pdf_zoom(slug, layout)
    if scale == 1:
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
