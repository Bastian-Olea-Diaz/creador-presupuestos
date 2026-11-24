"""Servidor local: muestra la interfaz en el navegador y atiende sus pedidos."""
import json
import logging
import mimetypes
import socket
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import unquote, urlparse

import almacenamiento as alm
from config import (ARCHIVO_PUERTO, ARCHIVO_REGISTRO, CARPETA_DATOS, CARPETA_PDF, CARPETA_WEB,
                    NOMBRE_APP, PUERTOS, calcular_version)

log = logging.getLogger("servidor")
VERSION = calcular_version()


def _configurar_registro() -> None:
    manejador = RotatingFileHandler(ARCHIVO_REGISTRO, maxBytes=500_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[manejador],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Con pythonw no hay consola: los errores no capturados van al registro.
    if sys.stderr is None or sys.stdout is None:
        flujo = open(ARCHIVO_REGISTRO, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or flujo
        sys.stderr = sys.stderr or flujo


def _abrir_con_windows(ruta) -> bool:
    try:
        os.startfile(str(ruta))  # abre con el programa predeterminado
        return True
    except OSError as e:
        log.warning("No se pudo abrir %s: %s", ruta, e)
        return False


class Manejador(BaseHTTPRequestHandler):
    server_version = "CreadorPresupuestos"

    def log_message(self, formato, *args):  # silenciar la salida por consola
        log.debug(formato, *args)

    # ------------------------------------------------------------ respuestas
    def _json(self, datos, estado=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, mensaje, estado=400):
        self._json({"error": mensaje}, estado)

    def _leer_json(self) -> dict:
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > 5_000_000:
            raise alm.ErrorPresupuesto("Los datos enviados son demasiado grandes.")
        crudo = self.rfile.read(largo) if largo else b"{}"
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except ValueError:
            raise alm.ErrorPresupuesto("Los datos enviados no son válidos.")
        if not isinstance(datos, dict):
            raise alm.ErrorPresupuesto("Los datos enviados no son válidos.")
        return datos

    def _origen_valido(self) -> bool:
        """Solo acepta pedidos hechos desde esta misma página, no desde otros sitios web."""
        puerto = self.server.server_address[1]
        permitidos = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}
        if self.headers.get("Host") not in permitidos:
            return False
        origen = self.headers.get("Origin")
        return origen is None or origen in {f"http://{h}" for h in permitidos}

    def _atender(self, metodo):
        if not self._origen_valido():
            return self._error("Pedido no permitido.", 403)
        ruta = urlparse(self.path).path
        try:
            if ruta.startswith("/api/"):
                return self._api(metodo, ruta[len("/api/"):].strip("/").split("/"))
            if metodo == "GET":
                return self._archivo_estatico(ruta)
            self._error("No encontrado.", 404)
        except alm.ErrorPresupuesto as e:
            self._error(str(e))
        except Exception:
            log.exception("Error inesperado en %s %s", metodo, self.path)
            self._error("Ocurrió un problema inesperado. Intente de nuevo; si sigue pasando, "
                        "cierre el navegador y vuelva a abrir el programa.", 500)

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def do_DELETE(self):
        self._atender("DELETE")

    # ------------------------------------------------------------ archivos de la interfaz
    def _archivo_estatico(self, ruta):
        nombre = unquote(ruta).lstrip("/") or "index.html"
        archivo = (CARPETA_WEB / nombre).resolve()
        if CARPETA_WEB.resolve() not in archivo.parents or not archivo.is_file():
            return self._error("No encontrado.", 404)
        contenido = archivo.read_bytes()
        tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(contenido)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(contenido)

    # ------------------------------------------------------------ API
    def _api(self, metodo, partes):
        recurso = partes[0]

        if recurso == "ping" and metodo == "GET":
            return self._json({"app": NOMBRE_APP, "version": VERSION})

        if recurso == "presupuestos":
            id_ = partes[1] if len(partes) > 1 else None
            if metodo == "GET" and not id_:
                return self._json({"presupuestos": alm.listar()})
            if metodo == "GET":
                return self._json(alm.obtener(id_))
            if metodo == "POST" and not id_:
                return self._json(alm.guardar(self._leer_json()))
            if metodo == "DELETE" and id_:
                alm.eliminar(id_)
                return self._json({"ok": True})

        if recurso == "notas":
            accion = partes[1] if len(partes) > 1 else None
            if metodo == "GET" and not accion:
                return self._json(alm.leer_notas())
            if metodo == "POST" and not accion:
                return self._json(alm.guardar_notas(self._leer_json().get("notas")))
            if metodo == "POST" and accion == "restablecer":
                return self._json(alm.restablecer_notas())

        if recurso == "pdf" and metodo == "POST":
            return self._crear_pdf(self._leer_json())

        if recurso == "abrir-carpeta" and metodo == "POST":
            return self._abrir_carpeta(self._leer_json())

        if recurso == "apagar" and metodo == "POST":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self._error("No encontrado.", 404)

    def _crear_pdf(self, cuerpo):
        import generar_pdf  # se importa aquí para que el servidor arranque rápido

        if cuerpo.get("id"):  # presupuesto guardado: se usa exactamente lo que está en el .json
            p = alm.normalizar(alm.obtener(cuerpo["id"]))
        else:  # presupuesto sin guardar
            p = alm.normalizar(cuerpo.get("datos") or {})
        alm.validar(p)
        ruta = generar_pdf.crear_pdf(p)
        log.info("PDF creado: %s", ruta.name)
        abierto = _abrir_con_windows(ruta) if cuerpo.get("abrir", True) else False
        self._json({"archivo": ruta.name, "abierto": abierto})

    def _abrir_carpeta(self, cuerpo):
        carpeta = CARPETA_DATOS if cuerpo.get("carpeta") == "datos" else CARPETA_PDF
        carpeta.mkdir(parents=True, exist_ok=True)
        archivo = os.path.basename(str(cuerpo.get("seleccionar") or ""))
        if archivo and (carpeta / archivo).is_file():
            subprocess.Popen(f'explorer /select,"{carpeta / archivo}"')
        else:
            _abrir_con_windows(carpeta)
        self._json({"ok": True})


class ServidorExclusivo(ThreadingHTTPServer):
    """En Windows, HTTPServer permite que dos programas usen el mismo puerto a la vez
    (SO_REUSEADDR), y los pedidos llegan a cualquiera de los dos. Aquí se pide el puerto
    en forma exclusiva: si ya está ocupado, se prueba el siguiente."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def iniciar() -> None:
    _configurar_registro()
    alm.asegurar_carpetas()
    servidor = None
    for puerto in PUERTOS:
        try:
            servidor = ServidorExclusivo(("127.0.0.1", puerto), Manejador)
            break
        except OSError:
            continue
    if servidor is None:
        log.error("No hay puertos libres entre %s y %s", PUERTOS[0], PUERTOS[-1])
        sys.exit(1)
    puerto = servidor.server_address[1]
    ARCHIVO_PUERTO.write_text(str(puerto), encoding="utf-8")
    log.info("Servidor iniciado en http://127.0.0.1:%s (versión %s)", puerto, VERSION)
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()
        log.info("Servidor detenido")


if __name__ == "__main__":
    iniciar()
