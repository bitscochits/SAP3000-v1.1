# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/ar.py  -  EL SECTOR Y SUS RESULTADOS, PARA LA APP DE AR
================================================================
 La regla de oro sigue igual: Python/OpenSees calcula, el JSON
 transporta y el telefono muestra. Este es el ultimo paso de Python
 hacia la app de realidad aumentada: toma el edificio y los resultados
 del laboratorio (los de salidas/resultados.json, los mismos que muestra
 el visor), se queda con el SECTOR alrededor del elemento donde se pega
 la imagen de referencia, y escribe salidas/ar.json. sap.py sincronizar
 lo copia a ar/web/datos/ar.json, que es lo que lee el telefono.

 Lo que viaja, todo en coordenadas y unidades de OpenSees (m, kN):

   marcador   donde esta la imagen en el edificio: su centro y sus tres
              ejes (x a la derecha de la imagen, y hacia arriba, z
              saliendo de la columna hacia quien la mira), y su ancho
              impreso. Es la POSE del marcador en el modelo.
   nodos      x, y, z de OpenSees, con el MISMO tag del modelo.
   elementos  el sector, con el MISMO elementTag que OpenSees.
   casos      los 15 del laboratorio: desplazamientos de los nodos del
              sector, esfuerzos por estacion (N, Vy, Vz, T, My, Mz), y la
              demanda-capacidad de los que tienen fierro.
   familias   la curva P-M de cada seccion del sector con fierro, buscada
              por su 'indice' y no por su posicion en la lista: si los
              resultados se reordenaran, la app dibujaria la curva de otra
              seccion y nada fallaria.
   tributaria los poligonos del area tributaria de las vigas del sector.

 En el telefono no se resuelve nada: se transforma (OpenSees -> marcador
 -> anchor de AR) y se dibuja. La transformacion esta escrita dos veces a
 proposito: en ar/web/ar.js (matrizModeloAAnchor), que corre en el
 telefono, y aca (a_anchor), que la verificacion corre contra la de ar.js
 en un navegador (verificacion/ar.py, registro_y_tracking).

 Donde se pega la imagen (elemento, cara, altura, ancho) y como se
 muestra (escalas de sitio y maqueta, caso por defecto) esta en
 entrada/laboratorio.json, bloque "ar".

   python sap.py exportar ar                          # -> salidas/ar.json
   python sap.py exportar ar --elemento 200069 --cara -y
================================================================
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import sys
import time

from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas

MAGNITUDES = ('N', 'Vy', 'Vz', 'T', 'My', 'Mz')
CARAS = {'+x': (1.0, 0.0, 0.0), '-x': (-1.0, 0.0, 0.0), '+y': (0.0, 1.0, 0.0), '-y': (0.0, -1.0, 0.0)}
# Estos no son elementos del edificio sino recursos del modelo (brazos que
# unen el eje de un muro con sus caras). Se dejan fuera del dibujo.
NO_SE_DIBUJAN = ('brazo', 'brazo_rigido')
DEC = 6


# ============================================================
# ALGEBRA MINIMA (sin numpy: el mismo codigo que se lee en ar.js)
# ============================================================
def resta(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def punto(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cruz(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def unitario(a):
    n = math.sqrt(punto(a, a))
    return [a[0] / n, a[1] / n, a[2] / n]


def a_marcador(p, marcador):
    """Un punto de OpenSees (m) en el sistema de la imagen (m):
    q = R^T (p - c), con R = [ex ey ez] en columnas."""
    d = resta(p, marcador['centro'])
    return [punto(d, marcador['ejes']['x']), punto(d, marcador['ejes']['y']), punto(d, marcador['ejes']['z'])]


def a_anchor(p, marcador, escala):
    """Lo mismo, en unidades del anchor de MindAR: 1 unidad = el ancho
    impreso de la imagen. Es lo que hace ar.js (matrizModeloAAnchor)."""
    q = a_marcador(p, marcador)
    k = escala / marcador['ancho_m']
    return [q[0] * k, q[1] * k, q[2] * k]


# ============================================================
# ENTRADAS
# ============================================================
def configuracion(elemento=None, cara=None, altura=None, ancho=None):
    """El bloque 'ar' de laboratorio.json, con lo que venga por linea de comandos encima."""
    cfg = dict(lab.bloque('ar'))
    for k, v in (('elemento', elemento), ('cara', cara),
                 ('altura_centro_m', altura), ('ancho_impreso_m', ancho)):
        if v is not None:
            cfg[k] = v
    return cfg


def leer_json(ruta):
    with io.open(ruta, encoding='utf-8') as fh:
        return json.load(fh)


def resultados_del_laboratorio(argv=()):
    """
    (resultados, de_donde): los resultados del laboratorio con los
    parametros de `argv` (los de laboratorio.json si no viene ninguno).

    Son los de salidas/resultados.json si ese archivo se armo con esos
    mismos parametros: su info.parametros es la huella (describir()). Si
    no existe, o es de otros parametros, se arman en memoria con el mismo
    codigo que lo escribe (exportar/resultados.py), para que el telefono
    no muestre numeros de otro laboratorio sin que nadie lo note.
    """
    huella = [l.strip() for l in lab.describir(lab.cargar(list(argv))).split('\n')]
    ruta = rutas.salida('resultados')
    if os.path.isfile(ruta):
        anexo = leer_json(ruta)
        if anexo.get('info', {}).get('parametros') == huella:
            return anexo, rutas.relativa(ruta).replace(os.sep, '/')
        motivo = 'el de disco es de otros parametros'
    else:
        motivo = 'no hay %s' % rutas.relativa(ruta).replace(os.sep, '/')
    from exportar import resultados                # el mismo codigo que lo escribe
    with open(os.devnull, 'w') as dn, contextlib.redirect_stdout(dn), opensees.AvisosDeOpenSees():
        anexo, _ctx = resultados.construir(list(argv))
    return anexo, 'exportar/resultados.construir() en memoria (%s)' % motivo


# ============================================================
# EL MARCADOR EN EL MODELO
# ============================================================
def pose_del_marcador(elemento, nodos, anexo_elem, cfg):
    """Centro y ejes de la imagen pegada en una cara de la columna."""
    if elemento['tipo'] not in ('columna', 'pilar_metal'):
        raise SystemExit('el elemento %s es %s: la imagen va en una columna'
                         % (elemento['id'], elemento['tipo']))
    n1, n2 = nodos[elemento['n1']], nodos[elemento['n2']]
    if abs(n1['x'] - n2['x']) > 1e-6 or abs(n1['y'] - n2['y']) > 1e-6:
        raise SystemExit('la columna %s no es vertical' % elemento['id'])
    cara = cfg['cara']
    normal = list(CARAS[cara])
    # Medio ancho de la seccion en la direccion de la normal, con la misma
    # convencion con que ar.js dibuja la barra: h a lo largo del eje local
    # z y b del y (en una viga, h es el alto y z la vertical). En una
    # columna cuadrada da lo mismo.
    b, h = float(anexo_elem['b']), float(anexo_elem['h'])
    local_z = elemento.get('localZ') or [1.0, 0.0, 0.0]
    medio = (h if abs(punto(normal, local_z)) > 0.5 else b) / 2.0
    z_base = min(n1['z'], n2['z'])
    centro = [n1['x'] + normal[0] * medio, n1['y'] + normal[1] * medio, z_base + float(cfg['altura_centro_m'])]
    ez = normal                        # sale de la imagen hacia quien la mira
    ey = [0.0, 0.0, 1.0]               # arriba de la imagen = arriba del edificio
    ex = cruz(ey, ez)                  # derecha de la imagen: sistema derecho
    # MAQUETA: la misma imagen, acostada sobre una mesa. Ahi la normal de
    # la imagen es la vertical, asi que el arriba del edificio (+z de
    # OpenSees) tiene que salir de la imagen. El origen es la base de la
    # columna, para que el sector se pare sobre la imagen.
    base = [n1['x'], n1['y'], z_base]
    mz = [0.0, 0.0, 1.0]
    mx = ex                             # la derecha de la imagen, igual que en sitio
    my = cruz(mz, mx)
    maqueta = {'centro': [round(v, DEC) for v in base], 'ejes': {'x': mx, 'y': my, 'z': mz},
               '_por_que': ('Imagen acostada sobre la mesa: su normal (z) es la vertical del '
                            'edificio, x es la misma derecha que en sitio y y = z cruz x. El origen '
                            'es la base de la columna: el sector se para sobre la imagen.')}
    return {
        'elemento': elemento['id'],
        'cara': cara,
        'centro': [round(v, DEC) for v in centro],
        'ejes': {'x': ex, 'y': ey, 'z': ez},
        'maqueta': maqueta,
        'ancho_m': float(cfg['ancho_impreso_m']),
        'altura_centro_m': float(cfg['altura_centro_m']),
        'medio_ancho_columna_m': medio,
        '_por_que': ('Centro de la imagen = eje de la columna + medio ancho de la seccion en la '
                     'direccion de la cara + altura sobre el nodo inferior. Ejes: z = normal de la '
                     'cara (sale de la imagen), y = +z de OpenSees (arriba), x = y cruz z (sistema '
                     'derecho). Todo en coordenadas de OpenSees, metros.'),
    }


# ============================================================
# EL SECTOR
# ============================================================
def sector(modelo, objetivo, radio):
    nodos = {int(n['id']): n for n in modelo['nodos']}
    n1, n2 = nodos[objetivo['n1']], nodos[objetivo['n2']]
    z_abajo, z_arriba = min(n1['z'], n2['z']), max(n1['z'], n2['z'])
    cx, cy = n1['x'], n1['y']
    tol = 1e-3
    elegidos = []
    for e in modelo['elementos']:
        if e['tipo'] in NO_SE_DIBUJAN:
            continue
        a, b = nodos[e['n1']], nodos[e['n2']]
        cerca = any(math.hypot(p['x'] - cx, p['y'] - cy) <= radio + tol for p in (a, b))
        dentro = (z_abajo - tol <= min(a['z'], b['z'])) and (max(a['z'], b['z']) <= z_arriba + tol)
        if cerca and dentro:
            elegidos.append(e)
    ids_nodos = sorted({e['n1'] for e in elegidos} | {e['n2'] for e in elegidos})
    return elegidos, ids_nodos


def familias_por_indice(anexo):
    """{indice: familia}: la curva P-M de cada familia por su 'indice', nunca por su posicion."""
    return {int(f['indice']): f for f in anexo['familias']}


# ============================================================
def construir(anexo, de_donde, cfg=None, edificio_=None):
    """
    ar.json en memoria, a partir de los resultados del laboratorio
    (`anexo`, ya armados) y del edificio. `de_donde` dice de donde salieron
    esos resultados: el telefono lo muestra al pie del panel.
    """
    cfg = cfg if cfg is not None else configuracion()
    edificio_ = edificio_ if edificio_ is not None else _ed.cargar()
    modelo = _ed.estructura(edificio_)
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elems = {int(e['id']): e for e in modelo['elementos']}
    anexo_elem = {int(e['id']): e for e in anexo['elementos']}
    obj_id = int(cfg['elemento'])
    if obj_id not in elems:
        raise SystemExit('el elemento %d no existe en entrada/edificio.json' % obj_id)
    objetivo = elems[obj_id]
    marcador = pose_del_marcador(objetivo, nodos, anexo_elem[obj_id], cfg)
    elegidos, ids_nodos = sector(modelo, objetivo, float(cfg['radio_sector_m']))
    ids_elem = [e['id'] for e in elegidos]
    en_sector = set(ids_elem)

    # --- geometria, con los tags del modelo ---
    salida_nodos = [{'id': i, 'x': nodos[i]['x'], 'y': nodos[i]['y'], 'z': nodos[i]['z'],
                     'restricciones': nodos[i].get('restricciones')} for i in ids_nodos]
    salida_elem = []
    for e in elegidos:
        ae = anexo_elem.get(e['id'], {})
        salida_elem.append({
            'id': e['id'], 'tipo': e['tipo'], 'seccion': e['seccion'], 'n1': e['n1'], 'n2': e['n2'],
            'b': ae.get('b'), 'h': ae.get('h'), 'L': ae.get('L'),
            'localY': e.get('localY'), 'localZ': e.get('localZ'),
            'familia': ae.get('familia', -1),
            'momento_en_el_plano': ae.get('momento_en_el_plano', ''),
            'tag_opensees': ae.get('tag_opensees'),
            'area_tributaria_m2': e.get('area_tributaria'),
        })

    # --- resultados de OpenSees, caso por caso, solo del sector ---
    casos = []
    for c in anexo['casos']:
        desp = {str(d['id']): [d['ux'], d['uy'], d['uz'], d['rx'], d['ry'], d['rz']]
                for d in c['desplazamientos'] if d['id'] in set(ids_nodos)}
        esf = {}
        for s in c['esfuerzos']:
            if s['id'] in en_sector:
                esf[str(s['id'])] = {'x': s['x'], 'f': s['f'], 'w': s.get('w'),
                                     **{m: s[m] for m in MAGNITUDES}}
        dem = {str(d['id']): {k: d[k] for k in ('P', 'M', 'Mn', 'u', 'pasa', 'extremo')}
               for d in c['demandas'] if d['id'] in en_sector}
        casos.append({'nombre': c['nombre'], 'tipo': c.get('tipo'), 'descripcion': c.get('descripcion'),
                      'factores': c.get('factores'), 'desplazamientos': desp, 'esfuerzos': esf,
                      'demandas': dem})

    fams = sorted({e['familia'] for e in salida_elem if e['familia'] is not None and e['familia'] >= 0})
    por_indice = familias_por_indice(anexo)
    familias = {str(k): {'clave': por_indice[k]['clave'], 'P': por_indice[k]['P'],
                         'Mn': por_indice[k]['Mn'], 'refuerzo': por_indice[k].get('refuerzo')}
                for k in fams}

    tributarias = [t for t in _ed.vista(edificio_).get('areas_tributarias', []) if t['elemento'] in en_sector]

    return {
        'info': {
            'edificio': _ed.NOMBRE,
            'generado_por': 'exportar/ar.py',
            'resultados_de': de_donde,
            'unidades': 'OpenSees: m, kN, kN*m, rad. Anchor de MindAR: 1 unidad = ancho impreso de la imagen',
            'regla_de_oro': 'Todo numero estructural de este archivo lo calculo OpenSees (anexo de la Semana 4). '
                            'El telefono solo transforma coordenadas y dibuja.',
            'ejes_opensees': 'x, y horizontales, z vertical hacia arriba; sistema derecho',
            'mapeo_unity': 'Unity(x, y, z) = OpenSees(x, z, y): y de Unity es la vertical. Cambiar y por z '
                           'invierte la mano: Unity es un sistema izquierdo (VisorEstructura.cs).',
            'mapeo_anchor': 'anchor = (escala / ancho_m) * R^T (p - centro), R = [ejes.x ejes.y ejes.z] del marcador',
            'escala_deformada': anexo['info'].get('escala_deformada'),
            'caso_por_defecto': cfg.get('caso_por_defecto') or anexo['info'].get('caso_por_defecto'),
            'modo_por_defecto': cfg.get('modo_por_defecto', 'maqueta'),
        },
        'modos': cfg['modos'],
        'marcador': marcador,
        'objetivo': obj_id,
        'nodos': salida_nodos,
        'elementos': salida_elem,
        'familias': familias,
        'tributarias': tributarias,
        'casos': casos,
    }


def escribir(ar, ruta=None):
    """salidas/ar.json (o `ruta`), compacto y de una vez: pesa ~200 KB y viaja por WiFi."""
    texto = json.dumps(ar, ensure_ascii=False, separators=(',', ':'))
    return rutas.escribir_atomico(ruta or rutas.salida('ar'), texto.encode('utf-8'))


def imprimir(ar, ruta, segundos, escrito=True):
    m = ar['marcador']
    objetivo = next(e for e in ar['elementos'] if e['id'] == ar['objetivo'])
    print('=' * 70)
    print('  AR: %s, elemento %d (%s, %s), cara %s' % (ar['info']['edificio'], ar['objetivo'],
                                                        objetivo['tipo'], objetivo['seccion'], m['cara']))
    print('=' * 70)
    print('  resultados de   %s' % ar['info']['resultados_de'])
    print('  marcador        centro %s m (OpenSees), ancho %.3f m' % (m['centro'], m['ancho_m']))
    print('                  ejes x %s  y %s  z %s' % (m['ejes']['x'], m['ejes']['y'], m['ejes']['z']))
    print('  sector          %d elementos, %d nodos, %d areas tributarias'
          % (len(ar['elementos']), len(ar['nodos']), len(ar['tributarias'])))
    tipos = {}
    for e in ar['elementos']:
        tipos[e['tipo']] = tipos.get(e['tipo'], 0) + 1
    print('                  %s' % ', '.join('%s %d' % kv for kv in sorted(tipos.items())))
    print('  casos           %d; familias P-M %d' % (len(ar['casos']), len(ar['familias'])))
    destino = rutas.relativa(ruta).replace(os.sep, '/')
    if escrito:
        print('  -> %s (%.0f KB, %.1f s)' % (destino, os.path.getsize(ruta) / 1024, segundos))
    else:
        print('  (--no-escribir: no se escribe %s; %.1f s)' % (destino, segundos))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='sap.py exportar ar',
                                 description='Exporta el sector y sus resultados para la app de AR. '
                                             'Acepta ademas los parametros del laboratorio (--cs, --q, ...).')
    ap.add_argument('--elemento', type=int)
    ap.add_argument('--cara', choices=sorted(CARAS))
    ap.add_argument('--altura', type=float, help='altura del centro de la imagen sobre el nodo inferior (m)')
    ap.add_argument('--ancho', type=float, help='ancho impreso de la imagen (m)')
    ap.add_argument('--salida', help='otro destino en vez de salidas/ar.json')
    ap.add_argument('--no-escribir', action='store_true', help='arma ar.json en memoria sin escribirlo')
    args, resto = ap.parse_known_args(sys.argv[1:] if argv is None else argv)

    t0 = time.time()
    cfg = configuracion(args.elemento, args.cara, args.altura, args.ancho)
    anexo, de_donde = resultados_del_laboratorio(resto)
    ar = construir(anexo, de_donde, cfg)
    ruta = args.salida or rutas.salida('ar')
    if not args.no_escribir:
        escribir(ar, ruta)
    imprimir(ar, ruta, time.time() - t0, escrito=not args.no_escribir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
