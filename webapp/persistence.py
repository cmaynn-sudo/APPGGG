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


def github_config() -> dict[str, str]:
    repo = (os.environ.get("GITHUB_BACKUP_REPO") or "").strip()
    token = (os.environ.get("GITHUB_BACKUP_TOKEN") or "").strip()
    return {
        "repo": repo,
        "token": token,
        "branch": (os.environ.get("GITHUB_BACKUP_BRANCH") or "app-data").strip(),
        "base_branch": (os.environ.get("GITHUB_BACKUP_BASE_BRANCH") or "main").strip(),
        "path": (os.environ.get("GITHUB_BACKUP_PATH") or "recepcion-state/state.zip").strip("/"),
    }


def r2_config() -> dict[str, str]:
    account_id = (os.environ.get("R2_ACCOUNT_ID") or "").strip()
    endpoint = (os.environ.get("R2_ENDPOINT_URL") or "").strip().rstrip("/")
    if not endpoint and account_id:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    return {
        "endpoint": endpoint,
        "access_key": (os.environ.get("R2_ACCESS_KEY_ID") or "").strip(),
        "secret_key": (os.environ.get("R2_SECRET_ACCESS_KEY") or "").strip(),
        "bucket": (os.environ.get("R2_BUCKET_NAME") or "").strip(),
        "key": (os.environ.get("R2_OBJECT_KEY") or "recepcion-state/state.zip").strip("/"),
        "region": (os.environ.get("R2_REGION") or "auto").strip(),
    }


def storage_backend() -> str:
    r2 = r2_config()
    if all(r2[key] for key in ("endpoint", "access_key", "secret_key", "bucket", "key")):
        return "r2"
    github = github_config()
    if github["repo"] and github["token"]:
        return "github"
    return ""


def is_configured() -> bool:
    return bool(storage_backend())


def should_restore_on_start() -> bool:
    raw = os.environ.get("PERSISTENCE_RESTORE_ON_START")
    if raw is None:
        raw = os.environ.get("GITHUB_BACKUP_RESTORE_ON_START")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "si", "on"}
    return os.environ.get("RENDER", "").strip().lower() == "true"


def runtime_status(data_dir: Path | None = None) -> dict[str, Any]:
    backend = storage_backend()
    github = github_config()
    r2 = r2_config()
    if backend == "r2":
        provider = "Cloudflare R2"
        location = f"{r2['bucket']} / {r2['key']}"
    elif backend == "github":
        provider = "GitHub"
        location = f"{github['repo']} / {github['branch']} / {github['path']}"
    else:
        provider = "Sin configurar"
        location = ""
    status = {
        "enabled": is_configured(),
        "backend": backend,
        "provider": provider,
        "location": location,
        "repo": github["repo"],
        "branch": github["branch"],
        "path": github["path"],
        "bucket": r2["bucket"],
        "object_key": r2["key"],
        "restore_on_start": should_restore_on_start(),
        "last_backup_at": LAST_BACKUP_AT,
        "last_restore_at": LAST_RESTORE_AT,
        "last_backup_error": LAST_BACKUP_ERROR,
        "last_restore_error": LAST_RESTORE_ERROR,
    }
    if data_dir:
        status["local_store_exists"] = (data_dir / STORE_FILENAME).exists()
        status["local_uploads_exists"] = (data_dir / UPLOADS_DIRNAME).exists()
    return status


def restore_state_if_configured(data_dir: Path, force: bool = False, once: bool = True) -> str:
    global RESTORE_ONCE, LAST_RESTORE_AT, LAST_RESTORE_ERROR
    if once and RESTORE_ONCE:
        return "skipped"
    if once:
        RESTORE_ONCE = True
    if not is_configured():
        return "disabled"
    if (
        (data_dir / STORE_FILENAME).exists()
        and os.environ.get("PERSISTENCE_FORCE_RESTORE", os.environ.get("GITHUB_BACKUP_FORCE_RESTORE", "")) != "true"
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


def restore_state_from_remote(data_dir: Path) -> str:
    return restore_state_if_configured(data_dir, force=True, once=False)


def restore_state_from_github(data_dir: Path) -> str:
    return restore_state_from_remote(data_dir)


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
        raise ValueError("El respaldo contiene una ruta inválida.")
    target = (root / normalized).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError("El respaldo intenta escribir fuera del directorio de datos.")
    return target


def download_backup() -> bytes:
    if storage_backend() == "r2":
        return download_r2_backup()
    cfg = github_config()
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
        raise ValueError("El respaldo externo no está en base64.")
    return base64.b64decode(blob.get("content", ""))


def upload_backup(archive: bytes) -> None:
    if storage_backend() == "r2":
        upload_r2_backup(archive)
        return
    cfg = github_config()
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


def r2_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("Falta instalar boto3 para usar Cloudflare R2.") from exc

    cfg = r2_config()
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name=cfg["region"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def download_r2_backup() -> bytes:
    cfg = r2_config()
    try:
        response = r2_client().get_object(Bucket=cfg["bucket"], Key=cfg["key"])
    except Exception as exc:
        response = getattr(exc, "response", {}) or {}
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return b""
        raise RuntimeError(f"Cloudflare R2 no pudo leer el respaldo: {exc}") from exc
    return response["Body"].read()


def upload_r2_backup(archive: bytes) -> None:
    cfg = r2_config()
    try:
        r2_client().put_object(
            Bucket=cfg["bucket"],
            Key=cfg["key"],
            Body=archive,
            ContentType="application/zip",
            Metadata={"updated-at": datetime.utcnow().isoformat(timespec="seconds") + "Z"},
        )
    except Exception as exc:
        raise RuntimeError(f"Cloudflare R2 no pudo guardar el respaldo: {exc}") from exc


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
        raise RuntimeError(f"GitHub respondió {exc.code}: {detail}") from exc
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))
