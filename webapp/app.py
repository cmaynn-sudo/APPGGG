from __future__ import annotations

import argparse
import hashlib
import io
import mimetypes
import os
import re
import zipfile
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

import auth
import analytics
import calculations
import core
import data_store
import document_library
import historical_import
import persistence
import renderer
from html_exporter import export_all_templates
from template_catalog import CERTIFICADO_ANUAL, SAMPLE_CONTEXT, STATIC_DIR, TEMPLATE_BY_SLUG, TEMPLATE_DIR, TEMPLATES


env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=ChainableUndefined,
)

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
PERSISTENCE_RECOVERY_PATHS = {
    "/respaldo/importar",
    "/respaldo/guardar-remoto",
    "/respaldo/guardar-github",
    "/respaldo/restaurar-remoto",
    "/respaldo/restaurar-github",
}


def static_asset_version() -> str:
    digest = hashlib.sha256()
    for filename in ("app.css", "print.css", "app.js"):
        path = STATIC_DIR / filename
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


ASSET_VERSION = static_asset_version()


class RecepcionHandler(BaseHTTPRequestHandler):
    server_version = "RecepcionWeb/0.2"

    def do_HEAD(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path.startswith("/static/"):
                self.serve_static(path)
                return
            if path == "/login":
                self.render_login(query)
                return
            if path == "/logout":
                self.logout()
                return
            if not self.require_login():
                return

            if path == "/":
                self.render_dashboard(query)
            elif path == "/documentos":
                self.render_documentos(query)
            elif path == "/leyes":
                self.render_leyes()
            elif path == "/boletines":
                self.render_boletines()
            elif path.startswith("/boletines/") and path.endswith("/facturacion.txt"):
                entrega_id = unquote(path.removeprefix("/boletines/").removesuffix("/facturacion.txt"))
                self.download_facturacion(entrega_id)
            elif path == "/certificados":
                self.render_certificados(query)
            elif path == "/sociedades":
                self.render_sociedades()
            elif path == "/regalias":
                self.render_regalias()
            elif path == "/parametros":
                self.render_parametros()
            elif path == "/control-datos":
                self.render_data_quality(query)
            elif path == "/editor-plantillas":
                self.render_layout_editor(query)
            elif path == "/respaldo":
                self.render_respaldo(query)
            elif path == "/respaldo/descargar":
                self.download_state_backup()
            elif path == "/entregas":
                self.render_entregas(query)
            elif path.startswith("/entregas/web/") and path.endswith("/descargar"):
                folder_id = unquote(path.removeprefix("/entregas/web/").removesuffix("/descargar").strip("/"))
                self.download_folder_zip("web", folder_id)
            elif path.startswith("/entregas/local/") and path.endswith("/descargar"):
                folder_id = unquote(path.removeprefix("/entregas/local/").removesuffix("/descargar").strip("/"))
                self.download_folder_zip("local", folder_id)
            elif path.startswith("/entregas/importadas/") and path.endswith("/descargar"):
                folder_id = unquote(path.removeprefix("/entregas/importadas/").removesuffix("/descargar").strip("/"))
                self.download_folder_zip("importadas", folder_id)
            elif path.startswith("/entregas/web/"):
                folder_id = unquote(path.removeprefix("/entregas/web/").strip("/"))
                self.render_entrega_detail("web", folder_id)
            elif path.startswith("/entregas/local/"):
                folder_id = unquote(path.removeprefix("/entregas/local/").strip("/"))
                self.render_entrega_detail("local", folder_id)
            elif path.startswith("/entregas/importadas/"):
                folder_id = unquote(path.removeprefix("/entregas/importadas/").strip("/"))
                self.render_entrega_detail("importadas", folder_id)
            elif path.startswith("/archivos/importado/"):
                file_id = unquote(path.removeprefix("/archivos/importado/").strip("/"))
                self.serve_imported_file(file_id, download=self.wants_download(query))
            elif path.startswith("/archivos/subido/"):
                file_id = unquote(path.removeprefix("/archivos/subido/").strip("/"))
                self.serve_uploaded_file(file_id, download=self.wants_download(query))
            elif path.startswith("/plantillas/asset/"):
                parts = [unquote(part) for part in path.split("/") if part]
                if len(parts) != 4:
                    self.send_error(HTTPStatus.NOT_FOUND, "Imagen de plantilla no encontrada")
                    return
                self.serve_template_asset(parts[2], parts[3])
            elif path.startswith("/print/"):
                self.render_business_print(path, query)
            elif path == "/api/sociedades":
                self.send_json(data_store.load_store().get("sociedades", []))
            elif path == "/api/regalias":
                self.send_json(data_store.load_store().get("regalias", []))
            elif path.startswith("/plantillas/"):
                parts = [part for part in path.split("/") if part]
                slug = parts[1] if len(parts) > 1 else ""
                if len(parts) == 3 and parts[2] == "print":
                    self.render_template_print(slug, query)
                else:
                    self.render_template_preview(slug)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            if path == "/login":
                self.handle_login()
                return
            if not self.require_login():
                return
            if path not in PERSISTENCE_RECOVERY_PATHS:
                data_store.load_store()
                storage_error = persistence.write_block_reason()
                if storage_error:
                    self.render_error(storage_error, HTTPStatus.SERVICE_UNAVAILABLE)
                    return

            if path == "/entregas/upload":
                fields, files = self.read_multipart_form()
                self.handle_upload(fields, files)
                return
            if path == "/entregas/importar-carpeta":
                _fields, files = self.read_multipart_form()
                historical_import.import_uploaded_history(files)
                self.redirect("/entregas?importacion=ok")
                return
            if path == "/entregas/importar-historico":
                _fields, files = self.read_multipart_form()
                historical_import.import_uploaded_history(files)
                self.redirect("/entregas?importacion=ok")
                return
            if path == "/entregas/reorganizar-historico":
                form = self.read_form()
                historical_import.reorganize_existing_folder(form.get("folder_id", ""))
                self.redirect("/entregas?importacion=ok&reorganizada=1")
                return
            if path == "/respaldo/importar":
                _fields, files = self.read_multipart_form()
                self.import_state_backup(files)
                return
            if path == "/editor-plantillas/imagen":
                fields, files = self.read_multipart_form()
                self.handle_template_asset_upload(fields, files)
                return

            form = self.read_form()
            if path == "/documentos/crear":
                data_store.create_entrega(form.get("numero", ""))
                self.redirect("/documentos")
            elif path == "/entregas/reconstruir":
                data_store.create_historical_entrega(form)
                self.redirect("/documentos?historica=ok")
            elif path == "/documentos/activar":
                data_store.set_active_entrega(form.get("entrega_id", ""))
                self.redirect(form.get("next", "/documentos"))
            elif path == "/documentos/finalizar":
                data_store.finalize_entrega(form.get("entrega_id", ""))
                self.redirect(form.get("next", "/documentos?finalizada=ok") or "/documentos?finalizada=ok")
            elif path == "/documentos/reabrir":
                data_store.reopen_entrega(form.get("entrega_id", ""))
                self.redirect(form.get("next", "/documentos?reabierta=ok") or "/documentos?reabierta=ok")
            elif path == "/documentos/agregar":
                data_store.add_entrega_item(form)
                self.redirect("/documentos")
            elif path == "/documentos/editar-item":
                data_store.update_entrega_item(form)
                self.redirect(form.get("next", "/documentos") or "/documentos")
            elif path == "/documentos/eliminar-item":
                data_store.delete_entrega_item(form.get("entrega_id", ""), form.get("item_id", ""))
                self.redirect(form.get("next", "/documentos") or "/documentos")
            elif path == "/leyes/guardar":
                data_store.update_ley(form)
                self.redirect("/leyes")
            elif path == "/leyes/eliminar":
                data_store.clear_ley(form)
                self.redirect("/leyes")
            elif path == "/boletines/parametros":
                data_store.update_parametros(form)
                self.redirect("/boletines")
            elif path == "/boletines/parametros/eliminar":
                data_store.clear_parametros(form.get("entrega_id", ""))
                self.redirect("/boletines")
            elif path == "/regalias/guardar":
                data_store.upsert_regalia(form)
                self.redirect("/regalias")
            elif path == "/regalias/eliminar":
                data_store.delete_regalia(form.get("mes", ""))
                self.redirect("/regalias")
            elif path == "/sociedades/guardar":
                data_store.upsert_sociedad(form)
                self.redirect("/sociedades")
            elif path == "/sociedades/eliminar":
                data_store.delete_sociedad(form.get("sociedad", ""))
                self.redirect("/sociedades")
            elif path == "/parametros/boletines":
                data_store.update_boletin_settings(form)
                self.redirect("/parametros")
            elif path == "/control-datos/guardar":
                data_store.upsert_dashboard_override(form)
                self.redirect("/control-datos?msg=Correcci%C3%B3n%20informativa%20guardada")
            elif path == "/control-datos/eliminar":
                data_store.delete_dashboard_override(form.get("quality_id", ""))
                self.redirect("/control-datos?msg=Correcci%C3%B3n%20informativa%20eliminada")
            elif path == "/editor-plantillas/guardar":
                slug = form.get("slug", "")
                data_store.update_template_layout(slug, form.get("layout_json", "{}"))
                self.redirect(
                    f"/editor-plantillas?plantilla={quote(slug)}&msg=Dise%C3%B1o%20guardado"
                )
            elif path == "/editor-plantillas/restablecer":
                slug = form.get("slug", "")
                data_store.reset_template_layout(slug)
                self.redirect(
                    f"/editor-plantillas?plantilla={quote(slug)}&msg=Dise%C3%B1o%20restablecido"
                )
            elif path == "/editor-plantillas/imagen/eliminar":
                slug = form.get("slug", "")
                element_id = form.get("element_id", "")
                data_store.delete_template_asset(slug, element_id)
                if self.headers.get("X-Requested-With") == "fetch":
                    self.send_json({"ok": True, "element_id": element_id})
                else:
                    self.redirect(
                        f"/editor-plantillas?plantilla={quote(slug)}&msg=Imagen%20original%20restaurada"
                    )
            elif path == "/entregas/eliminar":
                self.delete_folder(form)
            elif path == "/archivos/eliminar":
                self.delete_file(form)
            elif path in {"/respaldo/guardar-remoto", "/respaldo/guardar-github"}:
                self.save_state_to_remote()
            elif path in {"/respaldo/restaurar-remoto", "/respaldo/restaurar-github"}:
                self.restore_state_from_remote()
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")
        except Exception as exc:
            self.render_error(str(exc))

    def render_dashboard(self, query: dict) -> None:
        store = data_store.load_store()
        folders = document_library.all_folders()
        imported = [folder for folder in folders if folder.get("source") != "web"]
        dashboard = analytics.dashboard_summary(
            {
                key: query.get(key, [""])[0]
                for key in ("year", "month", "entrega", "proveedor")
            }
        )
        self.render(
            "dashboard.html",
            {
                "templates": TEMPLATES,
                "sociedades": store.get("sociedades", []),
                "regalias": store.get("regalias", []),
                "document_folders": folders,
                "imported_folders": imported,
                "web_entregas": data_store.list_entregas(),
                "exported_at": document_library.exported_at_label(),
                "backup_status": persistence.runtime_status(data_store.DATA_DIR),
                "dashboard": dashboard,
            },
        )

    def render_documentos(self, query: dict | None = None) -> None:
        query = query or {}
        store = data_store.load_store()
        entrega = data_store.get_entrega()
        context = {
            "sociedades": store.get("sociedades", []),
            "entregas": data_store.list_entregas(include_finalized=False),
            "all_entregas": data_store.list_entregas(),
            "entrega": entrega,
            "preliminares_context": calculations.preliminares_context(entrega.get("items", [])) if entrega else None,
            "generated_docs": document_library.generated_documents_for_entrega(entrega) if entrega else [],
            "historical_created": query.get("historica", [""])[0] == "ok",
            "finalized_success": query.get("finalizada", [""])[0] == "ok",
            "reopened_success": query.get("reabierta", [""])[0] == "ok",
        }
        self.render("documentos.html", context)

    def render_leyes(self) -> None:
        entrega = data_store.get_entrega()
        self.render(
            "leyes.html",
            {"entrega": entrega, "entregas": data_store.list_entregas(include_finalized=False)},
        )

    def render_boletines(self) -> None:
        store = data_store.load_store()
        entrega = data_store.get_entrega()
        boletines = data_store.boletines_for_entrega(entrega) if entrega else []
        self.render(
            "boletines.html",
            {
                "entrega": entrega,
                "entregas": data_store.list_entregas(include_finalized=False),
                "boletines": boletines,
                "regalias": store.get("regalias", []),
                "settings": data_store.get_entrega_boletin_settings(entrega, store) if entrega else data_store.get_boletin_settings(store),
                "months": core.MESES_ORDEN,
            },
        )

    def download_facturacion(self, entrega_id: str) -> None:
        entrega = data_store.get_entrega(entrega_id) if entrega_id else None
        if not entrega:
            self.send_error(HTTPStatus.NOT_FOUND, "Entrega no encontrada")
            return
        boletines = data_store.boletines_for_entrega(entrega)
        if not boletines:
            self.send_error(HTTPStatus.NOT_FOUND, "Esta entrega no tiene boletines listos")
            return
        body = calculations.facturacion_text(boletines).encode("utf-8-sig")
        self.send_bytes(body, "text/plain; charset=utf-8", filename="FACTURACION.txt", attachment=True)

    def render_certificados(self, query: dict) -> None:
        period = "annual" if query.get("period", [""])[0] == "annual" else "monthly"
        year = query.get("year", [""])[0]
        month = query.get("month", [""])[0]
        current_year, current_month = core.current_period()
        year = year or current_year
        if period == "monthly":
            month = month if month in core.MESES_ORDEN else current_month
        else:
            month = ""
        years = data_store.certificado_years() or [year]
        if year not in years:
            year = years[0]
        self.render(
            "certificados.html",
            {
                "period": period,
                "year": year,
                "month": month,
                "years": years,
                "months": core.MESES_ORDEN,
                "groups": data_store.certificado_groups(year, month if period == "monthly" else None),
            },
        )

    def render_sociedades(self) -> None:
        self.render("sociedades.html", {"sociedades": data_store.load_store().get("sociedades", [])})

    def render_regalias(self) -> None:
        self.render("regalias.html", {"regalias": data_store.load_store().get("regalias", []), "months": core.MESES_ORDEN})

    def render_parametros(self) -> None:
        store = data_store.load_store()
        self.render(
            "parametros.html",
            {
                "settings": data_store.get_boletin_settings(store),
            },
        )

    def render_data_quality(self, query: dict) -> None:
        store = data_store.load_store()
        quality = analytics.dashboard_data_quality(document_library.all_folders(), store)
        self.render(
            "data_quality.html",
            {
                "quality": quality,
                "message": query.get("msg", [""])[0],
            },
        )

    def render_layout_editor(self, query: dict) -> None:
        slug = query.get("plantilla", ["recibo-metales"])[0]
        if slug not in TEMPLATE_BY_SLUG:
            slug = "recibo-metales"
        spec = TEMPLATE_BY_SLUG[slug]
        sample_context = renderer.template_sample_context(slug)
        layout = data_store.get_template_layout(slug)
        assets = data_store.get_template_assets(slug)
        asset_urls = {
            element_id: {
                "url": f"/plantillas/asset/{quote(slug, safe='')}/{quote(element_id, safe='')}?v={quote(metadata.get('updated_at', ''), safe='')}",
                "filename": metadata.get("filename", "Imagen personalizada"),
            }
            for element_id, metadata in assets.items()
        }
        self.render(
            "layout_editor.html",
            {
                "templates": [*TEMPLATES, CERTIFICADO_ANUAL],
                "template": spec,
                "generated_template": spec.render_template_name,
                "preview_html": renderer.prepare_template_layout(
                    env.get_template(spec.render_template_name).render(**sample_context)
                ),
                "layout": layout,
                "template_assets": asset_urls,
                "layout_css": renderer.template_layout_css(slug, layout),
                "message": query.get("msg", [""])[0],
                **sample_context,
            },
        )

    def render_respaldo(self, query: dict) -> None:
        message = query.get("msg", [""])[0]
        error = query.get("error", [""])[0]
        self.render(
            "respaldo.html",
            {
                "backup_status": persistence.runtime_status(data_store.DATA_DIR),
                "message": message,
                "error": error,
            },
        )

    def render_entregas(self, query: dict) -> None:
        store = data_store.load_store()
        all_folders = document_library.all_folders()
        diagnostics = analytics.historical_pdf_diagnostics(all_folders, store)
        requested_rebuild = query.get("reconstruir", [""])[0]
        selected_issue = next(
            (group for group in diagnostics["groups"] if group["folder_id"] == requested_rebuild),
            None,
        )
        global_settings = data_store.get_boletin_settings(store)
        reconstruction_defaults = {
            "source_folder_id": selected_issue.get("folder_id", "") if selected_issue else "",
            "numero": selected_issue.get("delivery_number", "") if selected_issue else "",
            "fecha": selected_issue.get("date", "") if selected_issue else "",
            "mes_regalias": selected_issue.get("month", "") if selected_issue else "",
            "dolar": "",
            "oz_au": "",
            "oz_ag": "",
            "precio_negociacion_porcentaje": global_settings["precio_negociacion_porcentaje"],
            "retencion_porcentaje": global_settings["retencion_porcentaje"],
        }
        folders = list(all_folders)
        q = query.get("q", [""])[0].strip().lower()
        source = query.get("source", [""])[0]
        if q:
            folders = [folder for folder in folders if q in folder.get("name", "").lower() or q in folder.get("month", "").lower()]
        if source:
            folders = [folder for folder in folders if folder.get("source") == source]
        self.render(
            "entregas.html",
            {
                "folders": folders,
                "query": q,
                "source": source,
                "exported_at": document_library.exported_at_label(),
                "import_success": query.get("importacion", [""])[0] == "ok",
                "last_import": store.get("last_historical_import", {}),
                "legacy_candidates": historical_import.legacy_folder_candidates(store),
                "reorganized_success": query.get("reorganizada", [""])[0] == "1",
                "diagnostics": diagnostics,
                "reconstruction_open": bool(requested_rebuild or query.get("manual", [""])[0] == "1"),
                "reconstruction_defaults": reconstruction_defaults,
                "months": core.MESES_ORDEN,
            },
        )

    def render_entrega_detail(self, source: str, folder_id: str) -> None:
        detail = document_library.folder_detail(source, folder_id)
        if not detail:
            self.send_error(HTTPStatus.NOT_FOUND, "Entrega no encontrada")
            return
        self.render(
            "entrega_detail.html",
            {
                "folder": detail,
                "groups": document_library.grouped_documents(detail.get("docs", [])),
                "next_url": self.path,
            },
        )

    def render_template_preview(self, slug: str) -> None:
        spec = TEMPLATE_BY_SLUG.get(slug)
        if not spec:
            self.send_error(HTTPStatus.NOT_FOUND, "Plantilla no encontrada")
            return
        sample_context = renderer.template_sample_context(slug)
        layout = data_store.get_template_layout(slug)
        preview_html = renderer.prepare_template_layout(
            env.get_template(spec.render_template_name).render(**sample_context)
        )
        self.render(
            "template_preview.html",
            {
                "template": spec,
                "generated_template": spec.render_template_name,
                "preview_html": renderer.apply_template_content_overrides(
                    preview_html, layout, data_store.get_template_assets(slug)
                ),
                "layout_css": renderer.template_layout_css(slug, layout),
                **sample_context,
            },
        )

    def render_template_print(self, slug: str, query: dict) -> None:
        if slug not in TEMPLATE_BY_SLUG:
            self.send_error(HTTPStatus.NOT_FOUND, "Plantilla no encontrada")
            return
        filename = f"{TEMPLATE_BY_SLUG[slug].title}.pdf"
        self.send_print(slug, {}, download=self.wants_download(query), filename=filename)

    def render_business_print(self, path: str, query: dict) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            self.send_error(HTTPStatus.NOT_FOUND, "Documento no encontrado")
            return
        doc_type = parts[1]
        download = self.wants_download(query)

        if doc_type == "certificado" and len(parts) >= 5:
            year = parts[2]
            month = parts[3]
            key = parts[4]
            group = next((g for g in data_store.certificado_groups(year, month) if g["key"] == key), None)
            if not group:
                self.send_error(HTTPStatus.NOT_FOUND, "Certificado no encontrado")
                return
            filename = f"CERTIFICADO DE REGALÍAS {group['sociedad']} - {month}.pdf"
            self.send_print(
                "certificado-regalias",
                calculations.certificado_context(group["sociedad"], group["nit"], group["boletines"]),
                download=download,
                filename=filename,
            )
            return

        if doc_type == "certificado-anual" and len(parts) >= 4:
            year = parts[2]
            key = parts[3]
            group = next((g for g in data_store.certificado_groups(year) if g["key"] == key), None)
            if not group:
                self.send_error(HTTPStatus.NOT_FOUND, "Certificado anual no encontrado")
                return
            filename = f"CERTIFICADO ANUAL DE REGALÍAS {group['sociedad']} - {year}.pdf"
            context = calculations.certificado_context(
                group["sociedad"],
                group["nit"],
                group["boletines"],
            )
            context.update({"year": year, "periodo_label": f"Año {year}"})
            self.send_print(
                "certificado-anual",
                context,
                download=download,
                filename=filename,
            )
            return

        entrega_id = parts[2]
        entrega = data_store.get_entrega(entrega_id)
        if not entrega:
            self.send_error(HTTPStatus.NOT_FOUND, "Entrega no encontrada")
            return
        delivery_date = self.entrega_date(entrega)

        if doc_type == "preliminares":
            context = calculations.preliminares_context(entrega.get("items", []), current=delivery_date)
            context.update({"entrega": entrega.get("numero", ""), "fecha": entrega.get("fecha", "")})
            filename = f"PRELIMINARES - {entrega.get('numero', '')} ({entrega.get('fecha', '')}).pdf"
            self.send_print("preliminares", context, download=download, filename=filename)
            return
        if doc_type == "recibo" and len(parts) >= 4:
            item = self.find_item(entrega, parts[3])
            filename = f"{item.get('proveedor', 'RECIBO')} ({item.get('codigo', '')}).pdf"
            self.send_print("recibo-metales", calculations.recibo_context(item, current=delivery_date), download=download, filename=filename)
            return
        if doc_type == "reporte-analisis" and len(parts) >= 4:
            item = self.find_item(entrega, parts[3])
            filename = f"REPORTE LEYES - {item.get('barra', item.get('codigo', ''))}.pdf"
            self.send_print("reporte-analisis", calculations.reporte_analisis_context(item, current=delivery_date), download=download, filename=filename)
            return
        if doc_type == "boletin" and len(parts) >= 4:
            item = self.find_item(entrega, parts[3])
            store = data_store.load_store()
            parametros = entrega.get("parametros", {})
            regalias = data_store.get_regalias_for_month(store, parametros.get("mes_regalias", entrega.get("month", "")))
            settings = data_store.get_entrega_boletin_settings(entrega, store)
            filename = f"BOLETIN - {item.get('barra', item.get('codigo', ''))}.pdf"
            self.send_print("boletin", calculations.boletin_context(item, parametros, regalias, settings, current=delivery_date), download=download, filename=filename)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Documento no encontrado")

    def find_item(self, entrega: dict, item_id: str) -> dict:
        item = next((item for item in entrega.get("items", []) if item.get("id") == item_id), None)
        if not item:
            raise ValueError("Registro no encontrado en la entrega.")
        return item

    def entrega_date(self, entrega: dict) -> date:
        try:
            return date.fromisoformat(str(entrega.get("fecha", "")))
        except ValueError:
            return date.today()

    def handle_login(self) -> None:
        form = self.read_form()
        user = auth.authenticate(form.get("username", ""), form.get("password", ""))
        if not user:
            self.render_login({"next": [form.get("next", "/")]}, "Usuario o contraseña incorrectos.")
            return
        token = auth.create_session(user)
        next_url = form.get("next", "/") or "/"
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", next_url)
        self.send_header("Set-Cookie", auth.session_cookie_header(token, secure=self.is_secure_request()))
        self.end_headers()

    def logout(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", auth.clear_cookie_header())
        self.end_headers()

    def render_login(self, query: dict, error: str = "") -> None:
        if self.current_user():
            next_url = query.get("next", ["/"])[0] or "/"
            self.redirect(next_url)
            return
        next_url = query.get("next", ["/"])[0] or "/"
        self.render("login.html", {"next": next_url, "error": error}, public=True)

    def current_user(self) -> dict | None:
        if not hasattr(self, "_current_user"):
            self._current_user = auth.user_from_cookie(self.headers.get("Cookie"))
        return self._current_user

    def require_login(self) -> bool:
        if self.current_user():
            return True
        next_url = self.path or "/"
        self.redirect(f"/login?next={quote(next_url, safe='')}")
        return False

    def is_secure_request(self) -> bool:
        forwarded = self.headers.get("Forwarded", "")
        return self.headers.get("X-Forwarded-Proto", "") == "https" or "proto=https" in forwarded.lower()

    def handle_upload(self, fields: dict[str, str], files: list[dict[str, object]]) -> None:
        source = fields.get("folder_source", "")
        folder_id = fields.get("folder_id", "")
        if source not in {"web", "imported", "local"}:
            raise ValueError("Carpeta inválida.")
        if source == "web" and not data_store.get_entrega(folder_id):
            raise ValueError("Entrega web no encontrada.")
        if source == "imported" and not document_library.imported_delivery(folder_id):
            raise ValueError("Entrega importada no encontrada.")
        if source == "local" and not data_store.get_local_folder(folder_id):
            raise ValueError("Carpeta local no encontrada.")
        saved = 0
        for file_info in files:
            filename = str(file_info.get("filename") or "")
            content = file_info.get("content") or b""
            if filename and isinstance(content, bytes):
                data_store.save_uploaded_file(source, folder_id, filename, content, str(file_info.get("content_type") or ""))
                saved += 1
        if not saved:
            raise ValueError("Selecciona al menos un archivo.")
        self.redirect(self.folder_url(source, folder_id))

    def delete_folder(self, form: dict[str, str]) -> None:
        source = form.get("folder_source", "")
        folder_id = form.get("folder_id", "")
        if source == "web":
            data_store.delete_entrega(folder_id)
        elif source == "local":
            data_store.delete_local_folder(folder_id)
        elif source == "imported":
            if not document_library.remove_imported_delivery(folder_id):
                raise ValueError("Entrega importada no encontrada.")
            data_store.delete_uploaded_files_for("imported", folder_id)
        else:
            raise ValueError("Carpeta inválida.")
        self.redirect("/entregas")

    def delete_file(self, form: dict[str, str]) -> None:
        kind = form.get("kind", "")
        file_id = form.get("file_id", "")
        if kind == "uploaded":
            data_store.delete_uploaded_file(file_id)
        elif kind == "imported":
            if not document_library.remove_imported_file(file_id):
                raise ValueError("Archivo importado no encontrado.")
        else:
            raise ValueError("Archivo inválido.")
        self.redirect(form.get("next", "/entregas") or "/entregas")

    def download_state_backup(self) -> None:
        archive = persistence.build_backup_archive(data_store.DATA_DIR)
        if not archive:
            self.render_error("Todavía no hay datos para respaldar.")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.send_bytes(
            archive,
            "application/zip",
            filename=f"recepcion-respaldo-{stamp}.zip",
            attachment=True,
        )

    def import_state_backup(self, files: list[dict[str, object]]) -> None:
        backup_file = next((file_info for file_info in files if file_info.get("field") == "respaldo"), None)
        if not backup_file or not isinstance(backup_file.get("content"), bytes):
            raise ValueError("Selecciona un respaldo ZIP.")
        persistence.import_backup_archive(data_store.DATA_DIR, backup_file["content"])
        self.redirect("/respaldo?msg=Respaldo%20restaurado")

    def save_state_to_remote(self) -> None:
        if not persistence.is_configured():
            self.redirect("/respaldo?error=Configura%20Cloudflare%20R2%20o%20GitHub%20en%20Render")
            return
        if persistence.backup_state_if_configured(data_store.DATA_DIR):
            provider = persistence.runtime_status().get("provider", "almacenamiento externo")
            self.redirect(f"/respaldo?msg={quote('Respaldo guardado en ' + provider)}")
            return
        self.redirect("/respaldo?error=No%20se%20pudo%20guardar%20el%20respaldo")

    def restore_state_from_remote(self) -> None:
        if not persistence.is_configured():
            self.redirect("/respaldo?error=Configura%20Cloudflare%20R2%20o%20GitHub%20en%20Render")
            return
        result = persistence.restore_state_from_remote(data_store.DATA_DIR)
        if result == "restored":
            provider = persistence.runtime_status().get("provider", "el almacenamiento externo")
            self.redirect(f"/respaldo?msg={quote('Respaldo restaurado desde ' + provider)}")
            return
        if result == "remote-empty":
            self.redirect("/respaldo?error=No%20hay%20un%20respaldo%20externo%20guardado")
            return
        self.redirect(f"/respaldo?error={quote('No se pudo restaurar el respaldo: ' + result)}")

    def serve_imported_file(self, file_id: str, download: bool = False) -> None:
        file_info, path = document_library.find_imported_file(file_id)
        if not file_info or not path:
            self.send_error(HTTPStatus.NOT_FOUND, "Archivo no encontrado")
            return
        self.serve_file(path, file_info.get("name", path.name), download)

    def serve_uploaded_file(self, file_id: str, download: bool = False) -> None:
        file_info, path = data_store.find_uploaded_file(file_id)
        if not file_info or not path:
            self.send_error(HTTPStatus.NOT_FOUND, "Archivo no encontrado")
            return
        self.serve_file(path, file_info.get("name", path.name), download)

    def serve_template_asset(self, slug: str, element_id: str) -> None:
        metadata, path = data_store.template_asset_path(slug, element_id)
        if not metadata or not path:
            self.send_error(HTTPStatus.NOT_FOUND, "Imagen de plantilla no encontrada")
            return
        self.send_bytes(path.read_bytes(), metadata.get("content_type", "image/png"))

    def handle_template_asset_upload(
        self,
        fields: dict[str, str],
        files: list[dict[str, object]],
    ) -> None:
        slug = fields.get("slug", "")
        element_id = fields.get("element_id", "")
        image = next((item for item in files if item.get("field") == "image"), None)
        if not image:
            raise ValueError("Selecciona una firma o imagen para subir.")
        metadata = data_store.save_template_asset(
            slug,
            element_id,
            str(image.get("filename") or "imagen"),
            bytes(image.get("content") or b""),
        )
        asset_url = (
            f"/plantillas/asset/{quote(slug, safe='')}/{quote(element_id, safe='')}"
            f"?v={quote(metadata.get('updated_at', ''), safe='')}"
        )
        if self.headers.get("X-Requested-With") == "fetch":
            self.send_json(
                {
                    "ok": True,
                    "element_id": element_id,
                    "url": asset_url,
                    "filename": metadata.get("filename", "Imagen personalizada"),
                }
            )
            return
        self.redirect(
            f"/editor-plantillas?plantilla={quote(slug)}&msg=Imagen%20actualizada"
        )

    def serve_file(self, path: Path, filename: str, download: bool = False) -> None:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_bytes(body, content_type, filename=filename, attachment=download)

    def download_folder_zip(self, source: str, folder_id: str) -> None:
        detail = document_library.folder_detail(source, folder_id)
        if not detail:
            self.send_error(HTTPStatus.NOT_FOUND, "Entrega no encontrada")
            return
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if source == "web":
                entrega = detail.get("entrega", {})
                for name, content in self.generated_zip_entries(entrega):
                    zf.writestr(name, content)
            for doc in detail.get("docs", []):
                if doc.get("kind") == "imported":
                    _file, path = document_library.find_imported_file(doc.get("id", ""))
                    if path:
                        zf.write(path, f"{doc.get('category', 'Archivos')}/{doc.get('name', path.name)}")
                if doc.get("kind") == "uploaded":
                    _file, path = data_store.find_uploaded_file(doc.get("id", ""))
                    if path:
                        archive_path = doc.get("archive_path") or f"{doc.get('category', 'Archivos')}/{doc.get('name', path.name)}"
                        zf.write(path, archive_path)
        name = self.safe_download_name(detail.get("name", "entrega")) + ".zip"
        self.send_bytes(buffer.getvalue(), "application/zip", filename=name, attachment=True)

    def generated_zip_entries(self, entrega: dict) -> list[tuple[str, bytes]]:
        entries: list[tuple[str, bytes]] = []
        delivery_date = self.entrega_date(entrega)
        if entrega.get("items"):
            context = calculations.preliminares_context(entrega.get("items", []), current=delivery_date)
            context.update({"entrega": entrega.get("numero", ""), "fecha": entrega.get("fecha", "")})
            entries.append((f"Preliminares/PRELIMINARES - {entrega.get('numero', '')} ({entrega.get('fecha', '')}).pdf", renderer.render_print_pdf("preliminares", context)))
        store = data_store.load_store()
        for item in entrega.get("items", []):
            barra = item.get("barra", item.get("codigo", ""))
            proveedor = item.get("proveedor", "RECIBO")
            entries.append((f"Recibos de metales/{proveedor} ({barra}).pdf", renderer.render_print_pdf("recibo-metales", calculations.recibo_context(item, current=delivery_date))))
            if item.get("ley_au") not in ("", None) and item.get("ley_ag") not in ("", None):
                entries.append((f"Leyes/REPORTE LEYES - {barra}.pdf", renderer.render_print_pdf("reporte-analisis", calculations.reporte_analisis_context(item, current=delivery_date))))
                parametros = entrega.get("parametros", {})
                regalias = data_store.get_regalias_for_month(store, parametros.get("mes_regalias", entrega.get("month", "")))
                settings = data_store.get_entrega_boletin_settings(entrega, store)
                entries.append((f"Boletines/BOLETIN - {barra}.pdf", renderer.render_print_pdf("boletin", calculations.boletin_context(item, parametros, regalias, settings, current=delivery_date))))
        return entries

    def send_print(self, slug: str, context: dict, download: bool = False, filename: str = "") -> None:
        if download:
            pdf = renderer.render_print_pdf(slug, context)
            self.send_bytes(pdf, "application/pdf", filename=filename or f"{slug}.pdf", attachment=True)
            return
        body = renderer.render_print_html(slug, context).encode("utf-8")
        self.send_bytes(body, "text/html; charset=utf-8", filename=filename.replace(".pdf", ".html") if filename else f"{slug}.html", attachment=False)

    def render_error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        payload = {
            "message": message,
            "public": False,
            "user": self.current_user(),
            "request_path": self.path,
            "app_version": self.server_version,
            "asset_version": ASSET_VERSION,
            "backup_status": persistence.runtime_status(data_store.DATA_DIR),
        }
        body = env.get_template("error.html").render(**payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render(self, template_name: str, context: dict, public: bool = False) -> None:
        payload = dict(context)
        payload.setdefault("public", public)
        payload.setdefault("user", None if public else self.current_user())
        if not public:
            payload.setdefault("backup_status", persistence.runtime_status(data_store.DATA_DIR))
        payload.setdefault("request_path", self.path)
        payload.setdefault("app_version", self.server_version)
        payload.setdefault("asset_version", ASSET_VERSION)
        body = env.get_template(template_name).render(**payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data) -> None:
        body = core.json_response(data)
        self.send_bytes(body, "application/json; charset=utf-8")

    def send_bytes(self, body: bytes, content_type: str, filename: str = "", attachment: bool = False) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            disposition = "attachment" if attachment else "inline"
            self.send_header("Content-Disposition", self.content_disposition(disposition, filename))
        self.end_headers()
        self.wfile.write(body)

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("La solicitud supera el tamaño máximo permitido.")
        body = self.rfile.read(length).decode("utf-8")
        return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}

    def read_multipart_form(self) -> tuple[dict[str, str], list[dict[str, object]]]:
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
        if not match:
            raise ValueError("Formulario de archivos inválido.")
        boundary = (match.group(1) or match.group(2)).encode("utf-8")
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("El archivo supera el tamaño máximo permitido.")
        body = self.rfile.read(length)
        fields: dict[str, str] = {}
        files: list[dict[str, object]] = []
        for raw_part in body.split(b"--" + boundary):
            part = raw_part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            if part.endswith(b"--"):
                part = part[:-2].rstrip(b"\r\n")
            header_blob, sep, content = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            headers = header_blob.decode("latin-1", errors="replace").split("\r\n")
            disposition = next((header for header in headers if header.lower().startswith("content-disposition:")), "")
            name = self.header_param(disposition, "name")
            filename = self.header_param(disposition, "filename")
            part_content_type = ""
            for header in headers:
                if header.lower().startswith("content-type:"):
                    part_content_type = header.split(":", 1)[1].strip()
                    break
            if filename:
                files.append({"field": name, "filename": filename, "content": content, "content_type": part_content_type})
            elif name:
                fields[name] = content.decode("utf-8", errors="replace")
        return fields, files

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
        self.send_bytes(body, content_type)

    def wants_download(self, query: dict) -> bool:
        return query.get("download", [""])[0].lower() in {"1", "true", "si", "yes"}

    def folder_url(self, source: str, folder_id: str) -> str:
        if source == "web":
            route_source = "web"
        elif source == "local":
            route_source = "local"
        else:
            route_source = "importadas"
        return f"/entregas/{route_source}/{quote(folder_id)}"

    def safe_download_name(self, name: str) -> str:
        clean = re.sub(r'[\\/:*?"<>|]+', "-", name).strip()
        return clean or "archivo"

    def content_disposition(self, disposition: str, filename: str) -> str:
        fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip() or "archivo"
        return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"

    def header_param(self, header: str, name: str) -> str:
        match = re.search(rf'{re.escape(name)}="([^"]*)"', header)
        if match:
            return match.group(1)
        match = re.search(rf"{re.escape(name)}=([^;]+)", header)
        return match.group(1).strip() if match else ""

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    default_host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    parser = argparse.ArgumentParser(description="Recepción web local")
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--no-refresh-templates", action="store_true")
    args = parser.parse_args()

    if not args.no_refresh_templates and os.environ.get("RENDER") != "true":
        export_all_templates()

    httpd = ThreadingHTTPServer((args.host, args.port), RecepcionHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Recepción web disponible en {url}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
