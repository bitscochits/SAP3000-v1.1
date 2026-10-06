# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/ar.py  -  LA APP DE AR, CRITERIO POR CRITERIO
================================================================
 Tres bloques; sin bloque corre los tres:

   python -m verificacion.ar ids_resultados_pose    # sin navegador, segundos
   python -m verificacion.ar registro_y_tracking    # Chrome o Edge, ~1 minuto
   python -m verificacion.ar precision [--fov 70]   # lee lo que dejo el anterior

 IDS_RESULTADOS_POSE: lo que ve el telefono es lo que calculo OpenSees.
   [1] ELEMENTO / ID     cada elementTag y nodeTag de ar/web/datos/ar.json
                         existe en el edificio con los mismos nodos, tipo y
                         seccion; y la linea de OpenSees de los resultados
                         nombra ese mismo tag y esos mismos nodos.
   [2] RESULTADO         cada numero de la app (esfuerzos por estacion,
                         desplazamientos, demanda y curva P-M) es IDENTICO
                         al de los resultados del laboratorio: la app no
                         calcula.
   [3a] REGISTRO         la pose del marcador: ejes ortonormales y derechos,
                         en la cara de la columna, a la altura declarada.
   Y la TRAZA de la columna del marcador, del modelo al telefono, cada
   eslabon contra el anterior con una cota que sale de su causa:
   [traza 3] OPENSEES    el edificio resuelto AHORA, leyendo localForce SIN
                         el redondeo del servidor, contra lo que trae la app;
                         y la combinacion de la app corrida como UN caso.
   [traza 4] DEMANDA     P, M, Mn y u rehechos desde esas fuerzas con la
                         regla de calculo/demanda.py, contra los de la app;
                         cual combinacion gobierna.
   [traza 5] PANEL       lo que escribe el panel del telefono (ar.js), con
                         su mismo formato.

 REGISTRO_Y_TRACKING: la app corriendo de verdad, en un navegador sin
 ventana servido por ar/servir.py.
   [3b] REGISTRO         la transformacion modelo -> anchor de ar.js contra
                         la de exportar/ar.py (a_anchor). Esta escrita dos
                         veces a proposito (una corre en el telefono) y
                         esto es lo que impide que se separen.
   [4] IMAGE TRACKING    se genera un VIDEO SINTETICO de la imagen impresa,
                         vista desde una pose CONOCIDA con la camara que
                         supone MindAR (su campo de vision se LEE del codigo
                         de vendor/mindar), y se le da al navegador como si
                         fuera la camara. La app tiene que detectar la imagen
                         y recuperar esa pose: distancia e inclinacion.
   Deja lo medido en verificacion/registros/ar_tracking.json (lo lee el
   bloque precision; no se regenera con sap.py preparar).

 PRECISION: cuanto se equivoca el registro, una estimacion simple. Un
 error de angulo dtheta en la pose mueve un punto que esta a r del centro
 de la imagen en unos r * dtheta. Un error de escala eps (la distancia que
 estima MindAR, o el ancho impreso) lo mueve eps * r. Sobre eso se suma lo
 que corre la imagen entera (como se pego) y los sesgos (a que nivel esta
 el nodo). Todo con la MISMA transformacion de la app (a_anchor): la
 matriz no aporta error, todo el error es fisico.
   [1] BRAZO        a que distancia del centro de la imagen esta cada nodo
   [2] FUENTES      cada fuente, exacta, perturbando la pose del marcador
   [3] PRESUPUESTO  suma cuadratica y peor caso, en sitio y en maqueta
   [4] FOCAL        lo que el ensayo de tracking no puede ver: MindAR supone
                    su campo vertical fijo, y el iPhone no es eso
   [5] PRUEBA       lo que hay que medir en el iPhone, con lo que debe dar

 Ninguno escribe en salidas/.
================================================================
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import glob
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import openseespy.opensees as ops

from ar import servir
from calculo import demanda as dem
from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo import superposicion as sup
from exportar import ar as exar
from verificacion.comun import Informe, titulo

# MOVER A calculo/rutas.py: la copia de salidas/ar.json que lee el telefono
# (la deja sap.py sincronizar).
AR_JSON = os.path.join(rutas.AR_WEB, 'datos', 'ar.json')
MARCADOR = os.path.join(rutas.AR_WEB, 'marcador.png')
TARGETS = os.path.join(rutas.AR_WEB, 'targets.mind')
VENDOR_MINDAR = os.path.join(rutas.AR_WEB, 'vendor', 'mindar')
TRACKING = os.path.join(rutas.REGISTROS, 'ar_tracking.json')
PUERTO = 8093                  # el suyo: no choca con ar marcador (8091) ni con servir (8080)
BLOQUES = ('ids_resultados_pose', 'registro_y_tracking', 'precision')

EPS = sys.float_info.epsilon
EPS4 = 4.0 * sys.float_info.epsilon
CASOS = lab.CASOS_BASE
COMPONENTES = ('N', 'Vy', 'Vz', 'T', 'My', 'Mz')
R_F, R_U = 0.5e-4, 0.5e-8     # el servidor escribe 4 decimales en kN y 8 en m


def leer(ruta):
    with io.open(ruta, encoding='utf-8') as fh:
        return json.load(fh)


def rel(ruta):
    return rutas.relativa(ruta).replace(os.sep, '/')


def leer_app():
    if not os.path.isfile(AR_JSON):
        raise SystemExit('falta %s, lo que lee el telefono: python sap.py exportar ar y '
                         'python sap.py sincronizar' % rel(AR_JSON))
    return leer(AR_JSON)


def md5(ruta):
    with open(ruta, 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()


def fov_de_mindar():
    r"""
    (grados, archivo): el campo de vision VERTICAL que supone MindAR, leido
    de su propio codigo (vendor/mindar/controller-*.js, donde arma la
    camara: h = 45 * Math.PI / 180, f = (alto/2) / tan(h/2)). No se copia
    como constante: si se actualiza MindAR y lo cambia, una copia quedaria
    vieja sin que nada falle, y el video del tracking y el presupuesto de
    la focal se armarian con otra camara que la de la app.
    """
    archivos = sorted(glob.glob(os.path.join(VENDOR_MINDAR, 'controller-*.js')))
    for ruta in archivos:
        with io.open(ruta, encoding='utf-8') as fh:
            texto = fh.read()
        m = re.search(r'(\w+) = ([\d.]+) \* Math\.PI / 180, \w+ = this\.inputHeight / 2 / '
                      r'Math\.tan\(\1 / 2\)', texto)
        if m:
            return float(m.group(2)), ruta
    return None, (archivos[0] if archivos else VENDOR_MINDAR)


# ============================================================
# [1] y [2]
# ============================================================
def bloque_ids(ar, modelo, anexo, inf):
    titulo('[1] ELEMENTO / ID: los tags de la app son los de OpenSees')
    E = {e['id']: e for e in modelo['elementos']}
    N = {n['id']: n for n in modelo['nodos']}
    A = {e['id']: e for e in anexo['elementos']}
    malos = []
    for e in ar['elementos']:
        m = E.get(e['id'])
        if m is None or (m['n1'], m['n2'], m['tipo'], m['seccion']) != (e['n1'], e['n2'], e['tipo'], e['seccion']):
            malos.append('elemento %s' % e['id'])
            continue
        linea = A[e['id']]['tag_opensees']
        if not linea.startswith('element elasticBeamColumn %d %d %d ' % (e['id'], e['n1'], e['n2'])):
            malos.append('tag_opensees de %d: %s' % (e['id'], linea[:60]))
        if e['tag_opensees'] != linea:
            malos.append('la app lleva otra linea de OpenSees para %d' % e['id'])
    inf.check(not malos, '%d elementos: mismo elementTag, nodos, tipo y seccion que el modelo; la linea '
              '"element elasticBeamColumn <tag> <n1> <n2>" de los resultados nombra los mismos'
              % len(ar['elementos']), malos[:5])
    malos = [n['id'] for n in ar['nodos'] if n['id'] not in N or
             (N[n['id']]['x'], N[n['id']]['y'], N[n['id']]['z']) != (n['x'], n['y'], n['z'])]
    inf.check(not malos, '%d nodos: mismo nodeTag y las mismas x, y, z de OpenSees' % len(ar['nodos']), malos[:5])
    obj = E[ar['objetivo']]
    inf.check(ar['marcador']['elemento'] == ar['objetivo'] and obj['tipo'] == 'columna',
              'el marcador esta en el elemento %d (%s %s), el mismo que muestra la app'
              % (obj['id'], obj['tipo'], obj['seccion']))


def bloque_resultados(ar, anexo, inf):
    titulo('[2] RESULTADO ESTRUCTURAL: cada numero de la app es el de OpenSees')
    en = {e['id'] for e in ar['elementos']}
    nn = {n['id'] for n in ar['nodos']}
    casos_a = {c['nombre']: c for c in anexo['casos']}
    inf.check([c['nombre'] for c in ar['casos']] == [c['nombre'] for c in anexo['casos']],
              'los %d casos de los resultados, en el mismo orden' % len(ar['casos']))
    n_num, distintos = 0, []
    for c in ar['casos']:
        ca = casos_a[c['nombre']]
        for s in ca['esfuerzos']:
            if s['id'] in en:
                mine = c['esfuerzos'][str(s['id'])]
                for k in ('x', 'f') + exar.MAGNITUDES:
                    n_num += len(s[k])
                    if mine[k] != s[k]:
                        distintos.append('%s %s %s' % (c['nombre'], s['id'], k))
        for d in ca['desplazamientos']:
            if d['id'] in nn:
                n_num += 6
                if c['desplazamientos'][str(d['id'])] != [d[k] for k in ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')]:
                    distintos.append('%s nodo %s' % (c['nombre'], d['id']))
        for d in ca['demandas']:
            if d['id'] in en:
                n_num += 6
                if c['demandas'][str(d['id'])] != {k: d[k] for k in ('P', 'M', 'Mn', 'u', 'pasa', 'extremo')}:
                    distintos.append('%s demanda %s' % (c['nombre'], d['id']))
    # La familia por su 'indice', como la exporta exportar/ar.py: por la
    # posicion en la lista, un resultados.json reordenado haria que la app y
    # esta comparacion leyeran la MISMA curva equivocada y dijeran "identico".
    por_indice = exar.familias_por_indice(anexo)
    for k, f in ar['familias'].items():
        fa = por_indice[int(k)]
        n_num += len(fa['P']) + len(fa['Mn'])
        if (f['P'], f['Mn']) != (fa['P'], fa['Mn']):
            distintos.append('familia %s' % k)
    inf.check(not distintos, '%d numeros (esfuerzos, desplazamientos, demandas y curvas P-M) identicos a '
              'los resultados, bit a bit' % n_num, distintos[:5])
    obj = str(ar['objetivo'])
    d = next(c for c in ar['casos'] if c['nombre'] == ar['info']['caso_por_defecto'])['demandas'].get(obj)
    if d:
        print('         ej.: %s en %s: P = %.1f kN, M = %.1f kN m, Mn = %.1f kN m, u = %.3f, %s'
              % (obj, ar['info']['caso_por_defecto'], d['P'], d['M'], d['Mn'], d['u'], 'PASA' if d['pasa'] else 'NO PASA'))


# ============================================================
# [3] REGISTRO
# ============================================================
def bloque_pose(ar, modelo, inf):
    titulo('[3a] REGISTRO: la pose del marcador en el modelo')
    for nombre, pose in (('sitio', ar['marcador']), ('maqueta', ar['marcador']['maqueta'])):
        x, y, z = pose['ejes']['x'], pose['ejes']['y'], pose['ejes']['z']
        orto = max(abs(exar.punto(x, x) - 1), abs(exar.punto(y, y) - 1), abs(exar.punto(z, z) - 1),
                   abs(exar.punto(x, y)), abs(exar.punto(y, z)), abs(exar.punto(x, z)))
        cz = exar.cruz(x, y)
        mano = max(abs(cz[i] - z[i]) for i in range(3))
        inf.check(orto <= EPS4 and mano <= EPS4, '%s: ejes ortonormales (%.1e) y derechos, x cruz y = z (%.1e)'
                  % (nombre, orto, mano))
    N = {n['id']: n for n in modelo['nodos']}
    E = {e['id']: e for e in modelo['elementos']}
    obj = E[ar['objetivo']]
    m = ar['marcador']
    n1 = N[obj['n1']]
    d = exar.resta(m['centro'], [n1['x'], n1['y'], m['centro'][2]])
    dist_cara = exar.punto(d, m['ejes']['z'])
    lateral = math.hypot(*[d[i] - dist_cara * m['ejes']['z'][i] for i in range(3)])
    inf.check(abs(dist_cara - m['medio_ancho_columna_m']) <= 1e-6 and lateral <= 1e-6,
              'sitio: el centro de la imagen esta en la cara %s, a %.3f m del eje de la columna (medio ancho), '
              'centrado en la cara' % (m['cara'], dist_cara))
    z0 = min(N[obj['n1']]['z'], N[obj['n2']]['z'])
    inf.check(abs(m['centro'][2] - z0 - m['altura_centro_m']) <= 1e-6 and m['ejes']['y'] == [0.0, 0.0, 1.0],
              'sitio: centro a %.2f m sobre el nodo inferior (z = %.2f) y el arriba de la imagen es +z de OpenSees'
              % (m['altura_centro_m'], z0))
    mq = m['maqueta']
    inf.check(mq['centro'] == [n1['x'], n1['y'], z0] and mq['ejes']['z'] == [0.0, 0.0, 1.0],
              'maqueta: origen en la base de la columna y +z de OpenSees saliendo de la imagen')


def bloque_transformacion(ar, consola, inf):
    titulo('[3b] REGISTRO: la transformacion de ar.js (en el navegador) contra la de Python')
    lineas = [l for l in consola if l.startswith('AR_TRANSFORM ')]
    if not inf.check(bool(lineas), 'ar.js corrio y publico su transformacion (AR_TRANSFORM)'):
        return {}
    js = json.loads(lineas[-1][len('AR_TRANSFORM '):])
    medido = {}
    for modo in ('sitio', 'maqueta'):
        pose = ar['marcador'] if modo == 'sitio' else ar['marcador']['maqueta']
        esc = ar['modos'][modo]['escala']
        peor, donde = 0.0, ''
        for n in ar['nodos']:
            py = exar.a_anchor([n['x'], n['y'], n['z']], dict(pose, ancho_m=ar['marcador']['ancho_m']), esc)
            j = js[modo]['puntos'][str(n['id'])]
            err = max(abs(py[i] - j[i]) for i in range(3))
            if err > peor:
                peor, donde = err, 'nodo %d' % n['id']
        # La cota: los dos hacen las mismas ~10 operaciones en doble
        # precision sobre coordenadas de hasta ~60 m / 0.2 m = 300 anchos.
        cota = 64 * EPS4 * 300
        inf.check(peor <= cota, '%s: %d nodos, Python = ar.js (peor %.1e anchos en %s, cota %.1e)'
                  % (modo, len(ar['nodos']), peor, donde or '-', cota))
        c = js[modo]['puntos']['centro_marcador']
        inf.check(max(abs(v) for v in c) <= cota, '%s: el centro de la pose cae en el origen del anchor %s'
                  % (modo, [round(v, 12) for v in c]))
        medido[modo] = {'peor_anchos': peor, 'en': donde, 'cota_anchos': cota}
    # Una lectura fisica: en sitio, la columna mide su alto en anchos.
    obj = next(e for e in ar['elementos'] if e['id'] == ar['objetivo'])
    a = js['sitio']['puntos'][str(obj['n1'])]
    b = js['sitio']['puntos'][str(obj['n2'])]
    alto = math.dist(a, b) * ar['marcador']['ancho_m']
    inf.check(abs(alto - obj['L']) <= 1e-9, 'sitio: la columna mide %.3f m en el anchor x ancho, igual que en '
              'OpenSees (L = %.3f m): escala 1:1' % (alto, obj['L']))
    q = js['maqueta']['puntos']
    alto_m = math.dist(q[str(obj['n1'])], q[str(obj['n2'])]) * ar['marcador']['ancho_m']
    inf.check(abs(alto_m - obj['L'] * ar['modos']['maqueta']['escala']) <= 1e-9,
              'maqueta: la columna mide %.1f cm sobre la mesa = %.2f m x %g' % (alto_m * 100, obj['L'],
                                                                              ar['modos']['maqueta']['escala']))
    return medido


# ============================================================
# [4] IMAGE TRACKING con un video sintetico
# ============================================================
W_VIDEO, H_VIDEO = 640, 480


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def mat(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]


def generar_video(ruta, ancho_m, dist, incl_deg, giro_deg, fov_grados, cuadros=45):
    """La imagen impresa vista desde una camara con la pose dada, con los
    intrinsecos de MindAR, escrita como video .y4m (lo que Chrome acepta
    como camara falsa). Devuelve la pose verdadera."""
    from PIL import Image
    fovy = math.radians(fov_grados)
    src = np.asarray(Image.open(MARCADOR).convert('RGB'), dtype=np.float32)
    H0, W0 = src.shape[:2]
    alto_m = ancho_m * H0 / W0
    f = (H_VIDEO / 2) / math.tan(fovy / 2)
    K = np.array([[f, 0, W_VIDEO / 2], [0, f, H_VIDEO / 2], [0, 0, 1]])
    # Camara de frente (convencion OpenCV: x derecha, y abajo, z adelante):
    # x del marcador -> x, y (arriba) -> -y, z (hacia la camara) -> -z.
    R0 = [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
    R = np.array(mat(R0, mat(rot_x(math.radians(incl_deg)), rot_z(math.radians(giro_deg)))))
    t = np.array([0.0, 0.0, dist])
    # pixel de la imagen (u, v) -> punto del marcador (X, Y, 0) en metros
    A = np.array([[ancho_m / W0, 0, -ancho_m / 2], [0, -alto_m / H0, alto_m / 2], [0, 0, 1]])
    Hm = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ A
    Hinv = np.linalg.inv(Hm)
    uu, vv = np.meshgrid(np.arange(W_VIDEO), np.arange(H_VIDEO))
    p = Hinv @ np.stack([uu.ravel(), vv.ravel(), np.ones(uu.size)])
    us, vs = p[0] / p[2], p[1] / p[2]
    dentro = (us >= 0) & (us < W0 - 1) & (vs >= 0) & (vs < H0 - 1) & (p[2] > 0)
    rng = np.random.default_rng(7)
    fondo = (150 + 12 * rng.standard_normal((H_VIDEO * W_VIDEO, 3))).clip(0, 255)
    img = fondo.copy()
    u0, v0 = us[dentro].astype(int), vs[dentro].astype(int)
    du, dv = (us[dentro] - u0)[:, None], (vs[dentro] - v0)[:, None]
    img[dentro] = (src[v0, u0] * (1 - du) * (1 - dv) + src[v0, u0 + 1] * du * (1 - dv) +
                   src[v0 + 1, u0] * (1 - du) * dv + src[v0 + 1, u0 + 1] * du * dv)
    rgb = img.reshape(H_VIDEO, W_VIDEO, 3)
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    cb = 128 - 0.168736 * rgb[..., 0] - 0.331264 * rgb[..., 1] + 0.5 * rgb[..., 2]
    cr = 128 + 0.5 * rgb[..., 0] - 0.418688 * rgb[..., 1] - 0.081312 * rgb[..., 2]
    sub = lambda c: c.reshape(H_VIDEO // 2, 2, W_VIDEO // 2, 2).mean(axis=(1, 3))     # noqa: E731
    planos = [y.clip(0, 255).astype(np.uint8), sub(cb).clip(0, 255).astype(np.uint8), sub(cr).clip(0, 255).astype(np.uint8)]
    with open(ruta, 'wb') as fh:
        fh.write(b'YUV4MPEG2 W%d H%d F30:1 Ip A1:1 C420jpeg\n' % (W_VIDEO, H_VIDEO))
        for _ in range(cuadros):
            fh.write(b'FRAME\n')
            for pl in planos:
                fh.write(pl.tobytes())
    ancho_px = f * ancho_m / dist
    return {'dist_m': dist, 'incl_deg': incl_deg, 'giro_deg': giro_deg, 'R': R.tolist(), 'ancho_px': ancho_px}


def bloque_tracking(ar, nav, inf):
    titulo('[4] IMAGE TRACKING: video sintetico con pose conocida -> la pose que estima la app')
    fov, de_donde = fov_de_mindar()
    if not inf.check(fov is not None, 'la camara que supone MindAR, leida de su codigo (%s): campo de vision '
                     'vertical de %s grados' % (rel(de_donde), '%g' % fov if fov else '?')):
        return None, []
    poses = [(0.45, 0.0, 0.0), (0.55, 30.0, 0.0), (0.60, 40.0, 20.0)]
    medidas = []
    carpeta = tempfile.mkdtemp(prefix='ar_video_')
    try:
        for dist, incl, giro in poses:
            video = os.path.join(carpeta, 'pose.y4m')
            verdad = generar_video(video, ar['marcador']['ancho_m'], dist, incl, giro, fov)
            consola = navegador(nav, 'index.html?prueba=1&iniciar=maqueta', 60, video=video, esperar='AR_POSE', minimo=6)
            poses_js = [json.loads(l[len('AR_POSE '):]) for l in consola if l.startswith('AR_POSE ')]
            etiqueta = 'd = %.2f m, inclinacion %g, giro %g' % (dist, incl, giro)
            medida = {'verdad_m': dist, 'inclinacion_deg': incl, 'giro_deg': giro,
                      'poses_publicadas': len(poses_js), 'detecta': len(poses_js) >= 3}
            medidas.append(medida)
            if not inf.check(len(poses_js) >= 3, '%s: la app DETECTA la imagen (%d poses publicadas)'
                             % (etiqueta, len(poses_js))):
                medida['ok'] = False
                continue
            ult = poses_js[-3:]                              # ya sin el arranque del filtro
            d_est = sum(p['dist_m'] for p in ult) / len(ult)
            i_est = sum(p['giro_deg'] for p in ult) / len(ult)
            # Orientacion completa: los ejes del anchor en la camara de three.js
            # (x derecha, y ARRIBA, z HACIA ATRAS) contra los verdaderos (OpenCV).
            e = ult[-1]['m']
            eje = lambda c: [e[4 * c], e[4 * c + 1], e[4 * c + 2]]       # noqa: E731
            R = verdad['R']
            peor_ang = 0.0
            for c in range(3):
                v = eje(c)
                nv = math.sqrt(sum(a * a for a in v))
                ver = [R[0][c], -R[1][c], -R[2][c]]
                cosang = max(-1.0, min(1.0, sum(v[i] * ver[i] for i in range(3)) / nv))
                peor_ang = max(peor_ang, math.degrees(math.acos(cosang)))
            # Cotas desde el pixel: la imagen ocupa ancho_px en el cuadro y
            # MindAR ubica sus esquinas a ~1 px; eso mueve la distancia en
            # d * 1/ancho_px por lado y el angulo en atan(2/ancho_px) por
            # esquina. Se dejan 3 px de margen (esquinas en varias escalas).
            px = 3.0
            cota_d = dist * px / verdad['ancho_px']
            cota_a = math.degrees(math.atan(2 * px / verdad['ancho_px'])) * 2
            ok_d = inf.check(abs(d_est - dist) <= cota_d,
                             '%s: distancia estimada %.3f m (verdad %.3f, error %.1f mm, cota %.1f mm; la imagen ocupa %.0f px)'
                             % (etiqueta, d_est, dist, abs(d_est - dist) * 1000, cota_d * 1000, verdad['ancho_px']))
            ok_a = inf.check(abs(i_est - incl) <= cota_a and peor_ang <= cota_a,
                             '%s: inclinacion estimada %.1f deg (verdad %g) y los tres ejes a %.1f deg de los verdaderos '
                             '(cota %.1f deg)' % (etiqueta, i_est, incl, peor_ang, cota_a))
            # Lo que informa [4], con los digitos con que lo imprime: es lo que
            # usa el presupuesto de precision. Sin redondear, aparte.
            medida.update({
                'distancia_m': float('%.3f' % d_est),
                'error_mm': float('%.1f' % (abs(d_est - dist) * 1000)),
                'cota_mm': float('%.1f' % (cota_d * 1000)),
                'ancho_px': int('%.0f' % verdad['ancho_px']),
                'inclinacion_estimada_deg': float('%.1f' % i_est),
                'ejes_deg': float('%.1f' % peor_ang),
                'cota_deg': float('%.1f' % cota_a),
                'sin_redondear': {'distancia_m': d_est, 'error_mm': abs(d_est - dist) * 1000,
                                  'ancho_px': verdad['ancho_px'], 'inclinacion_estimada_deg': i_est,
                                  'ejes_deg': peor_ang},
                'ok': ok_d and ok_a,
            })
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    return fov, medidas


# ============================================================
# EL NAVEGADOR
# ============================================================
def navegador(nav, pagina, segundos, video=None, esperar=None, minimo=1):
    """Abre la pagina en el navegador sin ventana y devuelve lo que la app
    escribio en la consola (las lineas con prefijo AR_). Al terminar cierra
    ESE navegador y sus hijos (servir.cerrar, por PID), nunca otro."""
    perfil = tempfile.mkdtemp(prefix='ar_chrome_')
    log = os.path.join(perfil, 'consola.txt')
    args = [nav, '--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
            '--autoplay-policy=no-user-gesture-required', '--enable-logging=stderr', '--v=0',
            '--user-data-dir=' + perfil]
    if video:
        args += ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                 '--use-file-for-fake-video-capture=' + video]
    args.append('http://localhost:%d/%s' % (PUERTO, pagina))
    with open(log, 'wb') as fh:
        p = subprocess.Popen(args, stdout=fh, stderr=subprocess.STDOUT)
        try:
            t0 = time.time()
            while time.time() - t0 < segundos:
                time.sleep(2)
                if esperar:
                    with open(log, 'rb') as g:
                        if g.read().decode('utf-8', 'replace').count(esperar) >= minimo:
                            break
        finally:
            servir.cerrar(p)
    with open(log, 'rb') as g:
        texto = g.read().decode('utf-8', 'replace')
    servir.borrar_perfil(perfil)
    lineas = []
    for m in re.finditer(r'CONSOLE:\d+\] "(.*?)", source:', texto):
        lineas.append(m.group(1))
    return lineas


# ============================================================
# LA TRAZA DE LA COLUMNA DEL MARCADOR
# ============================================================
def traza_opensees(inf, conj, ar, eid):
    titulo('[traza 3] OPENSEES, resuelto ahora y SIN el redondeo del servidor, contra la app')
    p = lab.cargar([])
    with contextlib.redirect_stdout(io.StringIO()):
        arm = lab.armar_casos(conj, p)
    casos = arm['casos']
    datos = copy.deepcopy(conj)
    datos['casos_de_carga'] = [casos[c] for c in CASOS]
    with contextlib.redirect_stdout(io.StringIO()):
        coords, _avisos, _restr = opensees.construir_modelo(datos)
    e = next(x for x in conj['elementos'] if int(x['id']) == eid)
    ni, nj = int(e['n1']), int(e['n2'])
    # Se lee OpenSees directamente (eleNodes, localForce, nodeDisp) a
    # proposito: el servidor y los resultados redondean, y aca se compara
    # contra lo que OpenSees tiene en memoria.
    inf.check(list(ops.eleNodes(eid)) == [ni, nj],
              'dentro de OpenSees, eleNodes(%d) = [%d, %d]: el tag del JSON es el de OpenSees'
              % (eid, ni, nj))
    nodos = set(coords)
    elems = {int(x['id']) for x in datos['elementos']}

    previo = [None]

    def resolver(caso, tag):
        if previo[0] is not None:
            ops.remove('loadPattern', previo[0])
        ops.reset()
        ops.setTime(0.0)
        with contextlib.redirect_stdout(io.StringIO()):
            opensees.aplicar_cargas(caso, tag, nodos, elems)
        if opensees.resolver_caso() != 0:
            raise SystemExit('OpenSees no resolvio %s' % caso.get('nombre'))
        previo[0] = tag
        return (list(ops.eleResponse(eid, 'localForce')),
                [ops.nodeDisp(ni, k) for k in range(1, 7)] + [ops.nodeDisp(nj, k) for k in range(1, 7)])

    res = {c: resolver(casos[c], 100 + i) for i, c in enumerate(CASOS)}
    por_nombre = {c['nombre']: c for c in ar['casos']}
    peor = 0.0
    for c in CASOS:
        f_ar = por_nombre[c]['esfuerzos'][str(eid)]['f']
        peor = max(peor, max(abs(a - b) for a, b in zip(f_ar, res[c][0])))
    inf.check(peor <= R_F + 4 * EPS * 1e4,
              'casos base G, Q, EX y EY: max |app - OpenSees| = %.2e kN o kN m (cota %.0e: el '
              'servidor escribe 4 decimales)' % (peor, R_F))

    nombre = ar['info']['caso_por_defecto']
    lam = dict(zip(CASOS, por_nombre[nombre]['factores']))
    suma_l = sum(abs(v) for v in lam.values())
    f_sup = [sum(lam[c] * res[c][0][k] for c in CASOS) for k in range(12)]
    u_sup = [sum(lam[c] * res[c][1][k] for c in CASOS) for k in range(12)]
    caso_c = sup.combinar_cargas(dict(datos, casos_de_carga=[casos[c] for c in CASOS]), lam, 'COMB')
    f_exp, u_exp = resolver(caso_c, 200)
    d_f = max(abs(a - b) for a, b in zip(f_sup, f_exp))
    d_u = max(abs(a - b) for a, b in zip(u_sup, u_exp))
    inf.check(d_f <= R_F and d_u <= R_U,
              '%s corrida como UN caso de carga contra la suma de los casos: %.1e kN y %.1e m '
              '(bajo el paso del servidor, %.0e / %.0e: el modelo es lineal)' % (nombre, d_f, d_u, R_F, R_U))

    C = por_nombre[nombre]
    f_ar = C['esfuerzos'][str(eid)]['f']
    cota = R_F * (suma_l + 1)
    d_ar = max(abs(a - b) for a, b in zip(f_ar, f_sup))
    k_peor = max(range(12), key=lambda k: abs(f_ar[k] - f_sup[k]))
    inf.check(d_ar <= cota + 4 * EPS * 1e4,
              '%s: max |app - OpenSees| = %.2e en %s_%s (cota 0.5e-4 x (%.1f + 1) = %.2e: cada caso '
              'redondeado por su factor, mas el redondeo de la combinacion)'
              % (nombre, d_ar, COMPONENTES[k_peor % 6], 'ij'[k_peor // 6], suma_l, cota))
    print('         %-10s %s' % ('', ''.join('%12s' % c for c in COMPONENTES)))
    for etq, v in (('OpenSees i', f_sup[:6]), ('app i', f_ar[:6]),
                   ('OpenSees j', f_sup[6:]), ('app j', f_ar[6:])):
        print('         %-10s %s' % (etq, ''.join('%12.4f' % x for x in v)))
    u_ar = C['desplazamientos'][str(ni)] + C['desplazamientos'][str(nj)]
    d_ud = max(abs(a - b) for a, b in zip(u_ar, u_sup))
    inf.check(d_ud <= R_U * (suma_l + 1),
              'desplazamientos de %d y %d: max |app - OpenSees| = %.2e m (cota %.1e); techo ux = %.2f mm'
              % (ni, nj, d_ud, R_U * (suma_l + 1), 1000 * u_sup[6]),
              ['entre los dos extremos hay %.2f mm en %.2f m: con la combinacion MAYORADA y la gravedad '
               'adentro, NO es la deriva de NCh433' % (1000 * (u_sup[6] - u_sup[0]),
                                                       coords[nj][2] - coords[ni][2])])
    return nombre, f_sup


def traza_demanda(inf, ar, nombre, f_sup, eid):
    titulo('[traza 4] DEMANDA Y CAPACIDAD: desde esas fuerzas, con la regla de calculo/demanda.py')
    e = next(x for x in ar['elementos'] if x['id'] == eid)
    fam = ar['familias'][str(e['familia'])]
    curva = [{'P_kN': P, 'M_kNm': M} for P, M in zip(fam['P'], fam['Mn'])]
    d = dem.demanda(f_sup, tipo='columna')
    Mn = dem.capacidad_en(d['P_kN'], curva)
    u = d['M_kNm'] / Mn
    app = next(c for c in ar['casos'] if c['nombre'] == nombre)['demandas'][str(eid)]
    inf.check(abs(u - app['u']) <= 0.5e-6 + 1e-9 and d['extremo'] == app['extremo'],
              '%s: extremo %s, P = %.4f kN, M = sqrt(My^2 + Mz^2) = sqrt(%.2f^2 + %.2f^2) = %.4f kN m, '
              'Mn(P) = %.4f, u = %.6f = app %.6f' % (nombre, d['extremo'], d['P_kN'], abs(d['My']),
                                                    abs(d['Mz']), d['M_kNm'], Mn, u, app['u']),
              ['familia %s: %s' % (e['familia'], fam['refuerzo'])])
    filas = []
    for c in ar['casos']:
        dd = c['demandas'][str(eid)]
        filas.append((dd['u'], c['nombre'], dd))
    diseno = [x for x in filas if x[1] not in CASOS and x[1] != 'S3']
    u_g, n_g, dd = max(diseno, key=lambda x: x[0])
    inf.check(u_g < 1.0,
              'de las %d combinaciones mayoradas gobierna %s: P = %.1f kN, M = %.1f kN m, Mn = %.1f kN m, '
              'u = %.3f, PASA' % (len(diseno), n_g, dd['P'], dd['M'], dd['Mn'], u_g),
              ['Mn nominal, sin phi: con phi = 0.65 (ACI 318-08, columna con estribos) u = %.3f; '
               'sigue pasando' % (u_g / 0.65)])
    return app


def traza_panel(ar, nombre, app, eid):
    titulo('[traza 5] PANEL: lo que escribe el telefono (ar/web/ar.js, actualizarPanel)')
    e = next(x for x in ar['elementos'] if x['id'] == eid)
    C = next(c for c in ar['casos'] if c['nombre'] == nombre)
    s = C['esfuerzos'][str(eid)]
    print('  elementTag %d | %s %s   (%s)' % (e['id'], e['tipo'], e['seccion'], nombre))
    for m in COMPONENTES:
        print('    %-3s %10.1f %10.1f' % (m, s[m][0], s[m][-1]))
    for n in (e['n1'], e['n2']):
        u = C['desplazamientos'][str(n)]
        print('    u nodo %d [mm]: %.2f / %.2f / %.2f' % (n, 1000 * u[0], 1000 * u[1], 1000 * u[2]))
    print('    Demanda (extremo %s): P %.1f kN, M %.1f kN m; Mn(P) %.1f kN m; u = M/Mn %.3f %s'
          % (app['extremo'], app['P'], app['M'], app['Mn'], app['u'], 'PASA' if app['pasa'] else 'NO PASA'))
    print('    %s' % e['tag_opensees'])
    print('  (esfuerzos internos de los resultados: N = -f[0], asi que la compresion sale negativa en el panel')
    print('   y positiva como P de la demanda: %.1f y %.1f son el mismo axial)' % (s['N'][0], app['P']))


def traza(inf, modelo=None, ar=None):
    """
    La columna donde va el marcador, del modelo al telefono: [traza 3] a
    [traza 5]. La traza no empieza en la lamina: el edificio es un dato
    congelado (entrada/edificio.json) y los planos no son parte del
    programa. De que pilar del plano sale esta columna lo dicen
    supuestos.calce del edificio y el _elemento_por_que del bloque "ar" de
    laboratorio.json.
    """
    modelo = modelo if modelo is not None else _ed.estructura()
    ar = ar if ar is not None else leer_app()
    eid = int(ar['objetivo'])
    antes = len(inf.fallas)
    print()
    print('=' * 78)
    print('  LA COLUMNA %d, DEL MODELO AL TELEFONO' % eid)
    print('=' * 78)
    print('  app  %s (%s)' % (rel(AR_JSON), ar['info']['resultados_de']))
    nombre, f_sup = traza_opensees(inf, modelo, ar, eid)
    app = traza_demanda(inf, ar, nombre, f_sup, eid)
    traza_panel(ar, nombre, app, eid)
    print()
    print('=' * 78)
    if len(inf.fallas) > antes:
        print('  FALLA: %d' % (len(inf.fallas) - antes))
    else:
        print('  LA COLUMNA %d DE LA APP TIENE LOS NUMEROS DE OPENSEES' % eid)
        print('  (que calce con la columna FISICA en obra no se ha comprobado: falta el iPhone en sitio)')
    print('=' * 78)


# ============================================================
# LOS BLOQUES
# ============================================================
def ids_resultados_pose(inf, args=None):
    print('=' * 78)
    print('  LA APP DE AR, CRITERIO POR CRITERIO')
    print('=' * 78)
    ar = leer_app()
    modelo = _ed.estructura()
    anexo, de_donde = exar.resultados_del_laboratorio()
    print('  app        %s (%s, elemento %d, %d elementos)' % (rel(AR_JSON), ar['info']['edificio'],
                                                             ar['objetivo'], len(ar['elementos'])))
    print('  resultados %s' % de_donde)
    antes = len(inf.fallas)
    bloque_ids(ar, modelo, anexo, inf)
    bloque_resultados(ar, anexo, inf)
    bloque_pose(ar, modelo, inf)
    print()
    print('=' * 78)
    if len(inf.fallas) > antes:
        print('  NO CALZA (%d)' % (len(inf.fallas) - antes))
    else:
        print('  MISMO ELEMENTO Y MISMOS NUMEROS DE OPENSEES; POSE BIEN DEFINIDA ([3b] y [4]: registro_y_tracking)')
    print('=' * 78)
    traza(inf, modelo, ar)


def registro_y_tracking(inf, args=None):
    print('=' * 78)
    print('  LA APP DE AR EN UN NAVEGADOR: REGISTRO Y TRACKING')
    print('=' * 78)
    ar = leer_app()
    print('  app       %s (%s, elemento %d, %d nodos)' % (rel(AR_JSON), ar['info']['edificio'],
                                                        ar['objetivo'], len(ar['nodos'])))
    antes = len(inf.fallas)
    nav = servir.buscar_navegador()
    if not inf.check(nav is not None, 'hay Chrome o Edge para correr ar.js'):
        return
    srv = servir.levantar(PUERTO)
    try:
        consola = navegador(nav, 'index.html?prueba=1', 40, esperar='AR_TRANSFORM')
        errores = [l for l in consola if 'Uncaught' in l or 'Error' in l]
        inf.check(not errores, 'ar.js carga sin errores de JavaScript', errores[:3])
        transformacion = bloque_transformacion(ar, consola, inf)
        fov, medidas = bloque_tracking(ar, nav, inf)
    finally:
        servir.cerrar(srv)
    sano = len(inf.fallas) == antes
    registro = {
        '_que_es': ('Lo que midio python -m verificacion.ar registro_y_tracking: [3b] la transformacion de '
                    'ar.js contra la de Python y [4] el tracking con un video sintetico de pose conocida. Lo '
                    'lee el bloque precision. No se regenera con sap.py preparar: se vuelve a medir corriendo '
                    'ese bloque (necesita Chrome o Edge).'),
        '_digitos': ('distancia_m, error_mm, ancho_px, ejes_deg... van con los digitos con que [4] los informa '
                     '(los que usa el presupuesto de precision); sin_redondear trae los de la corrida.'),
        'medido': datetime.datetime.now().isoformat(timespec='seconds'),
        'navegador': os.path.basename(nav),
        'fov_mindar_grados': fov,
        'video_px': [W_VIDEO, H_VIDEO],
        'marcador_png_md5': md5(MARCADOR),
        'targets_mind_md5': md5(TARGETS) if os.path.isfile(TARGETS) else None,
        'transformacion': transformacion,
        'poses': medidas,
        'completa': len(medidas) == 3,
        'ok': sano,
    }
    texto = json.dumps(registro, ensure_ascii=False, indent=1)
    rutas.escribir_atomico(TRACKING, texto.encode('utf-8'))
    print()
    print('=' * 78)
    if sano:
        print('  LA APP DE AR, EN UN NAVEGADOR, TRANSFORMA COMO PYTHON Y RECUPERA LA POSE DE LA IMAGEN: '
              'BIEN REGISTRADA')
    else:
        print('  NO CALZA (%d)' % (len(inf.fallas) - antes))
    print('  medido en %s' % rel(TRACKING))
    print('=' * 78)


# ============================================================
# PRECISION DEL REGISTRO
# ============================================================
# Nodos sobre la mesa para la prueba de la regla (sector de la columna
# 200037; si el marcador va en otro elemento, se avisa y se saltan).
REGLA = (200064, 200078)

# SUPUESTOS de este presupuesto (no son mediciones: la prueba [5] los mide)
IMPRESION = 0.01        # la impresora achica o agranda un 1 % (19.8 cm en vez de 20.0)
COLOCACION_M = 0.005    # la imagen pegada 5 mm corrida
COLOCACION_GRADOS = 1.0 # y girada 1 grado en su plano
SESGOS_M = (0.05, 0.10) # nivel del nodo contra el piso terminado: 5 a 10 cm
                        # (la cota -0.05 es un nivel de losa de 15 cm de
                        # espesor; el piso terminado no esta en el modelo)

# Donde se para quien mira en sitio para ver la columna entera.
DIST_SITIO = 1.5
# La pantalla del iPhone 16 (vertical): 1179 x 2556 px, 460 ppi.
PANTALLA = (1179, 2556)
PPI = 460.0


def rot(eje, grados):
    """Rotacion de Rodrigues alrededor de un eje (no hace falta unitario)."""
    a = math.radians(grados)
    e = np.asarray(eje, float)
    e = e / np.linalg.norm(e)
    K = np.array([[0, -e[2], e[1]], [e[2], 0, -e[0]], [-e[1], e[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K


def cargar_precision():
    ar = leer_app()
    m = ar['marcador']
    poses = {'sitio': {'centro': m['centro'], 'ejes': m['ejes'], 'ancho_m': m['ancho_m']},
             'maqueta': {'centro': m['maqueta']['centro'], 'ejes': m['maqueta']['ejes'],
                         'ancho_m': m['ancho_m']}}
    nodos = {int(n['id']): [n['x'], n['y'], n['z']] for n in ar['nodos']}
    # La base y el techo de la columna del marcador: sus dos nodos, por cota.
    obj = next(e for e in ar['elementos'] if e['id'] == ar['objetivo'])
    base, techo = sorted((int(obj['n1']), int(obj['n2'])), key=lambda i: nodos[i][2])
    escalas = {modo: ar['modos'][modo]['escala'] for modo in ('sitio', 'maqueta')}
    return ar, poses, nodos, base, techo, escalas


def dibujado(nodos, pose, escala):
    """Cada nodo en el sistema de la imagen, en METROS DEL DIBUJO: el
    anchor de MindAR (1 = el ancho impreso) por el ancho impreso."""
    return {i: np.array(exar.a_anchor(p, pose, escala)) * pose['ancho_m']
            for i, p in nodos.items()}


def tracking_medido():
    """El error de pose de registro_y_tracking [4], de verificacion/registros/ar_tracking.json."""
    if not os.path.isfile(TRACKING):
        raise SystemExit('falta %s: correr  python -m verificacion.ar registro_y_tracking  (necesita '
                         'Chrome o Edge)' % rel(TRACKING))
    d = leer(TRACKING)
    if not (d.get('completa') and d.get('ok')):
        raise SystemExit('%s no es una corrida completa y sana de registro_y_tracking' % rel(TRACKING))
    dist = [(p['verdad_m'], p['distancia_m'], p['verdad_m'], p['error_mm'], p['ancho_px']) for p in d['poses']]
    ejes = [p['ejes_deg'] for p in d['poses']]
    if not dist or len(dist) != len(ejes):
        raise SystemExit('no se pudo leer el bloque [4] de %s' % rel(TRACKING))
    return {'poses': dist, 'ejes': ejes,
            'grados': max(ejes),
            'escala': max(x[3] / 1000.0 / x[2] for x in dist),
            'px': (min(x[4] for x in dist), max(x[4] for x in dist))}


def fuentes(q, modo, trk):
    r"""
    Corrimiento de un punto dibujado en q (m, sistema de la imagen) por
    cada fuente. Las de escala valen eps * |q|: si MindAR estima la
    distancia un eps de mas, dibuja el modelo como si fuera un eps mas
    chico alrededor del centro de la imagen (la proyeccion no cambia al
    escalar todo), y lo mismo pasa si la imagen impresa es un eps mas
    chica de lo declarado.
    """
    r = float(np.linalg.norm(q))
    angulo = max(float(np.linalg.norm(rot(e, trk['grados']) @ q - q))
                 for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    f = [('tracking, angulo (%.1f grados)' % trk['grados'], angulo),
         ('tracking, distancia (%.2f %%)' % (100 * trk['escala']), trk['escala'] * r),
         ('impresion (%.0f %%, supuesto)' % (100 * IMPRESION), IMPRESION * r)]
    if modo == 'sitio':
        f += [('colocacion, corrimiento (%.0f mm, supuesto)' % (1000 * COLOCACION_M), COLOCACION_M),
              ('colocacion, giro (%.0f grado, supuesto)' % COLOCACION_GRADOS,
               float(np.linalg.norm(rot((0, 0, 1), COLOCACION_GRADOS) @ q - q)))]
    return f


def presupuesto(nodos, poses, trk, base, techo, escalas):
    unidad = {'sitio': (100.0, 'cm'), 'maqueta': (1000.0, 'mm')}
    res = {}
    for modo in ('sitio', 'maqueta'):
        q = dibujado(nodos, poses[modo], escalas[modo])
        lejos = max(q, key=lambda i: np.linalg.norm(q[i]))
        k, u = unidad[modo]
        titulo('[1] BRAZO, %s (escala %g): distancia al centro de la imagen, dibujada'
               % (modo.upper(), escalas[modo]))
        for i, que in ((base, 'base de la columna'), (techo, 'techo de la columna'),
                       (lejos, 'el mas lejano del sector')):
            print('  nodo %d (%s): q = (%s) m, |q| = %.4f m'
                  % (i, que, ', '.join('%.3f' % v for v in q[i]), np.linalg.norm(q[i])))

        titulo('[2] FUENTES y [3] PRESUPUESTO, %s (en %s)' % (modo.upper(), u))
        filas = {}
        for i in (techo, lejos):
            filas[i] = fuentes(q[i], modo, trk)
        print('  %-44s %12s %12s' % ('fuente', 'nodo %d' % techo, 'nodo %d' % lejos))
        for j, (nombre, _v) in enumerate(filas[techo]):
            print('  %-44s %12.2f %12.2f' % (nombre, k * filas[techo][j][1], k * filas[lejos][j][1]))
        out = {}
        for i in (techo, lejos):
            v = [x for _n, x in filas[i]]
            rss, peor = math.sqrt(sum(x * x for x in v)), sum(v)
            out[i] = {'rss': rss, 'peor': peor, 'r': float(np.linalg.norm(q[i]))}
        print('  %-44s %12.2f %12.2f' % ('suma cuadratica (RSS)', k * out[techo]['rss'], k * out[lejos]['rss']))
        print('  %-44s %12.2f %12.2f' % ('peor caso (suma directa)', k * out[techo]['peor'], k * out[lejos]['peor']))
        if modo == 'sitio':
            # EXTRAPOLACION, no medicion: en el ensayo la camara estaba a
            # 0.45-0.60 m; en sitio, a DIST_SITIO. Con la misma camara la
            # imagen se ve d_ensayo / DIST_SITIO veces mas chica, y el error
            # de angulo de un ajuste de pose crece como 1 / (tamano en px).
            extra = max(g * DIST_SITIO / d for (d, *_r), g in zip(trk['poses'], trk['ejes']))
            menor = min(g * DIST_SITIO / d for (d, *_r), g in zip(trk['poses'], trk['ejes']))
            print('  %-44s %12s %12s' % ('EXTRAPOLADO a %.1f m (no medido): angulo' % DIST_SITIO,
                                         '%.1f-%.1f' % (k * out[techo]['r'] * math.radians(menor),
                                                        k * out[techo]['r'] * math.radians(extra)),
                                         '%.1f-%.1f' % (k * out[lejos]['r'] * math.radians(menor),
                                                        k * out[lejos]['r'] * math.radians(extra))))
            print('  %-44s %12s' % ('  (%.1f a %.1f grados en vez de %.1f)' % (menor, extra, trk['grados']), ''))
            for s in SESGOS_M:
                print('  %-44s %12.2f %12.2f'
                      % ('RSS con sesgo de nivel de %.0f cm' % (100 * s),
                         k * math.hypot(out[techo]['rss'], s), k * math.hypot(out[lejos]['rss'], s)))
                print('  %-44s %12.2f %12.2f'
                      % ('peor caso con sesgo de %.0f cm' % (100 * s),
                         k * (out[techo]['peor'] + s), k * (out[lejos]['peor'] + s)))
        res[modo] = {'q': q, 'lejos': lejos, 'out': out}
    return res


def proyectar(f, X):
    W, H = PANTALLA
    u = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1.0]]) @ X
    return u[:2] / u[2]


def escenario(modo, dist, grados):
    """(R, t): del sistema de la imagen (m) a la camara (x derecha, y
    abajo, z adelante), para una camara a 'dist' del centro de la imagen."""
    if modo == 'sitio':
        # de frente a la cara de la columna, a la altura del centro de la
        # imagen, levantada 'grados' para ver el techo
        C = np.array([0.0, 0.0, dist])
        zc = np.array([0.0, math.sin(math.radians(grados)), -math.cos(math.radians(grados))])
        xc = np.array([1.0, 0.0, 0.0])
    else:
        # la imagen en la mesa, mirada desde arriba con 'grados' de elevacion
        el = math.radians(grados)
        C = np.array([0.0, -dist * math.cos(el), dist * math.sin(el)])
        zc = np.array([0.0, 0.0, 0.04]) - C
        zc /= np.linalg.norm(zc)
        xc = np.cross(zc, [0.0, 0.0, 1.0])
        xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    R = np.vstack([xc, yc, zc])
    return R, -R @ C


def rejilla(ancho, n=9):
    """Puntos de la imagen impresa, con la proporcion de ar/web/marcador.png (1000 x 1010 px)."""
    from PIL import Image
    with Image.open(MARCADOR) as im:
        ancho_px, alto_px = im.size
    alto = ancho * alto_px / ancho_px
    return [np.array([x, y, 0.0]) for x in np.linspace(-ancho / 2, ancho / 2, n)
            for y in np.linspace(-alto / 2, alto / 2, n)]


def ajustar_pose(f, uv, Q, R0, t0, iteraciones=80):
    r"""
    La pose que minimiza la reproyeccion de los puntos de la imagen con
    la focal f: es lo que hace MindAR con SU focal. Gauss-Newton con
    jacobiano numerico, arrancando de la pose verdadera.
    """
    def residuo(x):
        R = (rot(x[:3], math.degrees(np.linalg.norm(x[:3])))
             if np.linalg.norm(x[:3]) > 1e-15 else np.eye(3)) @ R0
        return np.concatenate([proyectar(f, R @ q + t0 + x[3:]) - u for q, u in zip(Q, uv)]), R

    x = np.zeros(6)
    for _ in range(iteraciones):
        r, _R = residuo(x)
        J = np.zeros((r.size, 6))
        for k in range(6):
            dx = np.zeros(6)
            dx[k] = 1e-7
            J[:, k] = (residuo(x + dx)[0] - r) / 1e-7
        paso = np.linalg.lstsq(J, -r, rcond=None)[0]
        x = x + paso
        if np.linalg.norm(paso) < 1e-13:
            break
    r, R = residuo(x)
    return R, t0 + x[3:], float(np.sqrt(np.mean(r ** 2)))


def error_focal(q, ancho, R, t, f_real, razon):
    """px de pantalla entre donde esta cada punto y donde lo dibuja una
    app que cree que la focal es razon * f_real."""
    Q = rejilla(ancho)
    uv = [proyectar(f_real, R @ p + t) for p in Q]
    Ra, ta, rms = ajustar_pose(f_real * razon, uv, Q, R, t * razon)
    W, H = PANTALLA
    err = {}
    for i, p in q.items():
        Xc = R @ p + t
        if Xc[2] <= 0.05:
            continue
        verdad = proyectar(f_real, Xc)
        if 0 <= verdad[0] <= W and 0 <= verdad[1] <= H:
            err[i] = float(np.linalg.norm(proyectar(f_real * razon, Ra @ p + ta) - verdad))
    return err, float(np.linalg.norm(ta) / np.linalg.norm(t)), rms


def control_focal(f_real, razon):
    r"""
    La simulacion contra la formula cerrada, de frente: un punto a X en
    el plano de la imagen y n detras de el, con la camara a d. La app
    estima la distancia como razon * d y dibuja el punto en
    f X / (d + n / razon); de verdad esta en f X / (d + n).
    """
    d, X, n = 1.5, 0.30, 0.35
    R = np.array([[1.0, 0, 0], [0, -1.0, 0], [0, 0, -1.0]])
    t = np.array([0.0, 0.0, d])
    err, _dist, _rms = error_focal({1: np.array([0.0, X, -n])}, 0.20, R, t, f_real, razon)
    formula = f_real * X * abs(1.0 / (d + n / razon) - 1.0 / (d + n))
    return err[1], formula


def focal(res, poses, fov, fov_mindar, techo, inf):
    titulo('[4] FOCAL: MindAR supone %.0f grados de campo vertical; el iPhone, %.0f en el '
           'lado largo (SUPUESTO)' % (fov_mindar, fov))
    W, H = PANTALLA
    f_real = (H / 2) / math.tan(math.radians(fov / 2))
    corto = 2 * math.degrees(math.atan(math.tan(math.radians(fov / 2)) * W / H))
    # El alto del video es el lado largo si el video viene vertical, o el
    # corto (4:3) si viene apaisado: MindAR pone su campo en el alto.
    fov_43 = 2 * math.degrees(math.atan(math.tan(math.radians(fov / 2)) * 0.75))
    razones = [('video apaisado (alto = lado corto, %.1f grados)' % fov_43,
                math.tan(math.radians(fov_43 / 2)) / math.tan(math.radians(fov_mindar / 2))),
               ('video vertical (alto = lado largo, %.0f grados)' % fov,
                math.tan(math.radians(fov / 2)) / math.tan(math.radians(fov_mindar / 2)))]
    print('  pantalla %d x %d px, %.0f ppi: f = %.1f px; el lado corto ve %.1f grados'
          % (W, H, PPI, f_real, corto))
    s, formula = control_focal(f_real, razones[0][1])
    inf.check(abs(s - formula) <= 1e-6 * max(formula, 1.0),
              'control: de frente, simulacion %.3f px = formula cerrada %.3f px' % (s, formula))
    salida = {}
    for modo, dist, grados in (('sitio', DIST_SITIO, 25.0), ('maqueta', 0.5, 45.0)):
        q = res[modo]['q']
        R, t = escenario(modo, dist, grados)
        print('  %s: camara a %.2f m del centro de la imagen, %g grados' % (modo, dist, grados))
        for nombre, razon in razones:
            err, dist_app, rms = error_focal(q, poses[modo]['ancho_m'], R, t, f_real, razon)
            peor = max(err, key=err.get)
            texto_techo = ('%.1f px' % err[techo]) if techo in err else 'fuera de cuadro'
            print('    f_MindAR / f_real = %.3f, %s:' % (razon, nombre))
            print('      techo %d: %s; peor visible %.1f px (nodo %d) = %.1f mm de pantalla; '
                  'la app dice %.3f veces la distancia real (ajuste rms %.2f px)'
                  % (techo, texto_techo, err[peor], peor, err[peor] * 25.4 / PPI, dist_app, rms))
            salida.setdefault(modo, []).append((razon, err.get(techo), err[peor], peor, dist_app))
    return salida


def prueba(res, razones_focal, base, techo):
    titulo('[5] PRUEBA EN EL iPHONE: lo que hay que medir y lo que tiene que dar')
    qm = res['maqueta']['q']
    print('  a) FOCAL, con una cinta: el telefono de frente a la imagen a 30, 50 y 80 cm; la barra')
    print('     "pose:" tiene que decir lo mismo que la cinta. Si dice %s veces lo medido, la'
          % ' o '.join('%.2f' % r for r in razones_focal))
    print('     fila [4] se confirma y esa razon es la correccion.')
    print('  b) TEMBLOR: el telefono apoyado 10 s, grabando la pantalla; la dispersion de "pose:".')
    print('  c) MAQUETA, con una regla, desde el centro de la imagen (en el plano de la mesa):')
    for i in REGLA:
        if i in qm:
            print('     nodo %d: x = %.1f cm, y = %.1f cm (z = %.2f cm: sobre la mesa, sin paralaje)'
                  % (i, 100 * qm[i][0], 100 * qm[i][1], 100 * qm[i][2]))
        else:
            print('     nodo %d: no esta en el sector de este marcador (elegir otros nodos sobre la mesa)' % i)
    print('     y con una regla VERTICAL (la unica que ve la focal): el techo %d a %.2f cm de la mesa.'
          % (techo, 100 * qm[techo][2]))
    qs = res['sitio']['q']
    print('  d) SITIO: confirmar primero en obra cual es la columna (entrada/laboratorio.json, ar._elemento_por_que);')
    print('     cinta en las dos aristas de la cara +x a 0.5, 1.0 y 2.0 m sobre el centro de la imagen;')
    print('     la caja dibujada (0.70 m) tiene que calzar con ellas. La base dibujada esta %.2f m bajo'
          % -qs[base][1])
    print('     el centro de la imagen: la distancia entre esa base y el piso real es el sesgo de nivel.')


def precision(inf, args=None):
    fov = getattr(args, 'fov', 70.0) if args is not None else 70.0
    print('=' * 78)
    print('  PRECISION DEL REGISTRO DE LA AR (estimacion simple)')
    print('=' * 78)
    ar, poses, nodos, base, techo, escalas = cargar_precision()
    trk = tracking_medido()
    # La camara de la app, leida de MindAR: solo se dice algo si no se puede leer.
    fov_mindar, de_donde = fov_de_mindar()
    if fov_mindar is None:
        inf.check(False, 'la camara que supone MindAR, leida de su codigo (%s)' % rel(de_donde))
        return
    print('  app       %s (%s, elemento %d, %d nodos)'
          % (rel(AR_JSON), ar['info']['edificio'], ar['marcador']['elemento'], len(nodos)))
    print('  tracking  %s, bloque [4]: VIDEO SINTETICO con la camara que supone MindAR,' % rel(TRACKING))
    for (d, est, verdad, e_mm, px), grados in zip(trk['poses'], trk['ejes']):
        print('            a %.2f m: distancia %.3f m (error %.1f mm), ejes a %.1f grados, imagen de %d px'
              % (d, est, e_mm, grados, px))
    print('            -> se usa el peor: %.1f grados y %.2f %% de la distancia'
          % (trk['grados'], 100 * trk['escala']))
    res = presupuesto(nodos, poses, trk, base, techo, escalas)
    focales = focal(res, poses, fov, fov_mindar, techo, inf)
    prueba(res, [x[0] for x in focales['sitio']], base, techo)
    print()
    print('=' * 78)
    s, m = res['sitio']['out'], res['maqueta']['out']
    print('  SITIO:   techo de la columna %.1f cm RSS (%.1f cm con 5 cm de sesgo de nivel); nodo %d a %.1f m: %.1f cm'
          % (100 * s[techo]['rss'], 100 * math.hypot(s[techo]['rss'], SESGOS_M[0]),
             res['sitio']['lejos'], s[res['sitio']['lejos']]['r'], 100 * s[res['sitio']['lejos']]['rss']))
    print('  MAQUETA: techo de la columna %.1f mm RSS; nodo %d a %.1f cm: %.1f mm'
          % (1000 * m[techo]['rss'], res['maqueta']['lejos'], 100 * m[res['maqueta']['lejos']]['r'],
             1000 * m[res['maqueta']['lejos']]['rss']))
    print('  SIN la focal [4] y SIN confirmar la columna en obra. Nada de esto se midio en un iPhone.')
    print('=' * 78)


# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m verificacion.ar',
                                 description='La app de AR: tags, resultados, pose, registro, tracking y precision')
    ap.add_argument('bloques', nargs='*', metavar='bloque',
                    help='%s (sin bloque: los tres)' % ', '.join(BLOQUES))
    ap.add_argument('--fov', type=float, default=70.0,
                    help='precision: campo de vision del iPhone en el lado largo, en grados (supuesto)')
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    malos = [b for b in a.bloques if b not in BLOQUES]
    if malos:
        ap.error('bloque desconocido: %s (son: %s)' % (', '.join(malos), ', '.join(BLOQUES)))
    hacer = {'ids_resultados_pose': ids_resultados_pose, 'registro_y_tracking': registro_y_tracking,
             'precision': precision}
    inf = Informe()
    for b in (a.bloques or BLOQUES):
        try:
            hacer[b](inf, a)
        except SystemExit as e:
            # Un bloque que no puede ni empezar (falta ar.json, el puerto esta
            # tomado, no hay medicion de tracking) es una FALLA con su motivo,
            # y los demas bloques igual corren.
            if not isinstance(e.code, str):
                raise
            inf.check(False, '%s: %s' % (b, e.code))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
