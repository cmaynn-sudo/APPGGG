# Recepcion web

Esta carpeta migra el sistema actual a web sin depender de LibreOffice en Render.

La app conserva los Excel actuales como referencia visual y replica sus formulas en Python:

- `template_catalog.py` mapea cada plantilla, sus celdas dinamicas y el script actual que la usa.
- `html_exporter.py` genera plantillas HTML desde los `.xlsx`, copiando estilos, celdas combinadas, dimensiones e imagenes detectadas.
- `core.py` lee datos base actuales como sociedades, regalias y entregas.
- `app.py` levanta un panel web para operar entregas, leyes, boletines y certificados.
- `calculations.py` replica las formulas actuales de Excel en Python puro.
- `data_store.py` guarda entregas, regalias editadas y archivos subidos.
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

Las acciones de crear/eliminar carpetas y agregar/eliminar archivos piden la contraseña de autorizacion `ADMIN_ACTION_PASSWORD`.

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
ADMIN_ACTION_PASSWORD=1216727Er**
SESSION_SECRET=un-secreto-largo-y-aleatorio
MAX_UPLOAD_MB=25
```

En el plan gratuito, Render no conserva archivos subidos ni cambios hechos desde la app despues de reinicios o reposos. Los PDFs importados desde `CI GREEN GLOBAL` si viajan con Git porque quedan en `webapp/imported_docs/`.
