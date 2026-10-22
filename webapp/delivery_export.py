from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

import calculations
import data_store
import document_library
import renderer


@dataclass(frozen=True)
class PdfEntry:
    name: str
    slug: str
    context: dict


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: Path


def generated_documents(entrega: dict, store: dict) -> list[PdfEntry]:
    try:
        delivery_date = date.fromisoformat(str(entrega.get("fecha", "")))
    except ValueError:
        delivery_date = date.today()
    entries = []
    items = entrega.get("items", [])
    if items:
        context = calculations.preliminares_context(items, current=delivery_date)
        context.update(entrega=entrega.get("numero", ""), fecha=entrega.get("fecha", ""))
        entries.append(PdfEntry(
            f"Preliminares/PRELIMINARES - {entrega.get('numero', '')} ({entrega.get('fecha', '')}).pdf",
            "preliminares", context,
        ))
    parametros = entrega.get("parametros", {})
    regalias = data_store.get_regalias_for_month(store, parametros.get("mes_regalias", entrega.get("month", "")))
    settings = data_store.get_entrega_boletin_settings(entrega, store)
    for item in items:
        barra = item.get("barra", item.get("codigo", ""))
        proveedor = item.get("proveedor", "RECIBO")
        entries.append(PdfEntry(
            f"Recibos de metales/{proveedor} ({barra}).pdf", "recibo-metales",
            calculations.recibo_context(item, current=delivery_date),
        ))
        if item.get("ley_au") not in ("", None) and item.get("ley_ag") not in ("", None):
            entries.append(PdfEntry(
                f"Leyes/REPORTE LEYES - {barra}.pdf", "reporte-analisis",
                calculations.reporte_analisis_context(item, current=delivery_date),
            ))
            entries.append(PdfEntry(
                f"Boletines/BOLETIN - {barra}.pdf", "boletin",
                calculations.boletin_context(item, parametros, regalias, settings, current=delivery_date),
            ))
    return entries


def archive_name(name: str, used: set[str]) -> str:
    parts = PurePosixPath(str(name).replace("\\", "/")).parts
    clean = "/".join(re.sub(r"[\x00-\x1f:]", "_", part) for part in parts if part not in {"/", ".", ".."})
    path = PurePosixPath(clean or "archivo")
    candidate = str(path)
    suffix = 2
    while candidate.casefold() in used:
        candidate = str(path.with_name(f"{path.stem} ({suffix}){path.suffix}"))
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def export_entries(source: str, detail: dict, store: dict) -> list[PdfEntry | FileEntry]:
    entries: list[PdfEntry | FileEntry] = generated_documents(detail.get("entrega", {}), store) if source == "web" else []
    for doc in detail.get("docs", []):
        kind = doc.get("kind")
        if kind == "imported":
            _metadata, path = document_library.find_imported_file(doc.get("id", ""))
        elif kind == "uploaded":
            _metadata, path = data_store.find_uploaded_file(doc.get("id", ""), store=store)
        else:
            continue
        if not path:
            raise ValueError(f"No se encuentra el archivo {doc.get('name', '')}. Revisa la carpeta antes de descargar.")
        name = doc.get("archive_path") or f"{doc.get('category', 'Archivos')}/{doc.get('name', path.name)}"
        entries.append(FileEntry(name, path))
    return entries


def build_archive(path: Path, entries: list[PdfEntry | FileEntry], store: dict, progress) -> None:
    used: set[str] = set()
    # Each PDF is released after writing; the whole delivery is never kept in RAM.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for index, entry in enumerate(entries):
            progress(index, entry.name)
            try:
                name = archive_name(entry.name, used)
                if isinstance(entry, PdfEntry):
                    content = renderer.render_print_pdf(entry.slug, entry.context, store=store)
                    if not content.startswith(b"%PDF-"):
                        raise ValueError("El motor no devolvió un PDF válido.")
                    archive.writestr(name, content)
                    del content
                else:
                    archive.write(entry.path, name)
            except Exception as exc:
                raise RuntimeError(f"No se pudo preparar {entry.name}: {exc}") from exc
            progress(index + 1, entry.name)


class ExportManager:
    def __init__(self, *, ttl: float = 1800, max_jobs: int = 12, max_pending: int = 4):
        self.ttl = ttl
        self.max_jobs = max_jobs
        self.max_pending = max_pending
        self.directory = tempfile.TemporaryDirectory(prefix="recepcion-zip-")
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="entrega-zip")

    def _prune(self) -> None:
        for job_id, job in list(self.jobs.items()):
            if job["status"] in {"ready", "error"} and time.monotonic() - job["updated"] > self.ttl:
                self.jobs.pop(job_id)
                (Path(self.directory.name) / f"{job_id}.zip").unlink(missing_ok=True)

    def start(self, owner: str, source: str, folder_id: str, detail: dict, store: dict) -> dict:
        store = copy.deepcopy(store)
        entries = export_entries(source, detail, store)
        # Any data, layout, signature or file change invalidates a completed export.
        file_versions = []
        for entry in entries:
            if isinstance(entry, FileEntry):
                stat = entry.path.stat()
                file_versions.append((str(entry.path), stat.st_size, stat.st_mtime_ns))
        for assets in store.get("template_assets", {}).values():
            for metadata in assets.values():
                asset = (data_store.UPLOADS_DIR / str(metadata.get("stored_path", ""))).resolve()
                if asset.is_relative_to(data_store.UPLOADS_DIR.resolve()) and asset.is_file():
                    stat = asset.stat()
                    file_versions.append((str(asset), stat.st_size, stat.st_mtime_ns))
        fingerprint = hashlib.sha256(json.dumps(
            [source, folder_id, detail, store, file_versions], sort_keys=True, default=str,
        ).encode()).hexdigest()
        with self.lock:
            self._prune()
            for job in self.jobs.values():
                if job["owner"] == owner and job["fingerprint"] == fingerprint and job["status"] != "error":
                    job["updated"] = time.monotonic()
                    return self._public(job)
            pending = sum(job["status"] in {"queued", "running"} for job in self.jobs.values())
            if pending >= self.max_pending:
                raise ValueError("Hay varias descargas preparándose. Espera a que termine una e intenta de nuevo.")
            while len(self.jobs) >= self.max_jobs:
                finished = [job for job in self.jobs.values() if job["status"] in {"ready", "error"}]
                if not finished:
                    raise ValueError("La cola de descargas está ocupada. Intenta de nuevo en unos minutos.")
                oldest = min(finished, key=lambda job: job["updated"])
                self.jobs.pop(oldest["id"])
                (Path(self.directory.name) / f"{oldest['id']}.zip").unlink(missing_ok=True)
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id, "owner": owner, "fingerprint": fingerprint, "status": "queued",
                "completed": 0, "total": len(entries), "current": "", "error": "",
                "name": detail.get("name") or "Entrega", "source": source, "folder_id": folder_id,
                "updated": time.monotonic(),
            }
            self.jobs[job_id] = job
            self.executor.submit(self._build, job_id, entries, store)
            return self._public(job)

    def _public(self, job: dict) -> dict:
        return {key: value for key, value in job.items() if key not in {"owner", "fingerprint", "updated"}}

    def get(self, job_id: str, owner: str) -> dict | None:
        with self.lock:
            self._prune()
            job = self.jobs.get(job_id)
            return self._public(job) if job and job["owner"] == owner else None

    def open_result(self, job_id: str, owner: str):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["owner"] != owner or job["status"] != "ready":
                return None
            job["updated"] = time.monotonic()
            return (Path(self.directory.name) / f"{job_id}.zip").open("rb")

    def _update(self, job_id: str, **values) -> None:
        with self.lock:
            self.jobs[job_id].update(values, updated=time.monotonic())

    def _build(self, job_id: str, entries: list[PdfEntry | FileEntry], store: dict) -> None:
        path = Path(self.directory.name) / f"{job_id}.zip"
        self._update(job_id, status="running")
        try:
            build_archive(path, entries, store, lambda completed, current: self._update(
                job_id, completed=completed, current=current,
            ))
            self._update(job_id, status="ready", current="", size=path.stat().st_size)
        except Exception as exc:
            logging.exception("Error al preparar el ZIP %s", job_id)
            path.unlink(missing_ok=True)
            self._update(job_id, status="error", error=str(exc), current="")

    def close(self) -> None:
        self.executor.shutdown(wait=True)
        self.directory.cleanup()


manager = ExportManager()
