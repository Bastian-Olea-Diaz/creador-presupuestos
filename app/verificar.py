"""Comprueba que el programa quedó bien instalado. Lo ejecuta install.ps1 al terminar.

Revisa que estén las librerías, que se pueda escribir en la carpeta de los presupuestos
y que se pueda crear un PDF de prueba (en una carpeta temporal, sin dejar rastros).
"""
import sys
import tempfile
from pathlib import Path


def main() -> int:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("ERROR: falta la librería reportlab (necesaria para crear los PDF).")
        return 1

    import almacenamiento
    import config
    import generar_pdf
    import servidor  # noqa: F401  (comprueba que el servidor se pueda cargar)

    try:
        almacenamiento.asegurar_carpetas()
        prueba = config.CARPETA_DATOS / ".prueba-escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as e:
        print(f"ERROR: no se puede escribir en la carpeta de presupuestos ({config.CARPETA_DATOS}): {e}")
        return 1

    with tempfile.TemporaryDirectory() as temporal:
        generar_pdf.CARPETA_PDF = Path(temporal)
        datos = almacenamiento.normalizar({
            "cliente": "Prueba", "proyecto": "Prueba de instalación", "mano_de_obra": 1000,
            "filas": [{"tipo": "material", "nombre": "Material de prueba", "precio": 1990, "cantidad": 2}],
        })
        ruta = generar_pdf.crear_pdf(datos)
        if ruta.stat().st_size < 1000:
            print("ERROR: el PDF de prueba quedó vacío.")
            return 1

    print(f"OK|{config.CARPETA_BASE_DATOS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
