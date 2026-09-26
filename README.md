# Lector OMR CEPRE UNU

Aplicacion web local para revisar por lote hasta mas de 500 hojas OMR de 140 preguntas y cinco alternativas.

## Inicio

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra `http://127.0.0.1:8000` en el navegador.


Imprima `app/static/ficha-omr.pdf` en A4 horizontal. Al escanear la hoja completa, las 140 burbujas coinciden con la cuadricula del lector.
