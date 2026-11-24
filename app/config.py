"""Rutas y ajustes compartidos por el programa.

Dónde se guardan los presupuestos:
  - Si existe `config.local.json` en la raíz del proyecto (lo crea install.ps1) con
    {"carpeta_datos": "C:\\Users\\...\\Documents\\Presupuestos"}, se usa esa carpeta.
  - Si no, se usan carpetas dentro del propio proyecto (cómodo para desarrollo).
Así el código (que se actualiza desde GitHub) y los datos quedan siempre separados.
"""
import json
from pathlib import Path

CARPETA_APP = Path(__file__).resolve().parent
RAIZ = CARPETA_APP.parent
CARPETA_WEB = CARPETA_APP / "web"
ARCHIVO_CONFIG_LOCAL = RAIZ / "config.local.json"


def _carpeta_datos() -> Path:
    try:
        ajustes = json.loads(ARCHIVO_CONFIG_LOCAL.read_text(encoding="utf-8-sig"))
        carpeta = str(ajustes.get("carpeta_datos") or "").strip()
        if carpeta:
            return Path(carpeta).expanduser()
    except (OSError, ValueError, AttributeError):
        pass
    return RAIZ


CARPETA_BASE_DATOS = _carpeta_datos()

# Carpetas visibles para el usuario
CARPETA_DATOS = CARPETA_BASE_DATOS / "Presupuestos guardados"
CARPETA_ELIMINADOS = CARPETA_DATOS / "Eliminados"
CARPETA_PDF = CARPETA_BASE_DATOS / "Presupuestos en PDF"
ARCHIVO_NOTAS = CARPETA_BASE_DATOS / "notas.json"  # notas personalizadas del PDF

ARCHIVO_REGISTRO = CARPETA_APP / "registro.log"
ARCHIVO_PUERTO = CARPETA_APP / ".puerto"

NOMBRE_APP = "creador-presupuestos"
PUERTOS = range(8765, 8776)


def calcular_version() -> str:
    """Huella de los archivos del programa: cambia cuando se modifica el código."""
    archivos = list(CARPETA_APP.glob("*.py")) + list(CARPETA_WEB.glob("*"))
    marca = max((int(a.stat().st_mtime) for a in archivos if a.is_file()), default=0)
    return str(marca)
