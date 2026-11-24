"""Guarda y lee presupuestos como archivos .json (uno por presupuesto)."""
import json
import logging
import os
import re
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from config import CARPETA_DATOS, CARPETA_ELIMINADOS, CARPETA_PDF

_candado = threading.Lock()
log = logging.getLogger(__name__)


class ErrorPresupuesto(Exception):
    """Error con un mensaje apto para mostrar al usuario."""


def asegurar_carpetas() -> None:
    for carpeta in (CARPETA_DATOS, CARPETA_ELIMINADOS, CARPETA_PDF):
        carpeta.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- utilidades

def nombre_seguro(texto: str, largo: int = 60) -> str:
    """Convierte un texto en algo válido como nombre de archivo de Windows."""
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(texto))
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:largo].strip().rstrip(".")


def _entero(valor) -> int:
    try:
        return max(0, int(round(float(valor))))
    except (TypeError, ValueError):
        return 0


def _cantidad(valor):
    try:
        numero = max(0.0, round(float(valor), 3))
    except (TypeError, ValueError):
        return 0
    return int(numero) if numero.is_integer() else numero


def _fecha(valor) -> str:
    try:
        return date.fromisoformat(str(valor)).isoformat()
    except ValueError:
        return date.today().isoformat()


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalizar(datos: dict) -> dict:
    """Limpia los datos recibidos y recalcula todos los totales."""
    filas = []
    for fila in datos.get("filas") or []:
        if not isinstance(fila, dict):
            continue
        if fila.get("tipo") == "titulo":
            texto = str(fila.get("texto") or "").strip()
            if texto:
                filas.append({"tipo": "titulo", "texto": texto})
            continue
        nombre = str(fila.get("nombre") or "").strip()
        precio = _entero(fila.get("precio"))
        cantidad = _cantidad(fila.get("cantidad"))
        if not nombre and not precio:
            continue  # fila vacía
        filas.append({
            "tipo": "material",
            "nombre": nombre,
            "precio": precio,
            "cantidad": cantidad,
            "total": int(round(precio * cantidad)),
        })

    total_materiales = sum(f["total"] for f in filas if f["tipo"] == "material")
    return {
        "id": str(datos.get("id") or "").strip() or None,
        "cliente": str(datos.get("cliente") or "").strip(),
        "proyecto": str(datos.get("proyecto") or "").strip(),
        "fecha": _fecha(datos.get("fecha")),
        "filas": filas,
        "total_materiales": total_materiales,
        "mano_de_obra": _entero(datos.get("mano_de_obra")),
    }


def validar(p: dict) -> None:
    if not p["cliente"]:
        raise ErrorPresupuesto("Falta escribir el nombre del cliente.")
    if not p["proyecto"]:
        raise ErrorPresupuesto("Falta escribir el nombre del proyecto.")
    for numero, fila in enumerate((f for f in p["filas"] if f["tipo"] == "material"), 1):
        if not fila["nombre"]:
            raise ErrorPresupuesto(
                f"El material n.º {numero} tiene precio pero no tiene nombre. "
                "Escriba el nombre o quite esa fila."
            )


# ---------------------------------------------------------------- archivos

def _leer(ruta: Path) -> dict | None:
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        if isinstance(datos, dict) and datos.get("id"):
            return datos
    except (OSError, ValueError) as e:
        log.warning("No se pudo leer %s: %s", ruta.name, e)
    return None


def _todos() -> list[tuple[Path, dict]]:
    if not CARPETA_DATOS.exists():
        return []
    resultado = []
    for ruta in CARPETA_DATOS.glob("*.json"):
        datos = _leer(ruta)
        if datos:
            resultado.append((ruta, datos))
    return resultado


def _buscar(id_: str) -> tuple[Path, dict] | tuple[None, None]:
    for ruta, datos in _todos():
        if datos.get("id") == id_:
            return ruta, datos
    return None, None


def _base_archivo(p: dict) -> str:
    partes = [p["fecha"], nombre_seguro(p["cliente"], 40), nombre_seguro(p["proyecto"], 60)]
    return " - ".join(x for x in partes if x) or "Presupuesto"


def _ruta_libre(base: str, actual: Path | None) -> Path:
    """Elige un nombre de archivo que no choque con otro presupuesto."""
    n = 1
    while True:
        nombre = base if n == 1 else f"{base} ({n})"
        ruta = CARPETA_DATOS / f"{nombre}.json"
        if not ruta.exists() or (actual and ruta.resolve() == actual.resolve()):
            return ruta
        n += 1


# ---------------------------------------------------------------- operaciones

def resumen(datos: dict) -> dict:
    return {
        "id": datos.get("id"),
        "cliente": datos.get("cliente", ""),
        "proyecto": datos.get("proyecto", ""),
        "fecha": datos.get("fecha", ""),
        "total_materiales": datos.get("total_materiales", 0),
        "mano_de_obra": datos.get("mano_de_obra", 0),
        "cantidad_materiales": sum(1 for f in datos.get("filas", []) if f.get("tipo") == "material"),
        "modificado": datos.get("modificado", ""),
    }


def listar() -> list[dict]:
    lista = [resumen(d) for _, d in _todos()]
    lista.sort(key=lambda r: r["modificado"] or "", reverse=True)
    return lista


def obtener(id_: str) -> dict:
    _, datos = _buscar(id_)
    if not datos:
        raise ErrorPresupuesto("No se encontró ese presupuesto. Puede que haya sido eliminado.")
    return datos


def guardar(datos: dict) -> dict:
    p = normalizar(datos)
    validar(p)
    with _candado:
        asegurar_carpetas()
        ruta_actual, anterior = _buscar(p["id"]) if p["id"] else (None, None)
        ahora = _ahora()
        p["id"] = p["id"] or uuid.uuid4().hex[:12]
        p["creado"] = (anterior or {}).get("creado", ahora)
        p["modificado"] = ahora

        ruta = _ruta_libre(_base_archivo(p), ruta_actual)
        temporal = ruta.with_suffix(".tmp")
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        os.replace(temporal, ruta)
        if ruta_actual and ruta_actual.resolve() != ruta.resolve():
            ruta_actual.unlink(missing_ok=True)  # el nombre cambió
        log.info("Guardado %s", ruta.name)
        return p


def eliminar(id_: str) -> None:
    """No borra definitivamente: mueve el archivo a la carpeta «Eliminados»."""
    with _candado:
        ruta, _ = _buscar(id_)
        if not ruta:
            raise ErrorPresupuesto("No se encontró ese presupuesto. Puede que ya haya sido eliminado.")
        CARPETA_ELIMINADOS.mkdir(parents=True, exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        os.replace(ruta, CARPETA_ELIMINADOS / f"{ruta.stem} (eliminado {marca}).json")
        log.info("Eliminado %s", ruta.name)
