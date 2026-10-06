# -*- coding: utf-8 -*-
r"""
================================================================
 ar/marcador.py  -  LA IMAGEN DE REFERENCIA, EL PDF Y targets.mind
================================================================
 El image tracking reconoce la imagen por sus ESQUINAS (puntos de
 contraste fuerte que no se repiten). Se compararon cuatro candidatas
 compilandolas con MindAR (puntos de deteccion / de seguimiento):

   captura del visor, conjunto, sin agrandar   281 / 27 + 11   <- esta
   captura del visor, LT2                      338 / 31 + 10
   planta del conjunto dibujada del modelo     234 / 13 + 6    (grilla repetida)
   vista 3D del modelo con IDs                 184 /  9 + 7
   (y la primera: una captura AGRANDADA        ... / 21 + 12, borrosa)

 La captura del visor tiene texto, la curva P-M y el edificio: muchas
 esquinas nitidas y nada simetrico. Se usa la del edificio entero, SIN
 reescalar (reescalar la vuelve borrosa y pierde esquinas). El contenido
 de la foto no importa para el tracking: es la textura que se reconoce.
 Lo que dice que elemento es, es el rotulo.

 La foto es ar/marcador/captura_base.jpg (la captura del visor con la
 curva P-M de la columna 200005 y el mapa D/C en 0.9G-1.4EX). Si se
 cambia, sale OTRO marcador: hay que recompilar y reimprimir.

 Deja:
   ar/web/marcador.png                 lo que se compila y lo que se sirve
   ar/marcador/marcador_imprimir.pdf   la imagen a EXACTAMENTE ancho_impreso_m (A4, 100 %)
   ar/web/targets.mind                 los puntos caracteristicos de la imagen

 COMPILAR. MindAR no busca la imagen tal cual: busca sus PUNTOS
 CARACTERISTICOS a varias escalas, que se calculan una vez y quedan en
 targets.mind. El compilador de MindAR es JavaScript y corre en un
 navegador, asi que se abre web/herramientas/compilar.html en Chrome (o
 Edge) sin ventana, contra ar/servir.py, y se espera a que deje
 targets.mind. Imagen y compilacion van juntas a proposito: una imagen
 nueva con el targets.mind viejo sigue "funcionando" con los puntos de la
 imagen anterior.

 Lo que dice el rotulo (elemento, cara, ancho) sale de
 entrada/laboratorio.json, bloque "ar".

   python sap.py ar marcador                       # imagen + PDF + targets.mind
   python sap.py ar marcador --solo-imagen         # solo ar/web/marcador.png
   python sap.py ar marcador --sin-compilar        # imagen y PDF
   python sap.py ar marcador --solo-compilar       # solo targets.mind, de la imagen que hay
   python sap.py ar marcador --elemento 200069 --cara -y
================================================================
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tempfile
import time

from calculo import rutas
from ar import servir
from exportar.ar import CARAS, configuracion

CAPTURA_BASE = os.path.join(rutas.AR, 'marcador', 'captura_base.jpg')
PDF = os.path.join(rutas.AR, 'marcador', 'marcador_imprimir.pdf')
MARCADOR = os.path.join(rutas.AR_WEB, 'marcador.png')
TARGETS = os.path.join(rutas.AR_WEB, 'targets.mind')
RECORTE = (10, 90, 930, 860)      # 920 x 770 px de la captura de 1600 x 900: panel + edificio
ANCHO, ALTO_ROTULO = 1000, 200
PUERTO = 8091                     # el suyo: no choca con la verificacion (8093) ni con servir (8080)


def rel(ruta):
    return rutas.relativa(ruta).replace(os.sep, '/')


def fuente(tam, negrita=False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(os.path.join(r'C:\Windows\Fonts', 'arialbd.ttf' if negrita else 'arial.ttf'), tam)
    except OSError:
        return ImageFont.load_default()


def _guardar(imagen, ruta, formato, **opciones):
    """La imagen a `ruta` de una vez (rutas.escribir_atomico): el servidor puede estar sirviendola."""
    buf = io.BytesIO()
    imagen.save(buf, formato, **opciones)
    return rutas.escribir_atomico(ruta, buf.getvalue())


def generar(cfg, solo_imagen=False):
    """ar/web/marcador.png y (si no solo_imagen) el PDF para imprimirla."""
    from PIL import Image, ImageDraw
    ancho_m = float(cfg['ancho_impreso_m'])
    elem = cfg['elemento']

    foto = Image.open(CAPTURA_BASE).convert('RGB').crop(RECORTE)          # sin reescalar
    alto = 40 + foto.size[1] + ALTO_ROTULO
    img = Image.new('RGB', (ANCHO, alto), 'white')
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, ANCHO - 1, alto - 1], outline='black', width=20)
    x0 = (ANCHO - foto.size[0]) // 2
    img.paste(foto, (x0, 40))
    d.rectangle([x0, 40, x0 + foto.size[0], 40 + foto.size[1]], outline='black', width=5)
    y = 40 + foto.size[1] + 22
    d.text((48, y), 'GRUPO 7 · LAB AR', font=fuente(56, True), fill='black')
    d.text((48, y + 70), 'columna %d · cara %s · %.0f cm' % (elem, cfg['cara'], ancho_m * 100),
           font=fuente(40), fill=(30, 58, 95))
    # Figura asimetrica: la imagen no se confunde consigo misma girada.
    d.polygon([(ANCHO - 190, y + 6), (ANCHO - 60, y + 6), (ANCHO - 60, y + 120)], fill=(200, 100, 30))
    d.rectangle([ANCHO - 190, y + 78, ANCHO - 130, y + 120], fill=(30, 58, 95))

    _guardar(img, MARCADOR, 'PNG')
    print('ok', rel(MARCADOR), '(%dx%d px)' % img.size)
    if solo_imagen:
        return

    # PDF a tamano exacto: A4 a 300 dpi, la imagen de ancho_m y una regla
    # de 10 cm para comprobar que la impresora no escalo.
    dpi = 300
    a4 = (int(8.2677 * dpi), int(11.6929 * dpi))
    hoja = Image.new('RGB', a4, 'white')
    px = int(round(ancho_m / 0.0254 * dpi))
    py = int(round(px * alto / ANCHO))
    arriba = int(1.2 / 2.54 * dpi)
    hoja.paste(img.resize((px, py), Image.LANCZOS), ((a4[0] - px) // 2, arriba))
    dh = ImageDraw.Draw(hoja)
    y0 = arriba + py + int(1.0 / 2.54 * dpi)
    diez = int(round(10 / 2.54 * dpi))
    x1 = (a4[0] - diez) // 2
    dh.line([x1, y0, x1 + diez, y0], fill='black', width=4)
    for k in range(11):
        xx = x1 + int(round(k / 2.54 * dpi))
        dh.line([xx, y0 - (30 if k % 5 == 0 else 18), xx, y0], fill='black', width=3)
    f = fuente(38)
    dh.text((x1, y0 + 18), 'esta linea mide 10 cm: si no, la impresora escalo', font=f, fill='black')
    txt = ['Imprimir al 100 % ("tamano real", sin "ajustar a la pagina").',
           'La imagen tiene que medir %.1f cm de ANCHO (el borde negro, de lado a lado).' % (ancho_m * 100),
           'Si mide otra cosa: cambiar ancho_impreso_m en entrada/laboratorio.json (bloque ar)',
           'y correr python sap.py exportar ar y python sap.py sincronizar.',
           'EN SITIO: pegarla plana y derecha en la cara %s de la columna %d,' % (cfg['cara'], elem),
           'con su centro a %.2f m sobre el piso.' % cfg['altura_centro_m'],
           'MAQUETA: dejarla plana sobre la mesa.']
    for i, t in enumerate(txt):
        dh.text((int(2 / 2.54 * dpi), y0 + 100 + i * 54), t, font=f, fill='black')
    _guardar(hoja, PDF, 'PDF', resolution=dpi)
    print('ok', rel(PDF), '(imagen de %.1f x %.1f cm a %d dpi)'
          % (ancho_m * 100, ancho_m * 100 * alto / ANCHO, dpi))


def compilar(segundos=240):
    """ar/web/marcador.png -> ar/web/targets.mind, con el compilador de MindAR en un navegador sin ventana."""
    nav = servir.buscar_navegador()
    if not nav:
        raise SystemExit('No encuentro Chrome ni Edge: abre a mano '
                         'http://localhost:8080/herramientas/compilar.html con python sap.py ar servir --http')
    antes = os.path.getmtime(TARGETS) if os.path.exists(TARGETS) else 0
    srv = servir.levantar(PUERTO)
    perfil = tempfile.mkdtemp(prefix='compilar_ar_')
    chrome = None
    t0 = time.time()
    try:
        chrome = subprocess.Popen([nav, '--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                                   '--user-data-dir=' + perfil,
                                   'http://localhost:%d/herramientas/compilar.html' % PUERTO],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while time.time() - t0 < segundos:
            if os.path.exists(TARGETS) and os.path.getmtime(TARGETS) > antes:
                time.sleep(0.5)
                break
            time.sleep(1)
    finally:
        servir.cerrar(chrome)
        servir.cerrar(srv)
        servir.borrar_perfil(perfil)
    if not (os.path.exists(TARGETS) and os.path.getmtime(TARGETS) > antes):
        raise SystemExit('No se genero targets.mind en %d s' % segundos)
    print('ok %s (%d bytes, %.0f s)' % (rel(TARGETS), os.path.getsize(TARGETS), time.time() - t0))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='sap.py ar marcador',
                                 description='La imagen de referencia de la AR, su PDF y targets.mind')
    ap.add_argument('--elemento', type=int)
    ap.add_argument('--cara', choices=sorted(CARAS))
    ap.add_argument('--altura', type=float, help='altura del centro de la imagen sobre el piso (m), para el PDF')
    ap.add_argument('--ancho', type=float, help='ancho impreso de la imagen (m)')
    que = ap.add_mutually_exclusive_group()
    que.add_argument('--solo-imagen', action='store_true', help='solo ar/web/marcador.png')
    que.add_argument('--sin-compilar', action='store_true', help='imagen y PDF, sin targets.mind')
    que.add_argument('--solo-compilar', action='store_true', help='solo targets.mind, de la imagen que hay')
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if not a.solo_compilar:
        generar(configuracion(a.elemento, a.cara, a.altura, a.ancho), solo_imagen=a.solo_imagen)
    if not (a.solo_imagen or a.sin_compilar):
        compilar()
    return 0


if __name__ == '__main__':
    sys.exit(main())
