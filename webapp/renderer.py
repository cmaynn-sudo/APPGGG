from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

from template_catalog import SAMPLE_CONTEXT, STATIC_DIR, TEMPLATE_BY_SLUG, TEMPLATE_DIR, WEBAPP_DIR


env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=ChainableUndefined,
)


def render_print_html(slug: str, context: dict | None = None) -> str:
    spec = TEMPLATE_BY_SLUG[slug]
    data = dict(SAMPLE_CONTEXT)
    if context:
        data.update(context)
    body = env.get_template(spec.render_template_name).render(**data)
    print_css = (STATIC_DIR / "print.css").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{spec.title}</title>
  <style>
    @page {{ size: {spec.page_size}; margin: {spec.page_margin}; }}
    body {{ margin: 0; background: white; }}
    {print_css}
    .doc-sheet {{ box-shadow: none; margin: 0 auto; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def save_print_html(slug: str, output_path: Path, context: dict | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_print_html(slug, context), encoding="utf-8")
    return output_path


def render_print_pdf(slug: str, context: dict | None = None) -> bytes:
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise RuntimeError("Falta instalar xhtml2pdf para descargar documentos en PDF.") from exc

    import io

    html = render_print_html(slug, context)
    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer, link_callback=asset_path)
    if result.err:
        raise RuntimeError("No se pudo generar el PDF del documento.")
    return buffer.getvalue()


def asset_path(uri: str, _rel: str = "") -> str:
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path or uri)
    if raw_path.startswith("/static/"):
        candidate = (WEBAPP_DIR / raw_path.lstrip("/")).resolve()
        if str(candidate).startswith(str(WEBAPP_DIR.resolve())):
            return str(candidate)
    return uri
