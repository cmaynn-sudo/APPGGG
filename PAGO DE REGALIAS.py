import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox
import os
import re
from datetime import datetime
from pathlib import Path
import sys
import shutil
import tempfile
import pdfplumber
import zipfile
import xml.etree.ElementTree as ET

# =============================
# CONFIGURACIÓN / CONSTANTES
# =============================
APP_OWNER = "Angel"
SHEET_REGALIAS_PREFERRED = "REGALIAS"  # si no existe, usa la primera hoja

SOFFICE_CMD_PRIMARY = r"C:\Program Files\LibreOffice\program\soffice.exe"
SOFFICE_CMD_FALLBACK = r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "plantillas"
if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR = BASE_DIR

FILE_PLANTILLA_REGALIAS = str(TEMPLATES_DIR / "PAGO DE REGALIAS.xlsx")

# Celdas / filas de plantilla
CELL_SOCIEDAD = "A10"
CELL_NIT      = "E10"

# Zona detalle (por hoja)
DETALLE_ROW_START = 15
DETALLE_ROW_END   = 18
MAX_DETALLE_FILAS = DETALLE_ROW_END - DETALLE_ROW_START + 1   # 4 filas por hoja

COL_DOC   = "A"
COL_FECHA = "B"
COL_MES   = "C"
COL_ORO   = "D"  # FINOS ORO
COL_PLATA = "E"  # FINOS PLATA
COL_REG_O = "F"  # REGALÍAS ORO
COL_REG_P = "G"  # REGALÍAS PLATA

# Fila de totales detectada en tu plantilla: 19
TOTAL_ROW = 19
TOTAL_COLS = [COL_ORO, COL_PLATA, COL_REG_O, COL_REG_P]  # D,E,F,G

MESES_ES = {
    "January": "ENERO", "February": "FEBRERO", "March": "MARZO",
    "April": "ABRIL", "May": "MAYO", "June": "JUNIO",
    "July": "JULIO", "August": "AGOSTO", "September": "SEPTIEMBRE",
    "October": "OCTUBRE", "November": "NOVIEMBRE", "December": "DICIEMBRE"
}
MESES_ORDEN = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]

ROOT_BASE = Path.home() / "Documents" / "CI GREEN GLOBAL"
NIT_EMPRESA = "901.640.887-1"


# =============================
# HELPERS GENERAL
# =============================
def _get_soffice_cmd() -> str:
    if os.name == "nt":
        if os.path.exists(SOFFICE_CMD_PRIMARY):
            return SOFFICE_CMD_PRIMARY
        if os.path.exists(SOFFICE_CMD_FALLBACK):
            return SOFFICE_CMD_FALLBACK
        return ""

    if sys.platform == "darwin":
        mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        return mac if os.path.exists(mac) else "soffice"

    return "soffice"

def export_to_pdf_with_lo(xlsx_path: str, desired_pdf_path: str) -> bool:
    outdir = os.path.dirname(desired_pdf_path)
    base_pdf_name = os.path.splitext(os.path.basename(xlsx_path))[0] + ".pdf"
    generated_pdf_path = os.path.join(outdir, base_pdf_name)

    soffice = _get_soffice_cmd()
    if not soffice:
        messagebox.showerror(
            "LibreOffice no encontrado",
            "No se encontró LibreOffice.\n\n"
            f"PRIMARY:\n{SOFFICE_CMD_PRIMARY}\n\n"
            f"FALLBACK:\n{SOFFICE_CMD_FALLBACK}"
        )
        return False

    try:
        if os.path.exists(generated_pdf_path):
            os.remove(generated_pdf_path)
    except:
        pass

    cmd = f'"{soffice}" --headless --convert-to pdf --outdir "{outdir}" "{xlsx_path}"'
    os.system(cmd)

    if os.path.exists(generated_pdf_path):
        try:
            if os.path.exists(desired_pdf_path):
                os.remove(desired_pdf_path)
            os.rename(generated_pdf_path, desired_pdf_path)
            return True
        except:
            return os.path.exists(desired_pdf_path)

    return False

def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "-", name)
    name = re.sub(r"\s+", " ", name)
    return name

def parse_number_es(num_str: str):
    if num_str is None:
        return None
    s = str(num_str).strip()
    if s == "":
        return None
    s = re.sub(r"[^\d\.,\-]", "", s)

    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
        try:
            return float(s)
        except:
            return None
    else:
        s = s.replace(".", "")
        try:
            return int(s)
        except:
            try:
                return float(s)
            except:
                return None

def month_es_from_date_str(ddmmyyyy: str) -> str:
    try:
        dt = datetime.strptime(ddmmyyyy, "%d/%m/%Y")
        mes_en = dt.strftime("%B")
        return MESES_ES.get(mes_en, mes_en).upper()
    except:
        return ""

def extract_text_from_pdf(pdf_path: str) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)

def extract_document_from_filename(pdf_path: str) -> str:
    base = os.path.basename(pdf_path)
    m = re.search(r"BOLETIN\s*-\s*([A-ZÑ0-9]+-\d+)\.pdf$", base, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    return os.path.splitext(base)[0].strip()

def find_value(regex: str, text: str, flags=re.IGNORECASE):
    m = re.search(regex, text, flags)
    if m:
        return m.group(1).strip()
    return ""

def verify_template() -> bool:
    if not os.path.exists(FILE_PLANTILLA_REGALIAS):
        messagebox.showerror(
            "Falta plantilla",
            f"No se encontró PAGO DE REGALIAS.xlsx en:\n{FILE_PLANTILLA_REGALIAS}\n\n"
            "Solución:\n- Pon la plantilla en la carpeta 'plantillas' o junto al .py."
        )
        return False
    return True


# =============================
# PARSEO REGALÍAS + NIT PROVEEDOR
# =============================
def _extract_nit_proveedor(text: str) -> str:
    patron_nit_con_label = r"NIT:\s*(\d{3}\.\d{3}\.\d{3}-\d)"
    nits = re.findall(patron_nit_con_label, text, flags=re.IGNORECASE)
    if len(nits) >= 2:
        return nits[1].strip()

    patron_nit = r"\b\d{3}\.\d{3}\.\d{3}-\d\b"
    posibles_nits = re.findall(patron_nit, text)

    nit_empresa_clean = (NIT_EMPRESA or "").strip()
    for nit in posibles_nits:
        nit_clean = nit.strip()
        if nit_clean and nit_clean != nit_empresa_clean:
            return nit_clean
    return ""

def _extract_regalias_from_text(text: str):
    t = text.replace("\t", " ")
    t = re.sub(r"[ ]{2,}", " ", t)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]

    idx = None
    for i, ln in enumerate(lines):
        if re.search(r"(REGAL[ÍI]AS|REGALIZAS)\s+ADEUDADAS\s+POR\s+EL\s+PROVEEDOR", ln, flags=re.IGNORECASE):
            idx = i
            break

    if idx is None:
        for i, ln in enumerate(lines):
            if re.search(r"REGAL", ln, flags=re.IGNORECASE):
                window = lines[i:i+10]
                for w in window:
                    m0 = re.match(r"^\$?\s*([\d\.\,]+)\s+\$?\s*([\d\.\,]+)\s*$", w)
                    if m0:
                        return parse_number_es(m0.group(1)), parse_number_es(m0.group(2))
        return None, None

    window = lines[idx: min(len(lines), idx + 14)]

    order = "ORO_PLATA"
    for w in window:
        if re.fullmatch(r"ORO\s+PLATA", w, flags=re.IGNORECASE):
            order = "ORO_PLATA"
            break
        if re.fullmatch(r"PLATA\s+ORO", w, flags=re.IGNORECASE):
            order = "PLATA_ORO"
            break

    for w in window:
        m = re.match(r"^\$?\s*([\d\.\,]+)\s+\$?\s*([\d\.\,]+)\s*$", w)
        if m:
            a = parse_number_es(m.group(1))
            b = parse_number_es(m.group(2))
            if order == "PLATA_ORO":
                return b, a
            return a, b

    for w in window:
        if "$" in w:
            before = w.split("$", 1)[0]
            if re.search(r"[A-ZÑ]", before, flags=re.IGNORECASE):
                continue
        m2 = re.search(r"\$?\s*([\d\.\,]+)\s+\$?\s*([\d\.\,]+)", w)
        if m2:
            a = parse_number_es(m2.group(1))
            b = parse_number_es(m2.group(2))
            if order == "PLATA_ORO":
                return b, a
            return a, b

    return None, None

def parse_boletin_pdf(pdf_path: str) -> dict:
    text = extract_text_from_pdf(pdf_path)
    documento = extract_document_from_filename(pdf_path)

    proveedor = find_value(r"PROVEEDOR\s*:\s*(.+)", text)
    proveedor = proveedor.split("\n")[0].strip()

    nit = _extract_nit_proveedor(text)

    fecha = ""
    mfecha = re.search(r"FECHA.*?(\d{2}/\d{2}/\d{4})", text, flags=re.IGNORECASE | re.DOTALL)
    if mfecha:
        fecha = mfecha.group(1).strip()
    else:
        mfecha2 = re.search(r"(\d{2}/\d{2}/\d{4})", text)
        if mfecha2:
            fecha = mfecha2.group(1).strip()

    mes = month_es_from_date_str(fecha) if fecha else ""

    finos_oro_s = ""
    finos_plata_s = ""

    m_oro = re.search(r"FINO\s*\(G\)\s*ORO\s*([\d\.\,]+)", text, flags=re.IGNORECASE)
    if m_oro:
        finos_oro_s = m_oro.group(1)

    m_plata = re.search(r"FINO\s*\(G\)\s*PLATA\s*([\d\.\,]+)", text, flags=re.IGNORECASE)
    if m_plata:
        finos_plata_s = m_plata.group(1)

    if not finos_oro_s or not finos_plata_s:
        for line in text.splitlines():
            if re.search(r"FINO\s*\(G\)", line, flags=re.IGNORECASE):
                nums = re.findall(r"[\d\.\,]+", line)
                if len(nums) >= 2:
                    finos_oro_s = finos_oro_s or nums[-2]
                    finos_plata_s = finos_plata_s or nums[-1]
                    break

    finos_oro = parse_number_es(finos_oro_s)
    finos_plata = parse_number_es(finos_plata_s)

    regalia_oro, regalia_plata = _extract_regalias_from_text(text)

    return {
        "pdf_path": pdf_path,
        "documento": documento,
        "proveedor": proveedor,
        "nit": nit,
        "fecha": fecha,
        "mes": mes,
        "finos_oro": finos_oro,
        "finos_plata": finos_plata,
        "regalia_oro": regalia_oro,
        "regalia_plata": regalia_plata,
    }

def sort_boletines(items: list) -> list:
    def key(d):
        doc = d.get("documento", "")
        m = re.match(r"([A-ZÑ0-9]+)-(\d+)", doc)
        if m:
            return (m.group(1), int(m.group(2)))
        return (doc, 0)
    return sorted(items, key=key)


# =============================
# XLSX XML EDITOR + DUPLICAR HOJAS (PRESERVA TODO)
# =============================
_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("", _NS_MAIN)
ET.register_namespace("r", _NS_REL)

def _col_to_num(col: str) -> int:
    col = col.upper().strip()
    n = 0
    for ch in col:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - ord("A") + 1)
    return n

def _split_addr(addr: str):
    m = re.match(r"^([A-Z]+)(\d+)$", addr.upper().strip())
    if not m:
        raise ValueError(f"Dirección inválida: {addr}")
    return m.group(1), int(m.group(2))

def _sheet_files_from_workbook(z: zipfile.ZipFile):
    wb_xml = z.read("xl/workbook.xml")
    wb = ET.fromstring(wb_xml)
    sheets = wb.find(f"{{{_NS_MAIN}}}sheets")
    sheet_elems = sheets.findall(f"{{{_NS_MAIN}}}sheet") if sheets is not None else []

    rels_xml = z.read("xl/_rels/workbook.xml.rels")
    rels = ET.fromstring(rels_xml)
    rid_to_target = {}
    for rel in rels.findall(f"{{{_NS_PKG_REL}}}Relationship"):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            rid_to_target[rid] = target

    mapping = {}
    first_path = None
    for sh in sheet_elems:
        name = sh.attrib.get("name", "")
        rid = sh.attrib.get(f"{{{_NS_REL}}}id")
        target = rid_to_target.get(rid, "")
        if target:
            if target.startswith("/"):
                target = target[1:]
            if not target.startswith("xl/"):
                path = "xl/" + target
            else:
                path = target
            mapping[name] = path
            if first_path is None:
                first_path = path

    return mapping, first_path

def _find_or_create_row(root, row_idx: int):
    sheetData = root.find(f"{{{_NS_MAIN}}}sheetData")
    if sheetData is None:
        sheetData = ET.SubElement(root, f"{{{_NS_MAIN}}}sheetData")

    for row in sheetData.findall(f"{{{_NS_MAIN}}}row"):
        if int(row.attrib.get("r", "0")) == row_idx:
            return row

    row = ET.SubElement(sheetData, f"{{{_NS_MAIN}}}row", {"r": str(row_idx)})
    sheetData[:] = sorted(sheetData, key=lambda e: int(e.attrib.get("r", "0")))
    return row

def _find_cell(row_elem, addr: str):
    for c in row_elem.findall(f"{{{_NS_MAIN}}}c"):
        if c.attrib.get("r") == addr:
            return c
    return None

def _create_cell(row_elem, addr: str):
    c = ET.SubElement(row_elem, f"{{{_NS_MAIN}}}c", {"r": addr})

    def _cell_key(cell):
        a = cell.attrib.get("r", "")
        col, _r = _split_addr(a)
        return _col_to_num(col)

    cells = row_elem.findall(f"{{{_NS_MAIN}}}c")
    row_elem[:] = sorted(cells, key=_cell_key)
    return c

def _find_or_create_cell(row_elem, addr: str):
    c = _find_cell(row_elem, addr)
    if c is not None:
        return c
    return _create_cell(row_elem, addr)

def _clear_cell_preserve_style(cell_elem):
    for ch in list(cell_elem):
        cell_elem.remove(ch)
    cell_elem.attrib.pop("t", None)

def _set_cell_inline_str_preserve_style(cell_elem, value: str):
    for ch in list(cell_elem):
        cell_elem.remove(ch)
    cell_elem.attrib["t"] = "inlineStr"
    is_elem = ET.SubElement(cell_elem, f"{{{_NS_MAIN}}}is")
    t_elem = ET.SubElement(is_elem, f"{{{_NS_MAIN}}}t")
    t_elem.text = "" if value is None else str(value)

def _set_cell_number_preserve_style(cell_elem, value):
    for ch in list(cell_elem):
        cell_elem.remove(ch)
    cell_elem.attrib.pop("t", None)
    v = ET.SubElement(cell_elem, f"{{{_NS_MAIN}}}v")
    v.text = "" if (value is None or value == "") else str(value)

def _write_cells_to_xlsx(xlsx_path: str, sheet_name: str, updates: list):
    tmp_out = xlsx_path + ".xmltmp"

    with zipfile.ZipFile(xlsx_path, "r") as zin:
        mapping, first_sheet_path = _sheet_files_from_workbook(zin)
        sheet_path = mapping.get(sheet_name) or first_sheet_path
        if not sheet_path:
            raise RuntimeError("No se encontró ninguna hoja en el XLSX.")

        sheet_xml = zin.read(sheet_path)
        root = ET.fromstring(sheet_xml)

        for addr, kind, val in updates:
            _col, row_idx = _split_addr(addr)
            row_elem = _find_or_create_row(root, row_idx)
            cell_elem = _find_or_create_cell(row_elem, addr)

            if kind == "clear":
                _clear_cell_preserve_style(cell_elem)
            elif kind == "s":
                _set_cell_inline_str_preserve_style(cell_elem, val)
            elif kind == "n":
                _set_cell_number_preserve_style(cell_elem, val)
            else:
                _set_cell_inline_str_preserve_style(cell_elem, val)

        new_sheet_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(tmp_out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == sheet_path:
                    zout.writestr(item, new_sheet_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

    os.replace(tmp_out, xlsx_path)

def clear_detail_area_xml(xlsx_path: str, sheet_name: str):
    updates = []
    cols = [COL_DOC, COL_FECHA, COL_MES, COL_ORO, COL_PLATA, COL_REG_O, COL_REG_P]
    for r in range(DETALLE_ROW_START, DETALLE_ROW_END + 1):
        for c in cols:
            updates.append((f"{c}{r}", "clear", None))
    _write_cells_to_xlsx(xlsx_path, sheet_name, updates)

def _safe_sheet_name(name: str) -> str:
    # Excel: max 31 chars + no [ ] : * ? / \
    name = re.sub(r"[\[\]\:\*\?\/\\]", "-", name).strip()
    if len(name) > 31:
        name = name[:31]
    if not name:
        name = "HOJA"
    return name

def duplicate_sheet_full(xlsx_path: str, src_sheet_name: str, new_sheet_name: str) -> str:
    """
    Duplica una hoja COMPLETA dentro del XLSX (sheet xml + rels),
    preservando todo lo que cuelga debajo (firmas, imágenes, shapes, etc.)
    """
    new_sheet_name = _safe_sheet_name(new_sheet_name)

    tmp_out = xlsx_path + ".dupsheet_tmp"

    with zipfile.ZipFile(xlsx_path, "r") as zin:
        # ---- leer workbook.xml ----
        wb_xml = zin.read("xl/workbook.xml")
        wb_root = ET.fromstring(wb_xml)
        sheets_node = wb_root.find(f"{{{_NS_MAIN}}}sheets")
        if sheets_node is None:
            raise RuntimeError("workbook.xml no tiene <sheets>.")

        # ---- leer workbook.xml.rels ----
        rels_xml = zin.read("xl/_rels/workbook.xml.rels")
        rels_root = ET.fromstring(rels_xml)

        # map rId -> target
        rid_to_target = {}
        max_rid_num = 0
        for rel in rels_root.findall(f"{{{_NS_PKG_REL}}}Relationship"):
            rid = rel.attrib.get("Id", "")
            tgt = rel.attrib.get("Target", "")
            rid_to_target[rid] = tgt
            m = re.match(r"rId(\d+)$", rid)
            if m:
                max_rid_num = max(max_rid_num, int(m.group(1)))

        # encontrar hoja origen
        src_sheet_elem = None
        for sh in sheets_node.findall(f"{{{_NS_MAIN}}}sheet"):
            if sh.attrib.get("name", "") == src_sheet_name:
                src_sheet_elem = sh
                break
        if src_sheet_elem is None:
            raise RuntimeError(f"No existe la hoja origen: {src_sheet_name}")

        src_rid = src_sheet_elem.attrib.get(f"{{{_NS_REL}}}id")
        src_target = rid_to_target.get(src_rid, "")
        if not src_target:
            raise RuntimeError("No se pudo resolver target de la hoja origen.")

        # src sheet path real dentro del zip
        src_target = src_target.lstrip("/")
        if not src_target.startswith("xl/"):
            src_sheet_path = "xl/" + src_target
        else:
            src_sheet_path = src_target

        # deducir nombre sheetX.xml
        # buscar índices usados por archivos xl/worksheets/sheetN.xml
        used = set()
        for info in zin.infolist():
            m = re.match(r"xl/worksheets/sheet(\d+)\.xml$", info.filename)
            if m:
                used.add(int(m.group(1)))
        new_index = 1
        while new_index in used:
            new_index += 1

        new_sheet_filename = f"sheet{new_index}.xml"
        new_sheet_path = f"xl/worksheets/{new_sheet_filename}"

        # copiar sheet xml
        src_sheet_bytes = zin.read(src_sheet_path)

        # copiar sheet rels si existe
        src_rels_path = f"xl/worksheets/_rels/{os.path.basename(src_sheet_path)}.rels"
        new_rels_path = f"xl/worksheets/_rels/{new_sheet_filename}.rels"
        src_rels_bytes = zin.read(src_rels_path) if src_rels_path in zin.namelist() else None

        # agregar Relationship nuevo en workbook.xml.rels
        new_rid = f"rId{max_rid_num + 1}"
        new_rel = ET.Element(f"{{{_NS_PKG_REL}}}Relationship", {
            "Id": new_rid,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            "Target": f"worksheets/{new_sheet_filename}",
        })
        rels_root.append(new_rel)

        # calcular nuevo sheetId
        max_sheet_id = 0
        for sh in sheets_node.findall(f"{{{_NS_MAIN}}}sheet"):
            try:
                max_sheet_id = max(max_sheet_id, int(sh.attrib.get("sheetId", "0")))
            except:
                pass
        new_sheet_id = str(max_sheet_id + 1)

        # agregar hoja nueva a workbook.xml
        new_sheet_elem = ET.Element(f"{{{_NS_MAIN}}}sheet", {
            "name": new_sheet_name,
            "sheetId": new_sheet_id,
            f"{{{_NS_REL}}}id": new_rid
        })
        sheets_node.append(new_sheet_elem)

        new_wb_xml = ET.tostring(wb_root, encoding="utf-8", xml_declaration=True)
        new_rels_xml = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)

        # actualizar [Content_Types].xml para el nuevo sheet
        ct_xml = zin.read("[Content_Types].xml")
        ct_root = ET.fromstring(ct_xml)
        # chequear si ya existe override
        part_name = f"/xl/worksheets/{new_sheet_filename}"
        exists = False
        for ov in ct_root.findall("{http://schemas.openxmlformats.org/package/2006/content-types}Override"):
            if ov.attrib.get("PartName") == part_name:
                exists = True
                break
        if not exists:
            ov = ET.Element("{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
                "PartName": part_name,
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
            })
            ct_root.append(ov)

        new_ct_xml = ET.tostring(ct_root, encoding="utf-8", xml_declaration=True)

        # escribir zip nuevo
        with zipfile.ZipFile(tmp_out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "xl/workbook.xml":
                    zout.writestr(item, new_wb_xml)
                elif item.filename == "xl/_rels/workbook.xml.rels":
                    zout.writestr(item, new_rels_xml)
                elif item.filename == "[Content_Types].xml":
                    zout.writestr(item, new_ct_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

            # añadir sheet nuevo
            zout.writestr(new_sheet_path, src_sheet_bytes)
            if src_rels_bytes is not None:
                zout.writestr(new_rels_path, src_rels_bytes)

    os.replace(tmp_out, xlsx_path)
    return new_sheet_name

def fill_sociedad_xml(xlsx_path: str, sheet_name: str, sociedad: str, nit: str, boletines: list):
    """
    Llena una hoja (solo hasta 4 boletines porque la plantilla por hoja tiene 4 filas).
    IMPORTANTe: totales se escriben como VALOR (no fórmula) para que el PDF salga bien.
    """
    updates = []

    # A10 proveedor
    updates.append((CELL_SOCIEDAD, "s", sociedad))

    # E10 NIT SOLO (como pediste)
    updates.append((CELL_NIT, "s", nit or ""))

    # detalle
    row = DETALLE_ROW_START
    for b in boletines:
        updates.append((f"{COL_DOC}{row}",   "s", b.get("documento", "")))
        updates.append((f"{COL_FECHA}{row}", "s", b.get("fecha", "")))
        updates.append((f"{COL_MES}{row}",   "s", b.get("mes", "")))
        updates.append((f"{COL_ORO}{row}",   "n", b.get("finos_oro", None)))
        updates.append((f"{COL_PLATA}{row}", "n", b.get("finos_plata", None)))
        updates.append((f"{COL_REG_O}{row}", "n", b.get("regalia_oro", None)))
        updates.append((f"{COL_REG_P}{row}", "n", b.get("regalia_plata", None)))
        row += 1

    # limpiar filas sobrantes (si el chunk trae menos de 4)
    cols = [COL_DOC, COL_FECHA, COL_MES, COL_ORO, COL_PLATA, COL_REG_O, COL_REG_P]
    while row <= DETALLE_ROW_END:
        for c in cols:
            updates.append((f"{c}{row}", "clear", None))
        row += 1

    # totales (valor, no fórmula)
    tot_oro = 0.0
    tot_plata = 0.0
    tot_reg_oro = 0.0
    tot_reg_plata = 0.0

    for b in boletines:
        tot_oro += float(b.get("finos_oro") or 0)
        tot_plata += float(b.get("finos_plata") or 0)
        tot_reg_oro += float(b.get("regalia_oro") or 0)
        tot_reg_plata += float(b.get("regalia_plata") or 0)

    updates.append((f"{COL_ORO}{TOTAL_ROW}", "n", tot_oro))
    updates.append((f"{COL_PLATA}{TOTAL_ROW}", "n", tot_plata))
    updates.append((f"{COL_REG_O}{TOTAL_ROW}", "n", tot_reg_oro))
    updates.append((f"{COL_REG_P}{TOTAL_ROW}", "n", tot_reg_plata))

    _write_cells_to_xlsx(xlsx_path, sheet_name, updates)


# =============================
# BÚSQUEDA EN CARPETAS
# =============================
def list_years() -> list[str]:
    if not ROOT_BASE.exists():
        return []
    years = []
    for p in ROOT_BASE.iterdir():
        if p.is_dir() and re.match(r"^\d{4}$", p.name):
            years.append(p.name)
    years.sort()
    return years

def list_months_for_year(year: str) -> list[str]:
    year_dir = ROOT_BASE / year
    if not year_dir.exists():
        return []
    months = []
    for p in year_dir.iterdir():
        if p.is_dir():
            n = p.name.strip().upper()
            if n in MESES_ORDEN:
                months.append(n)
    months.sort(key=lambda m: MESES_ORDEN.index(m) if m in MESES_ORDEN else 999)
    return months

def find_entregas_in_month(base_mes: Path) -> list[Path]:
    entregas = []
    if not base_mes.exists():
        return entregas
    for p in base_mes.iterdir():
        if p.is_dir() and p.name.upper().startswith("ENTREGA"):
            entregas.append(p)
    entregas.sort(key=lambda x: x.name)
    return entregas

def find_boletin_pdfs_in_entrega(entrega_dir: Path) -> list[Path]:
    boletines_dir = entrega_dir / "BOLETINES"
    if not boletines_dir.exists() or not boletines_dir.is_dir():
        return []
    pdfs = []
    for f in boletines_dir.iterdir():
        if f.is_file() and f.suffix.lower() == ".pdf" and f.name.upper().startswith("BOLETIN"):
            pdfs.append(f)
    pdfs.sort(key=lambda x: x.name)
    return pdfs

def scan_month(year: str, month: str, log_fn):
    base_mes = ROOT_BASE / year / month
    warnings = []

    if not base_mes.exists():
        return base_mes, [], ["EN ESTE MES NO HAY SOCIEDADES"]

    entregas = find_entregas_in_month(base_mes)
    if not entregas:
        return base_mes, [], ["EN ESTE MES NO HAY SOCIEDADES"]

    all_pdfs = []
    for ent in entregas:
        pdfs = find_boletin_pdfs_in_entrega(ent)
        if not pdfs:
            warnings.append(f"EN LA ENTREGA ({ent.name}) NO HAY BOLETINES")
            continue
        all_pdfs.extend(pdfs)

    if not all_pdfs:
        if not warnings:
            warnings.append("EN ESTE MES NO HAY SOCIEDADES")
        return base_mes, [], warnings

    return base_mes, all_pdfs, warnings


# =============================
# GENERACIÓN
# =============================
def _copy_template_to_temp() -> str:
    tmp_dir = tempfile.mkdtemp(prefix="regalias_")
    tmp_xlsx = os.path.join(tmp_dir, "PAGO_DE_REGALIAS_TEMP.xlsx")
    shutil.copy2(FILE_PLANTILLA_REGALIAS, tmp_xlsx)
    return tmp_xlsx

def _cleanup_temp_file(temp_xlsx: str):
    try:
        tmp_dir = os.path.dirname(temp_xlsx)
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except:
        pass

def _get_base_sheet_name(xlsx_path: str) -> str:
    with zipfile.ZipFile(xlsx_path, "r") as z:
        mapping, first_sheet_path = _sheet_files_from_workbook(z)
        if SHEET_REGALIAS_PREFERRED in mapping:
            return SHEET_REGALIAS_PREFERRED
        # devolver la primera por nombre (no path)
        if mapping:
            return list(mapping.keys())[0]
        raise RuntimeError("No se encontró ninguna hoja en la plantilla.")

def _chunks(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]

def generate_for_selected_month(year: str, month: str, log_fn):
    if not verify_template():
        return

    base_mes, pdf_paths, warnings = scan_month(year, month, log_fn)
    log_fn(f"📂 Año/Mes seleccionado: {year}/{month}")
    log_fn(f"📍 Ruta: {base_mes}")

    for w in warnings:
        log_fn(f"⚠️ {w}")

    if not pdf_paths:
        messagebox.showwarning("Sin datos", "EN ESTE MES NO HAY SOCIEDADES")
        return

    log_fn(f"🔎 Boletines encontrados: {len(pdf_paths)}")

    boletines_data = []
    errores = 0

    for p in pdf_paths:
        try:
            d = parse_boletin_pdf(str(p))
            if not d.get("proveedor"):
                raise ValueError("No se pudo leer PROVEEDOR")
            if not d.get("mes"):
                d["mes"] = month
            boletines_data.append(d)
            log_fn(
                f"✅ OK: {d['documento']} | {d['proveedor']} | NIT={d.get('nit')} | "
                f"RegO={d.get('regalia_oro')} RegP={d.get('regalia_plata')}"
            )
        except Exception as e:
            errores += 1
            log_fn(f"❌ Error leyendo {p.name}: {e}")

    if not boletines_data:
        messagebox.showerror(
            "No se pudo procesar",
            "No se pudo extraer información de los boletines del mes seleccionado."
        )
        return

    if errores:
        log_fn(f"⚠️ Boletines con error: {errores}")

    # Agrupar por sociedad
    por_sociedad = {}
    nit_por_sociedad = {}
    for b in boletines_data:
        soc = (b.get("proveedor") or "").strip()
        if not soc:
            continue
        por_sociedad.setdefault(soc, []).append(b)

        nit_val = (b.get("nit") or "").strip()
        if soc not in nit_por_sociedad or (not nit_por_sociedad[soc] and nit_val):
            nit_por_sociedad[soc] = nit_val

    if not por_sociedad:
        messagebox.showwarning("Sin sociedades", "EN ESTE MES NO HAY SOCIEDADES")
        return

    total_sociedades = len(por_sociedad)
    log_fn(f"🧾 Sociedades detectadas: {total_sociedades}")

    generados = 0
    for sociedad, items in por_sociedad.items():
        items_sorted = sort_boletines(items)
        nit = nit_por_sociedad.get(sociedad, "")

        temp_xlsx = _copy_template_to_temp()

        try:
            base_sheet = _get_base_sheet_name(temp_xlsx)

            # dividir en chunks de 4 (por hoja)
            pages = list(_chunks(items_sorted, MAX_DETALLE_FILAS))

            # si necesita más hojas, duplicar
            sheet_names = [base_sheet]
            for i in range(1, len(pages)):
                new_name = _safe_sheet_name(f"{base_sheet} {i+1}")
                new_sheet = duplicate_sheet_full(temp_xlsx, base_sheet, new_name)
                sheet_names.append(new_sheet)

            # llenar cada hoja
            for i, chunk in enumerate(pages):
                sh = sheet_names[i]
                clear_detail_area_xml(temp_xlsx, sh)
                fill_sociedad_xml(temp_xlsx, sh, sociedad, nit, chunk)

            nombre_pdf = safe_filename(f"CERTIFICADO DE REGALÍAS {sociedad} - {month}.pdf")
            ruta_pdf = str(base_mes / nombre_pdf)

            ok = export_to_pdf_with_lo(temp_xlsx, ruta_pdf)
            if ok:
                generados += 1
                log_fn(f"📄 PDF generado: {nombre_pdf} ({len(pages)} hoja(s))")
            else:
                log_fn(f"❌ No se pudo generar PDF para: {sociedad}")

        finally:
            _cleanup_temp_file(temp_xlsx)

    messagebox.showinfo(
        "Proceso terminado",
        f"Listo.\n\nSociedades procesadas: {total_sociedades}\nPDFs generados: {generados}\n\nRuta:\n{base_mes}"
    )


# =============================
# UI (ttkbootstrap)
# =============================

BG = "#F4F7FA"
PANEL = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
BORDER = "#D8E0EA"
ACCENT = "#0E3662"

def configure_enterprise_style(window):
    window.configure(bg=BG)
    style = ttk.Style()
    style.configure("App.TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL, relief="solid", borderwidth=1)
    style.configure("Header.TFrame", background=ACCENT)
    style.configure("Title.TLabel", background=ACCENT, foreground="white", font=("Calibri", 23, "bold"))
    style.configure("Subtitle.TLabel", background=ACCENT, foreground="#DDE7F2", font=("Calibri", 11))
    style.configure("Section.TLabel", background=PANEL, foreground=INK, font=("Calibri", 13, "bold"))
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Calibri", 10))
    style.configure("Field.TLabel", background=PANEL, foreground=INK, font=("Calibri", 12, "bold"))
    style.configure("Treeview", rowheight=28, font=("Calibri", 11))
    style.configure("Treeview.Heading", font=("Calibri", 11, "bold"))

def make_header(parent, title, subtitle):
    header = ttk.Frame(parent, style="Header.TFrame", padding=(24, 18))
    header.pack(fill="x", pady=(0, 14))
    ttk.Label(header, text=title, style="Title.TLabel").pack(anchor="w")
    ttk.Label(header, text=subtitle, style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
    return header

def animate_window(window, step=0):
    try:
        alpha = min(1.0, 0.88 + step * 0.025)
        window.attributes("-alpha", alpha)
        if alpha < 1.0:
            window.after(20, lambda: animate_window(window, step + 1))
    except Exception:
        pass

def wire_button_hover(button, normal, hover):
    def enter(_event=None):
        try:
            if str(button.cget("state")) != "disabled":
                button.configure(bootstyle=hover)
        except Exception:
            pass
    def leave(_event=None):
        try:
            button.configure(bootstyle=normal)
        except Exception:
            pass
    button.bind("<Enter>", enter)
    button.bind("<Leave>", leave)
    return button

app = ttk.Window(themename="flatly")
app.title(f"Angel | CERTIFICADOS DE REGALÍAS")
app.geometry("1120x700")
app.minsize(1060, 660)
configure_enterprise_style(app)

main = ttk.Frame(app, style="App.TFrame", padding=16)
main.pack(fill="both", expand=True)
make_header(main, "CERTIFICADOS DE REGALÍAS", "Sistema Angel | Generación mensual agrupada por sociedad")

top = ttk.Frame(main, style="Card.TFrame", padding=18)
top.pack(fill="x", pady=(0, 12))
top.columnconfigure(5, weight=1)
ttk.Label(top, text="AÑO", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
combo_year = ttk.Combobox(top, width=12, font=("Calibri", 12), state="readonly")
combo_year.grid(row=0, column=1, sticky="w", padx=6)
ttk.Label(top, text="MES", style="Field.TLabel").grid(row=0, column=2, sticky="w", padx=(22, 8))
combo_month = ttk.Combobox(top, width=16, font=("Calibri", 12), state="readonly")
combo_month.grid(row=0, column=3, sticky="w", padx=6)
lbl_status = ttk.Label(top, text="", style="Muted.TLabel")
lbl_status.grid(row=1, column=0, columnspan=6, sticky="w", padx=0, pady=(12, 0))

frame_btn = ttk.Frame(main, style="Card.TFrame", padding=16)
frame_btn.pack(fill="x", pady=(0, 12))
frame_btn.columnconfigure(0, weight=1)
frame_btn.columnconfigure(1, weight=1)
frame_btn.columnconfigure(2, weight=1)
btn_generate = ttk.Button(frame_btn, text="GENERAR CERTIFICADOS", bootstyle=SUCCESS, state="disabled")
btn_generate.grid(row=0, column=0, padx=(0, 8), ipady=6, sticky="ew")
wire_button_hover(btn_generate, SUCCESS, PRIMARY)
btn_rescan = ttk.Button(frame_btn, text="REVISAR MES", bootstyle=INFO, state="disabled")
btn_rescan.grid(row=0, column=1, padx=8, ipady=6, sticky="ew")
wire_button_hover(btn_rescan, INFO, PRIMARY)
btn_clear_log = ttk.Button(frame_btn, text="LIMPIAR LOG", bootstyle=SECONDARY)
btn_clear_log.grid(row=0, column=2, padx=(8, 0), ipady=6, sticky="ew")
wire_button_hover(btn_clear_log, SECONDARY, PRIMARY)

log_panel = ttk.Frame(main, style="Card.TFrame", padding=16)
log_panel.pack(fill="both", expand=True)
ttk.Label(log_panel, text="Registro del proceso", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
log_box = ttk.Text(log_panel, height=20, font=("Consolas", 10), wrap="word")
log_box.pack(fill="both", expand=True)

def log(msg: str):
    log_box.insert("end", msg + "\n")
    log_box.see("end")
    app.update_idletasks()

def set_status(text: str, style=""):
    lbl_status.config(text=text)

def refresh_years():
    years = list_years()
    combo_year["values"] = years

    y_now = str(datetime.now().year)
    if y_now in years:
        combo_year.set(y_now)
    elif years:
        combo_year.set(years[-1])
    else:
        combo_year.set("")
    refresh_months_for_selected_year()

def refresh_months_for_selected_year():
    year = combo_year.get().strip()
    months = list_months_for_year(year) if year else []
    combo_month["values"] = months

    m_now = MESES_ES.get(datetime.now().strftime("%B"), datetime.now().strftime("%B")).upper()
    if m_now in months:
        combo_month.set(m_now)
    elif months:
        combo_month.set(months[-1])
    else:
        combo_month.set("")
    update_scan_and_buttons()

def update_scan_and_buttons():
    year = combo_year.get().strip()
    month = combo_month.get().strip()

    btn_generate.config(state="disabled")
    btn_rescan.config(state="disabled")

    if not year or not month:
        set_status("Selecciona un AÑO y un MES.", "")
        return

    if not verify_template():
        set_status("No se encontró la plantilla PAGO DE REGALIAS.xlsx.", "")
        return

    base_mes, pdfs, warnings = scan_month(year, month, log)

    if not base_mes.exists() or not pdfs:
        set_status("EN ESTE MES NO HAY SOCIEDADES", "")
        btn_generate.config(state="disabled")
        btn_rescan.config(state="normal")
        return

    set_status(f"Listo: {len(pdfs)} boletín(es) encontrado(s) en {year}/{month}.", "")
    btn_generate.config(state="normal")
    btn_rescan.config(state="normal")

def on_year_change(event=None):
    refresh_months_for_selected_year()

def on_month_change(event=None):
    update_scan_and_buttons()

def on_rescan():
    log("-" * 70)
    log("REVISANDO MES...")
    update_scan_and_buttons()

def on_generate():
    year = combo_year.get().strip()
    month = combo_month.get().strip()
    if not year or not month:
        messagebox.showwarning("Faltan datos", "Selecciona un AÑO y un MES.")
        return

    log("-" * 70)
    log("INICIANDO GENERACIÓN...")
    generate_for_selected_month(year, month, log)

def on_clear_log():
    log_box.delete("1.0", "end")

btn_generate.config(command=on_generate)
btn_rescan.config(command=on_rescan)
btn_clear_log.config(command=on_clear_log)

combo_year.bind("<<ComboboxSelected>>", on_year_change)
combo_month.bind("<<ComboboxSelected>>", on_month_change)

if not ROOT_BASE.exists():
    log(f"No existe la ruta base: {ROOT_BASE}")
    set_status(f"No existe la ruta base: {ROOT_BASE}", "")
else:
    log(f"Ruta base detectada: {ROOT_BASE}")

if verify_template():
    log("Plantilla encontrada.")
else:
    log("Plantilla NO encontrada.")

refresh_years()
animate_window(app)
app.mainloop()
