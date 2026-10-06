# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/relieve.py  -  EL RELIEVE DEL SITIO, PARA EL VISOR
================================================================
 Arma la malla del terreno alrededor del edificio y la deja en
 salidas/relieve.json. Unity solo la dibuja (AmbienteVisor, capa
 "Relieve del sitio"): nada de esto cambia un resultado estructural.

 Entradas (entrada/sitio/, con sus supuestos en sitio.json):
   topo_uandes.kmz              la ZONA, trazada en Google Earth
   techo_edificio_antiguo.kmz   el techo del cuerpo antiguo en la foto
   dem_copernicus_glo30.json    las COTAS (bajar_dem(), una sola vez)

 ----------------------------------------------------------------
 COMO SE UBICA
 ----------------------------------------------------------------
 1. Lat/lon -> metros: este y norte locales alrededor del centro del
    techo, con los radios del elipsoide WGS84 en esa latitud. En 300 m
    el error de esta proyeccion es de milimetros.
 2. El giro: el lado largo del techo en la foto tiene un rumbo; +x del
    modelo va en ese rumbo (sitio.json dice hacia que extremo, y aca se
    comprueba con la pendiente del terreno).
 3. La posicion: el centro del techo de la foto cae en el centro del
    rectangulo del techo del modelo (sitio.json, 'techo_en_el_modelo').
 4. La cota: el DEM se corre en vertical por minimos cuadrados para que
    el terreno calce con los apoyos en terreno del modelo.
 Con eso cada punto (x, y) del modelo tiene su lat/lon, y su cota sale
 del DEM por interpolacion bilineal.

 El relieve no se dibuja sobre la planta de cada cuerpo mas un margen
 (los 'huecos': ahi esta la excavacion, que la dibujan el suelo y las
 terrazas). Hay uno por cuerpo, y el cuerpo de cada nodo lo dice su tag
 (edificio.cuerpo_de).

 ----------------------------------------------------------------
 QUE COMPRUEBA (si algo falla, NO escribe y termina con 1)
 ----------------------------------------------------------------
   - el techo de la foto tiene el tamano del techo del modelo (mas el
     borde de la losa), y sus lados largos son paralelos;
   - el terreno sube hacia +x a lo largo del edificio, como las terrazas
     del modelo (si no, el giro esta 180 grados al reves);
   - cada apoyo en terreno cae dentro del DEM;
   - con --verificar, que salidas/relieve.json sea el que se arma ahora.

 El relieve lleva la HUELLA del modelo (cuantos nodos y elementos): el
 visor la compara al cargar y no dibuja un relieve armado para otro
 modelo. Que cada clave tenga su campo en el C# lo comprueba la
 verificacion del contrato con Unity.

   python sap.py exportar relieve                # escribe salidas/relieve.json
   python sap.py exportar relieve --verificar    # no escribe: compara
   python sap.py exportar relieve --figura       # + salidas/figuras/relieve_planta.png
   python sap.py exportar relieve --bajar-dem    # vuelve a bajar el DEM (internet, requests)
================================================================
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import math
import os
import re
import struct
import sys
import zipfile
import zlib

import numpy as np

from calculo import edificio as _ed
from calculo import rutas

FIGURA = os.path.join(rutas.FIGURAS, 'relieve_planta.png')
SIN_DATO = -9999.0
# WGS84
A_WGS = 6378137.0
E2_WGS = 6.69437999014e-3
# El trazo de Google Earth es el techo del cuerpo antiguo (el LT2 todavia
# no aparece en las imagenes, sitio.json): sus nodos son los que tienen que
# calzar con el rectangulo declarado y los que dan la pendiente a lo largo.
CUERPO_DEL_TECHO = 'ingenieria'
ATRIBUCION = ('Copernicus DEM GLO-30: (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space '
              'GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights '
              'reserved.')


def leer_json(ruta):
    with io.open(ruta, encoding='utf-8') as fh:
        return json.load(fh)


def rel(ruta):
    return rutas.relativa(ruta).replace(os.sep, '/')


class Fallas(object):
    def __init__(self):
        self.lista = []

    def check(self, ok, que):
        print('  [%s] %s' % ('OK  ' if ok else 'FALLA', que))
        if not ok:
            self.lista.append(que)
        return ok


# ============================================================
# KMZ de Google Earth
# ============================================================
def leer_kmz(ruta):
    """{'poligonos': [[(lon, lat), ...]], 'lineas': [[(lon, lat), ...]]} del
    primer doc.kml del KMZ. Las alturas se descartan: Google Earth las deja
    en 0 en un trazo pegado al terreno."""
    with zipfile.ZipFile(ruta) as z:
        kml = next(n for n in z.namelist() if n.lower().endswith('.kml'))
        texto = z.read(kml).decode('utf-8')

    def coords(bloque):
        c = re.search(r'<coordinates>(.*?)</coordinates>', bloque, re.S).group(1).split()
        return [tuple(float(v) for v in p.split(',')[:2]) for p in c]

    poligonos = [coords(b) for b in re.findall(r'<Polygon>(.*?)</Polygon>', texto, re.S)]
    lineas = [coords(b) for b in re.findall(r'<LineString>(.*?)</LineString>', texto, re.S)]
    return {'poligonos': poligonos, 'lineas': lineas}


# ============================================================
# Lat/lon <-> metros locales
# ============================================================
class Local(object):
    """Este/norte en metros alrededor de (lon0, lat0), con los radios de
    curvatura del elipsoide en lat0 (meridiano M y primer vertical N)."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        s = math.sin(math.radians(lat0))
        w = math.sqrt(1.0 - E2_WGS * s * s)
        self.M = A_WGS * (1.0 - E2_WGS) / w ** 3
        self.N = A_WGS / w
        self.cos0 = math.cos(math.radians(lat0))

    def a_metros(self, lon, lat):
        return (math.radians(lon - self.lon0) * self.N * self.cos0,
                math.radians(lat - self.lat0) * self.M)

    def a_grados(self, e, n):
        return (self.lon0 + math.degrees(e / (self.N * self.cos0)),
                self.lat0 + math.degrees(n / self.M))


def rumbo(de, a):
    """Azimut en grados (desde el norte, hacia el este) del vector de -> a."""
    return math.degrees(math.atan2(a[0] - de[0], a[1] - de[1])) % 360.0


# ============================================================
# La georreferencia: modelo (x, y) <-> metros locales (e, n)
# ============================================================
class Georreferencia(object):
    r"""
    e = e_c + cos(t)·(x - x_c) - sin(t)·(y - y_c)      t = 90 - rumbo de +x
    n = n_c + sin(t)·(x - x_c) + cos(t)·(y - y_c)
    con (x_c, y_c) el centro del techo en el modelo y (e_c, n_c) el de la
    foto. Sin escala: el modelo y Google Earth estan en metros.
    """

    def __init__(self, rumbo_x, centro_modelo, centro_local, local):
        self.rumbo_x = rumbo_x
        self.t = math.radians(90.0 - rumbo_x)
        self.xc, self.yc = centro_modelo
        self.ec, self.nc = centro_local
        self.local = local

    def a_local(self, x, y):
        c, s = math.cos(self.t), math.sin(self.t)
        dx, dy = x - self.xc, y - self.yc
        return self.ec + c * dx - s * dy, self.nc + s * dx + c * dy

    def a_modelo(self, e, n):
        c, s = math.cos(self.t), math.sin(self.t)
        de, dn = e - self.ec, n - self.nc
        return self.xc + c * de + s * dn, self.yc - s * de + c * dn

    def lonlat(self, x, y):
        return self.local.a_grados(*self.a_local(x, y))


class Dem(object):
    """El DEM de la ventana, con interpolacion bilineal en lon/lat."""

    def __init__(self, d):
        self.lon = np.array(d['lon'])
        self.lat = np.array(d['lat'])            # de norte a sur
        self.z = np.array(d['z'])
        self.d = d

    def cota(self, lon, lat):
        fi = (lon - self.lon[0]) / (self.lon[1] - self.lon[0])
        fj = (lat - self.lat[0]) / (self.lat[1] - self.lat[0])
        if not (0 <= fi <= len(self.lon) - 1 and 0 <= fj <= len(self.lat) - 1):
            return None
        i, j = min(int(fi), len(self.lon) - 2), min(int(fj), len(self.lat) - 2)
        u, v = fi - i, fj - j
        z = self.z
        return ((1 - u) * (1 - v) * z[j, i] + u * (1 - v) * z[j, i + 1]
                + (1 - u) * v * z[j + 1, i] + u * v * z[j + 1, i + 1])


# ============================================================
def envolvente(puntos):
    """Envolvente convexa (cadena monotona), antihoraria."""
    p = sorted(set(puntos))
    if len(p) < 3:
        return p

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    abajo, arriba = [], []
    for q in p:
        while len(abajo) >= 2 and cruz(abajo[-2], abajo[-1], q) <= 0:
            abajo.pop()
        abajo.append(q)
    for q in reversed(p):
        while len(arriba) >= 2 and cruz(arriba[-2], arriba[-1], q) <= 0:
            arriba.pop()
        arriba.append(q)
    return abajo[:-1] + arriba[:-1]


def dentro(pto, poli):
    """Punto en poligono convexo antihorario."""
    x, y = pto
    for a, b in zip(poli, poli[1:] + poli[:1]):
        if (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) < -1e-9:
            return False
    return True


def nodos_por_cuerpo(modelo):
    """
    {cuerpo: nodos} sin los auxiliares (los maestros de diafragma no son
    planta), con el cuerpo que dice el tag de cada nodo y en el orden de
    los tags (1xxxxx antes que 2xxxxx).
    """
    out = {}
    for n in modelo['nodos']:
        if n.get('auxiliar'):
            continue
        out.setdefault(_ed.cuerpo_de(n['id']), []).append(n)
    return dict(sorted(out.items(), key=lambda kv: min(int(n['id']) for n in kv[1])))


def armar(fallas, modelo=None):
    perfil = leer_json(os.path.join(rutas.SITIO, 'sitio.json'))
    techo_foto = leer_kmz(os.path.join(rutas.SITIO, perfil['techo']))['poligonos'][0]
    recorrido = leer_kmz(os.path.join(rutas.SITIO, perfil['recorrido']))['lineas'][0]
    dem = Dem(leer_json(os.path.join(rutas.SITIO, perfil['dem'])))
    conj = modelo if modelo is not None else _ed.estructura()

    # --- 1. la foto en metros locales, alrededor del centro del techo
    esquinas = techo_foto[:-1] if techo_foto[0] == techo_foto[-1] else techo_foto
    lon0 = sum(p[0] for p in esquinas) / len(esquinas)
    lat0 = sum(p[1] for p in esquinas) / len(esquinas)
    local = Local(lon0, lat0)
    E = [local.a_metros(*p) for p in esquinas]
    lados = [(E[k], E[(k + 1) % 4]) for k in range(4)]
    largos = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in lados]
    k_largo = 0 if largos[0] + largos[2] > largos[1] + largos[3] else 1
    # Rumbo del lado largo, promediando los dos lados opuestos como vectores
    # (el segundo da vuelta: va en sentido contrario en el poligono).
    rs = [rumbo(*lados[k_largo]), (rumbo(*lados[k_largo + 2]) + 180.0) % 360.0]
    vx = sum(math.sin(math.radians(r)) for r in rs)
    vy = sum(math.cos(math.radians(r)) for r in rs)
    r_largo = math.degrees(math.atan2(vx, vy)) % 360.0
    # Hacia que extremo apunta +x: el declarado en sitio.json.
    hacia = {'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5, 'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5,
             'S': 180, 'SSO': 202.5, 'SO': 225, 'OSO': 247.5, 'O': 270, 'ONO': 292.5, 'NO': 315,
             'NNO': 337.5}[perfil['x_del_modelo_hacia']]
    if math.cos(math.radians(r_largo - hacia)) < 0:
        r_largo = (r_largo + 180.0) % 360.0
    largo_foto = 0.5 * (largos[k_largo] + largos[k_largo + 2])
    ancho_foto = 0.5 * (largos[1 - k_largo] + largos[3 - k_largo])
    paralelo = abs(((rs[0] - rs[1] + 90) % 180) - 90)

    tm = perfil['techo_en_el_modelo']
    print('  techo en la foto: %.2f x %.2f m, lado largo a %.1f grados (los dos lados a %.1f grados '
          'entre si)' % (largo_foto, ancho_foto, r_largo, paralelo))
    print('  techo en el modelo, entre ejes: %.2f x %.2f m' % (tm['x'][1] - tm['x'][0], tm['y'][1] - tm['y'][0]))
    # El rectangulo declarado tiene que existir en el modelo: nodos del
    # cuerpo antiguo en esa z sobre sus cuatro bordes.
    cuerpos = nodos_por_cuerpo(conj)
    techo_nodos = [n for n in cuerpos[CUERPO_DEL_TECHO] if abs(n['z'] - tm['z']) < 0.01]
    bordes = [any(abs(n[c] - v) < 0.01 for n in techo_nodos) for c, v in
              (('x', tm['x'][0]), ('x', tm['x'][1]), ('y', tm['y'][0]), ('y', tm['y'][1]))]
    fallas.check(all(bordes), 'el rectangulo del techo de sitio.json tiene nodos del cuerpo antiguo en '
                 'sus cuatro bordes, en z = %.2f' % tm['z'])
    # La foto mide por fuera de la losa: tiene que ser algo MAS grande que
    # entre ejes, en no mas que el borde de la losa y el trazo a mano.
    d_largo = largo_foto - (tm['x'][1] - tm['x'][0])
    d_ancho = ancho_foto - (tm['y'][1] - tm['y'][0])
    fallas.check(-0.5 <= d_largo <= 3.0 and -0.5 <= d_ancho <= 3.0 and paralelo < 3.0,
                 'el techo de la foto es el del modelo mas el borde: +%.2f m de largo y +%.2f m de ancho '
                 '(se acepta de -0.5 a +3.0 m: medio pilar 0.35 m y el borde de la losa por lado, mas el '
                 'trazo a mano sobre la foto)' % (d_largo, d_ancho))

    geo = Georreferencia(r_largo, (0.5 * (tm['x'][0] + tm['x'][1]), 0.5 * (tm['y'][0] + tm['y'][1])),
                         (0.0, 0.0), local)

    # --- 2. el terreno sube hacia +x a lo largo del edificio?
    xs = [n['x'] for n in cuerpos[CUERPO_DEL_TECHO]]
    ym = 0.5 * (tm['y'][0] + tm['y'][1])
    z_oeste = dem.cota(*geo.lonlat(min(xs), ym))
    z_este = dem.cota(*geo.lonlat(max(xs), ym))
    fallas.check(z_este > z_oeste,
                 'el terreno sube hacia +x a lo largo del cuerpo antiguo (%.1f m en x = %.1f, %.1f m en '
                 'x = %.1f), como sus terrazas: el giro no esta al reves' % (z_oeste, min(xs), z_este, max(xs)))

    # --- 3. la cota: calce vertical con los apoyos en terreno
    apoyos = [n for n in conj['nodos'] if not n.get('auxiliar') and any(n.get('restricciones') or [])]
    dif = []
    for n in apoyos:
        z = dem.cota(*geo.lonlat(n['x'], n['y']))
        if z is not None:
            dif.append(z - n['z'])
    dif = np.array(dif)
    desfase = float(dif.mean())
    resid = dif - desfase
    print('  calce vertical: cota DEM = z del modelo + %.2f m (por minimos cuadrados sobre %d apoyos); '
          'residuo: rms %.2f m, de %.2f a %.2f m' % (desfase, len(dif), float(np.sqrt((resid ** 2).mean())),
                                                    float(resid.min()), float(resid.max())))
    fallas.check(len(dif) == len(apoyos), 'los %d apoyos en terreno caen dentro del DEM' % len(apoyos))

    # --- 4. la malla, en coordenadas del edificio
    zona = envolvente([geo.a_modelo(*local.a_metros(*p)) for p in recorrido])
    paso = float(perfil['paso_m'])
    x0 = math.floor(min(p[0] for p in zona) / paso) * paso
    y0 = math.floor(min(p[1] for p in zona) / paso) * paso
    nx = int(math.ceil((max(p[0] for p in zona) - x0) / paso)) + 1
    ny = int(math.ceil((max(p[1] for p in zona) - y0) / paso)) + 1
    malla = np.full((ny, nx), SIN_DATO)
    for j in range(ny):
        for i in range(nx):
            x, y = x0 + i * paso, y0 + j * paso
            if dentro((x, y), zona):
                z = dem.cota(*geo.lonlat(x, y))
                if z is not None:
                    malla[j, i] = z - desfase
    validos = malla[malla > SIN_DATO / 2]
    print('  malla: %d x %d nodos cada %.1f m (x %.1f a %.1f, y %.1f a %.1f), %d con cota, de %.2f a %.2f m '
          'del modelo' % (nx, ny, paso, x0, x0 + (nx - 1) * paso, y0, y0 + (ny - 1) * paso, validos.size,
                          float(validos.min()), float(validos.max())))

    techo_modelo = [geo.a_modelo(*e) for e in E]
    return {'perfil': perfil, 'geo': geo, 'dem': dem, 'conj': conj, 'cuerpos': cuerpos,
            'malla': malla, 'x0': x0, 'y0': y0, 'paso': paso, 'nx': nx, 'ny': ny, 'zona': zona,
            'techo_modelo': techo_modelo, 'desfase': desfase, 'resid': resid, 'r_largo': r_largo,
            'recorrido': [geo.a_modelo(*local.a_metros(*p)) for p in recorrido]}


def construir(r, vista=None):
    """El JSON del relieve: la malla, los huecos y el techo de la foto, en coordenadas del edificio."""
    vista = vista if vista is not None else _ed.vista()
    margen = float(r['perfil']['margen_hueco_m'])
    huecos = []
    for ns in r['cuerpos'].values():
        huecos.append({'x1': round(min(n['x'] for n in ns) - margen, 3),
                       'y1': round(min(n['y'] for n in ns) - margen, 3),
                       'x2': round(max(n['x'] for n in ns) + margen, 3),
                       'y2': round(max(n['y'] for n in ns) + margen, 3)})
    cota_fondo = float(vista.get('cota_terreno', SIN_DATO))
    # El JSON del visor no trae info.edificio: Unity reconoce su modelo
    # por cuantos nodos y elementos tiene al cargarlo (la huella).
    huella = {'n_nodos': len(r['conj']['nodos']), 'n_elementos': len(r['conj']['elementos'])}
    m = r['malla']
    z = [round(float(v), 3) if v > SIN_DATO / 2 else SIN_DATO for v in m.reshape(-1)]
    g = r['geo']
    return {
        'info': {
            'edificio': _ed.NOMBRE,
            'n_nodos': huella['n_nodos'],
            'n_elementos': huella['n_elementos'],
            'generado_por': 'exportar/relieve.py',
            'fuente': r['dem'].d['fuente'],
            'atribucion': ATRIBUCION,
            'zona': 'trazada en Google Earth (entrada/sitio/%s)' % r['perfil']['recorrido'],
            'rumbo_x_grados': round(g.rumbo_x, 3),
            'lon_centro_techo': round(g.local.lon0, 8),
            'lat_centro_techo': round(g.local.lat0, 8),
            'desfase_vertical_m': round(r['desfase'], 3),
            'residuo_rms_m': round(float(np.sqrt((r['resid'] ** 2).mean())), 3),
            '_por_que': ('Solo DIBUJO: el terreno natural (Copernicus GLO-30, celda de ~30 m, anterior a la '
                         'obra) alrededor del edificio, ubicado con el techo del cuerpo antiguo en Google '
                         'Earth y calzado en vertical con los apoyos en terreno. Ningun calculo lo usa. '
                         'Supuestos: entrada/sitio/sitio.json.'),
        },
        'x0': round(r['x0'], 3),
        'y0': round(r['y0'], 3),
        'paso': r['paso'],
        'nx': r['nx'],
        'ny': r['ny'],
        'sin_dato': SIN_DATO,
        'cota_fondo': round(cota_fondo, 3),
        'z': z,
        'huecos': huecos,
        'techo_foto': [{'x': round(p[0], 3), 'y': round(p[1], 3)} for p in r['techo_modelo']],
    }


def escribir(relieve):
    """salidas/relieve.json, compacto y de una vez."""
    texto = json.dumps(relieve, ensure_ascii=False, separators=(',', ':'))
    return rutas.escribir_atomico(rutas.salida('relieve'), texto.encode('utf-8'))


def figura(r, ruta):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    m = np.where(r['malla'] > SIN_DATO / 2, r['malla'], np.nan)
    X = r['x0'] + r['paso'] * np.arange(r['nx'])
    Y = r['y0'] + r['paso'] * np.arange(r['ny'])
    fig, ax = plt.subplots(figsize=(9, 9))
    cf = ax.contourf(X, Y, m, levels=20, cmap='terrain', alpha=0.85)
    cs = ax.contour(X, Y, m, levels=np.arange(np.floor(np.nanmin(m)), np.nanmax(m) + 1, 1.0),
                    colors='k', linewidths=0.4, alpha=0.5)
    ax.clabel(cs, cs.levels[::5], fmt='%.0f', fontsize=7)
    fig.colorbar(cf, ax=ax, shrink=0.7, label='z del modelo [m] (el DEM menos %.2f m)' % r['desfase'])
    for (nombre, ns), color in zip(r['cuerpos'].items(), ('#1f3a5f', '#c8641e', '#2e7d4f')):
        ax.plot([n['x'] for n in ns], [n['y'] for n in ns], '.', ms=2, color=color,
                label='nodos del cuerpo %s' % nombre)
    t = r['techo_modelo'] + r['techo_modelo'][:1]
    ax.plot([p[0] for p in t], [p[1] for p in t], '-', color='red', lw=1.6, label='techo trazado en Google Earth')
    rc = r['recorrido']
    ax.plot([p[0] for p in rc], [p[1] for p in rc], '-', color='gray', lw=0.5, alpha=0.6,
            label='recorrido "Topo Uandes"')
    # el norte
    g = r['geo']
    cx, cy = X[-1] - 25, Y[-1] - 25
    nx_, ny_ = g.a_modelo(g.ec, g.nc + 15.0)
    bx, by = g.a_modelo(g.ec, g.nc)
    ax.annotate('N', xy=(cx + nx_ - bx, cy + ny_ - by), xytext=(cx, cy), ha='center',
                arrowprops=dict(arrowstyle='->', lw=1.5), fontsize=12, fontweight='bold')
    ax.set_aspect('equal')
    ax.set_xlabel('x del modelo [m]')
    ax.set_ylabel('y del modelo [m]')
    ax.set_title('Relieve del sitio en coordenadas del edificio\n+x del modelo a %.1f grados (rumbo); '
                 'Copernicus GLO-30' % r['r_largo'], fontsize=10)
    ax.legend(loc='lower left', fontsize=8)
    fig.tight_layout()
    fig.savefig(rutas.asegurar(ruta), dpi=110)
    plt.close(fig)


# ============================================================
# EL DEM, BAJADO UNA VEZ (opcional: necesita internet y 'requests')
# ============================================================
# El recorrido de Google Earth dice DONDE se quiere el relieve, pero no
# las cotas: Google Earth guarda un trazo pegado al terreno con altura 0
# en todos sus puntos. Las cotas salen de un modelo digital de elevacion
# publico, que se baja UNA vez y queda en entrada/sitio/ solo la ventana
# del campus (unas decenas de celdas). Despues el relieve no necesita
# internet ni librerias nuevas.
#
# LA FUENTE. Copernicus DEM GLO-30 (ESA / Airbus, datos TanDEM-X de 2011
# a 2015), una celda por segundo de arco (~31 m en N-S y ~26 m en E-O a
# esta latitud). Es un modelo de SUPERFICIE: incluye arboles y edificios
# que existian entonces, y es anterior al LT2 (planos 2024) y
# probablemente al edificio antiguo (planos 2017). Se lee del bucket
# publico de la ESA en AWS (copernicus-dem-30m), un GeoTIFF 'cloud
# optimized' por grado: se pide por HTTP solo el bloque que cubre la
# ventana.
#
# EL FORMATO, SIN GDAL. TIFF con bloques de 1024 x 1024, float32,
# compresion deflate (zlib) y predictor 3 (punto flotante, Nota Tecnica 3
# de TIFF): cada fila viene con sus bytes en planos (primero el byte mas
# significativo de todas las muestras, despues el siguiente...) y
# diferenciados uno contra el anterior. Se deshace con una suma acumulada
# modulo 256 y reordenando. La georreferencia sale de ModelTiepoint,
# ModelPixelScale y GTRasterTypeGeoKey (celda como area o como punto).
BUCKET = 'https://copernicus-dem-30m.s3.amazonaws.com'
TIPOS = {1: ('B', 1), 2: ('c', 1), 3: ('H', 2), 4: ('I', 4), 11: ('f', 4), 12: ('d', 8), 16: ('Q', 8)}


class CogRemoto(object):
    """Lo minimo de un GeoTIFF 'cloud optimized' para leer una ventana."""

    def __init__(self, url):
        try:
            import requests
        except ImportError:
            raise SystemExit("bajar el DEM necesita 'requests' (pip install requests). El DEM ya "
                             "esta en entrada/sitio/: solo hace falta para ampliar la zona.")
        self.url = url
        self.sesion = requests.Session()
        cab = self._bytes(0, 65535)
        if cab[:4] != b'II*\x00':
            raise SystemExit('%s no es un TIFF little-endian clasico' % url)
        self._cab = cab
        off = struct.unpack('<I', cab[4:8])[0]
        n = struct.unpack('<H', cab[off:off + 2])[0]
        self.tags = {}
        for k in range(n):
            e = cab[off + 2 + 12 * k: off + 14 + 12 * k]
            tag, typ, cnt = struct.unpack('<HHI', e[:8])
            fmt, tam = TIPOS[typ]
            total = tam * cnt
            datos = e[8:8 + total] if total <= 4 else self._en(struct.unpack('<I', e[8:12])[0], total)
            self.tags[tag] = (datos.decode('latin-1').rstrip('\x00') if typ == 2
                              else list(struct.unpack('<%d%s' % (cnt, fmt), datos)))
        self.ancho, self.alto = self.tags[256][0], self.tags[257][0]
        self.tw, self.th = self.tags[322][0], self.tags[323][0]
        comp, pred = self.tags[259][0], self.tags.get(317, [1])[0]
        bits, fmt_muestra = self.tags[258][0], self.tags.get(339, [1])[0]
        if (comp, pred, bits, fmt_muestra) != (8, 3, 32, 3):
            raise SystemExit('formato no previsto: compresion %d, predictor %d, %d bits, tipo %d'
                             % (comp, pred, bits, fmt_muestra))
        self.offsets, self.cuentas = self.tags[324], self.tags[325]
        self.escala = self.tags[33550]                    # sx, sy, sz
        self.amarre = self.tags[33922]                    # i, j, k, x, y, z
        claves = self.tags.get(34735, [])
        geo = {claves[4 + 4 * i]: claves[4 + 4 * i + 3] for i in range(claves[3])} if claves else {}
        # GTRasterTypeGeoKey (1025): 1 = la celda es un area (el amarre es su
        # esquina), 2 = es un punto (el amarre es su centro).
        self.celda_es_area = geo.get(1025, 1) == 1

    def _bytes(self, a, b):
        r = self.sesion.get(self.url, headers={'Range': 'bytes=%d-%d' % (a, b)}, timeout=120)
        if r.status_code not in (200, 206):
            raise SystemExit('HTTP %d al pedir %s' % (r.status_code, self.url))
        return r.content

    def _en(self, off, n):
        if off + n <= len(self._cab):
            return self._cab[off:off + n]
        return self._bytes(off, off + n - 1)

    def centro(self, i, j):
        """(lon, lat) del centro de la celda columna i, fila j."""
        medio = 0.5 if self.celda_es_area else 0.0
        return (self.amarre[3] + (i - self.amarre[0] + medio) * self.escala[0],
                self.amarre[4] - (j - self.amarre[1] + medio) * self.escala[1])

    def indice(self, lon, lat):
        """(i, j) continuos de un punto: el inverso de centro()."""
        medio = 0.5 if self.celda_es_area else 0.0
        return ((lon - self.amarre[3]) / self.escala[0] + self.amarre[0] - medio,
                (self.amarre[4] - lat) / self.escala[1] + self.amarre[1] - medio)

    def bloque(self, bi, bj):
        """El bloque (bi, bj) decodificado: th x tw float32."""
        k = bj * ((self.ancho + self.tw - 1) // self.tw) + bi
        crudo = zlib.decompress(self._bytes(self.offsets[k], self.offsets[k] + self.cuentas[k] - 1))
        a = np.frombuffer(crudo, dtype=np.uint8).reshape(self.th, self.tw * 4)
        # Predictor 3: la diferencia es byte a byte a lo largo de la fila
        # entera (en uint8 la suma acumulada da la vuelta modulo 256)...
        a = np.cumsum(a, axis=1, dtype=np.uint8)
        # ...y los bytes vienen en planos: el mas significativo primero.
        planos = a.reshape(self.th, 4, self.tw).transpose(0, 2, 1).copy()
        return planos.view('>f4').reshape(self.th, self.tw).astype(np.float64)

    def ventana(self, i0, i1, j0, j1):
        """Celdas [j0, j1] x [i0, i1] (inclusive), leyendo solo sus bloques."""
        z = np.empty((j1 - j0 + 1, i1 - i0 + 1))
        cache = {}
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                clave = (i // self.tw, j // self.th)
                if clave not in cache:
                    cache[clave] = self.bloque(*clave)
                z[j - j0, i - i0] = cache[clave][j % self.th, i % self.tw]
        return z, sorted(cache)


def nombre_del_bloque(lon, lat):
    """El GeoTIFF de 1 grado que contiene el punto (esquina SO en el nombre)."""
    la, lo = math.floor(lat), math.floor(lon)
    return 'Copernicus_DSM_COG_10_%s%02d_00_%s%03d_00_DEM' % (
        'S' if la < 0 else 'N', abs(la), 'W' if lo < 0 else 'E', abs(lo))


def bajar_dem(margen=120.0, salida=None):
    """
    Baja la ventana del Copernicus DEM GLO-30 alrededor del recorrido de
    sitio.json, con `margen` metros, y la escribe donde sitio.json dice que
    esta el DEM (o en `salida`). Es una herramienta de UNA vez: la suite no
    la corre y el relieve no la necesita.
    """
    perfil = leer_json(os.path.join(rutas.SITIO, 'sitio.json'))
    salida = salida or os.path.join(rutas.SITIO, perfil['dem'])
    linea = leer_kmz(os.path.join(rutas.SITIO, perfil['recorrido']))['lineas'][0]
    lons = [p[0] for p in linea]
    lats = [p[1] for p in linea]
    lat_c = 0.5 * (min(lats) + max(lats))
    dlat = margen / 111320.0
    dlon = margen / (111320.0 * math.cos(math.radians(lat_c)))
    caja = (min(lons) - dlon, max(lons) + dlon, min(lats) - dlat, max(lats) + dlat)

    nombre = nombre_del_bloque(0.5 * (caja[0] + caja[1]), lat_c)
    if nombre_del_bloque(caja[0], caja[2]) != nombre or nombre_del_bloque(caja[1], caja[3]) != nombre:
        raise SystemExit('la ventana cruza el borde de un grado: falta leer dos archivos')
    url = '%s/%s/%s.tif' % (BUCKET, nombre, nombre)
    print('  DEM  %s' % url)
    cog = CogRemoto(url)
    i_a, j_a = cog.indice(caja[0], caja[3])
    i_b, j_b = cog.indice(caja[1], caja[2])
    i0, i1 = int(math.floor(i_a)), int(math.ceil(i_b))
    j0, j1 = int(math.floor(j_a)), int(math.ceil(j_b))
    z, bloques = cog.ventana(i0, i1, j0, j1)
    lons_c = [cog.centro(i, j0)[0] for i in range(i0, i1 + 1)]
    lats_c = [cog.centro(i0, j)[1] for j in range(j0, j1 + 1)]
    print('  celda %s, %d x %d celdas (bloques %s), cotas %.1f a %.1f m'
          % ('area' if cog.celda_es_area else 'punto', z.shape[1], z.shape[0], bloques,
             z.min(), z.max()))

    dem = {
        '_que_es': ('Ventana del Copernicus DEM GLO-30 alrededor del recorrido %s. La lee '
                    'exportar/relieve.py; la escribe exportar/relieve.py --bajar-dem.' % perfil['recorrido']),
        'fuente': 'Copernicus DEM GLO-30 (ESA/Airbus, TanDEM-X 2011-2015), modelo de superficie',
        'atribucion': ATRIBUCION,
        'url': url,
        'bajado': datetime.date.today().isoformat(),
        'celda_es_area': cog.celda_es_area,
        'paso_grados': [cog.escala[0], cog.escala[1]],
        'indices': {'i0': i0, 'i1': i1, 'j0': j0, 'j1': j1},
        'lon': [round(v, 9) for v in lons_c],
        'lat': [round(v, 9) for v in lats_c],
        '_z': 'z[fila][columna], filas de norte a sur (como lat), en metros sobre el geoide EGM2008',
        'z': [[round(float(v), 3) for v in fila] for fila in z],
    }
    texto = json.dumps(dem, ensure_ascii=False, indent=1)
    rutas.escribir_atomico(salida, texto.encode('utf-8'))
    print('  -> %s' % rel(salida))
    return 0


# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser(prog='sap.py exportar relieve', description='Relieve del sitio para el visor')
    ap.add_argument('--verificar', action='store_true',
                    help='no escribe: compara con salidas/relieve.json')
    ap.add_argument('--no-escribir', action='store_true', help='arma y comprueba, sin escribir')
    ap.add_argument('--figura', action='store_true', help='y la planta en salidas/figuras/relieve_planta.png')
    ap.add_argument('--bajar-dem', action='store_true',
                    help='vuelve a bajar el DEM a entrada/sitio/ (internet y requests)')
    ap.add_argument('--margen', type=float, default=120.0,
                    help='con --bajar-dem: margen alrededor del recorrido, en metros')
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.bajar_dem:
        return bajar_dem(a.margen)

    print('=' * 70)
    print('  RELIEVE DEL SITIO (exportar/relieve.py)')
    print('=' * 70)
    f = Fallas()
    r = armar(f)
    js = construir(r)
    ruta = rutas.salida('relieve')
    if a.verificar:
        igual = os.path.isfile(ruta) and leer_json(ruta) == json.loads(json.dumps(js))
        f.check(igual, '%s es el que se arma ahora%s'
                % (rel(ruta), '' if os.path.isfile(ruta) else
                   ' (no existe: python sap.py exportar relieve)'))
    elif a.no_escribir:
        print('  (--no-escribir: no se escribe %s)' % rel(ruta))
    elif f.lista:
        print('  NO SE ESCRIBE %s: el relieve no calza' % rel(ruta))
    else:
        escribir(js)
        print('  -> %s (%.0f KB)' % (rel(ruta), os.path.getsize(ruta) / 1024))
    if a.figura:
        figura(r, FIGURA)
        print('  -> %s' % rel(FIGURA))
    print('=' * 70)
    if f.lista:
        print('  FALLA: %d' % len(f.lista))
        return 1
    print('  EL RELIEVE CALZA CON EL TECHO Y CON LAS TERRAZAS DEL MODELO')
    return 0


if __name__ == '__main__':
    sys.exit(main())
