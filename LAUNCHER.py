import sys
import subprocess
from pathlib import Path
from PIL import Image
import customtkinter as ctk
from tkinter import messagebox
import math

# ================= CONFIGURACIÓN =================
BASE_PATH = Path(__file__).resolve().parent

# Busca logo en varias rutas (no inventa, solo intenta)
CANDIDATE_LOGOS = [
    BASE_PATH / "IMAGENES" / "LOGO GREEN.png",
    BASE_PATH / "logo.png",
    BASE_PATH / "logo.jpg",
    BASE_PATH / "logo.jpeg",
]

LOGO_PATH = next((p for p in CANDIDATE_LOGOS if p.exists()), None)

APP_OWNER = "GREEN GLOBAL"
APP_TITLE = f"Panel de Control | {APP_OWNER}"
APP_SIZE = "600x780"

# 🎨 Colores
COLOR_BOTON = "#0E3662"
COLOR_BOTON_HOVER = "#C0C9D6"
COLOR_TEXTO = "#1C1C1C"
COLOR_BOTON_TEXTO = "#FFFFFF"

SCRIPTS = [
    ("🌐", "VERSIÓN WEB LOCAL", "WEBAPP.py"),
    ("📄", "DOCUMENTOS", "DOCUMENTOS.py"),
    ("⚜️", "REPORTE DE LEYES", "LEYES.py"),
    ("📰", "GENERAR BOLETINES", "BOLETINES.py"),
    ("🪙", "CERTIFICADO REGALIAS" , "PAGO DE REGALIAS.PY"),
]

# ================= FUNCIONES =================
def ejecutar_script(nombre):
    ruta = BASE_PATH / nombre
    if not ruta.exists():
        messagebox.showerror("Error", f"No se encontró el script:\n{ruta}")
        return
    try:
        subprocess.Popen([sys.executable, str(ruta)], cwd=str(BASE_PATH))
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo ejecutar {nombre}\n\n{e}")

def animar_hover(widget, icon_label, hover=True):
    color = COLOR_BOTON_HOVER if hover else COLOR_BOTON
    widget.configure(fg_color=color)
    icon_label.configure(fg_color="transparent")

def rotar_emoji(icon_label, duracion=400, pasos=36):
    radio = 4
    intervalo = duracion // pasos

    def frame(i):
        if i >= pasos:
            icon_label.place_configure(relx=0.1, rely=0.5, anchor="center")
            return
        angulo = 2 * math.pi * (i / pasos)
        dx = radio * math.sin(angulo)
        dy = radio * math.cos(angulo)
        icon_label.place_configure(relx=0.1 + dx / 300, rely=0.5 + dy / 300, anchor="center")
        app.after(intervalo, lambda: frame(i + 1))

    frame(0)

# ================= INTERFAZ =================
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

COLOR_FONDO = "#F4F7FA"
COLOR_PANEL = "#FFFFFF"
COLOR_BORDE = "#D8E0EA"
COLOR_MUTED = "#667085"
COLOR_ACCENT_SOFT = "#E9F0F7"
COLOR_ACCENT_DARK = "#092A4D"

MODULE_DETAILS = {
    "WEBAPP.py": ("WEB", "VERSIÓN WEB LOCAL", "Panel inicial de migración con plantillas HTML"),
    "DOCUMENTOS.py": ("DOC", "DOCUMENTOS", "Preliminares, recibos y creación de entrega"),
    "LEYES.py": ("LEY", "REPORTE DE LEYES", "Registro de leyes AU/AG y reportes por sociedad"),
    "BOLETINES.py": ("BOL", "GENERAR BOLETINES", "Liquidación, cierre de venta y boletines PDF"),
    "PAGO DE REGALIAS.PY": ("REG", "CERTIFICADO REGALÍAS", "Certificados mensuales agrupados por sociedad"),
}

app = ctk.CTk()
app.title(APP_TITLE)
app.geometry("820x730")
app.resizable(False, False)
app.configure(fg_color=COLOR_FONDO)

def fade_in(step=0):
    try:
        alpha = min(1.0, 0.90 + step * 0.025)
        app.attributes("-alpha", alpha)
        if alpha < 1.0:
            app.after(20, lambda: fade_in(step + 1))
    except Exception:
        pass

def animate_row(row, target_y=7, current_y=20):
    if current_y <= target_y:
        row.pack_configure(pady=target_y)
        return
    row.pack_configure(pady=(current_y, target_y))
    app.after(18, lambda: animate_row(row, target_y, current_y - 2))

shell = ctk.CTkFrame(app, fg_color=COLOR_FONDO, corner_radius=0)
shell.pack(fill="both", expand=True, padx=28, pady=22)

header = ctk.CTkFrame(shell, fg_color=COLOR_PANEL, corner_radius=16, border_width=1, border_color=COLOR_BORDE)
header.pack(fill="x", pady=(0, 16))
header.grid_columnconfigure(1, weight=1)

if LOGO_PATH and LOGO_PATH.exists():
    logo_img = Image.open(LOGO_PATH).convert("RGBA")
    bbox = logo_img.getbbox()
    if bbox:
        logo_img = logo_img.crop(bbox)
    display_size = (96, 72)
    logo_hd = logo_img.resize((display_size[0] * 3, display_size[1] * 3), Image.LANCZOS)
    logo_ctk = ctk.CTkImage(light_image=logo_hd, dark_image=logo_hd, size=display_size)
    logo_label = ctk.CTkLabel(header, image=logo_ctk, text="")
    logo_label.grid(row=0, column=0, rowspan=3, padx=(22, 18), pady=18, sticky="w")
else:
    logo_label = ctk.CTkLabel(header, text="GG", width=82, height=62, corner_radius=14, fg_color=COLOR_BOTON, text_color="white", font=ctk.CTkFont(size=22, weight="bold"))
    logo_label.grid(row=0, column=0, rowspan=3, padx=(22, 18), pady=18, sticky="w")

ctk.CTkLabel(
    header,
    text="SISTEMA DE LIQUIDACIÓN",
    font=ctk.CTkFont(family="Helvetica", size=25, weight="bold"),
    text_color=COLOR_TEXTO
).grid(row=0, column=1, sticky="sw", padx=(0, 22), pady=(22, 0))

ctk.CTkLabel(
    header,
    text=f"{APP_OWNER.upper()} | Panel operativo documental",
    font=ctk.CTkFont(family="Helvetica", size=15, weight="bold"),
    text_color=COLOR_BOTON
).grid(row=1, column=1, sticky="w", padx=(0, 22), pady=(6, 0))

ctk.CTkLabel(
    header,
    text="Documentos, leyes, boletines y certificados desde un solo lugar",
    font=ctk.CTkFont(family="Helvetica", size=12),
    text_color=COLOR_MUTED
).grid(row=2, column=1, sticky="nw", padx=(0, 22), pady=(4, 20))

module_panel = ctk.CTkFrame(shell, fg_color="transparent")
module_panel.pack(fill="both", expand=True)

def bind_row_hover(row, button, badge):
    def enter(_event=None):
        row.configure(border_color=COLOR_BOTON, fg_color="#FBFCFE")
        button.configure(fg_color=COLOR_ACCENT_DARK)
        badge.configure(fg_color="#DCE8F5")
    def leave(_event=None):
        row.configure(border_color=COLOR_BORDE, fg_color=COLOR_PANEL)
        button.configure(fg_color=COLOR_BOTON)
        badge.configure(fg_color=COLOR_ACCENT_SOFT)
    row.bind("<Enter>", enter)
    row.bind("<Leave>", leave)

def create_module_row(parent, code, title, description, script):
    row = ctk.CTkFrame(parent, fg_color=COLOR_PANEL, corner_radius=14, border_width=1, border_color=COLOR_BORDE, height=86)
    row.pack(fill="x", pady=7)
    row.pack_propagate(False)
    row.grid_columnconfigure(1, weight=1)
    row.bind("<Button-1>", lambda e, s=script: ejecutar_script(s))

    badge = ctk.CTkLabel(
        row,
        text=code,
        width=64,
        height=48,
        corner_radius=12,
        fg_color=COLOR_ACCENT_SOFT,
        text_color=COLOR_BOTON,
        font=ctk.CTkFont(family="Helvetica", size=15, weight="bold")
    )
    badge.grid(row=0, column=0, rowspan=2, padx=(18, 16), pady=18, sticky="w")

    ctk.CTkLabel(
        row,
        text=title,
        font=ctk.CTkFont(family="Helvetica", size=17, weight="bold"),
        text_color=COLOR_TEXTO,
        anchor="w"
    ).grid(row=0, column=1, sticky="sw", padx=(0, 14), pady=(17, 0))

    ctk.CTkLabel(
        row,
        text=description,
        font=ctk.CTkFont(family="Helvetica", size=12),
        text_color=COLOR_MUTED,
        anchor="w"
    ).grid(row=1, column=1, sticky="nw", padx=(0, 14), pady=(3, 16))

    btn = ctk.CTkButton(
        row,
        text="ABRIR",
        command=lambda s=script: ejecutar_script(s),
        width=118,
        height=40,
        corner_radius=10,
        fg_color=COLOR_BOTON,
        hover_color=COLOR_ACCENT_DARK,
        text_color=COLOR_BOTON_TEXTO,
        font=ctk.CTkFont(size=13, weight="bold")
    )
    btn.grid(row=0, column=2, rowspan=2, padx=(10, 18), pady=20, sticky="e")
    bind_row_hover(row, btn, badge)
    return row

rows = []
for _icon, fallback_title, script in SCRIPTS:
    code, title, description = MODULE_DETAILS.get(script, ("MOD", fallback_title.upper(), "Abrir módulo"))
    rows.append(create_module_row(module_panel, code, title, description, script))

footer = ctk.CTkFrame(shell, fg_color="transparent")
footer.pack(fill="x", pady=(8, 0))
ctk.CTkLabel(
    footer,
    text="Angel Systems",
    font=ctk.CTkFont(family="Helvetica", size=12, weight="bold"),
    text_color=COLOR_MUTED
).pack(side="right")

for idx, row in enumerate(rows):
    app.after(90 + idx * 55, lambda r=row: animate_row(r))
fade_in()
app.mainloop()
