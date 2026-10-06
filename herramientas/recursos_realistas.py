# -*- coding: utf-8 -*-
r"""
================================================================
 herramientas/recursos_realistas.py  -  LAS TEXTURAS Y EL CIELO DE LA VISTA REALISTA
================================================================
 La vista realista del visor usa recursos descargados (CC0) que viven en
 unity/Assets/Resources/Ambiente/ (los arma, en el editor,
 unity/Assets/Editor/RecursosRealistas.cs; los usa AmbienteVisor). Esto
 hace lo que no se ve a simple vista y falla en silencio:

   [1] EL SOL DEL CIELO (y su suelo). El HDRI trae su sol en algun lugar del
       panorama, y la luz direccional de la vista realista esta en otro
       (AmbienteVisor.SOL_REALISTA). Sin girar el cielo, las sombras van
       para un lado y el sol se ve en otro. Se lee el .hdr (Radiance
       RGBE), se busca el pixel mas brillante, y se calcula el giro del
       Skybox/Panoramic que lo pone en el rumbo de la luz. Queda en
       Texturas/cielo/sol.json, que lee RecursosRealistas.cs.
   [2] LAS LICENCIAS. Cada recurso tiene su FUENTE.txt y dice CC0.
   [3] LOS MAPAS NORMALES importados como NormalMap (textureType 1 en el
       .meta). Importado como imagen comun, el relieve sale al reves y
       nadie lo nota.
   [4] LOS MATERIALES apuntan a esas texturas (por GUID) y el del
       hormigon tiene el keyword _NORMALMAP; el cielo tiene el giro de
       sol.json.
   [5] EL PATRON DE LEJOS. Una textura repetida cada 2-3 m se nota como
       una grilla. Sin escribir un shader propio (el 'stochastic tiling'
       de verdad lo pide, con sus sombras, SSAO y pases de profundidad),
       el URP/Lit trae un MAPA DE DETALLE que multiplica el color (x2)
       por otra textura con su propia escala. Se arma, por material,
       Texturas/<item>/detalle.png: ruido periodico (manchas grandes y
       variacion de ~1 m, ver DETALLES) en gris lineal de media 0.5 (=
       no cambia nada en promedio), estirado a ~300 m: la base se sigue
       repitiendo, pero cada repeticion queda distinta. Se verifica la
       media, que empalme consigo mismo y que el material lo use con
       _DETAIL_MULX2 y esa escala (Texturas/detalle.json).

 SOL_REALISTA se lee del C# (AmbienteVisor.cs, buscado con rutas.cs): si
 el archivo o la constante no aparecen, es una FALLA y no un salto.

 Correr:
   python sap.py recursos              escribe sol.json, el HDR con suelo y los detalles, y verifica
   python sap.py recursos --verificar  solo verifica (la suite)
================================================================
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import sys

import numpy as np

from calculo import rutas

AMBIENTE = os.path.join(rutas.RESOURCES, 'Ambiente')
TEXTURAS = os.path.join(AMBIENTE, 'Texturas')
# El C# donde vive SOL_REALISTA (lo busca rutas.cs: si cambia de carpeta,
# se sigue encontrando; si desaparece, es una falla).
CS_AMBIENTE = 'AmbienteVisor.cs'
# El HDRI tal como se bajo, FUERA de Assets (no entra a la build) y el que
# usa Unity: el mismo con el hemisferio de abajo cambiado por suelo.
HDR_ORIGINAL = os.path.join(rutas.UNITY_PROYECTO, 'FuentesAmbiente', 'cielo_2k.hdr')
HDR_UNITY = os.path.join(TEXTURAS, 'cielo', 'cielo_2k_suelo.hdr')
# Bajo el horizonte un HDRI 'puresky' trae mas cielo (borroso): visto desde
# arriba, el relieve del sitio parecia una isla flotando en las nubes. El
# cielo procedural de antes pintaba ahi un color de pasto (_GroundColor). Se
# hace lo mismo: un pasto lejano, con el brillo del cielo junto al horizonte
# por este factor, y una transicion de unos grados.
SUELO_COLOR = (0.36, 0.40, 0.30)
SUELO_BRILLO = 0.30
SUELO_TRANSICION_GRADOS = 2.5
ITEMS = ('hormigon_visto', 'hormigon_losa', 'pasto', 'tierra', 'acero')
# Tolerancia del giro: el sol del HDRI es un disco de unos 0.5 grados y
# se toma el pixel mas brillante de un panorama de 2048 px de ancho
# (0.18 grados por pixel); el material guarda el giro como float.
TOL_GIRO_GRADOS = 0.5

# Los '_por_que' que ya llevan sol.json y detalle.json. Se conservan tal
# cual para que regenerarlos de los MISMOS bytes: son assets de Unity con
# su .meta, y cambiar el texto es cambiar el asset, no solo su origen.
POR_QUE_SOL = ('Giro del Skybox/Panoramic (_Rotation) que pone el sol del HDRI en el rumbo '
               'de la luz direccional de la vista realista (AmbienteVisor.SOL_REALISTA). '
               'Lo calcula comun/recursos_realistas.py; lo aplica Editor/RecursosRealistas.cs.')
POR_QUE_DETALLE = ('Escala del mapa de detalle (URP/Lit _DetailAlbedoMap, x2) de cada material, respecto de '
                   'la base. La calcula comun/recursos_realistas.py (DETALLES) y la aplica '
                   'Editor/RecursosRealistas.cs.')

# El mapa de detalle de cada material. NO es la propia textura a otra
# escala: probado (simulacion de 16x16 tiles), eso arma una grilla NUEVA de
# manchas cada 1/escala tiles, que se ve mas que la original. Es ruido
# periodico solo cada 1/escala tiles (~300 m en el pasto: el suelo llega a
# 1 km y con 86 m se veian filas de manchas hacia el horizonte): manchas
# grandes (macro, 'ciclos_macro' por tile de detalle, ~100 m) y variacion de 1.5-5 m
# (medio, banda 'medio_ciclos'), en gris lineal de media 0.5. De lejos el
# mipmap promedia el medio y queda la mancha; de cerca el medio rompe la
# repeticion de la base. macro y medio = desviacion de cada parte del
# factor de brillo (x2). El acero no lleva: es poco y se ve de cerca.
DETALLES = {
    'pasto':          {'escala': 0.01, 'macro': 0.12, 'medio': 0.08, 'ciclos_macro': 3.0,
                       'medio_ciclos': (60.0, 200.0), 'semilla': 11},
    'tierra':         {'escala': 0.01, 'macro': 0.10, 'medio': 0.08, 'ciclos_macro': 3.0,
                       'medio_ciclos': (60.0, 200.0), 'semilla': 13},
    'hormigon_visto': {'escala': 0.05, 'macro': 0.07, 'medio': 0.04, 'ciclos_macro': 5.0,
                       'medio_ciclos': (25.0, 60.0), 'semilla': 17},
    'hormigon_losa':  {'escala': 0.05, 'macro': 0.07, 'medio': 0.04, 'ciclos_macro': 5.0,
                       'medio_ciclos': (25.0, 60.0), 'semilla': 19},
}
LADO_DETALLE = 1024


# ============================================================
# EL HDR
# ============================================================
def leer_hdr(ruta):
    """Radiance .hdr (RGBE, con o sin RLE) -> array (alto, ancho, 3) float32."""
    with io.open(ruta, 'rb') as f:
        datos = f.read()
    i = 0
    while True:                                   # cabecera hasta la linea vacia
        j = datos.index(b'\n', i)
        linea = datos[i:j]
        i = j + 1
        if linea.strip() == b'':
            break
    j = datos.index(b'\n', i)
    m = re.match(rb'-Y (\d+) \+X (\d+)', datos[i:j])
    if not m:
        raise ValueError('orientacion no soportada: %r' % datos[i:j])
    alto, ancho = int(m.group(1)), int(m.group(2))
    i = j + 1
    img = np.zeros((alto, ancho, 4), dtype=np.uint8)
    buf = memoryview(datos)
    for y in range(alto):
        if ancho >= 8 and buf[i] == 2 and buf[i + 1] == 2 and (buf[i + 2] << 8 | buf[i + 3]) == ancho:
            i += 4
            for c in range(4):                    # RLE nuevo: canal por canal
                x = 0
                while x < ancho:
                    n = buf[i]
                    i += 1
                    if n > 128:
                        n -= 128
                        img[y, x:x + n, c] = buf[i]
                        i += 1
                    else:
                        img[y, x:x + n, c] = np.frombuffer(buf[i:i + n], dtype=np.uint8)
                        i += n
                    x += n
        else:                                     # sin RLE
            img[y] = np.frombuffer(buf[i:i + 4 * ancho], dtype=np.uint8).reshape(ancho, 4)
            i += 4 * ancho
    e = img[:, :, 3].astype(np.int32)
    f = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0).astype(np.float32)
    return img[:, :, :3].astype(np.float32) * f[:, :, None]


def escribir_hdr(ruta, img):
    """Radiance .hdr plano (RGBE sin RLE), que Unity lee igual."""
    v = img.max(axis=2)
    m, e = np.frexp(v)
    escala = np.where(v > 1e-32, m * 256.0 / np.maximum(v, 1e-32), 0.0)
    rgbe = np.zeros(img.shape[:2] + (4,), dtype=np.uint8)
    rgbe[:, :, :3] = np.clip(img * escala[:, :, None], 0, 255).astype(np.uint8)
    rgbe[:, :, 3] = np.where(v > 1e-32, e + 128, 0).astype(np.uint8)
    with io.open(ruta, 'wb') as f:
        f.write(b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n')
        f.write(('-Y %d +X %d\n' % img.shape[:2]).encode('ascii'))
        f.write(rgbe.tobytes())


def con_suelo(img):
    """El panorama con el hemisferio de abajo cambiado por un pasto lejano."""
    alto = img.shape[0]
    fila = np.arange(alto) + 0.5
    depresion = np.degrees(np.pi * fila / alto) - 90.0       # > 0 bajo el horizonte
    banda = img[int(alto * 0.47):alto // 2].reshape(-1, 3).mean(axis=0)  # cielo junto al horizonte
    lum = 0.2126 * banda[0] + 0.7152 * banda[1] + 0.0722 * banda[2]
    c = np.array(SUELO_COLOR)
    suelo = c / (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) * lum * SUELO_BRILLO
    t = np.clip(depresion / SUELO_TRANSICION_GRADOS, 0.0, 1.0)
    t = t * t * (3 - 2 * t)
    out = img.copy()
    out[:] = img * (1 - t)[:, None, None] + suelo[None, None, :] * t[:, None, None]
    return out


def sol_del_hdri(img):
    """(fila, columna, phi' en grados, elevacion en grados) del pixel mas
    brillante. phi' es el angulo con que Skybox/Panoramic muestrea ese
    pixel: u = 0.5 - atan2(z, x) / 2pi (ToRadialCoords de Unity)."""
    lum = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    fila, col = np.unravel_index(int(np.argmax(lum)), lum.shape)
    alto, ancho = lum.shape
    u = (col + 0.5) / ancho
    latitud = math.pi * (fila + 0.5) / alto        # 0 en el cenit (fila 0 = arriba)
    phi = 2 * math.pi * (0.5 - u)
    return int(fila), int(col), math.degrees(phi), 90.0 - math.degrees(latitud), float(lum.max())


def sol_realista():
    """(pitch, yaw) de la luz en la vista realista, leidos del C#."""
    ruta = rutas.cs(CS_AMBIENTE)
    src = io.open(ruta, encoding='utf-8').read()
    m = re.search(r'SOL_REALISTA\s*=\s*new Vector3\(([-\d.]+)f,\s*([-\d.]+)f,\s*([-\d.]+)f\)', src)
    if m is None:
        raise ValueError('%s no declara SOL_REALISTA = new Vector3(...f, ...f, ...f)'
                         % rutas.relativa(ruta))
    return float(m.group(1)), float(m.group(2))


def giro_para(phi_hdri_grados, pitch, yaw):
    """
    _Rotation (grados) del Skybox/Panoramic que pone el sol del HDRI en
    el rumbo de la luz. El shader muestrea la direccion girada:
    x' + i z' = e^{i alfa} (x + i z), asi que phi' = phi + alfa. La luz
    viaja en su forward (Euler(pitch, yaw)); el sol esta en -forward.
    """
    p, y = math.radians(pitch), math.radians(yaw)
    fx, fz = math.sin(y) * math.cos(p), math.cos(y) * math.cos(p)
    phi_sol = math.degrees(math.atan2(-fz, -fx))
    return (phi_hdri_grados - phi_sol) % 360.0, phi_sol


# ============================================================
# LO QUE VERIFICA
# ============================================================
def a_lineal(srgb):
    s = srgb / 255.0
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)


def ruido_periodico(n, rng, filtro):
    """Ruido blanco filtrado en Fourier: empalma consigo mismo por construccion."""
    k = np.fft.fftfreq(n) * n
    kk = np.sqrt(k[:, None] ** 2 + k[None, :] ** 2)
    r = np.real(np.fft.ifft2(np.fft.fft2(rng.normal(size=(n, n))) * filtro(kk)))
    return r / r.std()


def detalle(item):
    """La textura de detalle (gris lineal, media 0.5, periodica) de un item."""
    cfg = DETALLES[item]
    n = LADO_DETALLE
    rng = np.random.default_rng(cfg['semilla'])
    macro = ruido_periodico(n, rng, lambda kk: np.exp(-(kk / cfg['ciclos_macro']) ** 2))
    lo, hi = cfg['medio_ciclos']
    medio = ruido_periodico(n, rng, lambda kk: ((kk >= lo) & (kk <= hi)).astype(float))
    d = 0.5 * (1.0 + cfg['macro'] * macro + cfg['medio'] * medio)
    d = np.clip(d, 0.15, 0.85)
    d += 0.5 - d.mean()
    return np.clip(np.rint(d * 255.0), 0, 255).astype(np.uint8)


def armar_detalles():
    from PIL import Image
    for item in DETALLES:
        Image.fromarray(detalle(item), mode='L').save(os.path.join(TEXTURAS, item, 'detalle.png'))
    lista = [{'item': i, 'escala': c['escala']} for i, c in DETALLES.items()]
    with io.open(os.path.join(TEXTURAS, 'detalle.json'), 'w', encoding='utf-8') as fh:
        json.dump({'items': lista, '_por_que': POR_QUE_DETALLE}, fh, indent=1, ensure_ascii=False)
    print('  escritos %d detalle.png y Texturas/detalle.json' % len(DETALLES))


def guid_de(ruta):
    with io.open(ruta + '.meta', encoding='utf-8') as f:
        return re.search(r'guid: ([0-9a-f]{32})', f.read()).group(1)


def main(argv):
    verificar = '--verificar' in argv
    fallas = []

    def check(ok, msg, detalle=''):
        print('  [%s] %s' % ('OK  ' if ok else 'FALLA', msg))
        if detalle:
            print('         ' + detalle)
        if not ok:
            fallas.append(msg)

    print('=' * 72)
    print('  RECURSOS DE LA VISTA REALISTA   (%s)' % os.path.relpath(AMBIENTE, rutas.RAIZ))
    print('=' * 72)
    hdr = HDR_ORIGINAL
    sol_json = os.path.join(TEXTURAS, 'cielo', 'sol.json')
    if not verificar:
        armar_detalles()
    if os.path.isfile(hdr):
        img = leer_hdr(hdr)
        fila, col, phi, elev, lum = sol_del_hdri(img)
        try:
            pitch, yaw = sol_realista()
        except (OSError, ValueError) as e:
            pitch = yaw = None
            check(False, '[1] se lee SOL_REALISTA de %s' % CS_AMBIENTE, str(e))
        if pitch is not None:
            giro, phi_luz = giro_para(phi, pitch, yaw)
            print('  el sol del HDRI: pixel (%d, %d) de %dx%d, phi\' %.1f grados, elevacion %.1f grados '
                  '(luminancia %.0f)' % (fila, col, img.shape[0], img.shape[1], phi, elev, lum))
            print('  la luz realista: Euler(%.0f, %.0f) -> sol en phi %.1f, elevacion %.0f; giro del cielo %.2f'
                  % (pitch, yaw, phi_luz, pitch, giro))
            datos = {'giro_grados': round(giro, 3), 'phi_hdri_grados': round(phi, 3),
                     'elevacion_hdri_grados': round(elev, 2), 'phi_luz_grados': round(phi_luz, 3),
                     'elevacion_luz_grados': pitch,
                     '_por_que': POR_QUE_SOL}
            if not verificar:
                with io.open(sol_json, 'w', encoding='utf-8') as f:
                    json.dump(datos, f, indent=1, ensure_ascii=False)
                print('  escrito %s' % os.path.relpath(sol_json, rutas.RAIZ))
            check(os.path.isfile(sol_json) and abs(json.load(io.open(sol_json, encoding='utf-8'))['giro_grados']
                                                   - giro) < 1e-3,
                  '[1] sol.json tiene el giro que sale del HDRI y de SOL_REALISTA (%.2f grados)' % giro)
            if abs(elev - pitch) > 20:
                print('  (ojo: el sol del HDRI esta a %.0f grados y la luz a %.0f: las sombras no calzan en altura)'
                      % (elev, pitch))
            cielo_mat = os.path.join(AMBIENTE, 'Cielo.mat')
            if os.path.isfile(cielo_mat):
                src = io.open(cielo_mat, encoding='utf-8').read()
                m = re.search(r'- _Rotation: ([-\d.e]+)', src)
                r = float(m.group(1)) if m else float('nan')
                check(m is not None and abs(((r - giro + 180) % 360) - 180) <= TOL_GIRO_GRADOS,
                      '[4] Cielo.mat tiene ese giro (%s) y usa el HDR' % (m.group(1) if m else 'sin _Rotation'),
                      '' if os.path.isfile(HDR_UNITY) and guid_de(HDR_UNITY) in src
                      else 'Cielo.mat no apunta a cielo_2k_suelo.hdr')
        if not verificar:
            escribir_hdr(HDR_UNITY, con_suelo(img))
            print('  escrito %s (bajo el horizonte, pasto lejano)' % os.path.relpath(HDR_UNITY, rutas.RAIZ))
        if os.path.isfile(HDR_UNITY):
            u = leer_hdr(HDR_UNITY)
            arriba = slice(0, img.shape[0] // 2 - 5)
            dif = float(np.abs(u[arriba] - img[arriba]).max() / max(img[arriba].max(), 1e-9))
            abajo = u[int(img.shape[0] * 0.75):]
            # max - min y no std: el std en float32 de un valor constante da ~1e-3
            check(dif < 0.01 and float(np.ptp(abajo.reshape(-1, 3), axis=0).max()) == 0.0,
                  '[1] cielo_2k_suelo.hdr = el original sobre el horizonte (dif. relativa %.1e, el RGBE) y '
                  'pasto parejo bajo el' % dif)
        else:
            check(False, '[4] existe Cielo.mat (correr Editor/RecursosRealistas.cs)')
    else:
        check(False, '[1] existe %s' % os.path.relpath(hdr, rutas.RAIZ))

    for item in ITEMS + ('cielo',):
        fuente = os.path.join(TEXTURAS, item, 'FUENTE.txt')
        ok = os.path.isfile(fuente) and 'CC0' in io.open(fuente, encoding='utf-8').read()
        check(ok, '[2] %s: FUENTE.txt dice CC0' % item)
    for item in ITEMS:
        color = os.path.join(TEXTURAS, item, 'color.jpg')
        normal = os.path.join(TEXTURAS, item, 'normal_gl.jpg')
        if not (os.path.isfile(color + '.meta') and os.path.isfile(normal + '.meta')):
            check(False, '[3] %s: sus texturas estan importadas (.meta)' % item)
            continue
        meta = io.open(normal + '.meta', encoding='utf-8').read()
        tipo = re.search(r'textureType: (\d+)', meta)
        check(tipo is not None and tipo.group(1) == '1', '[3] %s: el mapa normal se importa como NormalMap' % item,
              'textureType = %s' % (tipo.group(1) if tipo else '?'))
        mat = os.path.join(AMBIENTE, 'Mat_%s.mat' % item)
        if not os.path.isfile(mat):
            check(False, '[4] existe Mat_%s.mat' % item)
            continue
        src = io.open(mat, encoding='utf-8').read()
        check(guid_de(color) in src and guid_de(normal) in src and '_NORMALMAP' in src,
              '[4] Mat_%s apunta a su color y su normal, con _NORMALMAP' % item)
    # [5] el mapa de detalle
    from PIL import Image
    for item, cfg in DETALLES.items():
        ruta = os.path.join(TEXTURAS, item, 'detalle.png')
        if not os.path.isfile(ruta):
            check(False, '[5] %s: existe detalle.png' % item)
            continue
        im = np.asarray(Image.open(ruta), dtype=float) / 255.0
        media = float(im.mean())
        # empalma: el salto entre el borde y el borde opuesto no es mayor
        # que el salto tipico entre columnas vecinas
        salto_borde = float(np.abs(im[:, 0] - im[:, -1]).mean() + np.abs(im[0, :] - im[-1, :]).mean()) / 2
        salto_tipico = float(np.abs(np.diff(im, axis=1)).mean())
        check(im.ndim == 2 and abs(media - 0.5) < 0.01 and salto_borde < 1.5 * salto_tipico,
              '[5] %s: detalle.png gris, media %.3f (0.5 = neutro) y empalma (borde %.4f, tipico %.4f)'
              % (item, media, salto_borde, salto_tipico))
        mat = os.path.join(AMBIENTE, 'Mat_%s.mat' % item)
        if os.path.isfile(mat) and os.path.isfile(ruta + '.meta'):
            src = io.open(mat, encoding='utf-8').read()
            meta = io.open(ruta + '.meta', encoding='utf-8').read()
            m = re.search(r'_DetailAlbedoMap:\s*\n\s*m_Texture: \{fileID: \d+, guid: ([0-9a-f]+)[^\n]*\n'
                          r'\s*m_Scale: \{x: ([-\d.e]+), y: ([-\d.e]+)\}', src)
            check(m is not None and m.group(1) == guid_de(ruta) and '_DETAIL_MULX2' in src
                  and abs(float(m.group(2)) - cfg['escala']) < 1e-6 and 'sRGBTexture: 0' in meta,
                  '[5] Mat_%s usa su detalle.png (lineal) a escala %.3f, con _DETAIL_MULX2' % (item, cfg['escala']))
        else:
            check(False, '[5] Mat_%s y detalle.png.meta existen (correr Editor/RecursosRealistas.cs)' % item)
    perfil = os.path.join(AMBIENTE, 'PerfilRealista.asset')
    check(os.path.isfile(perfil) and all(k in io.open(perfil, encoding='utf-8').read()
                                         for k in ('Tonemapping', 'ColorAdjustments', 'Bloom')),
          '[4] PerfilRealista.asset trae Tonemapping, ColorAdjustments y Bloom')
    print('=' * 72)
    if fallas:
        print('  %d FALLA(S)' % len(fallas))
        return 1
    print('  TODO OK')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
