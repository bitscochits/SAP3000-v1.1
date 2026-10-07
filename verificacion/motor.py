# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/motor.py  -  EL MOTOR, EL SERVIDOR Y EL REANALISIS
================================================================
 Siete bloques; sin bloque corre los siete:

   python -m verificacion.motor servidor                                # M1
   python -m verificacion.motor casos_del_modelo                        # M2
   python -m verificacion.motor reanalisis                              # M3
   python -m verificacion.motor m1 [--float32] [--url URL] [--desde JSON]   # M4
   python -m verificacion.motor m3 [--float32] [--url URL] [--desde JSON]   # M5
   python -m verificacion.motor m4 [--float32] [--url URL] [--desde JSON]   # M6
   python -m verificacion.motor viga_partida [nodo]                     # M7

 SERVIDOR. calculo/opensees.py con modelos chicos que se pueden
 resolver a mano: el marco de prueba (el dato va abajo, en este
 archivo) sigue dando -0.06348 mm; resolver N casos sobre el mismo
 modelo da lo mismo que rearmarlo; R(G) + R(Q) = R(G+Q); apoyos por
 grado de libertad; diafragma rigido; brazos rigidos; entradas
 invalidas rechazadas con su motivo; el equilibrio de cada caso con la
 regla por grado de libertad; el edificio entero (salidas/modelo.json)
 en equilibrio y con la G del numero de control; POST /analizar por el
 test_client de exportar/servidor.py (el libro va a %TEMP%, no a
 salidas/); y el marco en la forma en que lo manda JsonUtility.

 CASOS_DEL_MODELO. salidas/casos_del_modelo.json y salidas/modelo.json
 son lo que da resolver el edificio AHORA (por objetos, tolerancia 0),
 y los casos G, Q, EX y EY del modelo dan sus numeros de control.

 REANALISIS. POST /analizar con salidas/modelo.json, el JSON que Unity
 reenvia al editar, reproduce la deformada G que trae el propio JSON y
 los casos del modelo; y la M1 por HTTP, mandada como la manda
 JsonUtility (float32, solo los campos de ModeloEstructural.cs).

 M1, M3, M4. Las modificaciones de la pestana Modificar sin abrir
 Unity: la edicion que hace EditorEstructura (borrar una barra,
 cambiarle la seccion, cambiar un apoyo) sobre salidas/modelo.json, el
 antes y el despues resueltos, el nodo y las barras que mira el panel y
 el equilibrio. Los ids salen de entrada/laboratorio.json
 (modificaciones). --float32 manda los numeros como JsonUtility; --url
 le pega a un servidor vivo (python sap.py servidor), el camino EXACTO
 de Unity; --desde toma el "despues" de un JSON guardado por Unity
 (boton Guardar JSON).

 VIGA_PARTIDA. Partir una viga no le pone una rotula: refinar los dos
 tramos en 2, 4 y 8 da la misma flecha. Lo que la hunde es la viga
 perpendicular que llega con su losa, sin columna debajo.

 Ninguno escribe en salidas/.
================================================================
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo.opensees import construir_y_resolver
from verificacion.comun import Informe, comparar_json, titulo
from verificacion.suite import calza, consola_tolerante, control

BLOQUES = ('servidor', 'casos_del_modelo', 'reanalisis', 'm1', 'm3', 'm4', 'viga_partida')


def rel(ruta):
    return rutas.relativa(ruta)


# ============================================================
# EL MARCO DE PRUEBA (DATO)
# ============================================================
# Cuatro columnas 30x30 y cuatro vigas L de 4 m en un piso de 3 m,
# hormigon G-25. Validado contra SAP2000: el nodo de techo baja
# -0.06375 mm alla y -0.06348 mm aca (0.4 %: la carga de la losa va
# repartida como uniforme y no como trapecio). Es el numero de oro del
# motor (numeros_de_control.json, benchmark): si deja de dar -0.06348,
# cambio el motor, no el marco.
FPC_MPa = 25.0
POISSON = 0.2
GAMMA = 25.0                                  # kN/m3


def _j_rectangular(b, h):
    """
    Constante de torsion de Saint-Venant de una seccion rectangular
    llena (Timoshenko / Roark), con a = lado LARGO y t = lado CORTO:

        J = a * t^3 * [ 1/3 - 0.21*(t/a)*(1 - t^4/(12*a^4)) ]

    Para la cuadrada da 0.1406*b^4. min(Iy,Iz)*0.3, que no es ninguna
    formula, daba 5.6 veces menos rigidez torsional.
    """
    a = max(b, h)
    t = min(b, h)
    return a * t**3 * (1.0/3.0 - 0.21 * (t/a) * (1.0 - t**4 / (12.0 * a**4)))


COL_B, COL_H = 0.30, 0.30
A_COL = COL_B * COL_H
IY_COL = COL_B * COL_H**3 / 12.0
IZ_COL = COL_H * COL_B**3 / 12.0
J_COL = _j_rectangular(COL_B, COL_H)

# Viga L (losa colaborante, ala = luz/4 segun ACI), calculada
# geometricamente: Iz es la de gravedad, Iy la lateral.
A_VIG = 0.237500
IY_VIG = 2.07271107e-02
IZ_VIG = 4.62842654e-03
J_VIG = 2.03909066e-03

T_LOSA_CARGA = 0.15                            # m, espesor de losa para la carga
SOBRECARGA_TERMINACIONES = 1.5                 # kN/m2
Q_LOSA = GAMMA * T_LOSA_CARGA + SOBRECARGA_TERMINACIONES   # 5.25 kN/m2
Q_VIVA = 2.0                                               # kN/m2


def w_viga(q, luz_viga, luz_transversal, incluir_peso_vigas=False):
    r"""
    Carga uniforme equivalente (kN/m) sobre una viga desde la carga de
    superficie q (kN/m2) de su pano: w = q * A_tributaria / luz. El area
    sale de las bisectrices a 45 grados desde las esquinas: trapecio
    b (2a - b) / 4 si esta viga es la larga (b <= a), triangulo a^2 / 4
    si es la corta. Conserva la resultante, que es lo que exige el
    equilibrio; el momento y la flecha difieren algo de los de la carga
    trapecial real (de ahi el 0.4 % contra SAP2000).
    """
    a = float(luz_viga)
    b = float(luz_transversal)
    if a <= 0.0 or b <= 0.0:
        raise ValueError('Luces deben ser positivas: a=%s, b=%s' % (a, b))
    A_trib = b * (2.0 * a - b) / 4.0 if b <= a else a * a / 4.0
    w = q * A_trib / luz_viga
    if incluir_peso_vigas:
        w += GAMMA * A_VIG        # peso propio distribuido (kN/m)
    return w


SEC = {
    "columna": {"A": A_COL, "Iy": IY_COL, "Iz": IZ_COL, "J": J_COL},
    "viga":    {"A": A_VIG, "Iy": IY_VIG, "Iz": IZ_VIG, "J": J_VIG},
    "muro":    {"A": 0.6, "Iy": 0.045, "Iz": 0.0018, "J": 0.0072},
}

NODOS = [
    {"id": 1, "x": 0, "y": 0, "z": 0, "fijo": True},
    {"id": 2, "x": 0, "y": 4, "z": 0, "fijo": True},
    {"id": 3, "x": 4, "y": 0, "z": 0, "fijo": True},
    {"id": 4, "x": 4, "y": 4, "z": 0, "fijo": True},
    {"id": 5, "x": 0, "y": 0, "z": 3},
    {"id": 6, "x": 0, "y": 4, "z": 3},
    {"id": 7, "x": 4, "y": 0, "z": 3},
    {"id": 8, "x": 4, "y": 4, "z": 3},
]
ELEMS = [
    {"id": 1, "n1": 1, "n2": 5, "seccion": "columna", "tipo": "columna"},
    {"id": 2, "n1": 2, "n2": 6, "seccion": "columna", "tipo": "columna"},
    {"id": 3, "n1": 3, "n2": 7, "seccion": "columna", "tipo": "columna"},
    {"id": 4, "n1": 4, "n2": 8, "seccion": "columna", "tipo": "columna"},
    {"id": 5, "n1": 5, "n2": 7, "seccion": "viga", "tipo": "viga_x"},
    {"id": 6, "n1": 6, "n2": 8, "seccion": "viga", "tipo": "viga_x"},
    {"id": 7, "n1": 5, "n2": 6, "seccion": "viga", "tipo": "viga_y"},
    {"id": 8, "n1": 7, "n2": 8, "seccion": "viga", "tipo": "viga_y"},
]
W_G = w_viga(Q_LOSA, 4.0, 4.0, incluir_peso_vigas=True)
W_Q = w_viga(Q_VIVA, 4.0, 4.0)

F_SISMO = 50.0          # kN por nodo de techo (pseudoestatico)
TECHO = (5, 6, 7, 8)
CARGAS_G = [{"elemento": e, "wy": 0, "wz": -W_G, "wx": 0} for e in (5, 6, 7, 8)]
CARGAS_Q = [{"elemento": e, "wy": 0, "wz": -W_Q, "wx": 0} for e in (5, 6, 7, 8)]
CARGAS_EX = [{"nodo": n, "fx": F_SISMO} for n in TECHO]
CARGAS_EY = [{"nodo": n, "fy": F_SISMO} for n in TECHO]

# Lo que tienen que dar las reacciones del marco con los cuatro casos:
# 4 vigas x 4 m x w, y 4 nodos x 50 kN.
EQUILIBRIO_DEL_MARCO = {'G': ('fz', 179.0), 'Q': ('fz', 32.0),
                        'EX': ('fx', -200.0), 'EY': ('fy', -200.0)}


def base(**extra):
    d = {"material": {"fpc_MPa": FPC_MPa, "poisson": POISSON},
         "nodos": copy.deepcopy(NODOS), "secciones": SEC,
         "elementos": copy.deepcopy(ELEMS)}
    d.update(extra)
    return d


def marco_como_unity():
    r"""
    El marco con la forma de salidas/modelo.json, la que Unity reenvia a
    /analizar: secciones en LISTA (JsonUtility no lee diccionarios), cada
    nodo con 'fijo', 'auxiliar' y sus seis restricciones, y los cuatro
    casos G, Q, EX y EY.
    """
    return {
        'info': {'descripcion': 'Marco de prueba: 4 columnas + 4 vigas L',
                 'unidades': 'm, kN, kPa'},
        'material': {'fpc_MPa': FPC_MPa, 'poisson': POISSON, 'gamma': GAMMA},
        'secciones': [dict(SEC[n], nombre=n) for n in ('columna', 'viga')],
        'nodos': [{'id': n['id'], 'x': n['x'], 'y': n['y'], 'z': n['z'],
                   'fijo': bool(n.get('fijo')), 'auxiliar': False,
                   'restricciones': [1] * 6 if n.get('fijo') else [0] * 6}
                  for n in NODOS],
        'elementos': copy.deepcopy(ELEMS),
        'diafragmas': [],
        'brazos_rigidos': [],
        'casos_de_carga': [
            {'nombre': 'G', 'cargas_distribuidas': copy.deepcopy(CARGAS_G), 'cargas_nodales': []},
            {'nombre': 'Q', 'cargas_distribuidas': copy.deepcopy(CARGAS_Q), 'cargas_nodales': []},
            {'nombre': 'EX', 'cargas_distribuidas': [], 'cargas_nodales': copy.deepcopy(CARGAS_EX)},
            {'nombre': 'EY', 'cargas_distribuidas': [], 'cargas_nodales': copy.deepcopy(CARGAS_EY)},
        ],
    }


def uz(res, nid=5):
    return [x for x in res['desplazamientos'] if x['id'] == nid][0]['uz']


def ux(res, nid=5):
    return [x for x in res['desplazamientos'] if x['id'] == nid][0]['ux']


@contextlib.contextmanager
def libro_en_temporal(prefijo='verificacion_motor_'):
    r"""
    Mientras dura el bloque, rutas.salida('reanalisis') apunta a una
    carpeta temporal: POST /analizar escribe su libro ahi y la
    verificacion no deja nada en salidas/. El servidor arma la ruta en
    cada pedido (exportar/servidor.escribir_excel), asi que basta con
    cambiar la funcion del modulo.
    """
    temporal = tempfile.mkdtemp(prefix=prefijo)
    original = rutas.salida

    def _salida(nombre):
        if nombre == 'reanalisis':
            return os.path.join(temporal, 'reanalisis.xlsx')
        return original(nombre)

    rutas.salida = _salida
    try:
        yield temporal
    finally:
        rutas.salida = original
        shutil.rmtree(temporal, ignore_errors=True)


def leer_modelo_del_visor():
    """salidas/modelo.json, el que Unity dibuja y reenvia a /analizar."""
    ruta = rutas.salida('modelo')
    if not os.path.isfile(ruta):
        raise SystemExit('no existe %s: python sap.py exportar modelo' % rel(ruta))
    with open(ruta, encoding='utf-8') as f:
        return json.load(f), ruta


# ============================================================
# SERVIDOR
# ============================================================
def servidor(inf, args=None):
    titulo('SERVIDOR: el motor con modelos chicos, el edificio y POST /analizar')

    def rechaza(nombre, data, fragmento):
        try:
            construir_y_resolver(data)
            inf.check(False, nombre, 'no lanzo excepcion')
        except Exception as e:
            ok = fragmento.lower() in str(e).lower()
            inf.check(ok, nombre, '"%s"' % str(e)[:70])

    # ------------------------------------------------------------
    print("\n1. Regresion del marco de prueba")
    r = construir_y_resolver(base(cargas_distribuidas=CARGAS_G))
    ref_mm, _cota = control('benchmark', 'UZ_techo_mm')
    inf.check(calza(uz(r) * 1000, 'benchmark', 'UZ_techo_mm'),
              "UZ techo = %.5f mm (numero de control)" % ref_mm,
              "%.5f mm" % (uz(r) * 1000))
    inf.check(abs(sum(x['fz'] for x in r['reacciones']) - 179.0) < 1e-3,
              "equilibrio vertical",
              "%.4f kN" % sum(x['fz'] for x in r['reacciones']))
    inf.check('casos' not in r, "respuesta plana (sin 'casos')")

    # ------------------------------------------------------------
    print("\n2. Multi-caso == reconstruir el modelo por cada caso")
    multi = construir_y_resolver(base(casos_de_carga=[
        {"nombre": "G", "cargas_distribuidas": CARGAS_G},
        {"nombre": "Q", "cargas_distribuidas": CARGAS_Q},
        {"nombre": "EX", "cargas_nodales": CARGAS_EX},
    ]))
    inf.check(isinstance(multi.get('casos'), list), "devuelve 'casos' como lista")
    inf.check(len(multi['casos']) == 3, "3 casos")
    inf.check([c['nombre'] for c in multi['casos']] == ["G", "Q", "EX"], "nombres conservados")

    solos = {
        "G": construir_y_resolver(base(cargas_distribuidas=CARGAS_G)),
        "Q": construir_y_resolver(base(cargas_distribuidas=CARGAS_Q)),
        "EX": construir_y_resolver(base(cargas_nodales=CARGAS_EX)),
    }
    for c in multi['casos']:
        s = solos[c['nombre']]
        dmax = max(abs(a['ux'] - b['ux']) + abs(a['uy'] - b['uy']) + abs(a['uz'] - b['uz'])
                   for a, b in zip(c['desplazamientos'], s['desplazamientos']))
        inf.check(dmax < 1e-12, "caso %s identico al modelo reconstruido" % c['nombre'],
                  "dif max %.2e m" % dmax)

    # El bug clasico: sin setTime(0) el 2do caso saldria x2.
    q_multi = [x for x in multi['casos'][1]['desplazamientos'] if x['id'] == 5][0]
    inf.check(abs(q_multi['uz'] - uz(solos['Q'])) < 1e-12,
              "el caso 2 NO viene amplificado por el tiempo",
              "Q multi=%.3e  solo=%.3e" % (q_multi['uz'], uz(solos['Q'])))

    # ------------------------------------------------------------
    print("\n3. Superposicion lineal:  R(G) + R(Q) == R(G+Q)")
    sumadas = [{"elemento": e, "wy": 0, "wz": -(W_G + W_Q), "wx": 0} for e in (5, 6, 7, 8)]
    juntos = construir_y_resolver(base(cargas_distribuidas=sumadas))
    suma = uz(solos['G']) + uz(solos['Q'])
    # La respuesta se redondea a 8 decimales, asi que comparar una SUMA de
    # dos valores redondeados arrastra hasta 2e-8. Esa es la tolerancia real
    # del contrato, no la precision del solver.
    inf.check(abs(suma - uz(juntos)) < 2e-8, "UZ(G)+UZ(Q) == UZ(G+Q)",
              "%.8e vs %.8e  (dif %.1e)" % (suma, uz(juntos), abs(suma - uz(juntos))))

    # ------------------------------------------------------------
    print("\n4. Apoyos por grado de libertad")
    emp = construir_y_resolver(base(cargas_nodales=CARGAS_EX))
    rot = base(cargas_nodales=CARGAS_EX)
    for nd in rot['nodos']:
        if nd.get('fijo'):
            nd.pop('fijo')
            nd['restricciones'] = [1, 1, 1, 0, 0, 0]   # rotula
    rot = construir_y_resolver(rot)
    inf.check(abs(ux(rot)) > abs(ux(emp)) * 2, "rotula es mas flexible que empotrado",
              "empotrado %.3f mm  vs rotula %.3f mm" % (ux(emp) * 1000, ux(rot) * 1000))
    mom_emp = sum(abs(x['my']) for x in emp['reacciones'])
    mom_rot = sum(abs(x['my']) for x in rot['reacciones'])
    inf.check(mom_rot < 1e-6 < mom_emp, "la rotula no transmite momento",
              "My empotrado %.3f  vs rotula %.3e kN*m" % (mom_emp, mom_rot))
    inf.check(abs(sum(x['fx'] for x in rot['reacciones']) + 200.0) < 1e-3,
              "equilibrio horizontal con rotulas")

    # ------------------------------------------------------------
    print("\n5. Diafragma rigido")
    d = base(cargas_nodales=[{"nodo": 5, "fx": 100.0}])   # carga en UN nodo
    sin_dia = construir_y_resolver(d)
    disp_sin = [ux(sin_dia, n) for n in (5, 6, 7, 8)]

    d = base(cargas_nodales=[{"nodo": 5, "fx": 100.0}])
    d['nodos'].append({"id": 99, "x": 2, "y": 2, "z": 3})
    d['diafragmas'] = [{"nodo_maestro": 99, "nodos": [5, 6, 7, 8], "perpendicular": 3}]
    con_dia = construir_y_resolver(d)
    disp_con = [ux(con_dia, n) for n in (5, 6, 7, 8)]

    inf.check((max(disp_sin) - min(disp_sin)) > 1e-6,
              "sin diafragma los nodos se mueven distinto",
              "rango %.4f mm" % (1000 * (max(disp_sin) - min(disp_sin))))

    # OJO: un diafragma rigido NO obliga a que todos los nodos tengan el
    # mismo ux. El piso se mueve como CUERPO RIGIDO en su plano, y con una
    # carga excentrica ademas ROTA, asi que los ux difieren legitimamente.
    # Lo que si debe cumplirse:
    #   (a) todos los nodos comparten el mismo giro rz
    #   (b) ux_i = ux_m - rz*(y_i - y_m)   y   uy_i = uy_m + rz*(x_i - x_m)
    D = {x['id']: x for x in con_dia['desplazamientos']}
    XY = {5: (0, 0), 6: (0, 4), 7: (4, 0), 8: (4, 4), 99: (2, 2)}
    rz = [D[n]['rz'] for n in (5, 6, 7, 8, 99)]
    inf.check((max(rz) - min(rz)) < 1e-12,
              "todos los nodos del diafragma comparten el giro rz",
              "rango %.2e rad" % (max(rz) - min(rz)))
    xm, ym = XY[99]
    um, vm, rzm = D[99]['ux'], D[99]['uy'], D[99]['rz']
    err_rig = max(abs(D[n]['ux'] - (um - rzm * (XY[n][1] - ym)))
                  + abs(D[n]['uy'] - (vm + rzm * (XY[n][0] - xm)))
                  for n in (5, 6, 7, 8))
    inf.check(err_rig < 1e-9, "cinematica de cuerpo rigido en el plano",
              "error max %.2e m" % err_rig)
    inf.check((max(disp_con) - min(disp_con)) < (max(disp_sin) - min(disp_sin)),
              "el diafragma SI rigidiza (menos deformacion relativa)")
    inf.check(abs(sum(x['fx'] for x in con_dia['reacciones']) + 100.0) < 1e-3,
              "equilibrio con diafragma",
              "%.4f kN" % sum(x['fx'] for x in con_dia['reacciones']))
    inf.check(any("fuera del plano" in a for a in con_dia['avisos']),
              "avisa que restringio el maestro fuera de plano")

    # ------------------------------------------------------------
    print("\n6. Brazos rigidos (muro como columna ancha)")
    # Muro vertical con un nodo colgando a 1 m de su eje. El brazo rigido
    # obliga a que ese nodo siga al del eje del muro.
    d = {"material": {"fpc_MPa": FPC_MPa, "poisson": POISSON},
         "nodos": [{"id": 1, "x": 0, "y": 0, "z": 0, "fijo": True},
                   {"id": 2, "x": 0, "y": 0, "z": 3},
                   {"id": 3, "x": 1, "y": 0, "z": 3}],
         "secciones": SEC,
         "elementos": [{"id": 1, "n1": 1, "n2": 2, "seccion": "muro",
                        "tipo": "muro", "vecxz": [1, 0, 0]}],
         "brazos_rigidos": [{"maestro": 2, "esclavo": 3, "tipo": "beam"}],
         "cargas_nodales": [{"nodo": 3, "fx": 50.0}]}
    r = construir_y_resolver(d)
    n2 = [x for x in r['desplazamientos'] if x['id'] == 2][0]
    n3 = [x for x in r['desplazamientos'] if x['id'] == 3][0]
    inf.check(r['ok'], "el modelo con rigidLink resuelve")
    inf.check(abs(n2['ry'] - n3['ry']) < 1e-12,
              "el nodo colgado gira solidario con el eje del muro",
              "ry eje=%.6e  ry cara=%.6e" % (n2['ry'], n3['ry']))
    # Brazo rigido: ux_esclavo = ux_maestro + ry_maestro * dz, con dz = 0 aca
    inf.check(abs(n3['ux'] - n2['ux']) < 1e-12, "traslacion consistente con el brazo",
              "ux eje=%.6e  ux cara=%.6e" % (n2['ux'], n3['ux']))
    inf.check(abs(sum(x['fx'] for x in r['reacciones']) + 50.0) < 1e-3,
              "equilibrio con rigidLink")

    # ------------------------------------------------------------
    print("\n7. Entradas invalidas")
    d = base(cargas_distribuidas=CARGAS_G)
    d['nodos'][0]['restricciones'] = [1, 1, 1]
    rechaza("restricciones de largo != 6", d, "6 valores")

    d = base(cargas_distribuidas=CARGAS_G)
    d['nodos'][0]['restricciones'] = [1, 1, 2, 0, 0, 0]
    rechaza("restriccion distinta de 0/1", d, "solo acepta 0 o 1")

    d = base(cargas_distribuidas=CARGAS_G)
    d['diafragmas'] = [{"nodo_maestro": 999, "nodos": [5, 6]}]
    rechaza("diafragma con maestro inexistente", d, "no existe")

    d = base(cargas_distribuidas=CARGAS_G)
    d['nodos'].append({"id": 99, "x": 2, "y": 2, "z": 3})
    d['diafragmas'] = [{"nodo_maestro": 99, "nodos": [1, 5, 6]}]
    rechaza("diafragma con nodos a distinta cota", d, "mismo plano")

    d = base(cargas_distribuidas=CARGAS_G)
    d['brazos_rigidos'] = [{"maestro": 5, "esclavo": 5}]
    rechaza("brazo rigido a si mismo", d, "mismo nodo")

    d = base(cargas_distribuidas=CARGAS_G)
    d['elementos'][0]['seccion'] = "inventada"
    rechaza("seccion inexistente", d, "no esta definida")

    d = base(cargas_distribuidas=CARGAS_G)
    d['elementos'][0]['vecxz'] = [0, 0, 1]
    rechaza("vecxz paralelo al eje", d, "paralelo")

    # ------------------------------------------------------------
    print("\n8. Equilibrio por caso en la respuesta")
    CLAVES_EQUILIBRIO = {'aplicada_kN', 'reaccion_kN', 'error_kN',
                         'cargas_sin_convertir', 'nodos_en_diafragma', 'confiable'}
    inf.check(all(set(c.get('equilibrio') or {}) == CLAVES_EQUILIBRIO for c in multi['casos']),
              "cada caso trae 'equilibrio' con las claves de opensees.equilibrio")
    eqG = multi['casos'][0]['equilibrio']
    inf.check(abs(eqG['aplicada_kN'][2] + 179.0) < 1e-3
              and abs(eqG['reaccion_kN'][2] - 179.0) < 1e-3 and eqG['confiable'],
              "marco G: aplicada Fz = -179 kN y reaccion +179",
              "aplicada %s  reaccion %s" % (eqG['aplicada_kN'], eqG['reaccion_kN']))
    inf.check('equilibrio' not in solos['G'] and 'casos' not in solos['G'],
              "la forma plana (un caso) no cambia: sin 'equilibrio'")

    # Con diafragma y la carga en el MAESTRO, que es como llega el sismo.
    # nodeReaction de los nodos del piso trae la fuerza de la restriccion:
    # sumar la lista entera no da -100.
    d = base(casos_de_carga=[{"nombre": "EX", "cargas_nodales": [{"nodo": 99, "fx": 100.0}]}])
    d['nodos'].append({"id": 99, "x": 2, "y": 2, "z": 3})
    d['diafragmas'] = [{"nodo_maestro": 99, "nodos": [5, 6, 7, 8], "perpendicular": 3}]
    dia = construir_y_resolver(d)['casos'][0]
    eq = dia['equilibrio']
    ingenua = sum(x['fx'] for x in dia['reacciones'])
    # 4 apoyos x 5e-5 (el servidor redondea cada reaccion a 4 decimales).
    inf.check(abs(eq['reaccion_kN'][0] + 100.0) <= 4 * 5e-5 and eq['confiable'],
              "con diafragma: reaccion Fx = -100 kN por grado de libertad",
              "reaccion %.4f kN, error %.1e; la suma de TODAS las reacciones daria %.4f"
              % (eq['reaccion_kN'][0], eq['error_kN'][0], ingenua))
    inf.check(eq['nodos_en_diafragma'] == 5, "cuenta los nodos del diafragma (4 + el maestro)",
              "%s" % eq['nodos_en_diafragma'])

    # ------------------------------------------------------------
    ruta = rutas.salida('modelo')
    print("\n9. Equilibrio del edificio completo (%s)" % rel(ruta))
    if not os.path.isfile(ruta):
        inf.check(False, "existe %s (python sap.py exportar modelo)" % rel(ruta))
    else:
        with open(ruta, encoding='utf-8') as f:
            ed = json.load(f)
        rl = construir_y_resolver(copy.deepcopy(ed))
        inf.check(rl['ok'] and len(rl['casos']) == 4, "resuelve los 4 casos",
                  ', '.join(c['nombre'] for c in rl['casos']))
        for c in rl['casos']:
            e = c.get('equilibrio') or {}
            n_reac = len(c['reacciones'])
            escala = max([abs(v) for v in e.get('aplicada_kN', [0.0])] + [1e-9])
            # La cota es su causa: cada reaccion viene redondeada a 4
            # decimales (5e-5 por fila), mas el residuo del solver, que sin
            # redondear se midio en 1.2e-6 kN sobre 3633 kN (3e-10).
            cota = 5e-5 * n_reac + 1e-9 * escala
            peor = max(abs(v) for v in e.get('error_kN', [float('inf')]))
            inf.check(e.get('confiable') is True and peor <= cota,
                      "%s: equilibrio confiable y cierra" % c['nombre'],
                      "aplicada %s  peor error %.1e kN <= cota %.1e (%d reacciones)"
                      % (e.get('aplicada_kN'), peor, cota, n_reac))
        cG = rl['casos'][0]
        eG = cG['equilibrio']
        G, _cota = control('edificio', 'G_kN')
        cota_G = 5e-5 * len(cG['reacciones']) + 1e-9 * abs(eG['aplicada_kN'][2])
        inf.check(cG['nombre'] == 'G' and calza(-eG['aplicada_kN'][2], 'edificio', 'G_kN')
                  and abs(eG['reaccion_kN'][2] + eG['aplicada_kN'][2]) <= cota_G,
                  "G: aplicada Fz = -%.4f kN (numero de control)" % G,
                  "aplicada %.4f  reaccion %.4f kN" % (eG['aplicada_kN'][2], eG['reaccion_kN'][2]))
        eX = next(c for c in rl['casos'] if c['nombre'] == 'EX')
        print("         (EX: la suma de TODAS las reacciones da Fx = %.2f kN "
              "con %.2f aplicados; por GDL, %.2f)"
              % (sum(x['fx'] for x in eX['reacciones']),
                 eX['equilibrio']['aplicada_kN'][0], eX['equilibrio']['reaccion_kN'][0]))

    # ------------------------------------------------------------
    print("\n10. POST /analizar: Excel del reanalisis y errores")
    from exportar import servidor as srv
    inf.check(srv.edificio_del_modelo({'info': {'edificio': 'lt2'}}, 'otro') == 'lt2',
              "nombre del pedido: info.edificio manda")
    inf.check(srv.edificio_del_modelo({'info': {'edificio': ''}}, 'conjunto') == 'conjunto',
              "nombre del pedido: info.edificio vacio -> ?edificio=")
    inf.check(srv.edificio_del_modelo({}, None) == 'modelo',
              "nombre del pedido: sin nada -> 'modelo'")
    inf.check(srv.edificio_del_modelo({'info': {'edificio': '../x'}}, '..\\y') == 'modelo',
              "nombre del pedido: '../x' se descarta entero")

    cliente = srv.app.test_client()
    with libro_en_temporal() as temporal:
        pedido = base(casos_de_carga=[{"nombre": "G", "cargas_distribuidas": CARGAS_G},
                                      {"nombre": "EX", "cargas_nodales": CARGAS_EX}])
        pedido['info'] = {'edificio': 'prueba'}
        resp = cliente.post('/analizar', json=pedido)
        cuerpo = resp.get_json()
        inf.check(resp.status_code == 200 and cuerpo.get('ok') is True, "HTTP 200 y ok",
                  "HTTP %s" % resp.status_code)
        inf.check('excel' in cuerpo and 'excel_error' in cuerpo,
                  "la raiz trae 'excel' y 'excel_error'")
        inf.check(all('equilibrio' in c for c in cuerpo.get('casos', [])),
                  "cada caso trae 'equilibrio' tambien por HTTP")
        esperado = os.path.join(temporal, 'reanalisis.xlsx')
        # Este pedido trae 'secciones' como DICCIONARIO (el motor acepta
        # las dos formas); el escritor del Excel espera la lista de Unity.
        lista = srv.modelo_como_lista(pedido)
        inf.check(isinstance(lista['secciones'], list) and isinstance(pedido['secciones'], dict)
                  and sorted(s['nombre'] for s in lista['secciones']) == sorted(pedido['secciones']),
                  "secciones en diccionario -> lista para el Excel, sin tocar el pedido",
                  ', '.join(s['nombre'] for s in lista['secciones']))
        if cuerpo.get('excel'):
            inf.check(os.path.isabs(cuerpo['excel']) and os.path.isfile(cuerpo['excel'])
                      and os.path.normcase(cuerpo['excel']) == os.path.normcase(esperado)
                      and cuerpo['excel_error'] is None,
                      "el Excel existe donde dice (rutas.salida('reanalisis'), aca en %TEMP%)",
                      cuerpo['excel'])
            from exportar import excel as _excel
            hojas = _excel.estructura(cuerpo['excel'])['hojas']
            inf.check('LEEME' in hojas and 'Resumen' in hojas,
                      "el libro trae LEEME y Resumen", ', '.join(hojas))
        else:
            inf.check(False, "el Excel del reanalisis se escribe",
                      "excel_error = %r" % cuerpo.get('excel_error'))

        # Un escritor que corta con SystemExit (como el codigo del laboratorio)
        # no puede tumbar la respuesta.
        from exportar import excel as modulo_excel
        original_escribir = modulo_excel.escribir_libro_reanalisis

        def _revienta(*_a, **_k):
            raise SystemExit('falla simulada del Excel')
        modulo_excel.escribir_libro_reanalisis = _revienta
        try:
            resp = cliente.post('/analizar', json=pedido)
            cuerpo = resp.get_json()
        finally:
            modulo_excel.escribir_libro_reanalisis = original_escribir
        inf.check(resp.status_code == 200 and cuerpo.get('ok') is True
                  and cuerpo.get('excel') is None
                  and 'SystemExit' in str(cuerpo.get('excel_error'))
                  and len(cuerpo.get('casos', [])) == 2,
                  "un Excel que falla no rompe /analizar",
                  "HTTP %s, excel_error = %r" % (resp.status_code, cuerpo.get('excel_error')))

        resp = cliente.post('/analizar', data='{esto no es json', content_type='application/json')
        cuerpo = resp.get_json(silent=True) or {}
        inf.check(resp.status_code == 400 and cuerpo.get('ok') is False and cuerpo.get('error'),
                  "JSON roto -> HTTP 400 con cuerpo JSON",
                  "HTTP %s: %s" % (resp.status_code, str(cuerpo.get('error'))[:60]))

        malo = copy.deepcopy(pedido)
        malo['elementos'][0]['seccion'] = 'inventada'
        resp = cliente.post('/analizar', json=malo)
        cuerpo = resp.get_json(silent=True) or {}
        inf.check(resp.status_code == 400 and 'no esta definida' in str(cuerpo.get('error')),
                  "seccion inexistente -> HTTP 400 con el motivo",
                  "HTTP %s: %s" % (resp.status_code, str(cuerpo.get('error'))[:60]))

        # RequestEntityTooLarge no hereda de BadRequest: un modelo mas grande
        # que MAX_CONTENT_LENGTH salia como 500, "falla del servidor". Se
        # achica el tope en vez de mandar 32 MB.
        tope_original = srv.app.config['MAX_CONTENT_LENGTH']
        srv.app.config['MAX_CONTENT_LENGTH'] = 100
        try:
            resp = cliente.post('/analizar', json=pedido)
        finally:
            srv.app.config['MAX_CONTENT_LENGTH'] = tope_original
        cuerpo = resp.get_json(silent=True) or {}
        inf.check(resp.status_code == 400 and cuerpo.get('ok') is False
                  and 'MAX_CONTENT_LENGTH' in str(cuerpo.get('error')),
                  "modelo sobre MAX_CONTENT_LENGTH -> HTTP 400 con cuerpo JSON",
                  "HTTP %s: %s" % (resp.status_code, str(cuerpo.get('error'))[:60]))
        inf.check(resp.headers.get('Access-Control-Allow-Origin') == '*' or not srv.PERMITIR_CORS,
                  "CORS para el build Web")

    # ------------------------------------------------------------
    print("\n11. El marco como lo manda JsonUtility, y sus cuatro casos")
    M = marco_como_unity()
    R = construir_y_resolver(copy.deepcopy(M))
    # JsonUtility SIEMPRE escribe todos los campos: los arreglos que Unity no
    # asigno salen como []. El servidor tiene que aceptarlo.
    sim = json.loads(json.dumps(M))
    for n in sim['nodos']:
        if not any(n.get('restricciones', [])):
            n['restricciones'] = []
    for e in sim['elementos']:
        e['vecxz'] = []
    sim['diafragmas'] = []
    sim['brazos_rigidos'] = []
    try:
        R2 = construir_y_resolver(sim)
        g = next(c for c in R2['casos'] if c['nombre'] == 'G')
        uz_mm = next(d for d in g['desplazamientos'] if d['id'] == 5)['uz'] * 1000
        inf.check(True, "el servidor acepta el JSON con listas vacias", "UZ(G) = %.5f mm" % uz_mm)
        inf.check(calza(uz_mm, 'benchmark', 'UZ_techo_mm'), "y da el mismo resultado",
                  "referencia %.5f mm" % ref_mm)
    except Exception as e:
        inf.check(False, "el servidor acepta el JSON con listas vacias", str(e)[:70])
    inf.check([c['nombre'] for c in R['casos']] == ['G', 'Q', 'EX', 'EY'],
              "estan los 4 casos", "%s" % [c['nombre'] for c in R['casos']])
    for c in R['casos']:
        # Sin diafragma, la suma de todas las reacciones SI es el equilibrio.
        s = {'fx': sum(r['fx'] for r in c['reacciones']),
             'fy': sum(r['fy'] for r in c['reacciones']),
             'fz': sum(r['fz'] for r in c['reacciones'])}
        comp, val = EQUILIBRIO_DEL_MARCO[c['nombre']]
        inf.check(abs(s[comp] - val) < 1e-3, "equilibrio %s" % c['nombre'],
                  "%s = %.4f kN (esperado %s)" % (comp, s[comp], val))


# ============================================================
# CASOS DEL MODELO
# ============================================================
def casos_del_modelo(inf, args=None):
    from exportar import modelo as _modelo
    ruta = rutas.salida('casos_del_modelo')
    ruta_visor = rutas.salida('modelo')
    titulo('CASOS DEL MODELO: %s y %s = el edificio resuelto ahora'
           % (rel(ruta), rel(ruta_visor)))
    t = time.time()
    datos = _modelo.casos_del_modelo()
    print('  %s resuelto en %.1f s' % (_ed.NOMBRE, time.time() - t))
    _modelo.imprimir_casos(datos)

    # El archivo contra lo de ahora, por objetos y sin tolerancia: los dos
    # son el mismo motor sobre el mismo edificio.
    nuevo = json.loads(json.dumps(datos))
    if inf.check(os.path.isfile(ruta), 'existe %s' % rel(ruta)):
        with open(ruta, encoding='utf-8') as f:
            disco = json.load(f)
        difs = comparar_json(disco, nuevo)
        inf.check(not difs, '%s = resolver ahora (por objetos, tolerancia 0)' % rel(ruta),
                  difs[:6] + ([] if not difs else ['corre: python sap.py calcular']))

    casos = {c['nombre']: c for c in datos['casos']}
    n_casos, _c = control('edificio', 'casos_del_modelo')
    inf.check([c['nombre'] for c in datos['casos']] == list(lab.CASOS_BASE)
              and len(casos) == n_casos,
              '%d casos del modelo: %s' % (len(casos), ', '.join(casos)))
    print()
    print('  numeros de control (verificacion/numeros_de_control.json, edificio):')
    for nombre, comp, signo, clave in (('G', 2, -1.0, 'G_kN'), ('Q', 2, -1.0, 'Q_del_modelo_kN'),
                                        ('EX', 0, 1.0, 'EX_del_modelo_kN'),
                                        ('EY', 1, 1.0, 'EY_del_modelo_kN')):
        c = casos.get(nombre)
        if c is None:
            inf.check(False, 'el caso %s esta en los casos del modelo' % nombre)
            continue
        aplicada = signo * c['equilibrio']['aplicada_kN'][comp]
        valor, cota = control('edificio', clave)
        inf.check(calza(aplicada, 'edificio', clave),
                  '%s: carga aplicada %.4f kN = %s (cota %.0e)' % (nombre, aplicada, clave, cota))
        mm = c['max_desplazamiento'] * 1000.0
        valor, cota = control('edificio', 'mayor_componente_mm', nombre)
        inf.check(calza(mm, 'edificio', 'mayor_componente_mm', nombre),
                  '%s: mayor componente %.4f mm = %.4f (cota %.0e)' % (nombre, mm, valor, cota))

    # Lo que dibuja el visor sale de la G de esos mismos casos.
    print()
    if inf.check(os.path.isfile(ruta_visor), 'existe %s' % rel(ruta_visor)):
        modelo_visor, _notas = _modelo.construir(caso_G=casos['G'])
        with open(ruta_visor, encoding='utf-8') as f:
            disco = json.load(f)
        difs = comparar_json(disco, json.loads(json.dumps(modelo_visor)))
        inf.check(not difs, '%s = exportar.modelo.construir con la G de ahora '
                  '(por objetos, tolerancia 0)' % rel(ruta_visor),
                  difs[:6] + ([] if not difs else ['corre: python sap.py exportar modelo']))


# ============================================================
# LA EDICION, IGUAL QUE EditorEstructura.cs
# ============================================================
# El servidor redondea cada reaccion a 4 decimales (extraer_resultados).
REDONDEO_REACCION_kN = 5e-5
# Residuo del solver sin redondear, medido en el LT2 (EX: 1.2e-6 kN sobre
# 3633 kN, 3e-10). Se toma 1e-9 relativo: tres veces lo medido.
RESIDUO_RELATIVO = 1e-9
# La deformada G que trae salidas/modelo.json: la devolvio el motor con 8
# decimales y el JSON la guarda tal cual.
TOL_DEFORMADA_m = 1e-7


def borrar_elemento(modelo, eid):
    """
    EditorEstructura.BorrarElemento + QuitarCargasDeElemento: fuera el
    elemento y las cargas distribuidas que lo nombran. No toca los nodos,
    ni las cargas NODALES, ni areas_tributarias. Devuelve {caso: [cargas
    quitadas]}.
    """
    antes = len(modelo['elementos'])
    modelo['elementos'] = [e for e in modelo['elementos'] if int(e['id']) != eid]
    if len(modelo['elementos']) == antes:
        raise SystemExit('el elemento %d no existe en el modelo' % eid)
    quitadas = {}
    for caso in modelo.get('casos_de_carga') or []:
        dist = caso.get('cargas_distribuidas') or []
        quitadas[caso['nombre']] = [c for c in dist if int(c['elemento']) == eid]
        caso['cargas_distribuidas'] = [c for c in dist if int(c['elemento']) != eid]
    return quitadas


def cambiar_seccion(modelo, eid, nombre):
    """
    EditorEstructura: la barra pasa a otra seccion del catalogo. Cambia
    A, Iy, Iz y J, o sea cambia K: exige reanalisis. El peso propio NO
    se recalcula (las cargas de G ya vienen sumadas en el modelo), y por
    eso la carga aplicada no se mueve.
    Devuelve (seccion_antes, seccion_despues) para poder contarlo.
    """
    secciones = {str(x['nombre']): x for x in modelo.get('secciones') or []}
    if nombre not in secciones:
        raise SystemExit('la seccion %r no esta en el modelo. Hay: %s'
                         % (nombre, ', '.join(sorted(secciones))))
    for e in modelo['elementos']:
        if int(e['id']) == eid:
            antes = str(e.get('seccion'))
            e['seccion'] = nombre
            return secciones.get(antes), secciones[nombre]
    raise SystemExit('el elemento %d no existe en el modelo' % eid)


def cambiar_apoyo(modelo, nid, restricciones):
    """
    EditorEstructura: otras restricciones en un nodo. Cambia que grados
    de libertad estan fijos, o sea cambia K: exige reanalisis.
    restricciones son 6 enteros [ux uy uz rx ry rz], 1 = fijo.
    Devuelve (antes, despues).
    """
    if len(restricciones) != 6 or any(v not in (0, 1) for v in restricciones):
        raise SystemExit('el apoyo necesita 6 enteros 0 o 1: [ux uy uz rx ry rz]')
    for n in modelo['nodos']:
        if int(n['id']) == nid:
            antes = list(n.get('restricciones') or ([1] * 6 if n.get('fijo') else [0] * 6))
            n['restricciones'] = list(restricciones)
            # 'fijo' es el atajo de los seis: se mantiene coherente.
            n['fijo'] = all(v == 1 for v in restricciones)
            return antes, list(restricciones)
    raise SystemExit('el nodo %d no existe en el modelo' % nid)


# ============================================================
# LO QUE MANDA UNITY: JsonUtility.ToJson(ModeloEstructural)
# ============================================================
def esquema_csharp(ruta=None):
    """
    {clase: [(campo, tipo, valor por defecto)]} de los campos publicos de
    ModeloEstructural.cs. Se lee del C# y no se copia aca: si alguien
    agrega un campo, la emulacion lo sigue sola. Los [NonSerialized] no
    viajan.
    """
    ruta = ruta or rutas.cs('ModeloEstructural.cs')
    with open(ruta, encoding='utf-8') as f:
        src = f.read()
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)
    clases = {}
    for m in re.finditer(r'class\s+(\w+)\s*(?::\s*[\w\.]+\s*)?\{', src):
        i = j = m.end() - 1
        prof = 0
        while j < len(src):
            prof += {'{': 1, '}': -1}.get(src[j], 0)
            if prof == 0:
                break
            j += 1
        cuerpo = src[i + 1:j]
        # solo el nivel superior de la clase: nada dentro de metodos
        plano, prof = [], 0
        for ch in cuerpo:
            if ch == '{':
                prof += 1
            elif ch == '}':
                prof -= 1
            elif prof == 0:
                plano.append(ch)
        campos = []
        for d in re.finditer(r'(\[[^\]]*\]\s*)*public\s+([\w<>\[\]\.]+)\s+([\w\s,]+?)'
                             r'\s*(?:=\s*([^;]*))?;', ''.join(plano)):
            if d.group(1) and 'NonSerialized' in d.group(1):
                continue
            tipo, defecto = d.group(2), (d.group(4) or '').strip()
            for nombre in d.group(3).split(','):
                nombre = nombre.strip()
                if re.fullmatch(r'\w+', nombre):
                    campos.append((nombre, tipo, defecto))
        clases[m.group(1)] = campos
    return clases


def _float32(v):
    """
    Como queda un numero despues de pasar por Unity: JsonUtility lo lee a
    float de 32 bits y al escribirlo usa el decimal mas corto que vuelve a
    ese mismo float. El servidor lee ese decimal como doble.
    """
    import numpy as np
    return float(np.format_float_positional(np.float32(v), unique=True, trim='0'))


def _defecto(tipo, texto):
    if texto:
        t = texto.rstrip('fF').strip('"')
        if tipo == 'float':
            return float(t)
        if tipo == 'int':
            return int(t)
        if tipo == 'bool':
            return t == 'true'
        return t
    return {'int': 0, 'float': 0.0, 'bool': False, 'string': ''}.get(tipo)


def como_jsonutility(valor, clase, clases):
    """El dict que resulta de FromJson + ToJson: campos del C#, float32,
    string nulo como "", lista nula como [], objeto nulo con sus defaults."""
    valor = valor if isinstance(valor, dict) else {}
    salida = {}
    for nombre, tipo, defecto in clases[clase]:
        v = valor.get(nombre)
        base_ = tipo[5:-1] if tipo.startswith('List<') else (tipo[:-2] if tipo.endswith('[]') else None)
        if base_ is not None:
            v = v if isinstance(v, list) else []
            if base_ in clases:
                salida[nombre] = [como_jsonutility(x, base_, clases) for x in v]
            elif base_ == 'float':
                salida[nombre] = [_float32(x) for x in v]
            elif base_ == 'int':
                salida[nombre] = [int(x) for x in v]
            else:
                salida[nombre] = list(v)
        elif tipo in clases:
            salida[nombre] = como_jsonutility(v, tipo, clases)
        elif v is None:
            salida[nombre] = _defecto(tipo, defecto)
        elif tipo == 'float':
            salida[nombre] = _float32(v)
        elif tipo == 'int':
            salida[nombre] = int(v)
        elif tipo == 'bool':
            salida[nombre] = bool(v)
        else:
            salida[nombre] = v if isinstance(v, str) else str(v)
    return salida


# ============================================================
# RESOLVER: en este proceso o por HTTP
# ============================================================
def url_con_edificio(url, modelo, edificio):
    """
    ClienteReanalisis.UrlConEdificio: si el modelo no trae info.edificio
    (salidas/modelo.json no lo trae), Unity agrega ?edificio=<el de los
    resultados> para que la consola del servidor nombre el pedido.
    """
    info = modelo.get('info') or {}
    if not edificio or info.get('edificio') or 'edificio=' in url:
        return url
    return url + ('&' if '?' in url else '?') + 'edificio=' + urllib.parse.quote(edificio)


def resolver(modelo, url=None, edificio=None):
    """(respuesta, segundos). Con url, POST como ClienteReanalisis."""
    t0 = time.time()
    if url is None:
        with opensees.LOCK:
            resp = construir_y_resolver(copy.deepcopy(modelo))
    else:
        url = url_con_edificio(url, modelo, edificio)
        pedido = urllib.request.Request(
            url, data=json.dumps(modelo).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(pedido, timeout=600) as r:
                resp = json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode('utf-8', 'replace')
            raise SystemExit('el servidor respondio HTTP %d: %s' % (e.code, cuerpo[:400]))
        except urllib.error.URLError as e:
            raise SystemExit('no pude conectar con %s (%s). Levanta el servidor: '
                             'python sap.py servidor' % (url, e.reason))
    if not resp.get('casos'):
        raise SystemExit('la respuesta no trae "casos": %s' % str(resp.get('error'))[:300])
    # Un servidor viejo no trae el equilibrio: se calcula con la MISMA
    # funcion, para no mezclar dos reglas.
    for caso, r in zip(modelo['casos_de_carga'], resp['casos']):
        if not r.get('equilibrio'):
            r['equilibrio'] = opensees.equilibrio(modelo, caso, r)
    return resp, time.time() - t0


# ============================================================
# FORMATO
# ============================================================
def panel(v, formato='0.####', escala=1.0):
    """
    Como lo escribe el C#: `(v*escala).ToString("0.####")` con v float de
    32 bits (EditorEstructura: d.uz*1000f), sin ceros de mas. .NET
    redondea los DIGITOS DECIMALES del float (su forma corta), con la
    mitad hacia afuera: -3.64515f sale -3.6452, aunque el binario de
    -3.64515f este un pelo por debajo. El servidor manda 8 decimales, asi
    que un desplazamiento en mm cae seguido justo en esa mitad: el ultimo
    digito del panel puede diferir en 1 del de la columna en doble.
    """
    from decimal import Decimal, ROUND_HALF_UP
    import numpy as np
    dec = formato.count('#')
    x32 = np.float32(_float32(v)) * np.float32(escala)
    corto = np.format_float_positional(x32, unique=True, trim='0')
    q = Decimal(corto).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    t = format(q, 'f')
    if '.' in t:
        t = t.rstrip('0').rstrip('.')
    return '0' if t in ('-0', '') else t


def por_id(lista):
    return {int(x['id']): x for x in lista}


def cota_equilibrio(r):
    eq = r['equilibrio']
    escala = max([abs(v) for v in eq['aplicada_kN']] + [1e-9])
    return REDONDEO_REACCION_kN * len(r['reacciones']) + RESIDUO_RELATIVO * escala


def sumar_distribuidas(modelo, caso_nombre, cargas):
    """Resultante global [Fx, Fy, Fz] de unas cargas distribuidas, con la
    misma conversion de ejes que opensees.equilibrio."""
    caso = {'nombre': caso_nombre, 'cargas_nodales': [], 'cargas_distribuidas': cargas}
    return opensees.equilibrio(modelo, caso, {'reacciones': []})['aplicada_kN']


# ============================================================
# EL REANALISIS DE UNA MODIFICACION (M1, M3, M4)
# ============================================================
def reanalizar(inf, original, ruta, borrar=(), secciones=(), apoyos=(), desde=None,
               nodo=None, extra=(), float32=False, url=None):
    r"""
    Lo que hace la demo en Unity, en memoria: la edicion de
    EditorEstructura sobre el modelo del visor, el antes y el despues
    resueltos y lo que cambio. Imprime lo mismo que el panel y devuelve
    (antes, despues, respuestas) para las comprobaciones de cada
    modificacion. Las fallas van a inf.

    borrar     [id]                      barras a borrar
    secciones  [(id, nombre)]            M3: la barra pasa a esa seccion
    apoyos     [(nodo, [6 enteros])]     M4: otras restricciones
    desde      ruta de un JSON ya editado (Guardar JSON de Unity)
    nodo       el nodo que se sigue
    extra      barras cuyos esfuerzos mostrar ademas de las del nodo
    """
    antes = copy.deepcopy(original)
    quitadas = {}
    ediciones = []
    if desde:
        with open(desde, encoding='utf-8-sig') as f:
            despues = json.load(f)
    else:
        despues = copy.deepcopy(original)
        for eid in borrar:
            for caso, lista in borrar_elemento(despues, eid).items():
                quitadas.setdefault(caso, []).extend(lista)
        for eid, nombre in secciones:
            sa, sd = cambiar_seccion(despues, int(eid), nombre)
            ediciones.append(
                'seccion del elemento %s: %s -> %s  (A %.4f -> %.4f m2, '
                'Iy %.3e -> %.3e, Iz %.3e -> %.3e m4)'
                % (eid, (sa or {}).get('nombre', '?'), nombre,
                   float((sa or {}).get('A', 0.0)), float(sd.get('A', 0.0)),
                   float((sa or {}).get('Iy', 0.0)), float(sd.get('Iy', 0.0)),
                   float((sa or {}).get('Iz', 0.0)), float(sd.get('Iz', 0.0))))
        for nid, r in apoyos:
            antes_r, despues_r = cambiar_apoyo(despues, int(nid), [int(v) for v in r])
            ediciones.append('apoyo del nodo %d: %s -> %s' % (int(nid), antes_r, despues_r))

    if float32:
        clases = esquema_csharp()
        antes = como_jsonutility(antes, 'ModeloEstructural', clases)
        despues = como_jsonutility(despues, 'ModeloEstructural', clases)

    print('=' * 76)
    print('  REANALISIS  %s   (lo que hace Unity: editar -> POST /analizar -> dibujar)'
          % _ed.NOMBRE.upper())
    print('=' * 76)
    casos = [c['nombre'] for c in original.get('casos_de_carga', [])]
    print('  modelo    %s  (%d nodos, %d elementos, casos %s)'
          % (rel(ruta), len(original['nodos']), len(original['elementos']), ', '.join(casos)))
    for c in ediciones:
        print('  edicion   %s' % c)
    if ediciones:
        print('            cambia K -> exige reanalisis')
    print('  motor     %s' % ('POST ' + url if url else
                              'opensees.construir_y_resolver, en este proceso'))
    print('  numeros   %s' % ('como JsonUtility: float32 y solo los campos de '
                              'ModeloEstructural.cs' if float32 else
                              'los del JSON, en doble precision'))

    nodos0 = por_id(original['nodos'])
    elems0 = por_id(original['elementos'])
    elems1 = por_id(despues['elementos'])
    mat = original.get('material', {})
    gamma = float(mat.get('gamma', 25.0))
    secs = {s['nombre']: s for s in original['secciones']} \
        if isinstance(original['secciones'], list) else original['secciones']

    # ---------------------------------------------------------- la edicion
    print()
    borrados = sorted(set(elems0) - set(elems1))
    agregados = sorted(set(elems1) - set(elems0))
    if desde:
        print('  EDICION leida de %s' % desde)
        print('    elementos borrados %s, agregados %s' % (borrados or '-', agregados or '-'))
        movidos = [n for n, nd in por_id(despues['nodos']).items()
                   if n in nodos0 and max(abs(float(nd[k]) - float(nodos0[n][k]))
                                          for k in ('x', 'y', 'z')) > 1e-4]
        print('    nodos movidos (> 0.1 mm) %s' % (movidos or '-'))
        cambios = [e for e in elems1 if e in elems0
                   and elems1[e]['seccion'] != elems0[e]['seccion']]
        print('    secciones cambiadas %s' % (cambios or '-'))
    else:
        print('  EDICION  (%s)'
              % ('EditorEstructura: seccion o apoyo' if ediciones
                 else 'EditorEstructura.BorrarElemento + QuitarCargasDeElemento'))
    peso_que_queda = 0.0
    for eid in borrados:
        e = elems0[eid]
        a, b = nodos0[int(e['n1'])], nodos0[int(e['n2'])]
        L = math.dist((a['x'], a['y'], a['z']), (b['x'], b['y'], b['z']))
        print('    borrar %d: %s %s, nodos %d (z %.2f) -> %d (z %.2f), L = %.2f m'
              % (eid, e['tipo'], e['seccion'], a['id'], a['z'], b['id'], b['z'], L))
        n_q = sum(len(v) for v in quitadas.values())
        if not desde:
            print('    cargas distribuidas quitadas: %d  (%s)'
                  % (n_q, ', '.join('%s %d' % (c, len(v)) for c, v in quitadas.items())))
        vertical = abs(a['x'] - b['x']) < 1e-6 and abs(a['y'] - b['y']) < 1e-6
        if vertical:
            A = float(secs[e['seccion']]['A'])
            peso = A * gamma * L
            peso_que_queda += peso
            g = next((c for c in original['casos_de_carga'] if c['nombre'] == 'G'), None)
            nodales = {int(c['nodo']): float(c.get('fz', 0.0))
                       for c in (g or {}).get('cargas_nodales', [])}
            print('    PESO PROPIO QUE QUEDA APLICADO: A*gamma*L = %.4g*%.4g*%.2f = %.2f kN,'
                  % (A, gamma, L, peso))
            print('      que viaja como carga NODAL de G, mitad en cada extremo '
                  '(asi lo trae el caso G del edificio).')
            print('      BorrarElemento no toca cargas nodales: siguen fz = %.3f kN en %d '
                  'y %.3f en %d' % (nodales.get(b['id'], 0.0), b['id'],
                                    nodales.get(a['id'], 0.0), a['id']))
            print('      (%.3f de cada uno eran de esta barra).' % (peso / 2.0))

    if nodo is None:
        if not borrados:
            raise SystemExit('con --desde hay que decir el nodo')
        e = elems0[borrados[0]]
        n1, n2 = nodos0[int(e['n1'])], nodos0[int(e['n2'])]
        nodo = int(n2['id'] if n2['z'] >= n1['z'] else n1['id'])
    if nodo not in nodos0:
        raise SystemExit('el nodo %d no existe' % nodo)

    # ---------------------------------------------------------- resolver
    r0, t0 = resolver(antes, url, _ed.NOMBRE)
    r1, t1 = resolver(despues, url, _ed.NOMBRE)
    print()
    print('  resuelto: antes %.1f s, despues %.1f s' % (t0, t1))
    if url:
        # Los dos pedidos escriben el MISMO libro: queda el del despues.
        for nombre, r in (('antes', r0), ('despues', r1)):
            print('  Excel del servidor (%s): %s' % (nombre, r.get('excel') or
                                                    'no -- %s' % r.get('excel_error')))

    def check(cond, texto, detalle=''):
        print('    [%s] %s%s' % ('OK  ' if cond else 'FALLA', texto,
                                 ('   ' + detalle) if detalle else ''))
        if not cond:
            inf.fallas.append(texto)

    c0 = {c['nombre']: c for c in r0['casos']}
    c1 = {c['nombre']: c for c in r1['casos']}

    # ---------------------------------------------------------- nodo
    n = nodos0[nodo]
    print()
    print('  NODO %d  (x %.3f, y %.3f, z %.2f)   mm, con los 8 decimales en m del servidor;'
          % (nodo, n['x'], n['y'], n['z']))
    print('    entre comillas, lo que escribe el panel del editor en Unity ("0.####" de un float)')
    print('    caso  comp        antes       despues    panel antes -> despues')
    for caso in casos:
        d0 = por_id(c0[caso]['desplazamientos']).get(nodo)
        d1 = por_id(c1[caso]['desplazamientos']).get(nodo)
        for k in ('ux', 'uy', 'uz'):
            v0 = d0[k] * 1000.0 if d0 else float('nan')
            v1 = d1[k] * 1000.0 if d1 else float('nan')
            print('    %-4s  %-2s  %12.5f  %12.5f    "%s %s mm" -> "%s %s mm"'
                  % (caso, k.upper(), v0, v1,
                     k.upper(), panel(d0[k], escala=1000.0) if d0 else '-',
                     k.upper(), panel(d1[k], escala=1000.0) if d1 else '-'))

    # ---------------------------------------------------------- maximos
    print()
    print('  MAXIMO POR CASO  (max_desplazamiento: la mayor COMPONENTE |ux|,|uy|,|uz|;')
    print('                    en Unity: Console "[caso] Max desplazamiento = ... mm")')
    for caso in casos:
        m0, m1_ = c0[caso]['max_desplazamiento'] * 1000, c1[caso]['max_desplazamiento'] * 1000
        print('    %-4s  %10.5f -> %10.5f mm   (x %.2f)' % (caso, m0, m1_, m1_ / m0 if m0 else 0))

    # ---------------------------------------------------------- barras
    vecinas = sorted({int(e['id']) for e in despues['elementos']
                      if nodo in (int(e['n1']), int(e['n2']))} | set(extra))
    print()
    print('  BARRAS EN EL NODO %d, caso G   (ejes locales; el panel muestra N_i, Vz_i, My_i / My_j)'
          % nodo)
    f0 = por_id(c0['G']['fuerzas_elementos']) if 'G' in c0 else {}
    f1 = por_id(c1['G']['fuerzas_elementos']) if 'G' in c1 else {}
    for eid in vecinas:
        e = elems1[eid] if eid in elems1 else elems0.get(eid)
        if e is None:
            continue
        print('    %d  %s %s  nodos %d -> %d' % (eid, e['tipo'], e['seccion'], e['n1'], e['n2']))
        for nombre, f in (('antes', f0.get(eid)), ('despues', f1.get(eid))):
            if f is None:
                print('      %-7s (no existe)' % nombre)
                continue
            v = f['f']
            print('      %-7s N %10.3f  Vz %9.3f  My %10.3f / %10.3f kN*m   '
                  '"My %s / %s kN*m"'
                  % (nombre, v[0], v[2], v[4], v[10], panel(v[4], '0.###'),
                     panel(v[10], '0.###')))

    # ---------------------------------------------------------- equilibrio
    print()
    print('  EQUILIBRIO POR CASO  (opensees.equilibrio: reacciones por grado de libertad)')
    print('    caso  antes/despues   aplicada [Fx, Fy, Fz] kN          '
          'reaccion [Fx, Fy, Fz] kN          peor error')
    for caso in casos:
        for nombre, r in (('antes', c0[caso]), ('despues', c1[caso])):
            eq = r['equilibrio']
            print('    %-4s  %-7s  [%9.3f, %9.3f, %10.3f]  [%9.3f, %9.3f, %10.3f]  %.1e'
                  % (caso, nombre, *eq['aplicada_kN'], *eq['reaccion_kN'],
                     max(abs(x) for x in eq['error_kN'])))

    # ---------------------------------------------------------- comprobaciones
    print()
    print('  COMPROBACIONES')
    peor, cual = 0.0, None
    if 'G' in c0:
        for d in c0['G']['desplazamientos']:
            nd = nodos0.get(int(d['id']))
            if nd is None or 'ux' not in nd:
                continue
            for k in ('ux', 'uy', 'uz'):
                err = abs(float(d[k]) - float(nd[k]))
                if err > peor:
                    peor, cual = err, (d['id'], k)
        check(peor < TOL_DEFORMADA_m + (2e-8 if float32 else 0.0),
              'el "antes" es la deformada G que Unity dibuja sin servidor',
              'peor %.1e m en %s' % (peor, cual))
    check(all(c['ok'] for c in r0['casos']) and all(c['ok'] for c in r1['casos']),
          'todos los casos convergen, antes y despues')
    for caso in casos:
        for nombre, r in (('antes', c0[caso]), ('despues', c1[caso])):
            eq = r['equilibrio']
            peor_eq, cota = max(abs(x) for x in eq['error_kN']), cota_equilibrio(r)
            check(eq['confiable'] and peor_eq <= cota,
                  'equilibrio %s %s confiable y cierra' % (caso, nombre),
                  '%.1e <= %.1e kN' % (peor_eq, cota))
    if not desde:
        for caso in casos:
            quitada = sumar_distribuidas(original, caso, quitadas.get(caso, []))
            a0, a1 = c0[caso]['equilibrio']['aplicada_kN'], c1[caso]['equilibrio']['aplicada_kN']
            dif = max(abs((a1[i] - a0[i]) + quitada[i]) for i in range(3))
            # aplicada_kN viene redondeada a 4 decimales: dos lecturas.
            check(dif <= 2 * 5e-5 + 1e-9 * max(abs(v) for v in a0 + [1.0]),
                  'la carga aplicada en %s cambia solo en lo que quito el editor' % caso,
                  'quitado [%.3f, %.3f, %.3f] kN, dif %.1e' % (*quitada, dif))

    print()
    if peso_que_queda:
        print('  OJO: %.2f kN de peso propio de lo borrado siguen aplicados como carga '
              'nodal en G.' % peso_que_queda)
    print('  No se escribio nada en salidas/.%s'
          % ('  (El servidor escribe su Excel en salidas/reanalisis.xlsx.)' if url else ''))
    return {'antes': c0, 'despues': c1, 'nodo': nodo, 'check': check,
            'peso_que_queda': peso_que_queda}


def _modificacion(clave):
    """La modificacion de entrada/laboratorio.json#modificaciones."""
    mods = lab.bloque('modificaciones')
    if clave not in mods:
        raise SystemExit('entrada/laboratorio.json no trae modificaciones.%s' % clave)
    return mods[clave]


def _opciones(args):
    return {'float32': bool(getattr(args, 'float32', False)),
            'url': getattr(args, 'url', None), 'desde': getattr(args, 'desde', None)}


def m1(inf, args=None):
    mod = _modificacion('M1')
    original, ruta = leer_modelo_del_visor()
    nodo = int(mod['nodo'])
    r = reanalizar(inf, original, ruta, borrar=[int(mod['borrar_elemento'])], nodo=nodo,
                   extra=[int(mod['elemento'])] if 'elemento' in mod else [], **_opciones(args))
    # Los numeros de control de la M1 (numeros_de_control.json, m1): el
    # nodo que se sigue tiene que ser el de esos numeros.
    print()
    print('  NUMEROS DE CONTROL DE LA M1')
    check = r['check']
    n_control, _c = control('m1', 'nodo')
    check(nodo == n_control, 'el nodo de la M1 (laboratorio.json) es el de los numeros de '
          'control: %d' % n_control)
    # Con --desde el "despues" es lo que el usuario edito en Unity, que
    # puede no ser la M1: solo el "antes" tiene numero de control.
    comparar = [('uz_G_antes_mm', r['antes'], 'antes')]
    if not getattr(args, 'desde', None):
        comparar.append(('uz_G_despues_mm', r['despues'], 'despues'))
    for clave, casos, etiqueta in comparar:
        d = por_id(casos['G']['desplazamientos']).get(nodo)
        v = d['uz'] * 1000.0 if d else float('nan')
        valor, cota = control('m1', clave)
        check(d is not None and calza(v, 'm1', clave),
              '%s: UZ%d (G) = %.5f mm' % (etiqueta, nodo, valor),
              '%.5f mm, cota %.0e' % (v, cota))
    if not getattr(args, 'desde', None):
        mG = r['despues']['G']['max_desplazamiento'] * 1000.0
        valor, cota = control('m1', 'uz_G_despues_mm')
        check(abs(mG - abs(valor)) <= cota * (1 + 1e-9),
              'despues: el maximo de G es ese nodo, %.5f mm' % abs(valor), '%.5f mm' % mG)


def m3(inf, args=None):
    mod = _modificacion('M3')
    original, ruta = leer_modelo_del_visor()
    reanalizar(inf, original, ruta, secciones=[(int(mod['elemento']), mod['seccion'])],
               nodo=int(mod['nodo']), **_opciones(args))


def m4(inf, args=None):
    mod = _modificacion('M4')
    original, ruta = leer_modelo_del_visor()
    reanalizar(inf, original, ruta,
               apoyos=[(int(mod['nodo_apoyo']), [int(v) for v in mod['restricciones']])],
               nodo=int(mod['nodo']), **_opciones(args))


# ============================================================
# REANALISIS = MODELO
# ============================================================
def reanalisis(inf, args=None):
    r"""
    Que REANALIZAR desde el JSON reproduzca lo que calculo Python. Cuando
    se modifica el modelo en Unity, el servidor lo reconstruye A PARTIR
    DEL JSON: si el JSON no describe exactamente el mismo problema, los
    numeros cambian y nadie se entera. Asi paso dos veces: el caso G sin
    el peso propio de vigas, columnas y muros (10.04 mm contra 11.78), y
    las inercias exportadas ya cruzadas, que el motor cruzaba otra vez
    (12.17 mm). Los muros (columna ancha con su vecxz propio) y los
    brazos rigidos (barras de seccion grande) dependen de que el motor
    lea el vecxz y la seccion que viajan en el JSON.
    """
    from exportar import servidor as srv
    modelo, ruta = leer_modelo_del_visor()
    titulo('REANALISIS: POST /analizar con %s = el modelo de Python' % rel(ruta))
    print('Modelo: %d nodos, %d elementos' % (len(modelo['nodos']), len(modelo['elementos'])))
    mod = _modificacion('M1')
    elemento_m1, nodo_m1 = int(mod['borrar_elemento']), int(mod['nodo'])
    cliente = srv.app.test_client()

    def analizar(m, que):
        """POST /analizar; None (y FALLA) si el servidor no lo acepta."""
        resp = cliente.post('/analizar', json=m)
        cuerpo = resp.get_json(silent=True) or {}
        if resp.status_code != 200:
            inf.check(False, 'el servidor acepta %s' % que,
                      'HTTP %d: %s' % (resp.status_code, str(cuerpo.get('error'))[:300]))
            return None
        return cuerpo

    def revisar_equilibrio(resp, que):
        """Cada caso trae 'equilibrio' confiable y cerrado a su cota: 5e-5 kN
        por reaccion (redondeo a 4 decimales) + 1e-9 relativo (residuo del
        solver medido: 1.2e-6 kN sobre 3633 kN)."""
        for c in resp.get('casos') or []:
            e = c.get('equilibrio') or {}
            if not e.get('aplicada_kN'):
                inf.check(False, "%s: el caso %s trae 'equilibrio'" % (que, c.get('nombre')))
                continue
            escala = max(abs(v) for v in e['aplicada_kN'])
            cota = 5e-5 * len(c['reacciones']) + 1e-9 * escala
            peor = max(abs(v) for v in e['error_kN'])
            inf.check(e.get('confiable') is True and peor <= cota,
                      '%s: equilibrio %s confiable y cierra' % (que, c['nombre']),
                      'aplicada %s  peor error %.1e <= %.1e kN' % (e['aplicada_kN'], peor, cota))

    def uz_mm(resp, caso, nodo):
        c = next(x for x in resp['casos'] if x['nombre'] == caso)
        return next(float(d['uz']) for d in c['desplazamientos'] if int(d['id']) == nodo) * 1000.0

    with libro_en_temporal():
        # ------------------------------------------------------------
        print("\n[1] El servidor responde")
        r = cliente.get('/ping')
        inf.check(r.status_code == 200 and (r.get_json(silent=True) or {}).get('estado') == 'vivo',
                  'el servidor contesta /ping')

        # ------------------------------------------------------------
        print("\n[2] Acepta el modelo completo del edificio")
        resp = analizar(modelo, 'el modelo')
        if resp is None:
            return
        inf.check(resp.get('ok') is True, 'el analisis resuelve', str(resp.get('error', ''))[:200])
        casos = resp.get('casos') or []
        desp = (casos[0].get('desplazamientos') if casos else resp.get('desplazamientos')) or []
        inf.check(len(desp) > 0, 'devuelve desplazamientos', '%d nodos' % len(desp))

        # ------------------------------------------------------------
        print("\n[3] Reproduce EXACTAMENTE el analisis de Python")
        # La deformada precalculada viaja en los propios nodos del JSON.
        previo = {n['id']: n for n in modelo['nodos']}
        peor, cual = 0.0, None
        comparados = 0
        for d in desp:
            n = previo.get(d['id'])
            if n is None:
                continue
            comparados += 1
            for k in ('ux', 'uy', 'uz'):
                e = abs(float(d[k]) - float(n[k]))
                if e > peor:
                    peor, cual = e, (d['id'], k)
        inf.check(comparados > 200, 'se comparan todos los nodos', '%d nodos comparados' % comparados)
        inf.check(peor < TOL_DEFORMADA_m,
                  'el reanalisis da los mismos desplazamientos que la G del modelo',
                  'peor diferencia %.3e m en %s' % (peor, cual))
        # Un chequeo de orden de magnitud, por si algun dia el JSON
        # quedara con la deformada en cero y todo "coincidiera".
        uz_max = max(abs(float(n['uz'])) for n in modelo['nodos'])
        inf.check(uz_max > 1e-4, 'la deformada de referencia no es trivialmente cero',
                  'UZ maximo %.3f mm' % (uz_max * 1000))
        # Y los cuatro casos, contra salidas/casos_del_modelo.json: el mismo
        # motor sobre el mismo edificio, sin tolerancia.
        ruta_casos = rutas.salida('casos_del_modelo')
        if inf.check(os.path.isfile(ruta_casos), 'existe %s' % rel(ruta_casos)):
            with open(ruta_casos, encoding='utf-8') as f:
                del_modelo = {c['nombre']: c for c in json.load(f)['casos']}
            difs = []
            for c in casos:
                ref = del_modelo.get(c['nombre'])
                if ref is None:
                    difs.append('%s: no esta en %s' % (c['nombre'], rel(ruta_casos)))
                    continue
                for clave in ('desplazamientos', 'reacciones', 'fuerzas_elementos',
                              'max_desplazamiento'):
                    difs += comparar_json(ref[clave], c[clave], ruta='%s.%s' % (c['nombre'], clave))
            inf.check(not difs and len(casos) == len(del_modelo),
                      'los %d casos de /analizar = %s (desplazamientos, reacciones, fuerzas y '
                      'maximo; tolerancia 0)' % (len(casos), rel(ruta_casos)), difs[:6])

        # ------------------------------------------------------------
        print("\n[4] La respuesta trae el equilibrio y el Excel")
        revisar_equilibrio(resp, 'sin editar')
        eG = next((c.get('equilibrio') or {} for c in casos if c['nombre'] == 'G'), {})
        G, _cota = control('edificio', 'G_kN')
        inf.check(calza(-float((eG.get('aplicada_kN') or [0, 0, 0])[2]), 'edificio', 'G_kN'),
                  'G aplicada = -%.4f kN (numero de control)' % G, '%s' % eG.get('aplicada_kN'))
        inf.check('excel' in resp and 'excel_error' in resp
                  and (resp['excel'] is None) != (resp['excel_error'] is None),
                  "la raiz trae 'excel' o 'excel_error' (uno de los dos)",
                  'excel = %r  excel_error = %r' % (resp.get('excel'),
                                                    str(resp.get('excel_error'))[:90]))
        if resp.get('excel'):
            inf.check(os.path.isfile(resp['excel']), 'el Excel existe donde dice (en %TEMP%)',
                      resp['excel'])

        # ------------------------------------------------------------
        print("\n[5] M1: borrar la columna %d como en Unity y reanalizar" % elemento_m1)
        clases = esquema_csharp()
        antes_unity = como_jsonutility(modelo, 'ModeloEstructural', clases)
        editado = json.loads(json.dumps(modelo))
        quitadas = borrar_elemento(editado, elemento_m1)
        despues_unity = como_jsonutility(editado, 'ModeloEstructural', clases)
        inf.check(len(despues_unity['elementos']) == len(modelo['elementos']) - 1
                  and len(despues_unity['nodos']) == len(modelo['nodos']),
                  'la edicion quita una barra y ningun nodo',
                  '%d elementos, %d nodos; cargas distribuidas quitadas %d'
                  % (len(despues_unity['elementos']), len(despues_unity['nodos']),
                     sum(len(v) for v in quitadas.values())))

        r_antes = analizar(antes_unity, 'el modelo como lo manda Unity')
        r_desp = analizar(despues_unity, 'el modelo editado')
        if r_antes and r_desp:
            inf.check(r_antes.get('ok') is True and r_desp.get('ok') is True,
                      'los dos analisis resuelven')
            ua, ud = uz_mm(r_antes, 'G', nodo_m1), uz_mm(r_desp, 'G', nodo_m1)
            v_antes, c_antes = control('m1', 'uz_G_antes_mm')
            v_desp, c_desp = control('m1', 'uz_G_despues_mm')
            inf.check(calza(ua, 'm1', 'uz_G_antes_mm'),
                      'antes: UZ%d (G) = %.5f mm' % (nodo_m1, v_antes), '%.5f mm' % ua)
            inf.check(calza(ud, 'm1', 'uz_G_despues_mm'),
                      'despues: UZ%d (G) = %.5f mm' % (nodo_m1, v_desp), '%.5f mm' % ud)
            mG = next(c for c in r_desp['casos'] if c['nombre'] == 'G')['max_desplazamiento'] * 1000
            inf.check(abs(mG - abs(v_desp)) <= c_desp * (1 + 1e-9),
                      'despues: maximo G = %.5f mm' % abs(v_desp), '%.5f mm' % mG)
            revisar_equilibrio(r_antes, 'antes (float32)')
            revisar_equilibrio(r_desp, 'despues')
            fz = [next(c for c in r['casos'] if c['nombre'] == 'G')['equilibrio']['aplicada_kN'][2]
                  for r in (r_antes, r_desp)]
            # La columna no tenia carga repartida y su peso propio es nodal:
            # la carga de G no cambia. Es la limitacion que se declara.
            inf.check(abs(fz[1] - fz[0]) <= 2 * 5e-5 and calza(-fz[1], 'edificio', 'G_kN'),
                      'G aplicada no cambia: el peso propio de la columna queda aplicado',
                      '%.4f -> %.4f kN' % (fz[0], fz[1]))


# ============================================================
# LA VIGA PARTIDA NO ES UNA ROTULA
# ============================================================
# El punto medio de una viga partida del cuerpo antiguo: llega una viga
# perpendicular con su losa y no hay columna debajo. Es el que se ve
# hundido en el visor.
NODO_VIGA_PARTIDA = 100373
# Cada uz viene redondeado a 8 decimales en m: dos lecturas de la misma
# flecha pueden diferir en un paso, 1e-8 m = 1e-5 mm.
COTA_REFINAR_mm = 2 * 0.5e-8 * 1000.0


def uz_en(modelo, nodo):
    datos = copy.deepcopy(modelo)
    datos['casos_de_carga'] = [c for c in datos['casos_de_carga'] if c['nombre'] == 'G']
    r = construir_y_resolver(datos)['casos'][0]
    d = {int(x['id']): x for x in r['desplazamientos']}
    return {n: float(d[n]['uz']) * 1000 for n in nodo}


def candidatos(modelo):
    """
    Los nodos interesantes, como LISTA de enteros: donde dos vigas
    alineadas se juntan, llega una perpendicular y NO hay columna. Son
    los que se ven hundidos.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    porta = {}
    apoyado = set()
    for e in modelo['elementos']:
        t = e.get('tipo', '')
        for nid in (int(e['n1']), int(e['n2'])):
            if t in ('columna', 'muro', 'pilar_metal'):
                apoyado.add(nid)
            elif t.startswith('viga'):
                porta.setdefault(nid, []).append(e)

    def eje(e):
        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        d = [float(b[k]) - float(a[k]) for k in ('x', 'y', 'z')]
        return max(range(3), key=lambda i: abs(d[i]))

    salida = []
    for nid, vigas in sorted(porta.items()):
        if nid in apoyado or len(vigas) < 3:
            continue
        ejes = {}
        for e in vigas:
            ejes.setdefault(eje(e), 0)
            ejes[eje(e)] += 1
        # dos alineadas mas al menos una perpendicular
        if max(ejes.values()) >= 2 and len(ejes) >= 2:
            salida.append(nid)
    return salida


def lista_de(modelo, cuantos=12):
    """Los mismos, en una linea, para los mensajes."""
    return ', '.join(str(n) for n in candidatos(modelo)[:cuantos]) or '(ninguno)'


def buscar_tramos(modelo, nodo_medio):
    """Los dos elementos de viga que se juntan en ese nodo, y sus otros
    extremos. Es la viga que uno diria que esta 'cortada'."""
    tramos = [e for e in modelo['elementos']
              if e.get('tipo', '').startswith('viga')
              and nodo_medio in (int(e['n1']), int(e['n2']))]
    # De los que llegan, la pareja alineada: misma seccion y misma
    # direccion. Los perpendiculares son justamente los que obligan a
    # que exista el nodo.
    nodos = {int(n['id']): n for n in modelo['nodos']}

    def eje(e):
        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        d = [float(b[k]) - float(a[k]) for k in ('x', 'y', 'z')]
        return max(range(3), key=lambda i: abs(d[i]))

    por_eje = {}
    for e in tramos:
        por_eje.setdefault(eje(e), []).append(e)
    linea = max(por_eje.values(), key=len) if por_eje else []
    if len(linea) < 2:
        raise SystemExit(
            'el nodo %d no es el punto medio de una viga partida.\n'
            'Nodos que si lo son en este edificio: %s'
            % (nodo_medio, lista_de(modelo)))
    extremos = [int(e['n1']) if int(e['n2']) == nodo_medio else int(e['n2'])
                for e in linea]
    return [int(e['id']) for e in linea], extremos


def viga_partida(inf, args=None):
    r"""
    Dos elementos que comparten un nodo comparten sus SEIS grados de
    libertad: el momento pasa entero. El nodo esta ahi porque sin el la
    viga perpendicular no tendria donde apoyarse. La prueba es refinar:
    si el corte fuera el problema, mas tramos cambiarian la respuesta.
    Se parten los dos tramos en 2, 4 y 8 (edificio.subdividir) y se mide
    cuanto de la flecha trae la viga perpendicular con su losa.
    """
    numeros = list(getattr(args, 'numeros', None) or [])
    BASE = _ed.estructura()
    medio = numeros[0] if numeros else NODO_VIGA_PARTIDA
    partidas, extremos = buscar_tramos(BASE, medio)
    mirar = [extremos[0], medio, extremos[-1]]

    nodos = {int(n['id']): n for n in BASE['nodos']}
    a, b = nodos[mirar[0]], nodos[mirar[-1]]
    largo = sum((float(b[k]) - float(a[k])) ** 2 for k in ('x', 'y', 'z')) ** 0.5
    perp = [int(e['id']) for e in BASE['elementos']
            if e.get('tipo', '').startswith('viga')
            and int(e['id']) not in partidas
            and medio in (int(e['n1']), int(e['n2']))]
    apoyo = [e['tipo'] for e in BASE['elementos']
             if e.get('tipo') in ('columna', 'muro', 'pilar_metal')
             and medio in (int(e['n1']), int(e['n2']))]

    print('=' * 74)
    print('  LA VIGA PARTIDA DEL NODO %d   (%s)' % (medio, _ed.NOMBRE))
    print('=' * 74)
    print('  tramos %s, del nodo %d al %d, %.2f m en total'
          % (partidas, mirar[0], mirar[-1], largo))
    print('  en el nodo %d llegan ademas %s' % (medio, perp or 'nada'))
    print('  apoyo vertical en el nodo %d: %s' % (medio, apoyo or 'NINGUNO'))
    print()
    print('  Si el corte fuera el problema, refinar cambiaria la respuesta.')
    print()
    print('  %-28s %10s %10s %10s %12s'
          % ('malla', 'uz %d' % mirar[0], 'uz %d' % medio,
             'uz %d' % mirar[-1], 'flecha rel.'))
    rel0, u0, peor = None, None, 0.0
    for veces in (1, 2, 4, 8):
        m = BASE if veces == 1 else _ed.subdividir(BASE, partidas, veces)
        u = uz_en(m, mirar)
        rel_ = u[medio] - (u[mirar[0]] + u[mirar[-1]]) / 2.0
        if rel0 is None:
            rel0, u0 = rel_, u
        peor = max([peor] + [abs(u[n] - u0[n]) for n in mirar])
        print('  %-28s %10.4f %10.4f %10.4f %12.4f'
              % ('como esta (%d tramos)' % len(partidas) if veces == 1
                 else '%d tramos por mitad' % veces,
                 u[mirar[0]], u[medio], u[mirar[-1]], rel_))

    # Sin la losa que trae la viga perpendicular.
    sin = copy.deepcopy(BASE)
    for c in sin['casos_de_carga']:
        c['cargas_distribuidas'] = [x for x in c.get('cargas_distribuidas', [])
                                    if int(x['elemento']) not in perp]
    u = uz_en(sin, mirar)
    rel_sin = u[medio] - (u[mirar[0]] + u[mirar[-1]]) / 2.0
    print('  %-28s %10.4f %10.4f %10.4f %12.4f'
          % ('sin la losa de la perpendicular',
             u[mirar[0]], u[medio], u[mirar[-1]], rel_sin))

    print()
    inf.check(peor <= COTA_REFINAR_mm * (1 + 1e-6),
              'refinar en 2, 4 y 8 tramos no mueve la flecha de los nodos %s' % mirar,
              'peor %.1e mm <= %.0e (dos redondeos a 8 decimales en m)' % (peor, COTA_REFINAR_mm))
    print('  El elemento esta bien: refinar no mueve el resultado.')
    print('  De la flecha, %.0f %% la trae la viga perpendicular con su losa.'
          % (100 * (rel0 - rel_sin) / rel0 if rel0 else 0))
    print('  %.2f mm sobre %.1f m es L/%.0f, contra el L/360 de la norma'
          % (abs(rel0), largo, largo * 1000 / abs(rel0)))
    print('  (L/360 serian %.1f mm). Lo que se ve grande en el visor es la'
          % (largo * 1000 / 360))
    print('  escala grafica: a x300, %.2f mm se dibujan como %.2f m.'
          % (abs(rel0), abs(rel0) / 1000 * 300))


# ============================================================
class _Argumentos(object):
    """Lo que entiende main: bloques, --float32, --url, --desde y numeros."""

    def __init__(self, argv):
        self.bloques, self.numeros = [], []
        self.float32, self.url, self.desde = False, None, None
        i = 0
        while i < len(argv):
            a = argv[i]
            if a in BLOQUES:
                self.bloques.append(a)
            elif a == '--float32':
                self.float32 = True
            elif a in ('--url', '--desde'):
                if i + 1 >= len(argv):
                    raise SystemExit('%s necesita un valor' % a)
                i += 1
                if a == '--url':
                    self.url = argv[i]
                else:
                    self.desde = argv[i] if os.path.isabs(argv[i]) else os.path.abspath(argv[i])
            elif re.fullmatch(r'\d+', a):
                self.numeros.append(int(a))
            else:
                raise SystemExit('no conozco %r. Bloques: %s; opciones: --float32, --url URL, '
                                 '--desde JSON (m1, m3, m4) y un nodo (viga_partida)'
                                 % (a, ', '.join(BLOQUES)))
            i += 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv):
        print(__doc__)
        return 0
    a = _Argumentos(argv)
    hacer = {'servidor': servidor, 'casos_del_modelo': casos_del_modelo,
             'reanalisis': reanalisis, 'm1': m1, 'm3': m3, 'm4': m4,
             'viga_partida': viga_partida}
    consola_tolerante()
    t0 = time.time()
    inf = Informe()
    for b in (a.bloques or BLOQUES):
        hacer[b](inf, a)
    print('  (%.0f s)' % (time.time() - t0))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
