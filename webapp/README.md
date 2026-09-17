# Recepción web

Esta carpeta migra el sistema actual a web sin depender de LibreOffice en Render.

La app conserva los Excel actuales como referencia visual y replica sus fórmulas en Python:

- `template_catalog.py` mapea cada plantilla, sus celdas dinámicas y el script actual que la usa.
- `html_exporter.py` genera plantillas HTML desde los `.xlsx`, copiando estilos, celdas combinadas, dimensiones e imágenes detectadas.
- `core.py` lee datos base actuales como sociedades, regalías y entregas.
- `app.py` levanta un panel web para operar entregas, leyes, boletines y certificados.
- `calculations.py` replica las fórmulas actuales de Excel en Python puro.
- `data_store.py` guarda entregas, regalías editadas y archivos subidos.
- `renderer.py` genera las vistas HTML y los PDFs descargables desde las mismas plantillas visuales.
- `document_library.py` mezcla entregas web, documentos generados e importaciones locales.
- `import_local_deliveries.py` copia los documentos existentes desde `~/Documents/CI GREEN GLOBAL` a `webapp/imported_docs/`.

Ejecutar:

```bash
python3 webapp/app.py
```

Abrir:

```text
http://127.0.0.1:8765
```

Credenciales temporales:

```text
Usuario: admin
Contraseña: admin
```

Después del login, el trabajo normal no pide claves adicionales: crear entregas, editar, eliminar, subir archivos y subir carpetas se hace desde la sesión activa.

## Parámetros de boletines

En el menú `Parámetros` se editan los porcentajes globales de:

- Precio de negociación, por defecto `97,5%`.
- Retención, por defecto `2,5%`.

La formula de precio de oro mantiene el redondeo de Excel:

```text
REDONDEAR(((OZ AU / 31,10347) * dólar) * precio_negociación; 0)
```

Puedes escribir porcentajes con coma o punto decimal, por ejemplo `97,5`, `97.5`, `2,5` o `2.5`.

## Respaldo para Render Free

Render Free no conserva archivos locales después de reinicios, reposos o deploys. Para que no se pierdan entregas, sociedades editadas, regalías y archivos subidos, configura un respaldo GitHub:

1. Crea un token de GitHub con permiso de escritura de contenido sobre este repositorio.
2. En Render, agrega `GITHUB_BACKUP_TOKEN` como variable secreta.
3. Deja `GITHUB_BACKUP_REPO=cmaynn-sudo/APPGGG`, `GITHUB_BACKUP_BRANCH=app-data` y `GITHUB_BACKUP_PATH=recepcion-state/state.zip`.

La app crea la rama `app-data` si no existe, guarda allí un ZIP del estado y lo restaura automáticamente al arrancar.

También queda disponible el módulo `Respaldo` dentro de la app para:

- Descargar un ZIP completo del estado actual.
- Restaurar ese ZIP manualmente.
- Forzar guardar o restaurar desde GitHub cuando `GITHUB_BACKUP_TOKEN` ya esté configurado.

## Render

La app está preparada para Render sin LibreOffice. Para que los PDFs queden iguales a la vista web, el despliegue recomendado es Docker, porque instala las librerías nativas que necesita WeasyPrint.

Dockerfile incluido:

```bash
Dockerfile
```

Docker Command en Render:

```text
Dejar vacío
```

Si mantienes el servicio como `Python runtime`, el sistema puede arrancar, pero los PDFs usarán el generador simplificado cuando WeasyPrint no encuentre librerías del sistema. En Render, crea o configura el servicio con `Language: Docker` para usar la salida fiel a la plantilla.

Start Command solo para el runtime Python anterior:

```bash
python webapp/app.py --no-refresh-templates
```

Variables recomendadas:

```text
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
SESSION_SECRET=un-secreto-largo-y-aleatorio
MAX_UPLOAD_MB=25
GITHUB_BACKUP_REPO=cmaynn-sudo/APPGGG
GITHUB_BACKUP_TOKEN=token-secreto-con-contenido-write
GITHUB_BACKUP_BRANCH=app-data
GITHUB_BACKUP_PATH=recepcion-state/state.zip
GITHUB_BACKUP_RESTORE_ON_START=true
```

En el plan gratuito, Render no conserva archivos subidos ni cambios hechos desde la app después de reinicios o reposos. Con `GITHUB_BACKUP_TOKEN`, la app restaura esos datos desde la rama `app-data`.

Los PDFs descargables se generan con WeasyPrint desde el mismo HTML/CSS que se visualiza en la app. Si WeasyPrint no está disponible, el sistema usa el PDF simplificado de respaldo para no bloquear la operación.
