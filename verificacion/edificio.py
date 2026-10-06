# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/edificio.py  -  EL EDIFICIO, CONTRA SI MISMO Y CONTRA SUS SUPUESTOS
================================================================
 Cuatro bloques; sin bloque corre los cuatro:

   python -m verificacion.edificio dato          # E1
   python -m verificacion.edificio junta         # E2
   python -m verificacion.edificio tributarias   # E3
   python -m verificacion.edificio modelo        # E4 (lenta)

 entrada/edificio.json es el unico modelo del programa: los dos cuerpos
 (el antiguo, tags 1xxxxx; el LT2, tags 2xxxxx) en un solo edificio con
 una junta de dilatacion LIBRE. Ya no hay un modelo por cuerpo en disco:
 lo que necesita mirar un cuerpo solo lo parte por rango de tag
 (edificio.por_cuerpo), en memoria.

 DATO. Lo que el archivo dice es coherente y es lo que declaran sus
 supuestos: validar(), los conteos, los tags por cuerpo, G por cuerpo,
 el hormigon de cada seccion (E = 4700 raiz(f'c) 1000, y el f'c el de
 su cuerpo), las cotas de piso compartidas, la convencion de muros de
 cada cuerpo y "lo declarado es lo usado".

 JUNTA. La junta es libre, y se tiene que notar: ninguna barra ni
 diafragma la cruza, cada barra usa una seccion de su cuerpo, las caras
 de los dos cuerpos quedan a la junta declarada, y cada cuerpo resuelto
 SOLO da lo mismo que dentro del edificio.

 TRIBUTARIAS. La losa llega donde se dibuja: el area sellada en cada
 elemento = los poligonos de la vista = la carga que aplican G y Q. Y
 POR CUERPO, q constante en cada piso y sum(w L) = q A.

 MODELO. Lo del modelo que el equilibrio no ve, por cuerpo: secciones,
 orientacion de los muros, linealidad, diafragma rigido, brazos rigidos
 de verdad, nodos colgando, la carga contra el plano de cargas, los
 dinteles, la losa piso contra piso, los cuatro casos del modelo y las
 derivas de NCh433.

 Ninguno escribe en salidas/.
================================================================
"""
from __future__ import annotations

import argparse
import collections
import copy
import io
import math
import os
import sys
import time

from calculo import demanda as dem
from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from verificacion.comun import Informe, medio_digito, titulo
from verificacion.suite import consola_tolerante, calza

BLOQUES = ('dato', 'junta', 'tributarias', 'modelo')

CASOS = ('G', 'Q', 'EX', 'EY')
GDL = ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')

# opensees.extraer_resultados devuelve las fuerzas con 4 decimales: cada
# reaccion llega con hasta medio ultimo digito de error.
R_KN = 0.5e-4
# opensees.equilibrio devuelve error_kN redondeado a 8 decimales.
R_EQ = 0.5e-8
EPS = sys.float_info.epsilon


def numero_de(cuerpo):
    """1 o 2: el k de tag = 100000 k + tag del cuerpo."""
    return next(k for k, v in _ed.CUERPOS.items() if v == cuerpo)


def seccion_de(modelo):
    return {s['nombre']: s for s in modelo['secciones']}


def hormigon_declarado(sup):
    """{cuerpo: f'c en MPa} como lo declaran los supuestos de cada cuerpo."""
    return {'ingenieria': float(sup['ingenieria']['secciones']['hormigon']['fpc_MPa']),
            'lt2': float(sup['lt2']['materiales']['hormigon']['fc_MPa'])}


def cotas_de_piso(sup):
    """Base y pisos de supuestos.lt2.niveles_del_modelo (el marco del edificio)."""
    n = sup['lt2']['niveles_del_modelo']
    return [round(float(n['base']), 2)] + [round(float(p['z']), 2) for p in n['pisos']]


# ============================================================
# DATO
# ============================================================
def dato(inf, args=None):
    """E1: el archivo es coherente y es lo que declaran sus supuestos."""
    edificio = _ed.cargar()
    modelo = _ed.estructura(edificio)
    vista = _ed.vista(edificio)
    sup = _ed.supuestos(edificio)
    partes = _ed.por_cuerpo(modelo)
    S = seccion_de(modelo)

    print('=' * 72)
    print('  EL DATO DEL EDIFICIO   %s' % rutas.relativa(rutas.EDIFICIO).replace(os.sep, '/'))
    print('=' * 72)
    print('  %s' % _ed.resumen(modelo))

    titulo('[1] SE PUEDE RESOLVER SIN PERDER CARGA EN SILENCIO')
    problemas = _ed.validar(modelo)
    inf.check(not problemas, 'edificio.validar(): ninguna carga huerfana, ningun nodo o seccion '
              'inexistente, cada diafragma a una sola cota', problemas[:5])
    nodos = {int(n['id']): n for n in modelo['nodos']}
    malos = []
    for d in modelo.get('diafragmas', []):
        m = nodos[int(d['nodo_maestro'])]
        if not (m.get('auxiliar') and _ed.restricciones_de(m) == [0, 0, 1, 1, 1, 0]
                and int(d.get('perpendicular', 3)) == 3):
            malos.append(int(d['nodo_maestro']))
    inf.check(not malos, '%d diafragmas horizontales; cada maestro es un nodo auxiliar fijo fuera '
              'de su plano [0 0 1 1 1 0]' % len(modelo.get('diafragmas', [])), malos[:5])

    titulo('[2] CONTEOS (los numeros de control)')
    cuenta = {'nodos': len(modelo['nodos']), 'elementos': len(modelo['elementos']),
              'secciones': len(modelo['secciones']), 'diafragmas': len(modelo['diafragmas']),
              'casos_del_modelo': len(modelo['casos_de_carga'])}
    inf.check(all(calza(v, 'edificio', k) for k, v in cuenta.items()),
              ', '.join('%d %s' % (v, k.replace('_', ' ')) for k, v in cuenta.items()))
    for cuerpo, sub in partes.items():
        inf.check(calza(len(sub['nodos']), 'edificio', 'nodos_por_cuerpo', cuerpo)
                  and calza(len(sub['elementos']), 'edificio', 'elementos_por_cuerpo', cuerpo),
                  '%-11s %d nodos y %d elementos' % (cuerpo, len(sub['nodos']), len(sub['elementos'])))

    titulo('[3] LOS TAGS DICEN DE QUE CUERPO ES CADA COSA')
    declarado = {int(k): v.split()[0] for k, v in sup['tags']['cuerpos'].items()}
    inf.check(declarado == _ed.CUERPOS and modelo['info'].get('cuerpos') == list(_ed.CUERPOS.values()),
              'tag = %d k + tag del cuerpo: %s (supuestos.tags = edificio.CUERPOS = info.cuerpos)'
              % (_ed.PASO_DE_TAG, ', '.join('%d -> %s' % kv for kv in sorted(_ed.CUERPOS.items()))))
    fuera = []
    for clave, tags in (('nodo', [n['id'] for n in modelo['nodos']]),
                        ('elemento', [e['id'] for e in modelo['elementos']]),
                        ('diafragma', [d['nodo_maestro'] for d in modelo['diafragmas']])):
        for t in tags:
            try:
                _ed.cuerpo_de(t)
            except ValueError:
                fuera.append('%s %s' % (clave, t))
    inf.check(not fuera, 'cada nodo, elemento y diafragma esta en el rango de un cuerpo', fuera[:5])
    ajenas = [e['id'] for e in modelo['elementos']
              if not e['seccion'].startswith(_ed.cuerpo_de(e['id']) + ':')]
    inf.check(not ajenas, 'cada barra usa una seccion con el prefijo de su cuerpo '
              '(ingenieria:... en 1xxxxx, lt2:... en 2xxxxx)', ajenas[:5])

    titulo('[4] G POR CUERPO')
    g = {}
    for cuerpo, sub in partes.items():
        caso = next(c for c in sub['casos_de_carga'] if c['nombre'] == 'G')
        g[cuerpo] = -opensees.equilibrio(sub, caso, {'reacciones': []})['aplicada_kN'][2]
    caso_g = next(c for c in modelo['casos_de_carga'] if c['nombre'] == 'G')
    g_total = -opensees.equilibrio(modelo, caso_g, {'reacciones': []})['aplicada_kN'][2]
    inf.check(calza(g['ingenieria'], 'edificio', 'G_por_cuerpo_kN', 'ingenieria')
              and calza(g['lt2'], 'edificio', 'G_por_cuerpo_kN', 'lt2')
              and calza(g_total, 'edificio', 'G_kN')
              and abs(g_total - g['ingenieria'] - g['lt2']) <= 2 * 0.5e-4,
              'G = %.4f kN = %.4f (ingenieria) + %.4f (lt2): los numeros de control'
              % (g_total, g['ingenieria'], g['lt2']))

    titulo('[5] EL HORMIGON DE CADA SECCION ES EL DE SU CUERPO')
    fpc = hormigon_declarado(sup)
    poisson = float(modelo['material'].get('poisson', 0.2))
    malos_E, malos_fpc, n_h = [], [], 0
    for s in modelo['secciones']:
        if 'fpc_MPa' not in s:
            continue
        n_h += 1
        cuerpo = s['nombre'].split(':')[0]
        Ec = 4700.0 * math.sqrt(float(s['fpc_MPa'])) * 1000.0
        # E y G se escribieron redondeados: la cota es medio ultimo digito
        # de cada uno (G = E / 2(1 + nu) arrastra el de E).
        cota_E = medio_digito(repr(float(s['E'])))
        cota_G = medio_digito(repr(float(s['G']))) + cota_E / (2.0 * (1.0 + poisson))
        if abs(float(s['E']) - Ec) > cota_E * (1 + 1e-9) \
                or abs(float(s['G']) - float(s['E']) / (2.0 * (1.0 + poisson))) > cota_G * (1 + 1e-9):
            malos_E.append(s['nombre'])
        if abs(float(s['fpc_MPa']) - fpc[cuerpo]) > 1e-12 or s.get('E_del_cuerpo') != cuerpo:
            malos_fpc.append(s['nombre'])
    inf.check(not malos_E and calza(n_h, 'edificio', 'secciones_de_hormigon'),
              '%d secciones de hormigon: E = 4700 raiz(f\'c) 1000 y G = E / 2(1 + %.1f), al ultimo '
              'digito escrito' % (n_h, poisson), malos_E[:5])
    inf.check(not malos_fpc,
              'el f\'c de cada una es el de su cuerpo: ingenieria %.0f MPa '
              '(supuestos.ingenieria.secciones.hormigon), lt2 %.0f MPa '
              '(supuestos.lt2.materiales.hormigon); y E_del_cuerpo lo dice'
              % (fpc['ingenieria'], fpc['lt2']), malos_fpc[:5])
    acero = float(sup['ingenieria']['constantes_del_modelo']['acero_E_kPa'])
    metal = [s for s in modelo['secciones'] if 'fpc_MPa' not in s]
    inf.check(all(float(s.get('E', 0.0)) == acero and abs(float(s.get('G', 0.0)) - acero / 2.6) <= 1e-6
                  for s in metal),
              '%d secciones de acero: E = %.0f kPa (supuestos.ingenieria.constantes_del_modelo) y '
              'G = E / 2(1 + 0.3)' % (len(metal), acero))

    titulo('[6] LOS DOS CUERPOS COMPARTEN SUS COTAS DE PISO')
    # El cuerpo antiguo estaba escrito en ALTURAS RELATIVAS (0, 3.96 ...) y
    # el LT2 en COTAS REALES del plano (-7.97, -4.01 ...). Sin el dz del
    # calce el antiguo quedaba 7.97 m mas arriba, y en los numeros NO se
    # nota: cada cuerpo se resuelve por su cuenta y el equilibrio cierra igual.
    cotas = []
    for cuerpo, sub in partes.items():
        zs = sorted({round(n['z'], 2) for n in sub['nodos']})
        cotas.append((cuerpo, zs))
        print('    %-11s  %s' % (cuerpo, zs))
    comunes = set(cotas[0][1]) & set(cotas[1][1])
    inf.check(len(comunes) >= min(len(cotas[0][1]), len(cotas[1][1])),
              'los dos cuerpos comparten sus cotas de piso')
    declaradas = cotas_de_piso(sup)
    de_diafragmas = sorted({round(float(nodos[int(d['nodo_maestro'])]['z']), 2)
                            for d in modelo['diafragmas']})
    inf.check(all(zs == declaradas for _c, zs in cotas) and de_diafragmas == declaradas[1:],
              'son las de supuestos.lt2.niveles_del_modelo (base %+.2f y %d pisos con diafragma en '
              'cada cuerpo)' % (declaradas[0], len(declaradas) - 1))

    titulo('[7] LOS MUROS, CADA CUERPO CON SU CONVENCION')
    # Los dos cuerpos eligieron distinto el vecxz de sus muros. En el LT2 es
    # la NORMAL y la inercia grande queda en Iz (momento del plano Mz); en
    # el antiguo es la direccion del LARGO y la grande queda en Iy (My).
    # Normalizarlas seria un cambio aparte: cada una tiene su guardia aca.
    muros = [e for e in modelo['elementos'] if e['tipo'] == 'muro']
    sin = [e['id'] for e in muros if not (e.get('largo', 0) > 0 and e.get('espesor', 0) > 0
                                          and len(e.get('dir_largo') or []) >= 2
                                          and len(e.get('vecxz') or []) >= 3)]
    inf.check(not sin, '%d muros traen largo, espesor, dir_largo y vecxz (el visor no deduce nada)'
              % len(muros), sin[:5])
    malos = collections.defaultdict(list)
    for e in muros:
        cuerpo = _ed.cuerpo_de(e['id'])
        d, v = e.get('dir_largo') or [0, 0], e.get('vecxz') or [0, 0, 0]
        s = S[e['seccion']]
        norma = math.hypot(float(d[0]), float(d[1]))
        # Unitario dentro del redondeo del plano: 4 decimales en las
        # coordenadas y el largo (1e-4 / largo) y 6 en el versor (1e-6).
        if abs(norma - 1.0) > 1e-4 / max(float(e['largo']), 1e-9) + 1e-6:
            malos['dir_largo no unitario'].append(e['id'])
        punto_ = (float(d[0]) * float(v[0]) + float(d[1]) * float(v[1])) / max(norma, 1e-12)
        cruz = (float(d[0]) * float(v[1]) - float(d[1]) * float(v[0])) / max(norma, 1e-12)
        plano = 'Mz' if cuerpo == 'lt2' else 'My'
        if abs(float(v[2])) > 1e-12:
            malos['vecxz no horizontal'].append(e['id'])
        if cuerpo == 'lt2' and (abs(punto_) > 1e-6 or not float(s['Iz']) > float(s['Iy'])):
            malos['lt2: vecxz no es la normal o la inercia grande no esta en Iz'].append(e['id'])
        if cuerpo == 'ingenieria' and (abs(cruz) > 1e-6 or not float(s['Iy']) > float(s['Iz'])):
            malos['ingenieria: vecxz no va a lo largo o la inercia grande no esta en Iy'].append(e['id'])
        if dem.momento_en_el_plano_de(modelo, e) != plano:
            malos['momento del plano no es %s' % plano].append(e['id'])
    por_cuerpo = collections.Counter(_ed.cuerpo_de(e['id']) for e in muros)
    inf.check(not malos,
              'lt2 (%d muros): vecxz = la normal, dir_largo perpendicular, inercia grande en Iz, '
              'momento del plano Mz; ingenieria (%d): vecxz a lo largo, inercia grande en Iy, '
              'momento del plano My; dir_largo unitario (1e-4/largo + 1e-6)'
              % (por_cuerpo['lt2'], por_cuerpo['ingenieria']),
              ['%s: %s' % (k, v[:5]) for k, v in malos.items()])
    cruzadas = []
    con_los_dos = 0
    for s in modelo['secciones']:
        if not (s.get('largo', 0) > 1e-3 and s.get('espesor', 0) > 1e-3):
            continue
        if not (s.get('b', 0) > 1e-3 and s.get('h', 0) > 1e-3):
            continue
        con_los_dos += 1
        if abs(s['b'] - s['espesor']) > 1e-3 or abs(s['h'] - s['largo']) > 1e-3:
            cruzadas.append('%s (b %.4g/esp %.4g, h %.4g/largo %.4g)'
                            % (s['nombre'], s['b'], s['espesor'], s['h'], s['largo']))
    # Las dos lecturas dan el MISMO A, Iy e Iz, asi que cruzarlas no se nota
    # en ningun numero: los muros del cuerpo antiguo llegaron a viajar con
    # b = 9.65 m y h = 0.30 m, deducidos con la regla del LT2.
    inf.check(not cruzadas, 'en las %d secciones con los dos pares, b = espesor y h = largo'
              % con_los_dos, cruzadas[:3])

    titulo('[8] LO DECLARADO ES LO USADO (supuestos)')
    calce = sup['calce']['edificios']
    terrenos = vista.get('terrenos', [])
    base = next((t for t in terrenos if t['nombre'] == 'base'), {})
    esperado = []
    for cuerpo in ('ingenieria', 'lt2'):
        z = float(sup[cuerpo]['terreno']['z']) + float(calce[cuerpo].get('dz', 0.0))
        esperado.append(('%s: terreno %+.2f + dz %+.2f' % (cuerpo, float(sup[cuerpo]['terreno']['z']),
                                                           float(calce[cuerpo].get('dz', 0.0))), z, base.get('z')))
        for t in sup[cuerpo]['terreno'].get('terrazas') or []:
            zt = float(t['z']) + float(calce[cuerpo].get('dz', 0.0))
            dibujada = next((x['z'] for x in terrenos if t['nombre'] in x['nombre']), None)
            esperado.append(('%s: %s %+.2f + dz' % (cuerpo, t['nombre'], float(t['z'])), zt, dibujada))
    inf.check(all(b is not None and abs(a - b) <= 0.005 for _t, a, b in esperado)
              and abs(float(vista.get('cota_terreno')) - base.get('z', 1e9)) <= 0.005,
              'el terreno de cada cuerpo, con el dz del calce, es el que dibuja la vista: %s'
              % '; '.join('%s = %+.2f' % (t, b if b is not None else float('nan')) for t, _a, b in esperado))
    col = sup['ingenieria']['secciones']
    pares = [('columna', 'ingenieria:columna'), ('viga_x', 'ingenieria:viga_x'), ('viga_y', 'ingenieria:viga_y')]
    inf.check(all(abs(float(col[k]['b']) - S[n]['b']) <= 1e-12 and abs(float(col[k]['h']) - S[n]['h']) <= 1e-12
                  for k, n in pares),
              'secciones del cuerpo antiguo: %s (supuestos.ingenieria.secciones)'
              % ', '.join('%s %.2fx%.2f' % (k, S[n]['b'], S[n]['h']) for k, n in pares))
    factor = float(sup['ingenieria']['constantes_del_modelo']['brazo_rigido_factor'])
    c, b = S['ingenieria:columna'], S['ingenieria:brazo_rigido']
    inf.check(all(abs(float(b[k]) - factor * float(c[k])) <= 1e-9 * abs(factor * float(c[k]))
                  for k in ('A', 'Iy', 'Iz', 'J')),
              'brazo rigido del cuerpo antiguo = columna x %.0f en A, Iy, Iz y J '
              '(constantes_del_modelo.brazo_rigido_factor)' % factor)
    diam = float(sup['ingenieria']['constantes_del_modelo']['diagonal_DM_diametro_m'])
    diag = S['ingenieria:diagonal_metal']
    inf.check(abs(float(diag['A']) - math.pi * diam ** 2 / 4.0) <= 1e-15,
              'diagonal metalica: A = pi %.3f^2 / 4 (constantes_del_modelo.diagonal_DM_diametro_m, '
              'supuesto)' % diam)
    fierro_de_cuerpo(inf, modelo, sup)


def fierro_de_cuerpo(inf, modelo, sup):
    """La enfierradura de cada elemento es la que declaran los supuestos."""
    pil = sup['lt2']['enfierradura_supuesta']['pilares']
    ac_lt2 = sup['lt2']['enfierradura_supuesta']['acero']
    col = sup['ingenieria']['secciones']['columna']['fierro']
    mur = sup['ingenieria']['fierro_de_muros']
    punta = mur['barras_de_punta']
    malos = collections.defaultdict(list)
    n = collections.Counter()
    for e in modelo['elementos']:
        fe = e.get('enfierradura')
        if not fe:
            continue
        cuerpo = _ed.cuerpo_de(e['id'])
        if fe.get('tipo') == 'muro':
            n[cuerpo + ' muro'] += 1
            if cuerpo != 'ingenieria':
                continue
            esp = int(round(float(fe['espesor_m']) * 100))
            tip = mur['tipico_por_espesor'].get(str(esp), {})
            if fe['malla_vertical']['texto'] != tip.get('malla_vertical') \
                    or fe['malla_horizontal']['texto'] != tip.get('malla_horizontal'):
                malos['malla del muro no es la tipica de su espesor'].append(e['id'])
            if any(bb.get('texto') != punta['texto'] or float(bb['diametro_mm']) != float(punta['diametro_mm'])
                   for bb in fe.get('barras_de_borde') or []):
                malos['barras de punta no son las declaradas'].append(e['id'])
            if int(fe.get('capas', 0)) != int(mur['capas']) \
                    or abs(float(fe.get('recubrimiento_m', 0)) - float(mur['recubrimiento_m'])) > 1e-12 \
                    or float(fe['acero']['fy_MPa']) != float(mur['acero']['fy_MPa']):
                malos['capas, recubrimiento o fy del muro'].append(e['id'])
            continue
        n[cuerpo + ' columna'] += 1
        lon = fe['longitudinal']
        if cuerpo == 'lt2':
            if float(lon['diametro_mm']) != float(pil['diametro_longitudinal_mm']) \
                    or abs(float(fe['recubrimiento_m']) - float(pil['recubrimiento_m'])) > 1e-12 \
                    or float(fe['acero']['fy_MPa']) != float(ac_lt2['fy_MPa']):
                malos['pilar del LT2: diametro, recubrimiento o fy'].append(e['id'])
        else:
            if float(lon['diametro_mm']) != float(col['diametro_longitudinal_mm']) \
                    or int(lon['por_cara']) != int(col['barras_por_cara']) \
                    or abs(float(fe['recubrimiento_m']) - float(col['recubrimiento_m'])) > 1e-12 \
                    or float(fe['estribo']['diametro_mm']) != float(col['estribo']['diametro_mm']) \
                    or float(fe['estribo']['separacion_cm']) != float(col['estribo']['separacion_cm']):
                malos['pilar del cuerpo antiguo: diametro, barras por cara, recubrimiento o estribo'].append(e['id'])
    inf.check(not malos,
              'fierro: %d pilares del LT2 con D%.0f supuesto y recubrimiento %.2f m; %d del cuerpo antiguo '
              'con %d por cara D%.0f, estribo D%.0f a %.0f cm; %d muros del cuerpo antiguo con la malla '
              'tipica de su espesor y %s de punta (supuestos)'
              % (n['lt2 columna'], float(pil['diametro_longitudinal_mm']), float(pil['recubrimiento_m']),
                 n['ingenieria columna'], int(col['barras_por_cara']), float(col['diametro_longitudinal_mm']),
                 float(col['estribo']['diametro_mm']), float(col['estribo']['separacion_cm']),
                 n['ingenieria muro'], punta['texto']),
              ['%s: %s' % (k, v[:5]) for k, v in malos.items()])


# ============================================================
# JUNTA
# ============================================================
# CUANTO PUEDEN DIFERIR DOS CORRIDAS QUE DEBERIAN SER IGUALES. Dos cosas
# separan al edificio de un cuerpo resuelto solo aunque el modelo sea el
# mismo:
#
#   1. el motor devuelve los desplazamientos redondeados a 8 decimales
#      -> piso absoluto de 1e-8 m;
#   2. el sistema es mas grande y se resuelve con otro ordenamiento de
#      ecuaciones, asi que el redondeo de punto flotante se acumula
#      distinto.
#
# Lo segundo NO es despreciable: los brazos rigidos tienen secciones x100
# y los tubos metalicos su propio E, y eso empeora el condicionamiento.
# Medido sobre el cuerpo antiguo, la diferencia ESCALA CON LA MAGNITUD,
# con la gran mayoria de los GDL en cero exacto: esa es la firma del
# redondeo. Un error de MODELADO se ve al reves: da una RAZON casi
# constante entre las dos corridas, y toca por igual a los valores grandes
# y a los chicos -- que es exactamente como se vio el 1.1180 del modulo
# elastico (el LT2 corriendo con el f'c del otro cuerpo).
#
# Por eso la tolerancia es relativa a la magnitud del caso y no un
# absoluto: el error del modulo elastico -- 3.7e-3 m en el techo -- habria
# fallado por cuatro ordenes de magnitud.
TOL_M = 1.5e-8
TOL_RELATIVA = 1.0e-5


def comparar(solo, junto, ids):
    """
    Los desplazamientos de un cuerpo resuelto solo contra los del mismo
    cuerpo dentro del edificio. Devuelve (n, peor, donde, limite, exactos).
    """
    a = {int(d['id']): d for d in solo.get('desplazamientos', []) if int(d['id']) in ids}
    b = {int(d['id']): d for d in junto.get('desplazamientos', [])}

    n, peor, donde, escala, exactos = 0, 0.0, None, 0.0, 0
    for tag, da in a.items():
        db = b.get(tag)
        if db is None:
            continue
        for k in GDL:
            n += 1
            y = float(db.get(k, 0.0))
            d = abs(float(da.get(k, 0.0)) - y)
            escala = max(escala, abs(y))
            if d == 0.0:
                exactos += 1
            if d > peor:
                peor, donde = d, (tag, k)
    limite = max(TOL_M, TOL_RELATIVA * escala)
    return n, peor, donde, limite, exactos


def _caja_de_caras(p):
    """
    (xmin, xmax, ymin, ymax) de un cuerpo, medido por las CARAS de sus
    elementos y no por sus nodos.

    La diferencia no es cosmetica. Un muro se modela como una barra en
    su EJE pero ocupa su espesor, y una columna de 0.70 sobresale 0.35
    de su nodo. Para apoyar dos edificios uno contra otro hay que medir
    caras: midiendo nodos, la separacion que se informa no es la junta.

    Los brazos rigidos se excluyen: su seccion es un artificio numerico
    (4 x 4 m en el LT2) y no es geometria de nada.
    """
    nod = {int(n['id']): n for n in p['nodos']}
    sec = {s['nombre']: s for s in p['secciones']}
    lim = [None, None, None, None]        # xmin, xmax, ymin, ymax

    def anotar(lo_x, hi_x, lo_y, hi_y):
        for i, v, peor in ((0, lo_x, min), (1, hi_x, max),
                           (2, lo_y, min), (3, hi_y, max)):
            lim[i] = v if lim[i] is None else peor(lim[i], v)

    for e in p['elementos']:
        # 'brazo' (LT2) y 'brazo_rigido' (el antiguo) son lo mismo: su
        # seccion es un artificio numerico, no geometria.
        if e.get('tipo') in ('brazo', 'brazo_rigido'):
            continue
        a, b = nod[int(e['n1'])], nod[int(e['n2'])]
        s = sec.get(e['seccion'], {})
        if e.get('tipo') == 'muro':
            d = e.get('dir_largo') or [0.0, 0.0]
            L = e.get('largo') or s.get('largo', 0.0)
            t = e.get('espesor') or s.get('espesor', 0.0)
            hx = abs(d[0]) * L / 2 + abs(d[1]) * t / 2
            hy = abs(d[1]) * L / 2 + abs(d[0]) * t / 2
            anotar(a['x'] - hx, a['x'] + hx, a['y'] - hy, a['y'] + hy)
            continue
        if e.get('tipo') == 'columna':
            h = max(s.get('b', 0.0), s.get('h', 0.0)) / 2
            anotar(a['x'] - h, a['x'] + h, a['y'] - h, a['y'] + h)
            continue
        # viga: a lo largo mandan sus extremos; de ancho, su b
        largo = math.hypot(b['x'] - a['x'], b['y'] - a['y'])
        ux = abs(b['x'] - a['x']) / largo if largo > 1e-9 else 0.0
        ancho = s.get('b', 0.0) / 2
        hx = 0.0 if ux > 0.5 else ancho
        hy = ancho if ux > 0.5 else 0.0
        anotar(min(a['x'], b['x']) - hx, max(a['x'], b['x']) + hx,
               min(a['y'], b['y']) - hy, max(a['y'], b['y']) + hy)
    return tuple(lim)


def revisar_la_junta(partes, junta):
    """
    Los dos cuerpos no se pueden solapar, y la separacion de cara a cara
    tiene que ser la junta declarada. Devuelve (avisos, cajas, separacion).

    No es un chequeo estructural sino GEOMETRICO, y es el unico que puede
    delatar que el calce esta mal: si dx estuviera equivocado, un cuerpo
    se meteria dentro del otro y aca se veria.
    """
    avisos, separacion = [], None
    cajas = [(nombre,) + _caja_de_caras(p) for nombre, p in partes.items()]

    for i in range(len(cajas)):
        for j in range(i + 1, len(cajas)):
            a, b = cajas[i], cajas[j]
            solape_x = min(a[2], b[2]) - max(a[1], b[1])
            solape_y = min(a[4], b[4]) - max(a[3], b[3])
            if solape_x > 0 and solape_y > 0:
                avisos.append(
                    'los cuerpos %s y %s se SOLAPAN en planta '
                    '(%.2f m en x por %.2f m en y). El calce esta mal.'
                    % (a[0], b[0], solape_x, solape_y))
            elif solape_y > 0:
                sep = -solape_x
                ancho = float(junta.get('ancho_m', 0.0))
                calza_ = abs(sep - ancho) < 0.005 if ancho else True
                separacion = (sep, ancho, calza_)
                avisos.append(
                    'separacion de cara a cara entre %s y %s: %.3f m  '
                    '(junta declarada %.3f m)   %s'
                    % (a[0], b[0], sep, ancho,
                       'OK' if calza_ else '<-- NO CALZA con lo declarado'))
    return avisos, cajas, separacion


def junta(inf, args=None):
    """E2: la junta es libre, y se tiene que notar."""
    edificio = _ed.cargar()
    modelo = _ed.estructura(edificio)
    sup = _ed.supuestos(edificio)
    partes = _ed.por_cuerpo(modelo)
    S = seccion_de(modelo)

    print('=' * 70)
    print('  LA JUNTA ES LIBRE, Y SE TIENE QUE NOTAR')
    print('=' * 70)
    print('  cuerpos: %s' % ', '.join(partes))

    titulo('[1] NADA CRUZA LA JUNTA')
    cruzan = [e['id'] for e in modelo['elementos']
              if len({_ed.cuerpo_de(e['id']), _ed.cuerpo_de(e['n1']), _ed.cuerpo_de(e['n2'])}) > 1]
    inf.check(not cruzan, 'ninguna de las %d barras une un nodo de un cuerpo con uno del otro'
              % len(modelo['elementos']), cruzan[:5])
    cruzan = [d['nodo_maestro'] for d in modelo['diafragmas']
              if len({_ed.cuerpo_de(d['nodo_maestro'])} | {_ed.cuerpo_de(n) for n in d['nodos']}) > 1]
    cruzan += ['brazo %s-%s' % (b['maestro'], b['esclavo']) for b in modelo.get('brazos_rigidos', [])
               if _ed.cuerpo_de(b['maestro']) != _ed.cuerpo_de(b['esclavo'])]
    inf.check(not cruzan, 'ninguno de los %d diafragmas ni de los %d brazos (rigidLink) ata los dos cuerpos'
              % (len(modelo['diafragmas']), len(modelo.get('brazos_rigidos', []))), cruzan[:5])

    titulo('[2] UN MATERIAL POR CUERPO, NO UNO PARA LOS DOS')
    # Al unir dos edificios el contrato tiene UN material: el LT2 (G35)
    # corrio con 28 MPa, 10.6 % mas blando, y el equilibrio cerraba igual.
    # Lo impide que cada seccion traiga su E y G, y que cada barra use una
    # seccion de su cuerpo.
    # Una seccion sin E o sin G corre con el material del modelo (28 MPa):
    # es justo la trampa. Una sin f'c es de acero y lleva el E del acero.
    Ec = {c: 4700.0 * math.sqrt(f) * 1000.0 for c, f in hormigon_declarado(sup).items()}
    acero = float(sup['ingenieria']['constantes_del_modelo']['acero_E_kPa'])
    sin_material, ajenas = [], []
    for e in modelo['elementos']:
        s = S[e['seccion']]
        cuerpo = _ed.cuerpo_de(e['id'])
        if 'E' not in s or 'G' not in s:
            sin_material.append(e['id'])
        elif abs(float(s['E']) - (Ec[cuerpo] if 'fpc_MPa' in s else acero)) > 1e-3:
            ajenas.append(e['id'])
    inf.check(not sin_material, 'cada barra trae el E y el G de su seccion: ninguna cae al material '
              'del modelo (%.0f MPa)' % float(modelo['material']['fpc_MPa']), sin_material[:5])
    inf.check(not ajenas, 'cada barra de hormigon corre con el E de su cuerpo: ingenieria %.3f, '
              'lt2 %.3f kPa; las de acero con %.0f kPa' % (Ec['ingenieria'], Ec['lt2'], acero), ajenas[:5])

    titulo('[3] LA JUNTA, MEDIDA POR LAS CARAS')
    avisos, cajas, separacion = revisar_la_junta(partes, sup['calce'].get('junta', {}))
    print('  EN PLANTA, YA CALZADOS  (medido por las CARAS, no por los nodos)')
    for nombre, x0, x1, y0, y1 in cajas:
        print('    %-11s  x [%8.3f , %8.3f]   y [%8.3f , %8.3f]'
              % (nombre, x0, x1, y0, y1))
    for a in avisos:
        print('    %s' % a)
    inf.check(separacion is not None and separacion[2],
              'la separacion de cara a cara es la junta declarada (supuestos.calce.junta.ancho_m) '
              'dentro de 5 mm' + ('' if separacion is None else ': %.3f m' % separacion[0]))
    if separacion is not None:
        inf.check(calza(round(separacion[0], 3), 'edificio', 'junta_m'),
                  'junta %.3f m: el numero de control' % separacion[0])

    titulo('[4] CADA CUERPO RESUELTO SOLO = DENTRO DEL EDIFICIO')
    print('  la junta es libre, asi que cada uno tiene que dar lo MISMO')
    print('  que resuelto solo, no algo parecido.')
    with opensees.AvisosDeOpenSees():
        junto = {r['nombre']: r for r in opensees.construir_y_resolver(copy.deepcopy(modelo))['casos']}
    fallos = []
    solos = {}
    for cuerpo, sub in partes.items():
        print()
        print('  %s   (tags %dxxxxx, resuelto solo con edificio.por_cuerpo)' % (cuerpo, numero_de(cuerpo)))
        with opensees.AvisosDeOpenSees():
            solo = {r['nombre']: r for r in opensees.construir_y_resolver(copy.deepcopy(sub))['casos']}
        solos[cuerpo] = solo
        ids = {int(n['id']) for n in sub['nodos']}
        for caso in CASOS:
            n, peor, donde, limite, exactos = comparar(solo[caso], junto[caso], ids)
            ok = peor <= limite
            print('    %-3s  %5d GDL   %4d exactos (%.0f %%)   peor %.2e m   '
                  'limite %.2e   %s%s'
                  % (caso, n, exactos, 100.0 * exactos / max(n, 1), peor,
                     limite, 'ok' if ok else 'NO COINCIDE',
                     '' if ok else '   (nodo %s, %s)' % donde))
            if not ok:
                fallos.append('%s en %s: %.3e m de diferencia' % (cuerpo, caso, peor))
    inf.check(not fallos, 'cada cuerpo se comporta dentro del edificio exactamente como resuelto '
              'por su cuenta (tolerancia max(%.1e m, %.0e x la magnitud del caso))' % (TOL_M, TOL_RELATIVA),
              fallos)

    titulo('[5] LA COLUMNA DEL MARCADOR AR, SOLA Y DENTRO')
    eid = 200037
    fa = next(x['f'] for x in solos['lt2']['G']['fuerzas_elementos'] if int(x['id']) == eid)
    fb = next(x['f'] for x in junto['G']['fuerzas_elementos'] if int(x['id']) == eid)
    inf.check(fa == fb, 'el LT2 solo y el edificio dan el mismo localForce de %d bajo G en las 12 '
              'componentes: N_i = %.4f kN' % (eid, fa[0]))
    otra = eid - _ed.PASO_DE_TAG
    fi = next((x['f'] for x in junto['G']['fuerzas_elementos'] if int(x['id']) == otra), None)
    if fi:
        print('         %d es el mismo tag del cuerpo (37) en el otro cuerpo, y es OTRA columna '
              '(N_i = %.4f kN): por eso cada cuerpo suma su 100000 k' % (otra, fi[0]))


# ============================================================
# TRIBUTARIAS
# ============================================================
# Cuanto puede desviarse el q implicito de una barra respecto de la
# mediana de SU PISO, en tanto por uno. Con el peso propio bien tratado
# los dos cuerpos dan cero barras fuera, asi que el 2% es margen de
# redondeo: los w viajan redondeados a 6 decimales y las areas a 6.
TOL_Q = 0.02

# Cuanto puede alejarse una carga de ser exactamente el peso propio de
# la barra para seguir considerandola "solo peso propio", en tanto por
# uno. Una viga sin losa encima aplica su peso y nada mas.
TOL_PESO_PROPIO = 1e-4

# Cuanto pueden discrepar el area sellada en un elemento y la que suman
# sus poligonos, en m2. Los dos vienen redondeados a 4 y 6 decimales, asi
# que 1e-3 m2 -- 10 cm2 -- es holgado para el redondeo y fino para
# cualquier error de reparto real.
TOL_AREA_M2 = 1e-3

# Casos que reparten losa por area. Los laterales aplican fuerza en los
# nodos maestros y no tienen nada que ver con esto.
CASOS_DE_GRAVEDAD = ('G', 'Q')


def _cota(e, nodos):
    n1, n2 = nodos[int(e['n1'])], nodos[int(e['n2'])]
    return round((float(n1['z']) + float(n2['z'])) / 2.0, 2)


def _mediana(v):
    v = sorted(v)
    if not v:
        return 0.0
    mitad = len(v) // 2
    return v[mitad] if len(v) % 2 else (v[mitad - 1] + v[mitad]) / 2.0


def peso_propio_por_metro(e, secciones, gamma):
    """Lo que pesa un metro de esta barra, en kN/m."""
    s = secciones.get(e.get('seccion'))
    if not s:
        return 0.0
    return float(s.get('A', 0.0)) * gamma


def repartir(caso, elementos, nodos, secciones, gamma, con_area, restar_pp):
    """
    Recorre las cargas distribuidas de un caso y devuelve, por cota:
    los q implicitos de cada barra, los kN de losa aplicados y los m2
    que se le atribuyen. Devuelve tambien las cargas que no se explican
    y cuantas barras aplican solo su propio peso.
    """
    por_piso, losa, area = {}, {}, {}
    sin_explicar, solo_su_peso = [], 0

    for c in caso.get('cargas_distribuidas', []):
        t = int(c['elemento'])
        w = abs(float(c.get('wz', 0.0)))
        if w == 0.0 or t not in elementos:
            continue
        e = elementos[t]
        pp = peso_propio_por_metro(e, secciones, gamma)
        A = con_area.get(t, 0.0)

        if A <= 0:
            # Una viga sin losa encima aplica su peso y nada mas: eso
            # esta bien. Cualquier otra carga sin area detras es carga
            # que nadie puede dibujar ni justificar.
            if pp > 0 and abs(w - pp) <= TOL_PESO_PROPIO * max(pp, 1.0):
                solo_su_peso += 1
            else:
                sin_explicar.append(t)
            continue

        L = _ed.largo(e, nodos)
        if L <= 1e-9:
            continue
        w_losa = w - pp if (restar_pp and w > pp) else w
        z = _cota(e, nodos)
        por_piso.setdefault(z, []).append((w_losa * L / A, t))
        losa[z] = losa.get(z, 0.0) + w_losa * L
        area[z] = area.get(z, 0.0) + A

    return por_piso, losa, area, sin_explicar, solo_su_peso


def _cuantas_fuera(por_piso):
    """Barras cuyo q se aparta de la mediana de su piso."""
    n = 0
    for valores in por_piso.values():
        q_piso = _mediana([q for q, _t in valores])
        n += sum(1 for q, _t in valores
                 if abs(q - q_piso) > TOL_Q * max(q_piso, 1e-9))
    return n


def revisar_tributarias(modelo, vista_, nombre):
    """
    Revisa un modelo (el edificio o un cuerpo). Devuelve (problemas, q) con
    q = {caso: {cota: q del piso}} (vacio si el modelo junta dos cuerpos).
    Imprime el detalle por consola.

    EL PESO PROPIO VIAJA ADENTRO. En G, w = A_sec*gamma + q*A_trib/L.
    Dividir w por el area no da la presion de la losa. El caso lo declara
    en 'incluye_peso_propio'; si no lo declara, se INFIERE probando las dos
    hipotesis y se dice que se infirio. La resta es condicional (solo si w
    supera al peso propio): un brazo rigido tiene seccion ficticia de 400
    kN/m que nunca se aplico.

    EL q SE COMPARA DENTRO DE CADA PISO. Un techo carga menos que un piso
    tipo, y eso es correcto. Si el modelo junta los dos cuerpos no se
    compara: un mismo nivel tiene losas con presiones distintas (eso lo
    hace la revision por cuerpo).
    """
    problemas = []
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}
    secciones = {s['nombre']: s for s in modelo.get('secciones', [])}
    gamma = float(modelo.get('material', {}).get('gamma', 0.0) or 0.0)
    cuerpos = sorted({_ed.cuerpo_de(t) for t in elementos})
    q_por_piso = {}

    con_area = {t: float(e[_ed.CAMPO_AREA])
                for t, e in elementos.items()
                if float(e.get(_ed.CAMPO_AREA, 0.0)) > 0}

    print('  %d de %d elementos reciben losa, %.2f m2 en total'
          % (len(con_area), len(elementos), sum(con_area.values())))

    if not con_area:
        problemas.append('%s: ningun elemento trae area tributaria' % nombre)
        return problemas, q_por_piso

    # ---- 1. el modelo y su dibujo dicen lo mismo -------------------
    del_dibujo = _ed.areas_por_elemento(vista_)
    if del_dibujo:
        solo_modelo = sorted(set(con_area) - set(del_dibujo))
        solo_dibujo = sorted(set(del_dibujo) - set(con_area))
        peor, cual = 0.0, None
        for t in set(con_area) & set(del_dibujo):
            if abs(con_area[t] - del_dibujo[t]) > peor:
                peor, cual = abs(con_area[t] - del_dibujo[t]), t
        print('     dibujo: %d elementos, %.2f m2; peor diferencia %.6f m2'
              % (len(del_dibujo), sum(del_dibujo.values()), peor))
        if solo_modelo:
            problemas.append(
                '%s: %d elemento(s) reciben losa sin tener poligono (el '
                'visor los deja como hueco blanco): %s'
                % (nombre, len(solo_modelo), solo_modelo[:8]))
        if solo_dibujo:
            problemas.append(
                '%s: %d poligono(s) dibujados sobre elementos sin area '
                'sellada: %s' % (nombre, len(solo_dibujo), solo_dibujo[:8]))
        if peor > TOL_AREA_M2:
            problemas.append(
                '%s: el elemento %d tiene %.4f m2 en el modelo y %.4f m2 '
                'en el dibujo' % (nombre, cual, con_area[cual],
                                  del_dibujo[cual]))
    else:
        problemas.append('%s: la vista no trae poligonos de losa con que comparar' % nombre)

    # ---- 2. y 3. la carga contra el area, piso por piso ------------
    for caso in modelo.get('casos_de_carga', []):
        if caso.get('nombre') not in CASOS_DE_GRAVEDAD:
            continue
        etiqueta = caso['nombre']

        comun = (elementos, nodos, secciones, gamma, con_area)
        declarado = caso.get(_ed.CAMPO_PESO_PROPIO)
        if declarado is not None:
            restar, origen = bool(declarado), 'declarado'
        else:
            # Se prueban las dos y gana la que deja el q constante
            # dentro de cada piso. El empate se resuelve por la
            # hipotesis simple: la carga es solo losa.
            con_resta = repartir(caso, *comun, restar_pp=True)
            sin_resta = repartir(caso, *comun, restar_pp=False)
            restar = _cuantas_fuera(con_resta[0]) < _cuantas_fuera(sin_resta[0])
            origen = 'inferido'

        por_piso, losa, area, sin_explicar, solo_su_peso = repartir(
            caso, *comun, restar_pp=restar)

        if not por_piso:
            continue

        if sin_explicar:
            problemas.append(
                '%s, caso %s: %d elemento(s) reciben carga que no es losa ni '
                'su propio peso: %s' % (nombre, etiqueta, len(sin_explicar),
                                        sorted(sin_explicar)[:8]))

        print('     caso %s   peso propio en la carga distribuida: %s (%s)%s'
              % (etiqueta, 'SI' if restar else 'no', origen,
                 ('   %d barra(s) aplican solo su peso propio' % solo_su_peso)
                 if solo_su_peso else ''))

        # La tabla de abajo solo cuenta lo que baja REPARTIDO. La losa
        # que se apoya directo sobre un muro va como carga puntual en su
        # baricentro, asi que su area no aparece en ninguna fila. Sin
        # decirlo, las columnas no suman el total del encabezado y quien
        # mire va a creer que falta losa.
        repartida = sum(area.values())
        puntual = sum(con_area.values()) - repartida
        if puntual > TOL_AREA_M2:
            print('        %.2f m2 bajan repartidos y %.2f m2 como carga '
                  'puntual sobre muros' % (repartida, puntual))

        if len(cuerpos) > 1:
            print('        (%s junta %s: el q por piso mezcla dos losas y no '
                  'se compara)' % (nombre, ' y '.join(cuerpos)))
            continue

        q_por_piso[etiqueta] = {}
        print('        %-8s %5s %12s %14s %12s'
              % ('cota', 'n', 'q [kN/m2]', 'losa [kN]', 'area [m2]'))
        for z in sorted(por_piso):
            valores = [q for q, _t in por_piso[z]]
            q_piso = _mediana(valores)
            q_por_piso[etiqueta][z] = q_piso
            fuera = [(q, t) for q, t in por_piso[z]
                     if abs(q - q_piso) > TOL_Q * max(q_piso, 1e-9)]
            print('        %+8.2f %5d %12.4f %14.2f %12.2f   %s'
                  % (z, len(valores), q_piso, losa[z], area[z],
                     '' if not fuera else '<-- %d fuera del %.0f%%'
                     % (len(fuera), TOL_Q * 100)))
            for q, t in sorted(fuera, key=lambda p: -abs(p[0] - q_piso))[:5]:
                print('            elemento %d: q = %.4f kN/m2 (%.1f%% del piso)'
                      % (t, q, 100.0 * q / max(q_piso, 1e-9)))
            if fuera:
                problemas.append(
                    '%s, caso %s, cota %+.2f: %d barra(s) con q implicito '
                    'fuera del %.0f%% de %.4f kN/m2'
                    % (nombre, etiqueta, z, len(fuera), TOL_Q * 100, q_piso))

            # La conservacion que pide el laboratorio:  suma = q * A.
            # Es identidad si todas las barras del piso dan el mismo q,
            # que es justo lo que se acaba de comprobar; se calcula
            # igual porque es EL numero que hay que mostrar.
            esperado = q_piso * area[z]
            if abs(esperado - losa[z]) > 1e-3 * max(esperado, 1.0):
                problemas.append(
                    '%s, caso %s, cota %+.2f: la losa aplicada suma %.4f kN '
                    'pero q*A da %.4f kN'
                    % (nombre, etiqueta, z, losa[z], esperado))

    return problemas, q_por_piso


def vista_de(vista_, cuerpo):
    """Los poligonos de losa de un cuerpo (por el tag de su elemento)."""
    v = dict(vista_)
    v['areas_tributarias'] = [a for a in vista_.get('areas_tributarias', [])
                              if _ed.cuerpo_de(a['elemento']) == cuerpo]
    return v


def tributarias(inf, args=None):
    """E3: la losa que se aplica es la que se dibuja, en el edificio y por cuerpo."""
    edificio = _ed.cargar()
    modelo = _ed.estructura(edificio)
    vista_ = _ed.vista(edificio)

    print('=' * 68)
    print('  AREAS TRIBUTARIAS: EL MODELO CONTRA SU DIBUJO')
    print('=' * 68)
    print('\n%s' % _ed.NOMBRE)
    problemas, _q = revisar_tributarias(modelo, vista_, _ed.NOMBRE)
    con_area = [e for e in modelo['elementos'] if float(e.get(_ed.CAMPO_AREA, 0.0)) > 0]
    area = sum(float(e[_ed.CAMPO_AREA]) for e in con_area)
    inf.check(not problemas, '%s: el area sellada = la de los poligonos y ninguna carga sin explicar'
              % _ed.NOMBRE, problemas[:5])
    inf.check(calza(len(con_area), 'tributarias', 'elementos_con_losa')
              and calza(round(area, 2), 'tributarias', 'area_m2'),
              '%d elementos con losa, %.2f m2: los numeros de control' % (len(con_area), area))

    # POR CUERPO. En el edificio el q por piso no se compara (cada nivel
    # tiene las dos losas); un pano de losa que nunca entro al modelo NO
    # rompe el equilibrio, y la unica forma de verlo es esta tabla: q
    # constante dentro de cada piso de cada cuerpo, y sum(w L) = q A.
    for cuerpo, sub in _ed.por_cuerpo(modelo).items():
        print('\n%s   (tags %dxxxxx)' % (cuerpo, numero_de(cuerpo)))
        problemas, q = revisar_tributarias(sub, vista_de(vista_, cuerpo), cuerpo)
        inf.check(not problemas and set(q) == set(CASOS_DE_GRAVEDAD),
                  '%s: q constante en cada piso (%.0f %%) y sum(w L) = q A en G y Q'
                  % (cuerpo, 100 * TOL_Q), problemas[:5])
    print('\n' + '=' * 68)


# ============================================================
# MODELO
# ============================================================
def J_rectangular(b, h):
    """
    Torsion de Saint-Venant para seccion rectangular llena.

    NO es min(Iy,Iz)*0.3: esa expresion no corresponde a ninguna
    formula y subestima J varias veces.
    """
    a = max(b, h)
    t = min(b, h)
    return a * t ** 3 * (1.0 / 3.0 - 0.21 * (t / a) * (1.0 - t ** 4 / (12.0 * a ** 4)))


def mediana_superior(v):
    """v[n // 2] de la lista ordenada: la mediana con que se miden los pisos."""
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


def _cota_de(sub):
    """{maestro: cota} y la cota de la base de un cuerpo."""
    nodos = {int(n['id']): n for n in sub['nodos']}
    niveles = [(round(float(nodos[int(d['nodo_maestro'])]['z']), 2), int(d['nodo_maestro']))
               for d in sub['diafragmas']]
    return sorted(niveles), round(min(float(n['z']) for n in sub['nodos']), 2)


def _con_brazo(sub, cuerpo, f):
    """El cuerpo con la seccion de sus brazos escalada al factor f."""
    m = copy.deepcopy(sub)
    m['casos_de_carga'] = [c for c in m['casos_de_carga'] if c['nombre'] == 'G']
    S = seccion_de(m)
    if cuerpo == 'lt2':
        # El brazo del LT2 es un cuadrado de lado 0.8 raiz(f): f = 25 da el
        # 4 x 4 m del edificio.
        lado = math.sqrt(f) * 0.8
        s = S['lt2:BRAZO']
        s.update({'b': lado, 'h': lado, 'A': lado * lado, 'Iy': lado * lado ** 3 / 12.0,
                  'Iz': lado * lado ** 3 / 12.0, 'J': J_rectangular(lado, lado)})
    else:
        # El del cuerpo antiguo es la columna por f (A, I y J): f = 100 es el
        # del edificio.
        c, s = S['ingenieria:columna'], S['ingenieria:brazo_rigido']
        for k in ('A', 'Iy', 'Iz', 'J'):
            s[k] = float(c[k]) * f
    return m


def _resolver_crudo(data, caso, factor=1.0):
    """
    Arma `data` en OpenSees y resuelve `caso` (con sus cargas por `factor`,
    que en 2.0 es exacto en coma flotante). Devuelve {nodo: [6 GDL]} SIN
    redondear: la linealidad y el diafragma se ven al ultimo bit.
    """
    sol = opensees.Resolutor(data)
    if factor != 1.0:
        caso = copy.deepcopy(caso)
        for c in caso.get('cargas_nodales', []):
            for k in ('fx', 'fy', 'fz', 'mx', 'my', 'mz'):
                if k in c:
                    c[k] = float(c[k]) * factor
        for c in caso.get('cargas_distribuidas', []):
            for k in ('wx', 'wy', 'wz'):
                if k in c:
                    c[k] = float(c[k]) * factor
    opensees.aplicar_cargas(caso, 100, set(sol.coords), {int(e['id']) for e in data['elementos']})
    if opensees.resolver_caso() != 0:
        raise SystemExit('OpenSees no convergio')
    return sol.desplazamientos()


def _casos_del(sub):
    return {c['nombre']: c for c in sub['casos_de_carga']}


def modelo(inf, args=None):
    """E4: lo del modelo que el equilibrio no ve, por cuerpo."""
    edificio = _ed.cargar()
    mod = _ed.estructura(edificio)
    vista_ = _ed.vista(edificio)
    sup = _ed.supuestos(edificio)
    partes = _ed.por_cuerpo(mod)
    S = seccion_de(mod)

    print('=' * 68)
    print('  VERIFICACION DEL MODELO, POR CUERPO')
    print('=' * 68)
    with opensees.AvisosDeOpenSees():
        resueltos, _av = opensees.resolver_edificio(mod)
    res = {r['caso']: r for r in resueltos}
    desp = {c: {int(d['id']): d for d in r['desplazamientos']} for c, r in res.items()}
    print()
    for cuerpo, sub in partes.items():
        t = collections.Counter(e['tipo'] for e in sub['elementos'])
        reales = sum(1 for n in sub['nodos'] if not n.get('auxiliar'))
        metal = t['pilar_metal'] + t['diagonal'] + t['viga_metal']
        print('  %-11s %d nodos · %d columnas · %d muros · %d vigas · %d brazos%s'
              % (cuerpo, reales, t['columna'], t['muro'], t['viga_x'] + t['viga_y'] + t['viga'],
                 t['brazo'] + t['brazo_rigido'], (' · %d barras de acero' % metal) if metal else ''))

    # ------------------------------------------------------------
    print('\n1. Secciones contra calculo a mano')
    p, v = S['lt2:P 0.70x0.70'], S['lt2:V 0.60x0.80']
    # El dato viene con 9 decimales: la cota es medio ultimo digito.
    r9 = 0.5e-9
    inf.check(abs(p['A'] - 0.49) < 1e-12, 'pilar 0.70x0.70: A = 0.49 m2')
    inf.check(abs(p['Iz'] - 0.70 ** 4 / 12.0) <= r9 and abs(p['Iy'] - p['Iz']) < 1e-15,
              '  Iy = Iz = 0.70^4/12   I = %.6f m4' % p['Iz'])
    inf.check(abs(v['Iz'] - 0.60 * 0.80 ** 3 / 12.0) <= r9,
              'viga 0.60x0.80: Iz (gravedad) = b*h^3/12   Iz = %.6f m4' % v['Iz'])
    inf.check(abs(v['Iy'] - 0.80 * 0.60 ** 3 / 12.0) <= r9,
              '  Iy (lateral) = h*b^3/12   Iy = %.6f m4' % v['Iy'])
    inf.check(v['Iz'] > v['Iy'], '  Iz > Iy (canto mayor que ancho)')
    J = J_rectangular(0.30, 0.30)
    inf.check(abs(J / (0.30 ** 4 / 12.0 * 0.3) - 1.0) > 0.5,
              'J de Saint-Venant no es min(Iy,Iz)*0.3   J = %.3e vs el atajo %.3e'
              % (J, 0.30 ** 4 / 12.0 * 0.3))
    # Y TODAS las rectangulares de hormigon, cada una en la convencion de su
    # cuerpo: Iz la de gravedad (b h^3/12) salvo en los muros del cuerpo
    # antiguo, donde la grande (b h^3/12, b = espesor) va en Iy.
    malas, n_rect = [], 0
    for s in mod['secciones']:
        if 'fpc_MPa' not in s or not (s.get('b') and s.get('h')):
            continue
        n_rect += 1
        b, h = float(s['b']), float(s['h'])
        fuerte, debil = b * h ** 3 / 12.0, h * b ** 3 / 12.0
        es_muro_antiguo = s['nombre'].startswith('ingenieria:muro')
        Iy, Iz = (fuerte, debil) if es_muro_antiguo else (debil, fuerte)
        esperado = {'A': b * h, 'Iy': Iy, 'Iz': Iz, 'J': J_rectangular(b, h)}
        if s['nombre'].startswith('lt2:'):
            # El LT2 escribio sus secciones con 9 decimales.
            cotas = {k: r9 + 4 * EPS * abs(x) for k, x in esperado.items()}
        else:
            # El antiguo calculo A, I y J con el largo SIN redondear (una
            # diferencia de coordenadas de menos de 100 m: hasta 2 ulp de
            # 100) y escribio el largo redondeado: hasta 3 dh / h relativo en I.
            dh = 2 * math.ulp(100.0)
            cotas = {k: abs(x) * (3 * dh / h + 4 * EPS) for k, x in esperado.items()}
        if any(abs(float(s[k]) - x) > cotas[k] for k, x in esperado.items()):
            malas.append(s['nombre'])
    inf.check(not malas, 'las %d secciones rectangulares de hormigon: A = b h, sus inercias en la '
              'convencion de su cuerpo y J de Saint-Venant (cota: el redondeo con que se escribio cada '
              'una: 9 decimales en el LT2, el largo sin redondear en el antiguo)' % n_rect, malas[:5])

    # ------------------------------------------------------------
    print('\n2. Equilibrio global (G)')
    for cuerpo, sub in partes.items():
        caso = _casos_del(sub)['G']
        r_sub = _del_cuerpo(res['G'], sub)
        eq = opensees.equilibrio(sub, caso, r_sub)
        nz = opensees.filas_que_cuentan(sub, r_sub['reacciones'])[2]
        err = abs(eq['error_kN'][2])
        inf.check(eq['confiable'] and err <= nz * R_KN + R_EQ,
                  '%s: suma de reacciones = carga aplicada   error = %.3e kN sobre %.0f kN '
                  '(cota del redondeo %.1e: %d apoyos x 0.5e-4)'
                  % (cuerpo, err, -eq['aplicada_kN'][2], nz * R_KN + R_EQ, nz))

    # ------------------------------------------------------------
    print('\n3. Orientacion de los muros (el error que no avisa)')
    # Un muro mal orientado aporta (L/t)^2 veces menos rigidez lateral y el
    # modelo no se queja. La inercia FUERTE tiene que estar en el hueco que
    # le corresponde segun la convencion de su cuerpo.
    for cuerpo, sub in partes.items():
        muros = [e for e in sub['elementos'] if e['tipo'] == 'muro']
        if not muros:
            continue
        hueco = 'Iz' if cuerpo == 'lt2' else 'Iy'
        malos = [e['id'] for e in muros
                 if not float(S[e['seccion']][hueco]) > float(S[e['seccion']]['Iy' if hueco == 'Iz' else 'Iz'])]
        inf.check(not malos, '%s: todos los muros llevan la inercia fuerte en %s de la seccion'
                  % (cuerpo, hueco), malos[:5])
        razones = [(float(S[e['seccion']]['h']) / float(S[e['seccion']]['b'])) ** 2 for e in muros]
        inf.check(max(razones) > 100,
                  '%s: la razon I_fuerte/I_debil llega a valores enormes   maximo (L/t)^2 = %.0f  ->  '
                  'orientar mal un muro lo hace %.0f veces menos rigido' % (cuerpo, max(razones), max(razones)))
    nodos = {int(n['id']): n for n in mod['nodos']}
    paralelos = []
    for e in mod['elementos']:
        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        pi, pj = (a['x'], a['y'], a['z']), (b['x'], b['y'], b['z'])
        vecxz = e.get('vecxz') or _ed.vecxz_por_defecto(pi, pj)
        base, _L = _ed.ejes_locales(pi, pj, [float(x) for x in vecxz])
        if base is None:
            paralelos.append(e['id'])
    inf.check(not paralelos, 'ningun vecxz (propio o el de la regla del motor) es paralelo al eje de '
              'su barra, en las %d' % len(mod['elementos']), paralelos[:5])

    # ------------------------------------------------------------
    print('\n4. Linealidad y superposicion')
    # El modelo es lineal: duplicar la carga duplica todo. Si no lo hace,
    # hay algo no lineal metido sin querer. Se lee sin el redondeo del motor.
    caso_g = _casos_del(mod)['G']
    with opensees.AvisosDeOpenSees():
        u1 = _resolver_crudo(mod, caso_g)
        u2 = _resolver_crudo(mod, caso_g, factor=2.0)
    for cuerpo, sub in partes.items():
        ids = [int(n['id']) for n in sub['nodos']]
        comunes = [t for t in ids if abs(u1[t][2]) > 1e-9]
        error = max(abs(u2[t][2] / u1[t][2] - 2.0) for t in comunes)
        inf.check(error < 1e-9, '%s: 2x carga da exactamente 2x desplazamiento   peor error relativo = %.2e'
                  % (cuerpo, error))

    # ------------------------------------------------------------
    print('\n5. Compatibilidad del diafragma rigido')
    # equalDOF NO es un diafragma: obliga al mismo ux en todo el piso. El
    # diafragma real permite ROTACION y cumple
    #     ux_i = ux_m - rz*(y_i - y_m)
    #     uy_i = uy_m + rz*(x_i - x_m)
    for cuerpo, sub in partes.items():
        peor_err, giro_max = 0.0, 0.0
        for d in sub['diafragmas']:
            m = int(d['nodo_maestro'])
            xm, ym = float(nodos[m]['x']), float(nodos[m]['y'])
            uxm, uym, rz = u1[m][0], u1[m][1], u1[m][5]
            giro_max = max(giro_max, abs(rz))
            for s in d['nodos']:
                s = int(s)
                x, y = float(nodos[s]['x']), float(nodos[s]['y'])
                ex = abs(u1[s][0] - (uxm - rz * (y - ym)))
                ey = abs(u1[s][1] - (uym + rz * (x - xm)))
                peor_err = max(peor_err, ex, ey)
        inf.check(peor_err < 1e-9, '%s: todos los nodos del piso cumplen la relacion del diafragma   '
                  'peor error = %.2e m' % (cuerpo, peor_err))
        inf.check(giro_max > 0.0, '%s: el diafragma PERMITE giro (no es un equalDOF disfrazado)   '
                  'giro maximo de piso = %.2e rad' % (cuerpo, giro_max))

    # ------------------------------------------------------------
    print('\n6. Los brazos son rigidos de verdad')
    # Un brazo representa el pedazo de muro entre el extremo real de la viga
    # y el baricentro de la columna ancha. Si el resultado depende de cuan
    # rigido se lo hizo, es que no es rigido: es una viga mas.
    declarado = {'lt2': 25.0,
                 'ingenieria': float(sup['ingenieria']['constantes_del_modelo']['brazo_rigido_factor'])}
    for cuerpo, sub in partes.items():
        reales = [int(n['id']) for n in sub['nodos'] if not n.get('auxiliar')]
        med = {}
        for f in (25.0, 100.0, 400.0):
            with opensees.AvisosDeOpenSees():
                r = opensees.construir_y_resolver(_con_brazo(sub, cuerpo, f))['casos'][0]
            uz = {int(d['id']): d['uz'] for d in r['desplazamientos']}
            med[f] = mediana_superior([abs(uz[t]) for t in reales])
        variacion = (max(med.values()) - min(med.values())) / max(med.values())
        detalle = ('x25: %.3f mm · x100: %.3f mm · x400: %.3f mm  ->  varia %.2f %%'
                   % (med[25.0] * 1000, med[100.0] * 1000, med[400.0] * 1000, 100 * variacion))
        if cuerpo == 'lt2' or variacion < 0.02:
            inf.check(variacion < 0.02,
                      '%s: el resultado no depende del factor de rigidez del brazo (el del edificio: x%.0f)'
                      % (cuerpo, declarado[cuerpo]), detalle)
        else:
            # El brazo del cuerpo antiguo es la columna x 100 (supuestos.
            # ingenieria.constantes_del_modelo), diez veces menos inercia que
            # el 4 x 4 m del LT2 y hasta 4 m de largo: los nodos que cuelgan
            # de un brazo todavia sienten su flexion. Subir el factor cambia
            # todos los numeros del edificio: es una decision, no un arreglo,
            # y queda abierta con lo que mide.
            print('         %s' % detalle)
            inf.pendiente('%s: el resultado DEPENDE del factor del brazo (x%.0f en el edificio): la '
                          'mediana de uz en G varia %.1f %% entre x25 y x400 (el LT2: 0.00 %%). Queda '
                          'abierto: subir el factor es una decision que mueve todos los numeros'
                          % (cuerpo, declarado[cuerpo], 100 * variacion))

    # ------------------------------------------------------------
    print('\n7. Zonas sin apoyo vertical (un nodo colgando)')
    # Un nodo que baja diez veces mas que la mediana de su piso no es "una
    # viga flexible": es una zona que cuelga de una cadena de vigas sin
    # ningun muro ni pilar abajo. LAPACK no siempre falla con la matriz
    # singular; a veces devuelve un numero enorme, que es peor, porque
    # parece un resultado (un muro colgando dio UZ = -1.2e14 mm).
    uzG = {t: abs(float(d['uz'])) for t, d in desp['G'].items()}
    for cuerpo, sub in partes.items():
        niveles, z0 = _cota_de(sub)
        reales = {int(n['id']): n for n in sub['nodos'] if not n.get('auxiliar')}
        sospechosos = []
        por_nivel = {}
        for z, _m in niveles:
            del_piso = {t: uzG[t] for t, n in reales.items() if abs(round(float(n['z']), 2) - z) < 1e-9}
            por_nivel[z] = del_piso
            if len(del_piso) < 5:
                continue
            med = mediana_superior(list(del_piso.values()))
            if med <= 0:
                continue
            for t, u in del_piso.items():
                if u > 10.0 * med:
                    sospechosos.append((z, t, u * 1000, u / med))
        print('     %s: nodos que bajan mas de 10 veces la mediana de su piso: %d'
              % (cuerpo, len(sospechosos)))
        for z, t, mm_, veces in sorted(sospechosos, key=lambda s: -s[2])[:6]:
            print('       nivel %+6.2f  nodo %6d  uz = %8.2f mm  (%.0fx)' % (z, t, mm_, veces))
        if sospechosos:
            print('     -> revisar esos puntos CONTRA EL PLANO antes de usar el modelo')
        # Los niveles LIMPIOS (sin ningun nodo sospechoso) tienen que estar en
        # rango de hormigon armado; el nivel sospechoso se declara pendiente,
        # no se aprueba. Y NINGUN nivel puede pasar de ese rango: un muro que
        # cuelga sin nada debajo no da un nodo "sospechoso", da 1e14 mm.
        sucios = {s[0] for s in sospechosos}
        for z, _m in niveles:
            vals = sorted(u * 1000 for u in por_nivel[z].values())
            inf.check(vals[-1] < 15.0, '%s nivel %+6.2f: el peor nodo baja menos de 15 mm'
                      % (cuerpo, z), 'maximo = %.2f mm, mediana = %.2f mm' % (vals[-1], mediana_superior(vals)))
            if z in sucios:
                inf.pendiente('%s nivel %+6.2f: NO se aprueba. maximo = %.2f mm, mediana = %.2f mm: hay '
                              'nodos colgando de vigas sin muro ni pilar debajo'
                              % (cuerpo, z, vals[-1], mediana_superior(vals)))

    # ------------------------------------------------------------
    print('\n8. La carga contra lo declarado (supuestos)')
    q = {}
    for cuerpo, sub in partes.items():
        with _silencio():
            _p, q[cuerpo] = revisar_tributarias(sub, vista_de(vista_, cuerpo), cuerpo)
    gamma = float(mod['material']['gamma'])
    # El LT2: la lamina 2024_22-700 trae el peso muerto adicional y la
    # sobrecarga por planta, en kgf/m2; la losa pesa e * gamma.
    cargas = sup['lt2']['cargas']
    g_ms2 = float(cargas['g_ms2'])
    lamina_de = {round(float(pp['z']), 2): pp['lamina'] for pp in sup['lt2']['niveles_del_modelo']['pisos']}
    espesores, area_piso = {}, collections.defaultdict(float)
    for a in vista_de(vista_, 'lt2')['areas_tributarias']:
        area_piso[round(float(a['z']), 2)] += float(a['area'])
    for lam, c in cargas['por_lamina'].items():
        zs = [z for z, l in lamina_de.items() if l == lam]
        pm = c['peso_muerto_adicional_kgf_m2'] * g_ms2 / 1000.0
        sc = c['sobrecarga_kgf_m2'] * g_ms2 / 1000.0
        qG = [q['lt2']['G'][z] for z in zs]
        qQ = [q['lt2']['Q'][z] for z in zs]
        e = [(x - pm) / gamma for x in qG]
        espesores[lam] = e
        inf.check(max(e) - min(e) <= 1e-5,
                  '%s: G = peso losa + PM adicional del plano' % lam,
                  'G = %.2f kN/m2 (losa %.2f + PM adic %.2f) en %d piso(s): losa de e = %.3f m'
                  % (qG[0], gamma * e[0], pm, len(zs), e[0]))
        inf.check(max(abs(x - sc) for x in qQ) <= 1e-4,
                  '  Q = sobrecarga del plano   Q = %.2f kN/m2' % qQ[0])
    todos = [x for v_ in espesores.values() for x in v_]
    e_losa = todos[0]
    inf.check(max(todos) - min(todos) <= 1e-5,
              'el LT2 tiene una sola losa: e = %.3f m en las dos plantas de cargas' % e_losa)
    peso_losa = e_losa * gamma
    inf.check(abs(peso_losa - e_losa * 2500 * g_ms2 / 1000.0) / peso_losa < 0.03,
              'el peso propio de la losa calza con el "e x 2500 kgf/m3" del plano',
              'modelo %.3f kN/m2 con gamma=%.0f vs plano %.3f kN/m2 con 2500 kgf/m3'
              % (peso_losa, gamma, e_losa * 2500 * g_ms2 / 1000.0))
    g_lt2 = -opensees.equilibrio(partes['lt2'], _casos_del(partes['lt2'])['G'], {'reacciones': []})['aplicada_kN'][2]
    carga_losa = sum(q['lt2']['G'][z] * area_piso[z] for z in lamina_de)
    inf.check(0.25 < carga_losa / g_lt2 < 0.85, 'lt2: la carga de losa es una fraccion sensata del total',
              'losa %.0f kN de %.0f kN totales (%.0f %%)' % (carga_losa, g_lt2, 100 * carga_losa / g_lt2))
    # El cuerpo antiguo: losa supuesta + terminaciones, y la sobrecarga de trabajo.
    cte = sup['ingenieria']['constantes_del_modelo']
    e_ing = float(sup['ingenieria']['secciones']['losa']['espesor_m'])
    qG_ing = gamma * e_ing + float(cte['terminaciones_kN_m2'])
    inf.check(max(abs(x - qG_ing) for x in q['ingenieria']['G'].values()) <= 1e-4,
              'ingenieria: G = gamma e + terminaciones = %.0f x %.2f + %.1f = %.2f kN/m2 en todos los pisos'
              % (gamma, e_ing, float(cte['terminaciones_kN_m2']), qG_ing))
    inf.check(max(abs(x - float(cte['sobrecarga_kN_m2'])) for x in q['ingenieria']['Q'].values()) <= 1e-4,
              'ingenieria: Q = %.1f kN/m2 en todos los pisos (constantes_del_modelo.sobrecarga, sin fuente '
              'normativa: el laboratorio usa su propio q)' % float(cte['sobrecarga_kN_m2']))

    # ------------------------------------------------------------
    print('\n9. Los dinteles declarados estan en el modelo')
    dx = float(sup['calce']['edificios']['lt2'].get('dx', 0.0))
    dy = float(sup['calce']['edificios']['lt2'].get('dy', 0.0))
    niveles_lt2 = cotas_de_piso(sup)
    hallados, faltan = [], []
    for d in sup['lt2']['dinteles']:
        vg = d['viga']
        seccion = 'lt2:V %.2fx%.2f' % (float(vg['ancho']), float(vg['alto']))
        z = niveles_lt2[int(d['desde_nivel'])]
        p1 = (float(vg['x1']) + dx, float(vg['y1']) + dy)
        p2 = (float(vg['x2']) + dx, float(vg['y2']) + dy)
        L = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        u = ((p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L)
        cubierto = 0.0
        for e in partes['lt2']['elementos']:
            if e['seccion'] != seccion:
                continue
            a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
            if abs(a['z'] - z) > 1e-6 or abs(b['z'] - z) > 1e-6:
                continue
            # sobre la recta del dintel (a 1 cm) y cuanto de su vano cubre
            lejos = max(abs((n['x'] - p1[0]) * u[1] - (n['y'] - p1[1]) * u[0]) for n in (a, b))
            if lejos > 0.01:
                continue
            s1 = (a['x'] - p1[0]) * u[0] + (a['y'] - p1[1]) * u[1]
            s2 = (b['x'] - p1[0]) * u[0] + (b['y'] - p1[1]) * u[1]
            cubierto += max(0.0, min(max(s1, s2), L) - max(min(s1, s2), 0.0))
        (hallados if cubierto >= L - 0.01 else faltan).append(d['nombre'])
    inf.check(not faltan, 'los dinteles declarados (supuestos.lt2.dinteles) estan en el modelo, con su '
              'seccion y en su nivel', 'declarados: %s' % sorted(hallados + faltan)
              + ('; FALTAN: %s' % faltan if faltan else ''))

    # ------------------------------------------------------------
    print('\n10. El area de losa, piso contra piso')
    # Un pano que desaparece es un agujero silencioso: la losa sigue
    # dibujada y rotulada en el plano, pero su peso deja de bajar, y el
    # equilibrio cierra igual porque esa carga nunca entro. La unica forma
    # de verlo es comparar un piso con los demas, y una diferencia solo
    # pasa si esta DECLARADA con su motivo.
    for cuerpo in partes:
        areas = collections.defaultdict(float)
        for a in vista_de(vista_, cuerpo)['areas_tributarias']:
            areas[round(float(a['z']), 2)] += float(a['area'])
        cfg = sup.get(cuerpo, {}).get('losa_diferencias_aceptadas')
        tipico = mediana_superior(list(areas.values()))
        print('    %s' % cuerpo)
        print('    %-8s %12s %12s   %s' % ('nivel', 'area [m2]', 'vs tipico', ''))
        if cfg is None:
            for z, a_ in sorted(areas.items()):
                print('    %+7.2f %12.2f %+12.2f' % (z, a_, a_ - tipico))
            inf.pendiente('%s: supuestos.%s no declara losa_diferencias_aceptadas: sus pisos se '
                          'informan y no se exigen' % (cuerpo, cuerpo))
            continue
        tol_area = float(cfg.get('tolerancia_m2', 0.5))
        declaradas = {round(float(d['z']), 2): d for d in cfg.get('niveles', [])}
        sin_declarar = []
        for z, a_ in sorted(areas.items()):
            dif = a_ - tipico
            d = declaradas.get(z)
            if abs(dif) < tol_area:
                nota = ''
            elif d is not None and abs(dif - float(d['diferencia_m2'])) < tol_area:
                nota = '  declarada%s' % (' (PROVISORIA)' if d.get('provisorio') else '')
            else:
                nota = '  <-- SIN DECLARAR'
                sin_declarar.append((z, dif))
            print('    %+7.2f %12.2f %+12.2f   %s' % (z, a_, dif, nota))
        inf.check(not sin_declarar, '%s: toda diferencia de area de losa esta declarada' % cuerpo,
                  ('sin declarar: %s' % ['%+.2f en %+.2f' % (d, z) for z, d in sin_declarar])
                  if sin_declarar else
                  'piso tipico %.2f m2; %d diferencia(s) declarada(s)' % (tipico, len(declaradas)))
        for z, d in sorted(declaradas.items()):
            if d.get('provisorio'):
                print('    PENDIENTE en %+.2f (%+.2f m2): %s'
                      % (z, float(d['diferencia_m2']),
                         (d['motivo'][0] if isinstance(d['motivo'], list) else d['motivo'])))

    # ------------------------------------------------------------
    print('\n11. Los cuatro casos de carga del modelo')
    for cuerpo, sub in partes.items():
        casos = _casos_del(sub)
        niveles, z0 = _cota_de(sub)
        suma_G = sum(lab.peso_vertical_por_nivel(sub, casos['G']))
        carga_G = -opensees.equilibrio(sub, casos['G'], {'reacciones': []})['aplicada_kN'][2]
        inf.check(abs(suma_G - carga_G) < 1e-3, '%s: el peso por nivel suma la carga G aplicada'
                  % cuerpo, 'por nivel %.4f vs aplicado %.4f kN' % (suma_G, carga_G))
        eqs = {}
        for c, eje in (('G', 2), ('Q', 2), ('EX', 0), ('EY', 1)):
            r_sub = _del_cuerpo(res[c], sub)
            eq = opensees.equilibrio(sub, casos[c], r_sub)
            n = opensees.filas_que_cuentan(sub, r_sub['reacciones'])
            eqs[c] = (eq, n)
            cota = n[eje] * R_KN + R_EQ
            inf.check(eq['confiable'] and abs(eq['error_kN'][eje]) <= cota,
                      '%s caso %s: equilibrio' % (cuerpo, c),
                      'aplicada %.4f  reacciones %.4f  error %.2e kN (cota %.1e)'
                      % (eq['aplicada_kN'][eje], eq['reaccion_kN'][eje], abs(eq['error_kN'][eje]), cota))
        for c in ('EX', 'EY'):
            eq, n = eqs[c]
            inf.check(abs(eq['reaccion_kN'][2]) <= n[2] * R_KN + R_EQ,
                      '%s caso %s: no introduce carga vertical' % (cuerpo, c),
                      'suma Fz = %.2e kN (cota %.1e)' % (eq['reaccion_kN'][2], n[2] * R_KN + R_EQ))
        for c in ('G', 'Q'):
            eq, n = eqs[c]
            inf.check(abs(eq['reaccion_kN'][0]) <= n[0] * R_KN + R_EQ
                      and abs(eq['reaccion_kN'][1]) <= n[1] * R_KN + R_EQ,
                      '%s caso %s: no introduce corte horizontal' % (cuerpo, c),
                      'Fx = %.2e   Fy = %.2e kN' % (eq['reaccion_kN'][0], eq['reaccion_kN'][1]))
        _sismo_del_cuerpo(inf, cuerpo, sub, casos, niveles, z0, sup, desp)

    # ------------------------------------------------------------
    print('\n12. Derivas de entrepiso bajo sismo')
    print('    NCh433 5.9.2: la deriva medida en el CENTRO DE MASA no puede')
    print('    pasar de 0.002 de la altura de entrepiso. El centro de masa es')
    print('    justamente el nodo maestro del diafragma, asi que se lee ahi.')
    LIMITE = 0.002
    for cuerpo, sub in partes.items():
        niveles, z0 = _cota_de(sub)
        for caso, i in (('EX', 0), ('EY', 1)):
            comp = 'ux' if i == 0 else 'uy'
            peor, donde = 0.0, None
            print('    %s %s:' % (cuerpo, caso))
            z_ant, u_ant = z0, 0.0        # la base no se desplaza
            for z, m in niveles:
                u = float(desp[caso][m][comp])
                h = z - z_ant
                d = (u - u_ant) / h
                print('      nivel %+6.2f   h=%4.2f m   u=%7.3f mm   deriva = 1/%-6.0f %s'
                      % (z, h, u * 1000, (1.0 / d) if d > 1e-12 else float('inf'),
                         '' if d <= LIMITE else '  <-- PASADA'))
                if d > peor:
                    peor, donde = d, z
                z_ant, u_ant = z, u
            inf.check(peor <= LIMITE, '%s caso %s: deriva de entrepiso bajo el limite' % (cuerpo, caso),
                      'peor %.5f (1/%.0f) en el nivel %+.2f; limite %.3f (1/500)'
                      % (peor, 1.0 / peor if peor else 0, donde or 0.0, LIMITE))
            inf.check(calza(round(1.0 / peor), 'derivas', cuerpo, caso)
                      and calza(donde, 'derivas', cuerpo, 'cota_%s' % caso),
                      '%s caso %s: 1/%.0f en %+.2f, el numero de control' % (cuerpo, caso, 1.0 / peor, donde))


def _sismo_del_cuerpo(inf, cuerpo, sub, casos, niveles, z0, sup, desp):
    """El corte basal del modelo de un cuerpo es el declarado, y se reparte entero."""
    maestro_z = {m: z for z, m in niveles}
    F = {maestro_z[int(c['nodo'])]: float(c.get('fx', 0.0)) for c in casos['EX']['cargas_nodales']}
    FY = {maestro_z[int(c['nodo'])]: float(c.get('fy', 0.0)) for c in casos['EY']['cargas_nodales']}
    V, VY = sum(F.values()), sum(FY.values())
    h = {z: z - z0 for z, _m in niveles}
    if cuerpo == 'lt2':
        # El peso sismico del LT2: W_k = G_k + factor_sobrecarga Q_k en cada
        # nivel con diafragma; lo que cuelga bajo el primer piso (la mitad
        # inferior de los verticales del subterraneo) se pierde en la base,
        # como en un edificio real: esa masa no oscila.
        s = sup['lt2']['sismo']
        coef, lam, n = float(s['coef_basal']), float(s['factor_sobrecarga']), float(s['exponente_altura'])
        Gk, Qk = _peso_por_cota(sub, casos['G']), _peso_por_cota(sub, casos['Q'])
        W = {z: Gk.get(z, 0.0) + lam * Qk.get(z, 0.0) for z in h}
        inf.check(abs(V - coef * sum(W.values())) <= 0.5e-4 * len(F),
                  'lt2: el corte basal es coef x peso sismico (supuestos.lt2.sismo)',
                  'V = %.2f = %.3f x %.2f kN, W = G + %.2f Q en los niveles con diafragma'
                  % (V, coef, sum(W.values()), lam))
        cte = [F[z] / (W[z] * h[z] ** n) for z in sorted(h)]
        # Cada F viaja con 4 decimales: el cociente con medio ultimo digito.
        desvio = max(rel(c_, cte[0]) for c_ in cte)
        cota = max(0.5e-4 / min(F.values()), 1e-12)
        inf.check(desvio <= cota, 'lt2: reparto W h^%g: F_k / (W_k h_k) = %.7f en los %d niveles '
                  '(desvio %.1e, cota del redondeo de F %.1e)' % (n, cte[0], len(cte), desvio, cota))
    else:
        # El cuerpo antiguo armaba su peso sismico (solo G, sin sobrecarga)
        # con su propia cuenta por nivel, que no se puede rehacer desde las
        # cargas del edificio (contaba los pilares y muros de otra forma).
        # Se exige lo que si se puede: que no pase del G del cuerpo.
        cte = sup['ingenieria']['constantes_del_modelo']
        coef = float(cte['coef_sismico'])
        g_c = -opensees.equilibrio(sub, casos['G'], {'reacciones': []})['aplicada_kN'][2]
        inf.check(V <= coef * g_c,
                  'ingenieria: el corte basal no pasa de coef x G del cuerpo (constantes_del_modelo: '
                  'peso sismico sin sobrecarga)',
                  'V = %.2f kN = %.3f x %.2f kN (el peso sismico implicito es el %.1f %% del G del cuerpo, '
                  '%.2f kN)' % (V, coef, V / coef, 100 * V / coef / g_c, g_c))
    inf.check(abs(V - VY) <= 1e-9 * V, '%s: EX y EY tienen el mismo corte basal' % cuerpo,
              '%.2f kN en las dos direcciones' % V)
    # La trampa: repartir con la cota ABSOLUTA en vez de la altura desde la
    # base. La base esta en -7.97, asi que los pisos del subterraneo saldrian
    # con h negativo y recibirian la fuerza al reves.
    inf.check(all(x > 0 for x in h.values()), '%s: todas las alturas de reparto son positivas' % cuerpo,
              'h desde la base %+.2f: %s' % (z0, ['%.2f' % h[z] for z in sorted(h)]))
    inf.check(all(F[z] > 0 for z in F), '%s: ninguna fuerza de piso apunta al reves' % cuerpo,
              'F: %s kN' % ['%.0f' % F[z] for z in sorted(F)])
    orden = [F[z] for z in sorted(F)]
    inf.check(all(a <= b + 1e-9 for a, b in zip(orden, orden[1:])),
              '%s: la fuerza de piso crece con la altura' % cuerpo)
    ids = {int(n['id']) for n in sub['nodos']}
    for caso, i, j in (('EX', 0, 1), ('EY', 1, 0)):
        d = [desp[caso][t] for t in ids]
        k = ('ux', 'uy')
        propio = max(abs(float(x[k[i]])) for x in d)
        cruzado = max(abs(float(x[k[j]])) for x in d)
        inf.check(propio > cruzado, '%s caso %s: el desplazamiento manda en su direccion' % (cuerpo, caso),
                  '%.2f mm en %s contra %.2f mm en la otra' % (propio * 1000, 'XY'[i], cruzado * 1000))


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


def _peso_por_cota(sub, caso):
    """La carga vertical de un caso, sumada por la cota donde actua (una
    repartida sobre una barra no horizontal va mitad a cada extremo)."""
    nodos = {int(n['id']): n for n in sub['nodos']}
    els = {int(e['id']): e for e in sub['elementos']}
    W = collections.defaultdict(float)
    for c in caso.get('cargas_nodales', []):
        W[round(float(nodos[int(c['nodo'])]['z']), 2)] -= float(c.get('fz', 0.0))
    for c in caso.get('cargas_distribuidas', []):
        e = els[int(c['elemento'])]
        za, zb = (round(float(nodos[int(e[k])]['z']), 2) for k in ('n1', 'n2'))
        w = -float(c.get('wz', 0.0)) * _ed.largo(e, nodos)
        if za == zb:
            W[za] += w
        else:
            W[za] += w / 2.0
            W[zb] += w / 2.0
    return W


def _del_cuerpo(res, sub):
    """El resultado del edificio restringido a los nodos de un cuerpo."""
    ids = {int(n['id']) for n in sub['nodos']}
    out = dict(res)
    for k in ('desplazamientos', 'reacciones'):
        out[k] = [x for x in res.get(k, []) if int(x['id']) in ids]
    return out


class _silencio(object):
    """Calla lo que se imprime dentro (una revision que solo se usa por sus numeros)."""

    def __enter__(self):
        self._viejo = sys.stdout
        sys.stdout = io.StringIO()
        return self

    def __exit__(self, *exc):
        sys.stdout = self._viejo
        return False


# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m verificacion.edificio',
                                 description='El edificio contra si mismo y contra sus supuestos')
    ap.add_argument('bloques', nargs='*', metavar='bloque',
                    help='%s (sin bloque: los cuatro)' % ', '.join(BLOQUES))
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    malos = [b for b in a.bloques if b not in BLOQUES]
    if malos:
        ap.error('bloque desconocido: %s (son: %s)' % (', '.join(malos), ', '.join(BLOQUES)))
    hacer = {'dato': dato, 'junta': junta, 'tributarias': tributarias, 'modelo': modelo}
    consola_tolerante()
    t0 = time.time()
    inf = Informe()
    for b in (a.bloques or BLOQUES):
        hacer[b](inf, a)
    print('  (%.0f s)' % (time.time() - t0))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
