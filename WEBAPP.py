import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from tkinter import messagebox


BASE_PATH = Path(__file__).resolve().parent
WEBAPP_PATH = BASE_PATH / "webapp" / "app.py"
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def main() -> None:
    if not WEBAPP_PATH.exists():
        messagebox.showerror("Version web", f"No se encontro:\n{WEBAPP_PATH}")
        return

    if not port_is_open(HOST, PORT):
        subprocess.Popen(
            [sys.executable, str(WEBAPP_PATH), "--host", HOST, "--port", str(PORT)],
            cwd=str(BASE_PATH),
        )
        time.sleep(1.2)

    webbrowser.open(URL)
    messagebox.showinfo("Version web", f"Panel web local disponible en:\n{URL}")


if __name__ == "__main__":
    main()
