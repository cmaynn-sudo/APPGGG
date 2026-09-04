from __future__ import annotations

import argparse
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

import calculations
import core
import data_store
import renderer
from html_exporter import export_all_templates
from template_catalog import SAMPLE_CONTEXT, STATIC_DIR, TEMPLATE_BY_SLUG, TEMPLATE_DIR, TEMPLATES


env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=ChainableUndefined,
)


class RecepcionHandler(BaseHTTPRequestHandler):
    server_version = "RecepcionWeb/0.1"

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        html_routes = {"/", "/documentos", "/leyes", "/boletines", "/certificados", "/sociedades", "/regalias"}
        if path in html_routes or path.startswith("/plantillas/") or path.startswith("/print/"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if path.startswith("/api/"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                self.render_dashboard()
            elif path == "/documentos":
                self.render_documentos()
            elif path == "/leyes":
                self.render_leyes()
            elif path == "/boletines":
                self.render_boletines()
            elif path == "/certificados":
                self.render_certificados(query)
            elif path == "/sociedades":
                self.render_sociedades()
            elif path == "/regalias":
                self.render_regalias()
            elif path.startswith("/print/"):
                self.render_business_print(path)
            elif path == "/api/sociedades":
                self.send_json(data_store.load_store().get("sociedades", []))
            elif path == "/api/regalias":
                self.send_json(data_store.load_store().get("regalias", []))
            elif path.startswith("/plantillas/"):
                parts = [part for part in path.split("/") if part]
                slug = parts[1] if len(parts) > 1 else ""
                if len(parts) == 3 and parts[2] == "print":
                    self.render_template_print(slug)
                else:
                    self.render_template_preview(slug)
            elif path.startswith("/static/"):
                self.serve_static(path)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            form = self.read_form()
            if path == "/documentos/crear":
                data_store.create_entrega(form.get("numero", ""))
                self.redirect("/documentos")
            elif path == "/documentos/agregar":
                data_store.add_entrega_item(form)
                self.redirect("/documentos")
            elif path == "/leyes/guardar":
                data_store.update_ley(form)
                self.redirect("/leyes")
            elif path == "/boletines/parametros":
                data_store.update_parametros(form)
                self.redirect("/boletines")
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")
        except Exception as exc:
            self.render_error(str(exc))

    def render_dashboard(self) -> None:
        year, month = core.current_period()
        years = core.list_years()
        selected_year = year if year in years else (years[-1] if years else year)
        months = core.list_months_for_year(selected_year)
        selected_month = month if month in months else (months[-1] if months else month)
        self.render(
            "dashboard.html",
            {
                "templates": TEMPLATES,
                "sociedades": data_store.load_store().get("sociedades", []),
                "regalias": data_store.load_store().get("regalias", []),
                "years": years,
                "selected_year": selected_year,
                "selected_month": selected_month,
                "months": months,
                "entregas": core.list_entregas(selected_year, selected_month),
                "root_base": core.ROOT_BASE,
                "web_entregas": data_store.list_entregas(),
            },
        )

    def render_documentos(self) -> None:
        store = data_store.load_store()
        entrega = data_store.get_entrega()
        context = {
            "sociedades": store.get("sociedades", []),
            "entregas": data_store.list_entregas(),
            "entrega": entrega,
            "preliminares_context": calculations.preliminares_context(entrega.get("items", [])) if entrega else None,
        }
        self.render("documentos.html", context)

    def render_leyes(self) -> None:
        entrega = data_store.get_entrega()
        self.render("leyes.html", {"entrega": entrega, "entregas": data_store.list_entregas()})

    def render_boletines(self) -> None:
        store = data_store.load_store()
        entrega = data_store.get_entrega()
        boletines = data_store.boletines_for_entrega(entrega) if entrega else []
        self.render(
            "boletines.html",
            {
                "entrega": entrega,
                "entregas": data_store.list_entregas(),
                "boletines": boletines,
                "regalias": store.get("regalias", []),
            },
        )

    def render_certificados(self, query: dict) -> None:
        year = query.get("year", [""])[0]
        month = query.get("month", [""])[0]
        if not year or not month:
            current_year, current_month = core.current_period()
            year = year or current_year
            month = month or current_month
        self.render(
            "certificados.html",
            {
                "year": year,
                "month": month,
                "years": sorted({e.get("year", "") for e in data_store.list_entregas() if e.get("year")}),
                "months": core.MESES_ORDEN,
                "groups": data_store.certificado_groups(year, month),
            },
        )

    def render_sociedades(self) -> None:
        self.render("sociedades.html", {"sociedades": data_store.load_store().get("sociedades", [])})

    def render_regalias(self) -> None:
        self.render("regalias.html", {"regalias": data_store.load_store().get("regalias", [])})

    def render_template_preview(self, slug: str) -> None:
        spec = TEMPLATE_BY_SLUG.get(slug)
        if not spec:
            self.send_error(HTTPStatus.NOT_FOUND, "Plantilla no encontrada")
            return
        self.render(
            "template_preview.html",
            {
                "template": spec,
                "generated_template": spec.generated_template_name,
                **SAMPLE_CONTEXT,
            },
        )

    def render_template_print(self, slug: str) -> None:
        if slug not in TEMPLATE_BY_SLUG:
            self.send_error(HTTPStatus.NOT_FOUND, "Plantilla no encontrada")
            return
        body = renderer.render_print_html(slug).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render_business_print(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            self.send_error(HTTPStatus.NOT_FOUND, "Documento no encontrado")
            return
        doc_type = parts[1]

        if doc_type == "certificado" and len(parts) >= 5:
            year = parts[2]
            month = parts[3]
            key = parts[4]
            group = next((g for g in data_store.certificado_groups(year, month) if g["key"] == key), None)
            if not group:
                self.send_error(HTTPStatus.NOT_FOUND, "Certificado no encontrado")
                return
            self.send_print("certificado-regalias", calculations.certificado_context(group["sociedad"], group["nit"], group["boletines"]))
            return

        entrega_id = parts[2]
        entrega = data_store.get_entrega(entrega_id)
        if not entrega:
            self.send_error(HTTPStatus.NOT_FOUND, "Entrega no encontrada")
            return

        if doc_type == "preliminares":
            context = calculations.preliminares_context(entrega.get("items", []))
            context.update({"entrega": entrega.get("numero", ""), "fecha": entrega.get("fecha", "")})
            self.send_print("preliminares", context)
            return
        if doc_type == "recibo" and len(parts) >= 4:
            item = self.find_item(entrega, parts[3])
            self.send_print("recibo-metales", calculations.recibo_context(item))
            return
        if doc_type == "reporte-analisis" and len(parts) >= 4:
            item = self.find_item(entrega, parts[3])
            self.send_print("reporte-analisis", calculations.reporte_analisis_context(item))
            return
        if doc_type == "boletin" and len(parts) >= 4:
            item = self.find_item(entrega, parts[3])
            store = data_store.load_store()
            parametros = entrega.get("parametros", {})
            regalias = data_store.get_regalias_for_month(store, parametros.get("mes_regalias", entrega.get("month", "")))
            self.send_print("boletin", calculations.boletin_context(item, parametros, regalias))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Documento no encontrado")

    def find_item(self, entrega: dict, item_id: str) -> dict:
        item = next((item for item in entrega.get("items", []) if item.get("id") == item_id), None)
        if not item:
            raise ValueError("Registro no encontrado en la entrega.")
        return item

    def send_print(self, slug: str, context: dict) -> None:
        body = renderer.render_print_html(slug, context).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render_error(self, message: str) -> None:
        self.render("error.html", {"message": message})

    def render(self, template_name: str, context: dict) -> None:
        body = env.get_template(template_name).render(**context).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data) -> None:
        body = core.json_response(data)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def serve_static(self, request_path: str) -> None:
        rel = request_path.removeprefix("/static/").lstrip("/")
        file_path = (STATIC_DIR / rel).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Archivo no encontrado")
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    default_host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    parser = argparse.ArgumentParser(description="Recepcion web local")
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--no-refresh-templates", action="store_true")
    args = parser.parse_args()

    if not args.no_refresh_templates and os.environ.get("RENDER") != "true":
        export_all_templates()

    httpd = ThreadingHTTPServer((args.host, args.port), RecepcionHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Recepcion web disponible en {url}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
