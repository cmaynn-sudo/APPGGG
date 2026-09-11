from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


API_ROOT = "https://api.github.com"
STORE_FILENAME = "recepcion_store.json"
UPLOADS_DIRNAME = "uploads"
RESTORE_ONCE = False
LAST_BACKUP_ERROR = ""
LAST_RESTORE_ERROR = ""
LAST_BACKUP_AT = ""
LAST_RESTORE_AT = ""


def config() -> dict[str, str]:
    repo = (os.environ.get("GITHUB_BACKUP_REPO") or "").strip()
    token = (os.environ.get("GITHUB_BACKUP_TOKEN") or "").strip()
    return {
        "repo": repo,
        "token": token,
        "branch": (os.environ.get("GITHUB_BACKUP_BRANCH") or "app-data").strip(),
        "base_branch": (os.environ.get("GITHUB_BACKUP_BASE_BRANCH") or "main").strip(),
        "path": (os.environ.get("GITHUB_BACKUP_PATH") or "recepcion-state/state.zip").strip("/"),
    }


def is_configured() -> bool:
    cfg = config()
    return bool(cfg["repo"] and cfg["token"])


def runtime_status(data_dir: Path | None = None) -> dict[str, Any]:
    cfg = config()
    status = {
        "enabled": is_configured(),
        "repo": cfg["repo"],
        "branch": cfg["branch"],
        "path": cfg["path"],
        "last_backup_at": LAST_BACKUP_AT,
        "last_restore_at": LAST_RESTORE_AT,
        "last_backup_error": LAST_BACKUP_ERROR,
        "last_restore_error": LAST_RESTORE_ERROR,
    }
    if data_dir:
        status["local_store_exists"] = (data_dir / STORE_FILENAME).exists()
        status["local_uploads_exists"] = (data_dir / UPLOADS_DIRNAME).exists()
    return status


def restore_state_if_configured(data_dir: Path, force: bool = False) -> str:
    global RESTORE_ONCE, LAST_RESTORE_AT, LAST_RESTORE_ERROR
    if RESTORE_ONCE and not force:
        return "skipped"
    RESTORE_ONCE = True
    if not is_configured():
        return "disabled"
    if (
        (data_dir / STORE_FILENAME).exists()
        and os.environ.get("GITHUB_BACKUP_FORCE_RESTORE") != "true"
        and not force
    ):
        return "local-present"
    try:
        archive = download_backup()
        if not archive:
            return "remote-empty"
        extract_backup(data_dir, archive)
        LAST_RESTORE_AT = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        LAST_RESTORE_ERROR = ""
        return "restored"
    except Exception as exc:
        LAST_RESTORE_ERROR = str(exc)
        print(f"[recepcion] No se pudo restaurar el respaldo externo: {exc}")
        return "failed"


def restore_state_from_github(data_dir: Path) -> str:
    return restore_state_if_configured(data_dir, force=True)


def backup_state_if_configured(data_dir: Path) -> bool:
    global LAST_BACKUP_AT, LAST_BACKUP_ERROR
    if not is_configured():
        return False
    try:
        archive = build_backup_archive(data_dir)
        if not archive:
            return False
        upload_backup(archive)
        LAST_BACKUP_AT = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        LAST_BACKUP_ERROR = ""
        return True
    except Exception as exc:
        LAST_BACKUP_ERROR = str(exc)
        print(f"[recepcion] No se pudo guardar el respaldo externo: {exc}")
        return False


def build_backup_archive(data_dir: Path) -> bytes:
    store_path = data_dir / STORE_FILENAME
    if not store_path.exists():
        return b""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(store_path, STORE_FILENAME)
        uploads_dir = data_dir / UPLOADS_DIRNAME
        if uploads_dir.exists():
            for path in sorted(uploads_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, f"{UPLOADS_DIRNAME}/{path.relative_to(uploads_dir).as_posix()}")
    return buffer.getvalue()


def import_backup_archive(data_dir: Path, archive: bytes) -> None:
    extract_backup(data_dir, archive)
    backup_state_if_configured(data_dir)


def extract_backup(data_dir: Path, archive: bytes) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for member in zf.infolist():
            target = safe_extract_target(data_dir, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src:
                target.write_bytes(src.read())


def safe_extract_target(root: Path, name: str) -> Path:
    normalized = Path(str(name).replace("\\", "/"))
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        raise ValueError("El respaldo contiene una ruta invalida.")
    target = (root / normalized).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError("El respaldo intenta escribir fuera del directorio de datos.")
    return target


def download_backup() -> bytes:
    cfg = config()
    ensure_backup_branch(cfg)
    meta = github_json(
        "GET",
        f"/repos/{cfg['repo']}/contents/{urllib.parse.quote(cfg['path'])}?ref={urllib.parse.quote(cfg['branch'])}",
        cfg,
        allow_404=True,
    )
    if not meta:
        return b""
    blob = github_json("GET", f"/repos/{cfg['repo']}/git/blobs/{meta['sha']}", cfg)
    if blob.get("encoding") != "base64":
        raise ValueError("El respaldo externo no esta en base64.")
    return base64.b64decode(blob.get("content", ""))


def upload_backup(archive: bytes) -> None:
    cfg = config()
    ensure_backup_branch(cfg)
    meta = github_json(
        "GET",
        f"/repos/{cfg['repo']}/contents/{urllib.parse.quote(cfg['path'])}?ref={urllib.parse.quote(cfg['branch'])}",
        cfg,
        allow_404=True,
    )
    payload = {
        "message": "Actualizar respaldo de recepcion",
        "content": base64.b64encode(archive).decode("ascii"),
        "branch": cfg["branch"],
    }
    if meta:
        payload["sha"] = meta["sha"]
    github_json("PUT", f"/repos/{cfg['repo']}/contents/{urllib.parse.quote(cfg['path'])}", cfg, payload)


def ensure_backup_branch(cfg: dict[str, str]) -> None:
    if github_json("GET", f"/repos/{cfg['repo']}/git/ref/heads/{urllib.parse.quote(cfg['branch'])}", cfg, allow_404=True):
        return
    base_ref = github_json("GET", f"/repos/{cfg['repo']}/git/ref/heads/{urllib.parse.quote(cfg['base_branch'])}", cfg)
    github_json(
        "POST",
        f"/repos/{cfg['repo']}/git/refs",
        cfg,
        {"ref": f"refs/heads/{cfg['branch']}", "sha": base_ref["object"]["sha"]},
    )


def github_json(
    method: str,
    path: str,
    cfg: dict[str, str],
    payload: dict[str, Any] | None = None,
    allow_404: bool = False,
) -> dict[str, Any] | None:
    url = f"{API_ROOT}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {cfg['token']}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub respondio {exc.code}: {detail}") from exc
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))
