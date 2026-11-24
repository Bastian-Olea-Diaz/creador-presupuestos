"""Lo ejecuta el archivo .bat: deja el servidor funcionando en segundo plano y abre el navegador."""
import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from config import ARCHIVO_PUERTO, CARPETA_APP, NOMBRE_APP, PUERTOS, calcular_version


def _ping(puerto: int, espera: float = 0.4):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/ping", timeout=espera) as r:
            datos = json.load(r)
        return datos if datos.get("app") == NOMBRE_APP else None
    except Exception:
        return None


def _buscar_en_marcha():
    for puerto in PUERTOS:
        datos = _ping(puerto)
        if datos:
            return puerto, datos.get("version")
    return None, None


def _apagar(puerto: int) -> None:
    pedido = urllib.request.Request(f"http://127.0.0.1:{puerto}/api/apagar", data=b"{}", method="POST",
                                    headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(pedido, timeout=2).read()
    except Exception:
        pass
    for _ in range(20):
        if not _ping(puerto):
            return
        time.sleep(0.2)


def _lanzar_servidor() -> int | None:
    ARCHIVO_PUERTO.unlink(missing_ok=True)
    ejecutable = Path(sys.executable)
    sin_ventana = ejecutable.with_name("pythonw.exe")
    if sin_ventana.exists():
        ejecutable = sin_ventana
    banderas = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(ejecutable), str(CARPETA_APP / "servidor.py")], cwd=str(CARPETA_APP),
                     creationflags=banderas, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(75):  # hasta 15 segundos
        time.sleep(0.2)
        if ARCHIVO_PUERTO.exists():
            try:
                puerto = int(ARCHIVO_PUERTO.read_text(encoding="utf-8").strip())
            except ValueError:
                continue
            if _ping(puerto):
                return puerto
    return None


def main() -> int:
    puerto, version = _buscar_en_marcha()
    if puerto and version != calcular_version():
        print("Actualizando el programa...")
        _apagar(puerto)  # hay una versión anterior funcionando: se reinicia
        puerto = None
    if not puerto:
        print("Abriendo el Creador de presupuestos, espere un momento...")
        puerto = _lanzar_servidor()
    if not puerto:
        print()
        print("No se pudo abrir el programa.")
        print(f"Los detalles del problema quedaron en: {CARPETA_APP / 'registro.log'}")
        return 1
    webbrowser.open(f"http://127.0.0.1:{puerto}/")
    print("Listo. El programa se abrió en el navegador.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
