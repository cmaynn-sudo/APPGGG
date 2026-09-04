# Recepcion web

Esta carpeta es la base paralela para migrar el sistema actual a web sin romper los scripts de escritorio.

La primera fase conserva los Excel actuales como fuente visual:

- `template_catalog.py` mapea cada plantilla, sus celdas dinamicas y el script actual que la usa.
- `html_exporter.py` genera plantillas HTML desde los `.xlsx`, copiando estilos, celdas combinadas, dimensiones e imagenes detectadas.
- `core.py` lee datos base actuales como sociedades, regalias y entregas.
- `app.py` levanta un panel web para operar entregas, leyes, boletines y certificados.
- `calculations.py` replica las formulas actuales de Excel en Python puro.
- `data_store.py` guarda entregas y datos en JSON para la version local/demo.

Ejecutar:

```bash
python3 webapp/app.py
```

Abrir:

```text
http://127.0.0.1:8765
```

El siguiente paso es conectar formularios web para reproducir las acciones actuales de `DOCUMENTOS.py`, `LEYES.py`, `BOLETINES.py` y `PAGO DE REGALIAS.py`.

## Render

La app esta preparada para Render sin LibreOffice. El servidor toma el puerto desde `PORT` y escucha en `0.0.0.0` cuando corre en Render.

En el plan gratuito, Render no conserva archivos creados por la app despues de reinicios o reposos. Para uso real con historial permanente, conecta una base de datos externa o un servicio con disco persistente.
