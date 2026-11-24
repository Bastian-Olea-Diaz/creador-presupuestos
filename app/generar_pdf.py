"""Crea el documento PDF de un presupuesto a partir de sus datos (los mismos del .json)."""
import os
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, HRFlowable, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from almacenamiento import ErrorPresupuesto, nombre_seguro
from config import CARPETA_PDF

NOTAS = [
    "No se incluyen fletes, retiro de escombros.",
    "Vigencia del presupuesto: 30 días.",
    "Los precios de los materiales se revisarán al momento de aceptar la oferta, "
    "en caso de existir alguna variación considerable en sus valores.",
    "Forma de pago mano de obra: 100% al finalizar trabajo.",
    "Forma de pago materiales: 100% al momento de iniciar obra.",
]
DIAS_VIGENCIA = 30

# ---------------------------------------------------------------- paleta
AZUL = colors.HexColor("#1B2B48")        # color principal: títulos, encabezados
AZUL_MEDIO = colors.HexColor("#3C4F70")
BRONCE = colors.HexColor("#B08D57")      # acento: detalles finos
TEXTO = colors.HexColor("#2B2F36")
GRIS = colors.HexColor("#6B7280")
LINEA = colors.HexColor("#E3E6EB")
FONDO = colors.HexColor("#F5F6F8")
FONDO_ALTERNO = colors.HexColor("#FAFBFC")
FONDO_SUBTITULO = colors.HexColor("#EDF0F5")

ANCHO_PAGINA, ALTO_PAGINA = LETTER
MARGEN_X = 2.2 * cm
ANCHO = ANCHO_PAGINA - 2 * MARGEN_X

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------- fuentes

class Fuentes:
    normal = "Helvetica"
    negrita = "Helvetica-Bold"
    liviana = "Helvetica"
    cursiva = "Helvetica-Oblique"


def _registrar_fuentes() -> type[Fuentes]:
    """Usa la familia Calibri de Windows si está disponible; si no, Helvetica."""
    carpeta = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    archivos = {"Calibri": "calibri.ttf", "Calibri-Bold": "calibrib.ttf",
                "Calibri-Light": "calibril.ttf", "Calibri-Italic": "calibrii.ttf"}
    if not all((carpeta / a).exists() for a in archivos.values()):
        return Fuentes
    try:
        registradas = pdfmetrics.getRegisteredFontNames()
        for nombre, archivo in archivos.items():
            if nombre not in registradas:
                pdfmetrics.registerFont(TTFont(nombre, str(carpeta / archivo)))
        pdfmetrics.registerFontFamily("Calibri", normal="Calibri", bold="Calibri-Bold",
                                      italic="Calibri-Italic", boldItalic="Calibri-Bold")
    except Exception:  # fuente dañada o ilegible
        return Fuentes

    class Calibri(Fuentes):
        normal, negrita, liviana, cursiva = "Calibri", "Calibri-Bold", "Calibri-Light", "Calibri-Italic"
    return Calibri


# ---------------------------------------------------------------- formatos

def pesos(n: int) -> str:
    return "$" + f"{int(n):,}".replace(",", ".")


def cantidad(q) -> str:
    q = float(q or 0)
    texto = f"{int(q):,}".replace(",", ".")
    if not q.is_integer():
        texto += "," + f"{q:.3f}".split(".")[1].rstrip("0")
    return texto


def _fecha(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


def fecha_corta(iso: str) -> str:
    d = _fecha(iso)
    return d.strftime("%d-%m-%Y") if d else iso


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def nombre_pdf(p: dict) -> str:
    partes = ["Presupuesto", nombre_seguro(p["proyecto"], 60), nombre_seguro(p["cliente"], 40)]
    return " - ".join(x for x in partes if x) + f" ({fecha_corta(p['fecha'])}).pdf"


# ---------------------------------------------------------------- piezas gráficas

class Etiqueta(Flowable):
    """Texto corto en mayúsculas con espaciado entre letras (rótulos y encabezados)."""

    def __init__(self, texto, fuente, tamano, color, espacio=1.2, alinear="left"):
        super().__init__()
        self.texto, self.fuente, self.tamano = texto.upper(), fuente, tamano
        self.color, self.espacio, self.alinear = color, espacio, alinear
        self.ancho_disponible = 0

    def _ancho_texto(self):
        return (pdfmetrics.stringWidth(self.texto, self.fuente, self.tamano)
                + self.espacio * max(len(self.texto) - 1, 0))

    def wrap(self, ancho_disponible, alto_disponible):
        self.ancho_disponible = ancho_disponible
        return ancho_disponible, self.tamano * 1.25

    def draw(self):
        ancho = self._ancho_texto()
        x = {"left": 0, "right": self.ancho_disponible - ancho,
             "center": (self.ancho_disponible - ancho) / 2}[self.alinear]
        t = self.canv.beginText(x, self.tamano * 0.28)
        t.setFont(self.fuente, self.tamano)
        t.setCharSpace(self.espacio)
        t.setFillColor(self.color)
        t.textOut(self.texto)
        self.canv.drawText(t)


def _titulo_seccion(texto, f):
    return [
        Etiqueta(texto, f.negrita, 9, AZUL, espacio=1.6),
        Spacer(1, 4),
        HRFlowable(width=1.1 * cm, thickness=2, color=BRONCE, hAlign="LEFT", spaceAfter=10),
    ]


# ---------------------------------------------------------------- fondo de cada página

def _canvas_con_marco(p: dict, f: type[Fuentes]):
    """Dibuja la franja superior y el pie de página («Página X de Y») en cada hoja."""

    class CanvasConMarco(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for estado in self._paginas:
                self.__dict__.update(estado)
                self._decorar(total)
                super().showPage()
            super().save()

        def _decorar(self, total):
            # franja superior
            self.setFillColor(AZUL)
            self.rect(0, ALTO_PAGINA - 0.42 * cm, ANCHO_PAGINA, 0.42 * cm, stroke=0, fill=1)
            self.setFillColor(BRONCE)
            self.rect(0, ALTO_PAGINA - 0.48 * cm, ANCHO_PAGINA, 0.06 * cm, stroke=0, fill=1)
            # pie
            y = 1.45 * cm
            self.setStrokeColor(LINEA)
            self.setLineWidth(0.6)
            self.line(MARGEN_X, y + 0.38 * cm, ANCHO_PAGINA - MARGEN_X, y + 0.38 * cm)
            self.setFont(f.normal, 8)
            self.setFillColor(GRIS)
            pie = f"Presupuesto · {p['proyecto']} · {p['cliente']}"
            while pdfmetrics.stringWidth(pie, f.normal, 8) > ANCHO * 0.75 and len(pie) > 10:
                pie = pie[:-2].rstrip() + "…"
            self.drawString(MARGEN_X, y, pie)
            self.drawRightString(ANCHO_PAGINA - MARGEN_X, y, f"Página {self._pageNumber} de {total}")

    return CanvasConMarco


# ---------------------------------------------------------------- documento

def crear_pdf(p: dict) -> Path:
    """Genera el PDF y devuelve su ruta. `p` debe venir de almacenamiento.normalizar()."""
    f = _registrar_fuentes()

    def estilo(nombre, **kw):
        base = dict(fontName=f.normal, fontSize=10, leading=13.5, textColor=TEXTO)
        base.update(kw)
        return ParagraphStyle(nombre, **base)

    e_titulo = estilo("titulo", fontName=f.liviana, fontSize=27, leading=31, textColor=AZUL)
    e_meta = estilo("meta", fontName=f.negrita, fontSize=10.5, leading=13, textColor=AZUL, alignment=TA_RIGHT)
    e_cliente = estilo("cliente", fontName=f.negrita, fontSize=13.5, leading=17, textColor=AZUL)
    e_celda = estilo("celda")
    e_subtitulo = estilo("subtitulo", fontName=f.negrita, textColor=AZUL)
    e_monto = estilo("monto", fontName=f.negrita, fontSize=12.5, leading=15, textColor=AZUL, alignment=TA_RIGHT)
    e_nota = estilo("nota", fontSize=9.8, leading=13.5)
    e_vineta = estilo("vineta", fontName=f.negrita, fontSize=11, leading=13.5, textColor=BRONCE)

    historia = []

    # --- encabezado: título a la izquierda, fechas a la derecha
    emision = _fecha(p["fecha"])
    if emision:
        fechas = [
            Etiqueta("Fecha de emisión", f.negrita, 7.5, GRIS, espacio=1.2, alinear="right"),
            Spacer(1, 2),
            Paragraph(fecha_larga(emision), e_meta),
            Spacer(1, 9),
            Etiqueta("Válido hasta", f.negrita, 7.5, GRIS, espacio=1.2, alinear="right"),
            Spacer(1, 2),
            Paragraph(fecha_larga(emision + timedelta(days=DIAS_VIGENCIA)), e_meta),
        ]
    else:
        fechas = [Paragraph(escape(p["fecha"]), e_meta)]

    encabezado = Table(
        [[[Etiqueta("Presupuesto", f.negrita, 10, BRONCE, espacio=3.2), Spacer(1, 8),
           Paragraph(escape(p["proyecto"]), e_titulo)], fechas]],
        colWidths=[ANCHO * 0.64, ANCHO * 0.36],
    )
    encabezado.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    historia += [encabezado, Spacer(1, 18)]

    # --- tarjeta del cliente
    cliente = Table([[[Etiqueta("Cliente", f.negrita, 7.5, GRIS, espacio=1.4), Spacer(1, 3),
                       Paragraph(escape(p["cliente"]), e_cliente)]]], colWidths=[ANCHO])
    cliente.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FONDO),
        ("LINEBEFORE", (0, 0), (0, -1), 3, BRONCE),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    historia += [cliente, Spacer(1, 20)]

    # --- tabla de materiales
    historia += _titulo_seccion("Detalle de materiales", f)
    anchos = [1.0 * cm, ANCHO - 8.9 * cm, 2.9 * cm, 2.0 * cm, 3.0 * cm]

    def cabecera(texto, alinear):
        return Etiqueta(texto, f.negrita, 7.8, colors.white, espacio=1.1, alinear=alinear)

    filas = [[cabecera("N.º", "center"), cabecera("Descripción", "left"), cabecera("Precio unit.", "right"),
              cabecera("Cant.", "center"), cabecera("Total", "right")]]
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 1), (-1, -1), f.normal),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXTO),
        ("TOPPADDING", (0, 0), (-1, 0), 9), ("BOTTOMPADDING", (0, 0), (-1, 0), 9),
        ("TOPPADDING", (0, 1), (-1, -1), 6), ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 1), (0, -1), GRIS),
        ("FONTSIZE", (0, 1), (0, -1), 8.5),
        ("FONTNAME", (4, 1), (4, -1), f.negrita),
        ("TEXTCOLOR", (4, 1), (4, -1), AZUL),
    ]

    numero = 0
    alterna = 0
    for fila in p["filas"]:
        i = len(filas)
        estilos.append(("LINEBELOW", (0, i), (-1, i), 0.6, LINEA))
        if fila["tipo"] == "titulo":
            filas.append(["", Paragraph(escape(fila["texto"]), e_subtitulo), "", "", ""])
            estilos += [("SPAN", (1, i), (-1, i)), ("BACKGROUND", (0, i), (-1, i), FONDO_SUBTITULO),
                        ("LINEBEFORE", (0, i), (0, i), 2.5, BRONCE)]
            alterna = 0
            continue
        numero += 1
        filas.append([str(numero), Paragraph(escape(fila["nombre"]), e_celda), pesos(fila["precio"]),
                      cantidad(fila["cantidad"]), pesos(fila["total"])])
        if alterna % 2:
            estilos.append(("BACKGROUND", (0, i), (-1, i), FONDO_ALTERNO))
        alterna += 1

    if len(filas) == 1:
        filas.append(["", Paragraph("<i>Sin materiales</i>", e_celda), "", "", ""])
        estilos.append(("SPAN", (1, 1), (-1, 1)))
    estilos.append(("LINEBELOW", (0, -1), (-1, -1), 1, AZUL))

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(TableStyle(estilos))
    historia += [tabla, Spacer(1, 14)]

    # --- resumen de totales (alineado a la derecha)
    def fila_resumen(etiqueta, valor):
        return [Etiqueta(etiqueta, f.negrita, 8, AZUL_MEDIO, espacio=1.1), Paragraph(pesos(valor), e_monto)]

    resumen = Table([fila_resumen("Total materiales", p["total_materiales"]),
                     fila_resumen("Mano de obra", p["mano_de_obra"])],
                    colWidths=[4.6 * cm, 3.4 * cm], hAlign="RIGHT")
    resumen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FONDO),
        ("LINEABOVE", (0, 0), (-1, 0), 2, BRONCE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    historia += [KeepTogether(resumen), Spacer(1, 22)]

    # --- notas
    caja = Table([[Paragraph("•", e_vineta), Paragraph(escape(n), e_nota)] for n in NOTAS],
                 colWidths=[0.95 * cm, ANCHO - 0.95 * cm])
    caja.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FONDO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 14), ("LEFTPADDING", (1, 0), (1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (1, 0), (1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 12), ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
    ]))
    historia.append(KeepTogether(_titulo_seccion("Notas", f) + [caja]))

    # --- escribir el archivo (primero a uno temporal, para no dejar un PDF a medias)
    CARPETA_PDF.mkdir(parents=True, exist_ok=True)
    destino = CARPETA_PDF / nombre_pdf(p)
    temporal = destino.with_suffix(".tmp")
    doc = BaseDocTemplate(
        str(temporal), pagesize=LETTER,
        title=f"Presupuesto - {p['proyecto']}", subject=f"Cliente: {p['cliente']}",
        author="", creator="Creador de presupuestos",
    )
    marco = Frame(MARGEN_X, 2.2 * cm, ANCHO, ALTO_PAGINA - 2.2 * cm - 1.9 * cm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="pagina", frames=[marco])])
    doc.build(historia, canvasmaker=_canvas_con_marco(p, f))
    try:
        os.replace(temporal, destino)
    except PermissionError:
        temporal.unlink(missing_ok=True)
        raise ErrorPresupuesto(
            "No se pudo crear el PDF porque una versión anterior está abierta en otro programa. "
            "Cierre el PDF e intente de nuevo."
        )
    return destino
