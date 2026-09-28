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
- `analytics.py` consolida facturación y pesos por mes, incluyendo boletines PDF de carpetas históricas.
- `historical_import.py` recibe la carpeta completa o un ZIP, detecta todas las entregas y las guarda sin duplicarlas.
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

## Almacenamiento persistente para Render Free

Render Free no conserva archivos locales después de reinicios, reposos o deploys. La opción recomendada para esta aplicación es Cloudflare R2, porque está diseñada para archivos y usa una API compatible con S3.

1. En Cloudflare crea un bucket R2, por ejemplo `recepcion-green-global`.
2. Crea credenciales S3 con permiso de lectura y escritura para ese bucket.
3. Agrega en Render las variables `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` y `R2_BUCKET_NAME`.
4. Conserva `R2_OBJECT_KEY=recepcion-state/state.zip` y `PERSISTENCE_RESTORE_ON_START=true`.

La aplicación guarda automáticamente un ZIP con el estado y los archivos subidos, verifica que el proveedor haya recibido el archivo y lo restaura al arrancar. Si R2 está configurado, tiene prioridad. El respaldo anterior en GitHub se mantiene como alternativa para no interrumpir instalaciones existentes.

En Render, `PERSISTENCE_REQUIRED=true` impide que una modificación aparezca como guardada cuando no existe un proveedor externo o cuando el último respaldo falló. No es una autorización adicional: después del login el flujo sigue siendo normal, pero una falla de almacenamiento se muestra de forma explícita y las siguientes escrituras quedan detenidas hasta guardar o restaurar el respaldo.

También queda disponible el módulo `Respaldo` dentro de la app para:

- Descargar un ZIP completo del estado actual.
- Restaurar ese ZIP manualmente.
- Forzar un guardado o una restauración desde el almacenamiento externo configurado.

Variables de R2:

```text
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=credencial-r2
R2_SECRET_ACCESS_KEY=secreto-r2
R2_BUCKET_NAME=recepcion-green-global
R2_OBJECT_KEY=recepcion-state/state.zip
PERSISTENCE_RESTORE_ON_START=true
```

Compatibilidad con el respaldo anterior:

```text
GITHUB_BACKUP_REPO=cmaynn-sudo/APPGGG
GITHUB_BACKUP_TOKEN=token-secreto-con-contenido-write
GITHUB_BACKUP_BRANCH=app-data
GITHUB_BACKUP_PATH=recepcion-state/state.zip
```

## Dashboard

El dashboard se puede filtrar por año, mes, entrega y proveedor. Suma por mes y para toda la selección:

- Subtotal, equivalente al valor total de metales.
- Valor a pagar.
- Regalías de oro.
- Regalías de plata.
- Valor pagado, equivalente al valor a transferir.
- Gramos iniciales facturados.
- Gramos finales facturados.
- Entregas y cantidad de boletines.

Las entregas creadas en la web se calculan directamente con las mismas fórmulas del boletín. Al subir una carpeta histórica, la aplicación también lee sus PDFs de boletines y evita contabilizar duplicados.

## Importación histórica

En `Entregas` se puede seleccionar la carpeta completa `CI GREEN GLOBAL` o un ZIP con la misma estructura. La aplicación:

- Detecta todas las carpetas con el formato `ENTREGA ... (AAAA-MM-DD)`.
- Conserva el año, mes, fecha, subcarpetas y documentos originales.
- Separa certificados y archivos mensuales que estén fuera de una entrega.
- Actualiza una importación repetida en lugar de crear carpetas duplicadas.
- Excluye archivos auxiliares de macOS como `.DS_Store`.
- Lee los boletines PDF para alimentar el dashboard sin recalcular las cifras históricas.
- Informa cuáles boletines PDF no se pudieron leer y explica la causa.
- Detecta cargas antiguas que quedaron reunidas en una sola carpeta y permite reorganizarlas sin volver a subir los archivos.
- Confirma la importación completa en el respaldo externo configurado.

Las entregas se crean por separado según su ruta `AÑO / MES / ENTREGA (fecha)`. El panel plegable de reconstrucción manual permite volver a crear en la web una entrega cuyo PDF haya sido modificado, indicando su fecha original, mes de regalías, dólar, onzas, negociación y retención. Los documentos regenerados conservan esa fecha histórica.

El límite predeterminado es de `25 MB` para la carga HTTP y `100 MB` después de descomprimir un ZIP. Se puede ajustar con `MAX_UPLOAD_MB` y `MAX_HISTORICAL_IMPORT_MB`.

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
PERSISTENCE_RESTORE_ON_START=true
PERSISTENCE_REQUIRED=true
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=credencial-r2
R2_SECRET_ACCESS_KEY=secreto-r2
R2_BUCKET_NAME=recepcion-green-global
R2_OBJECT_KEY=recepcion-state/state.zip
GITHUB_BACKUP_REPO=cmaynn-sudo/APPGGG
GITHUB_BACKUP_TOKEN=token-secreto-con-contenido-write
GITHUB_BACKUP_BRANCH=app-data
GITHUB_BACKUP_PATH=recepcion-state/state.zip
GITHUB_BACKUP_RESTORE_ON_START=true
```

En el plan gratuito, Render no conserva archivos subidos ni cambios hechos desde la app después de reinicios o reposos. Con R2 configurado, la app restaura esos datos automáticamente. Si R2 no está configurado, intenta usar el respaldo GitHub anterior.

Los PDFs descargables se generan con WeasyPrint desde el mismo HTML/CSS que se visualiza en la app. Si WeasyPrint no está disponible, el sistema usa el PDF simplificado de respaldo para no bloquear la operación.
