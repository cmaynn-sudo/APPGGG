# Recepcion web

Esta carpeta migra el sistema actual a web sin depender de LibreOffice en Render.

La app conserva los Excel actuales como referencia visual y replica sus formulas en Python:

- `template_catalog.py` mapea cada plantilla, sus celdas dinamicas y el script actual que la usa.
- `html_exporter.py` genera plantillas HTML desde los `.xlsx`, copiando estilos, celdas combinadas, dimensiones e imagenes detectadas.
- `core.py` lee datos base actuales como sociedades, regalias y entregas.
- `app.py` levanta un panel web para operar entregas, leyes, boletines y certificados.
- `calculations.py` replica las formulas actuales de Excel en Python puro.
- `data_store.py` guarda entregas, regalias editadas y archivos subidos.
- `renderer.py` genera las vistas HTML y los PDFs descargables.
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

Despues del login, el trabajo normal no pide claves adicionales: crear entregas, editar, eliminar, subir archivos y subir carpetas se hace desde la sesion activa.

## Parametros de boletines

En el menu `Parametros` se editan los porcentajes globales de:

- Precio de negociacion, por defecto `97,5%`.
- Retencion, por defecto `2,5%`.

La formula de precio de oro mantiene el redondeo de Excel:

```text
REDONDEAR(((OZ AU / 31,10347) * dolar) * precio_negociacion; 0)
```

Puedes escribir porcentajes con coma o punto decimal, por ejemplo `97,5`, `97.5`, `2,5` o `2.5`.

## Respaldo para Render Free

Render Free no conserva archivos locales despues de reinicios, reposos o deploys. Para que no se pierdan entregas, sociedades editadas, regalias y archivos subidos, configura un respaldo GitHub:

1. Crea un token de GitHub con permiso de escritura de contenido sobre este repositorio.
2. En Render, agrega `GITHUB_BACKUP_TOKEN` como variable secreta.
3. Deja `GITHUB_BACKUP_REPO=cmaynn-sudo/APPGGG`, `GITHUB_BACKUP_BRANCH=app-data` y `GITHUB_BACKUP_PATH=recepcion-state/state.zip`.

La app crea la rama `app-data` si no existe, guarda alli un ZIP del estado y lo restaura automaticamente al arrancar.

Tambien queda disponible el modulo `Respaldo` dentro de la app para:

- Descargar un ZIP completo del estado actual.
- Restaurar ese ZIP manualmente.
- Forzar guardar o restaurar desde GitHub cuando `GITHUB_BACKUP_TOKEN` ya este configurado.

## Render

La app esta preparada para Render sin LibreOffice. El servidor toma el puerto desde `PORT` y escucha en `0.0.0.0` cuando corre en Render.

Start Command:

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
```

En el plan gratuito, Render no conserva archivos subidos ni cambios hechos desde la app despues de reinicios o reposos. Con `GITHUB_BACKUP_TOKEN`, la app restaura esos datos desde la rama `app-data`.
