"""
Punto de entrada para el ejecutable LectorOMR.
Lanza uvicorn en un hilo y abre el navegador automáticamente.
"""
from __future__ import annotations

import sys
import os
import time
import threading
import webbrowser

# ── Ajuste de rutas cuando corre como PyInstaller onefile ──────────────────
if getattr(sys, "frozen", False):
    # _MEIPASS es la carpeta temporal donde PyInstaller extrae los archivos
    BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
    # Ejecutamos desde esa carpeta para que los paths relativos funcionen
    os.chdir(BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"


def _open_browser() -> None:
    """Espera un momento y abre el navegador predeterminado."""
    time.sleep(2.5)
    webbrowser.open(URL)


def main() -> None:
    import uvicorn

    print("=" * 55)
    print("  Lector OMR CEPRE UNU")
    print(f"  Servidor iniciado en {URL}")
    print("  Abriendo navegador…")
    print("  Cierra esta ventana para detener el servidor.")
    print("=" * 55)

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
