"""Guarda y lee presupuestos como archivos .json (uno por presupuesto)."""
import json
import logging
import os
import re
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from config import ARCHIVO_NOTAS, CARPETA_DATOS, CARPETA_ELIMINADOS, CARPETA_PDF

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
    mano_de_obra = _entero(datos.get("mano_de_obra"))
    return {
        "id": str(datos.get("id") or "").strip() or None,
        "cliente": str(datos.get("cliente") or "").strip(),
        "proyecto": str(datos.get("proyecto") or "").strip(),
        "fecha": _fecha(datos.get("fecha")),
        "filas": filas,
        "total_materiales": total_materiales,
        "mano_de_obra": mano_de_obra,
        "total_general": total_materiales + mano_de_obra,
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
        with open(ruta, encoding="utf-8-sig") as f:  # acepta archivos con o sin BOM (p. ej. editados en el Bloc de notas)
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
        # los presupuestos guardados con versiones anteriores no tienen este dato: se calcula
        "total_general": datos.get("total_general",
                                   (datos.get("total_materiales") or 0) + (datos.get("mano_de_obra") or 0)),
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


# ---------------------------------------------------------------- notas del PDF

NOTAS_PREDETERMINADAS = [
    "No se incluyen fletes, retiro de escombros.",
    "Vigencia del presupuesto: 30 días.",
    "Los precios de los materiales se revisarán al momento de aceptar la oferta, "
    "en caso de existir alguna variación considerable en sus valores.",
    "Forma de pago mano de obra: 100% al finalizar trabajo.",
    "Forma de pago materiales: 100% al momento de iniciar obra.",
]
MAX_NOTAS = 30
MAX_LARGO_NOTA = 600


def leer_notas() -> dict:
    """Notas que van al final de los PDF: las personalizadas, o las predeterminadas si no hay."""
    try:
        with open(ARCHIVO_NOTAS, encoding="utf-8-sig") as f:
            datos = json.load(f)
        notas = datos.get("notas") if isinstance(datos, dict) else None
        if isinstance(notas, list):
            return {"notas": [str(n) for n in notas], "personalizadas": True,
                    "predeterminadas": NOTAS_PREDETERMINADAS}
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        log.warning("No se pudieron leer las notas (%s); se usan las predeterminadas.", e)
    return {"notas": list(NOTAS_PREDETERMINADAS), "personalizadas": False,
            "predeterminadas": NOTAS_PREDETERMINADAS}


def guardar_notas(notas) -> dict:
    if not isinstance(notas, list):
        raise ErrorPresupuesto("Las notas enviadas no son válidas.")
    limpias = [" ".join(str(n).split()) for n in notas]
    limpias = [n for n in limpias if n]
    if len(limpias) > MAX_NOTAS:
        raise ErrorPresupuesto(f"Puede haber como máximo {MAX_NOTAS} notas.")
    if any(len(n) > MAX_LARGO_NOTA for n in limpias):
        raise ErrorPresupuesto(f"Cada nota puede tener como máximo {MAX_LARGO_NOTA} letras.")
    with _candado:
        ARCHIVO_NOTAS.parent.mkdir(parents=True, exist_ok=True)
        temporal = ARCHIVO_NOTAS.with_suffix(".tmp")
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump({"notas": limpias, "modificado": _ahora()}, f, ensure_ascii=False, indent=2)
        os.replace(temporal, ARCHIVO_NOTAS)
    log.info("Notas del PDF guardadas (%s)", len(limpias))
    return leer_notas()


def restablecer_notas() -> dict:
    with _candado:
        ARCHIVO_NOTAS.unlink(missing_ok=True)
    log.info("Notas del PDF restablecidas")
    return leer_notas()
