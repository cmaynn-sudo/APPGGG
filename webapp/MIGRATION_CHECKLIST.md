# Checklist de migracion a web

Objetivo: llevar el sistema actual a una app web sin perder funciones ni apariencia documental.

## Regla de trabajo

Los scripts actuales quedan como referencia operativa hasta que cada modulo web produzca el mismo resultado:

1. mismo dato de entrada;
2. mismo nombre de archivo;
3. misma estructura de carpetas;
4. mismo PDF final;
5. mismo cambio en consecutivos o datos base cuando aplique.

## Paridad por modulo

### DOCUMENTOS.py

Plantillas actuales:

- `PRELIMINARES.xlsx` -> `templates/generated/preliminares.html`
- `RECIBO DE METALES.xlsx` -> `templates/generated/recibo-metales.html`

Funciones que deben conservarse:

- crear `~/Documents/CI GREEN GLOBAL/{AÑO}/{MES}/ENTREGA °{numero} - ({fecha})`;
- leer sociedades desde `SOCIEDADES.xlsx`;
- generar codigo `{PREFIJO}-{CONSECUTIVO + 1}`;
- guardar proveedor, codigo, peso inicial, peso post y muestras en preliminares;
- generar un recibo individual por sociedad;
- actualizar `SOCIEDADES.xlsx` columna `CONSECUTIVO`;
- limpiar la plantilla o estado temporal despues de generar.

### LEYES.py

Plantilla actual:

- `REPORTE DE ANALISIS.xlsx` -> `templates/generated/reporte-analisis.html`

Funciones que deben conservarse:

- seleccionar una carpeta de entrega;
- detectar el PDF de preliminares;
- extraer sociedad, barra, peso inicial y peso final;
- cruzar sociedad contra `SOCIEDADES.xlsx`;
- recibir ley AU y ley AG;
- generar `LEYES/REPORTE LEYES - {barra}.pdf`;
- marcar sociedades procesadas.

### BOLETINES.py

Plantillas actuales:

- `REPORTE DE LIQUIDACION.xlsx` -> `templates/generated/boletin.html`
- `REGALIAS.xlsx` se mantiene como dato base temporal.

Funciones que deben conservarse:

- detectar PDFs de leyes;
- extraer proveedor, NIT, barra, pesos y leyes;
- guardar parametros de cierre de venta;
- aplicar regalías del mes;
- generar `BOLETINES/BOLETIN - {barra}.pdf`;
- procesar uno o todos los reportes.

### PAGO DE REGALIAS.py

Plantilla actual:

- `PAGO DE REGALIAS.xlsx` -> `templates/generated/certificado-regalias.html`

Funciones que deben conservarse:

- listar años y meses desde `~/Documents/CI GREEN GLOBAL`;
- encontrar entregas del mes;
- encontrar boletines dentro de cada entrega;
- extraer proveedor, NIT, fecha, mes, finos y regalías;
- agrupar por sociedad;
- dividir en paginas de 4 boletines;
- generar `CERTIFICADO DE REGALIAS {sociedad} - {mes}.pdf`.

## Pendientes tecnicos

- Ajustar la fidelidad visual de HTML a PDF desde el navegador.
- Elegir motor final de PDF si se requiere descarga automatica server-side. En Render gratis se evita LibreOffice.
- Crear una base de datos externa para persistencia real en Render Free.
- Sustituir `SOCIEDADES.xlsx` y `REGALIAS.xlsx` por base de datos cuando el flujo web este validado.
- Agregar usuarios y permisos si el sistema va a estar en internet.
