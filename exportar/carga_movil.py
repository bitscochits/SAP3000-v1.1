# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/carga_movil.py  -  UNA CARGA PUNTUAL QUE RECORRE UN EJE DE VIGAS
================================================================
 Precalcula en OpenSees una carga vertical P que avanza por una linea
 de vigas continuas de un piso, verifica cada posicion y deja todo en
 salidas/carga_movil.json para que VisorCargaMovil.cs lo MUESTRE. Unity
 no calcula nada: elige una posicion ya resuelta y la dibuja.

 Correr:
   python sap.py exportar carga_movil
   python sap.py exportar carga_movil --P 50 --divisiones 3
   python sap.py exportar carga_movil --no-escribir      solo verificar

 El recorrido (cota, eje, coordenada), la P y las divisiones por
 defecto son de entrada/laboratorio.json, bloque 'carga_movil'.

 Sale con 0 si todo cierra y escribio; con 1 si algo no cierra, y en
 ese caso NO escribe nada. Con --no-escribir (lo que corre la suite)
 ademas compara salidas/carga_movil.json con lo que se arma ahora: un
 archivo viejo tambien es una falla.

 ----------------------------------------------------------------
 LA REGLA FISICA
 ----------------------------------------------------------------
 En cada posicion la carga actua sobre UNA viga del recorrido, en su
 abscisa local a = xL*L medida desde n1, con

     ops.eleLoad('-ele', eid, '-type', '-beamPoint', Py, Pz, xL, Px)

 Las componentes locales salen de los versores de la barra (la misma
 regla que geomTransf, edificio.ejes_locales): P hacia abajo es el
 vector global (0, 0, -P), y su componente en cada eje local es el
 producto punto. En las vigas horizontales del LT2 localZ = (0,0,1):
 Pz = -P y Py = Px = 0.

 El elemento es Euler-Bernoulli: OpenSees convierte la carga en sus
 fuerzas de empotramiento perfecto y resuelve EXACTO. No se reparte a
 mano a los nodos con funciones de forma lineales (P(1-xi), P xi):
 conservan la resultante pero borran la flexion local -- el script lo
 mide (bloque "por que no").

 ----------------------------------------------------------------
 EL REPARTO: POR QUE NO ES 50/50
 ----------------------------------------------------------------
 Lo que la viga le entrega a cada extremo es el corte de localForce,
 Vz_i y Vz_j (fuerzas de los nodos SOBRE la barra). Por equilibrio de
 la barra (momentos en torno a i, eje local y):

     Vz_j = P a/L + (My_i + My_j)/L          Vz_i = P - Vz_j

 El primer termino es la palanca de una viga simplemente apoyada (a
 mitad de vano: 50/50). El segundo lo ponen los MOMENTOS DE EXTREMO,
 y esos dependen de lo que hay en cada nodo: un nodo con columna
 retiene el giro y no baja; uno sin columna (el 200116, un cruce de
 vigas) cuelga de la viga transversal, baja y gira. La carga se va
 hacia el extremo rigido. Se informa tambien la referencia de
 empotramiento perfecto (las "fuerzas nodales equivalentes" que
 OpenSees ensambla): la diferencia con Vz real la explican los
 desplazamientos de los nodos.

 ----------------------------------------------------------------
 LO QUE SE VERIFICA
 ----------------------------------------------------------------
 En cada posicion (sobre los valores REDONDEADOS como el servidor,
 que son los que viajan al visor):
   [a] conservacion: sum Rz = P, con la regla de opensees.equilibrio
       (por grado de libertad, sin maestros). Cota: n_apoyos * 5e-5 kN
       (cada reaccion viene redondeada a 4 decimales) + coma flotante.
   [b] horizontales: sum Rx y sum Ry = 0 con la misma cota.
   [c] la viga cargada: Vz_i + Vz_j + Pz = 0 y el cierre en x = L con
       el termino del salto H(x-a), contra esfuerzos.cota_de_cierre --
       la misma que usa el anexo de diagramas de resultados.json.
   [d] la explicacion del reparto cierra: Vz_j - palanca = (My_i+My_j)/L.
 Globales (en memoria, sin redondeo; criterio: indistinguible en el
 JSON, 1e-8 m y 1e-4 kN, los decimales que escribe el servidor):
   [e] beamPoint contra la viga PARTIDA con un nodo bajo la carga y
       carga nodal (edificio.subdividir): desplazamientos de todos los
       nodos, corte y momento bajo la carga, la flecha bajo la carga que
       se calcula aca y la ELASTICA de la viga cargada que dibuja el
       visor (en los 9 nodos interiores).
   [f] continuidad en un nodo: beamPoint en xL=1 de una viga, en xL=0
       de la siguiente y carga nodal en el nodo comun.
   [g] reciprocidad de Betti entre dos puntos del recorrido.
   [h] superposicion: dos posiciones en una corrida = suma de las dos.
   [i] fuerzas de empotramiento perfecto: la formula de texto contra
       OpenSees en una viga biempotrada aislada.
 Si cualquiera falla, no se escribe nada. Que el JSON calce con las
 clases C# de VisorCargaMovil.cs lo comprueba la verificacion del
 contrato JSON <-> C# (verificacion.unity), no este archivo.

 Las formulas de la viga (Hermite, biempotrada, M con P) son las de
 calculo/elastica.py, las mismas que transcribe el C#.
================================================================
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import time

from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo.elastica import (carga_local, desplazamiento_en, ejes_de, elastica, empotramiento,
                              esfuerzos_con_puntual, rigidez, xyz)

GENERADO_POR = 'exportar/carga_movil.py'

# ------------------------------------------------------------
# LO DECLARADO (no sale del plano: se elige y se dice por que)
# ------------------------------------------------------------
# El recorrido es una linea recta de vigas de un piso, dada por su
# cota, el eje global a lo largo del cual corre y la coordenada fija del
# otro eje. Los elementos se BUSCAN por geometria (recorrido()), no se
# escriben. Todo vive en entrada/laboratorio.json.
RECORRIDO = lab.bloque('carga_movil')
P_POR_DEFECTO = float(RECORRIDO['P_kN'])
DIVISIONES_POR_DEFECTO = int(RECORRIDO['divisiones'])

# Criterio de "indistinguible" para las verificaciones globales: los
# decimales que escribe el servidor (extraer_resultados redondea
# desplazamientos a 8 y fuerzas a 4). Dos resultados que difieren menos
# que eso son el mismo numero en el JSON que ve el visor.
RESOLUCION_U = 1e-8          # m y rad
RESOLUCION_F = 1e-4          # kN y kN*m

# La deformada se dibuja con la mayor traslacion del recorrido llevada a
# este largo. Es solo grafico y fijo para TODAS las posiciones: si cada
# posicion tuviera su escala, la animacion mostraria "respirar" a la
# estructura sin que cambie nada.
LARGO_DIBUJO_M = float(RECORRIDO['largo_dibujo_m'])

TAG_BASE = 7000


# ============================================================
# SALIDA
# ============================================================
def decir(texto=''):
    print(texto)


FALLOS = []


def check(cond, msg, detalle=''):
    decir('  [%s] %s' % ('OK  ' if cond else 'FALLA', msg))
    if detalle:
        decir('         %s' % detalle)
    if not cond:
        FALLOS.append(msg)
    return bool(cond)


# ============================================================
# GEOMETRIA DEL RECORRIDO
# ============================================================
def recorrido(modelo, z, eje, coord, tol=0.02):
    """
    Las vigas colineales de la cota z sobre la linea eje = coord,
    encadenadas por sus nodos y ordenadas a lo largo del eje. Error si
    la cadena tiene un hueco: una carga movil no salta de viga.
    Devuelve {elementos, sentidos, nodos, largo_m, desde, hasta}.
    """
    k = {'x': 0, 'y': 1}[eje]
    otro = 1 - k
    nodos = {int(n['id']): n for n in modelo['nodos']}
    tramos = []
    for e in modelo['elementos']:
        if not str(e.get('tipo', '')).startswith('viga'):
            continue
        a, b = xyz(nodos[int(e['n1'])]), xyz(nodos[int(e['n2'])])
        if abs(a[2] - z) > tol or abs(b[2] - z) > tol:
            continue
        if abs(a[otro] - coord) > tol or abs(b[otro] - coord) > tol:
            continue
        L = math.dist(a, b)
        if L < 1e-9 or abs(b[k] - a[k]) < 0.999 * L:
            continue
        sentido = 1 if b[k] > a[k] else -1
        inicio, fin = (int(e['n1']), int(e['n2'])) if sentido > 0 else (int(e['n2']), int(e['n1']))
        tramos.append((min(a[k], b[k]), int(e['id']), sentido, inicio, fin, L))
    if not tramos:
        raise SystemExit('no hay vigas en z=%.2f, %s, coordenada %.4f'
                         % (z, eje, coord))
    tramos.sort()
    for t0, t1 in zip(tramos, tramos[1:]):
        if t0[4] != t1[3]:
            raise SystemExit('el recorrido tiene un hueco entre las vigas %d y %d '
                             '(nodos %d y %d)' % (t0[1], t1[1], t0[4], t1[3]))
    cadena = [tramos[0][3]] + [t[4] for t in tramos]
    return {
        'elementos': [t[1] for t in tramos],
        'sentidos': [t[2] for t in tramos],
        'nodos': cadena,
        'largos': [t[5] for t in tramos],
        'largo_m': sum(t[5] for t in tramos),
    }


def que_llega_a(modelo, nid):
    """Los tipos de barra que llegan a un nodo, para describirlo."""
    tipos = sorted({str(e.get('tipo', '')) for e in modelo['elementos']
                    if nid in (int(e['n1']), int(e['n2']))})
    return tipos


def posiciones(modelo, rec, divisiones):
    """
    Las posiciones de la carga: en cada viga, xL = (k + 1/2)/divisiones
    desde el inicio del recorrido. Ninguna cae sobre un nodo: ahi la carga
    la comparten todas las barras que llegan y "el reparto de la viga" no
    es una pregunta con sentido. Lo que pasa al cruzar un nodo lo cubre
    la verificacion de continuidad [f].
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    salida, s0 = [], 0.0
    for eid, sentido, L in zip(rec['elementos'], rec['sentidos'], rec['largos']):
        e = por_id[eid]
        pi, pj = xyz(nodos[int(e['n1'])]), xyz(nodos[int(e['n2'])])
        for k in range(divisiones):
            t = (k + 0.5) / divisiones          # fraccion en el sentido del recorrido
            xL = t if sentido > 0 else 1.0 - t  # fraccion desde n1, la de OpenSees
            salida.append({
                'elemento': eid, 'xL': xL, 'a': xL * L, 'L': L,
                's': s0 + t * L,
                'punto': tuple(pi[c] + xL * (pj[c] - pi[c]) for c in range(3)),
            })
        s0 += L
    return salida


# ============================================================
# LAS CORRIDAS: el modelo del motor, construido UNA vez
# ============================================================
class Corridas:
    """
    opensees.Resolutor (el modelo armado una vez con construir_modelo, lo
    mismo que /analizar, y un patron de carga a la vez) mas lo que guarda
    cada corrida de la carga movil: el resultado redondeado como lo
    devuelve el servidor y la memoria sin redondeo, y cuanto tarda.
    """

    def __init__(self, modelo):
        t0 = time.time()
        self.motor = opensees.Resolutor(modelo, tag_base=TAG_BASE)
        self.t_construir = time.time() - t0
        self.restr = self.motor.restr
        self.t_resolver = 0.0

    @property
    def n_resueltos(self):
        return self.motor.n_resueltos

    def resolver(self, puntuales=(), nodales=()):
        """
        puntuales: [(eid, Px, Py, Pz, xL)] en ejes locales.
        nodales:   [(nid, fx, fy, fz)] globales.
        Devuelve (res redondeado como el servidor, memoria sin redondeo).
        """
        t0 = time.time()
        self.motor.resolver(puntuales=puntuales,
                            nodales=[(nid, (fx, fy, fz, 0.0, 0.0, 0.0))
                                     for nid, fx, fy, fz in nodales])
        res = self.motor.extraer()
        memoria = {
            'u': self.motor.desplazamientos(),
            'R': self.motor.reacciones(),
            'f': self.motor.fuerzas(),
        }
        self.t_resolver += time.time() - t0
        return res, memoria


def cierre_en_L(f, Px, Py, Pz, a, L):
    """
    (peor error/cota, componente) de esfuerzo(L) contra f_j, con
    esfuerzos.cota_de_cierre (el redondeo del servidor) y las magnitudes
    de los terminos, incluidos los de la carga.
    """
    en_L = esfuerzos_con_puntual(f, Px, Py, Pz, a, [L])
    mag = es.magnitudes_de_cierre(f, (0.0, 0.0, 0.0), L)
    b = L - a
    mag = [mag[0] + abs(Px), mag[1] + abs(Py), mag[2] + abs(Pz), mag[3],
           mag[4] + abs(Pz) * b, mag[5] + abs(Py) * b]
    cotas = es.cota_de_cierre(L, 1.0, mag)
    peor = (0.0, 'N', 0.0, 0.0)
    for k, nombre in enumerate(('N', 'Vy', 'Vz', 'T', 'My', 'Mz')):
        err = abs(en_L[nombre][0] - float(f[6 + k]))
        c = err / cotas[k] if cotas[k] > 0 else (0.0 if err == 0 else math.inf)
        if c >= peor[0]:
            peor = (c, nombre, err, cotas[k])
    return peor


# ============================================================
# CONSERVACION CON LA REGLA DE opensees.equilibrio
# ============================================================
def pesos_de_reaccion(modelo, restr):
    """
    {nodo: (cuenta_x, cuenta_y, cuenta_z)} segun opensees.equilibrio,
    sin copiar la regla: se le pasa una reaccion unitaria de a un nodo
    y se lee que sumo. Asi la cota (cuantos valores redondeados entran)
    y la suma en memoria usan la MISMA definicion que el resto del
    programa.
    """
    vacio = {'nombre': 'conteo', 'cargas_nodales': [], 'cargas_distribuidas': []}
    pesos = {}
    for nid in restr:
        fila = {'id': nid, 'fx': 1.0, 'fy': 1.0, 'fz': 1.0, 'mx': 0.0, 'my': 0.0, 'mz': 0.0}
        eq = opensees.equilibrio(modelo, vacio, {'reacciones': [fila]})
        pesos[nid] = tuple(int(round(v)) for v in eq['reaccion_kN'])
    return pesos


def conservacion(modelo, res, memoria, carga_global, pesos):
    """El equilibrio del contrato (claves de opensees.equilibrio) con la
    carga puntual SUMADA a 'aplicada_kN', y el veredicto con su cota."""
    vacio = {'nombre': 'MOVIL', 'cargas_nodales': [], 'cargas_distribuidas': []}
    eq = opensees.equilibrio(modelo, vacio, res)
    aplicada = [eq['aplicada_kN'][i] + carga_global[i] for i in range(3)]
    reaccion = eq['reaccion_kN']
    error = [aplicada[i] + reaccion[i] for i in range(3)]

    n = [sum(p[i] for p in pesos.values()) for i in range(3)]
    en_memoria = [sum(pesos[nid][i] * memoria['R'][nid][i] for nid in pesos) for i in range(3)]
    err_mem = [aplicada[i] + en_memoria[i] for i in range(3)]
    tam = [abs(aplicada[i]) + sum(abs(float(r[k])) for r in res['reacciones'])
           for i, k in enumerate(('fx', 'fy', 'fz'))]
    cota = [n[i] * es.COTA_REDONDEO + es.FACTOR_COMA_FLOTANTE * tam[i] for i in range(3)]
    return {
        'equilibrio': {
            'aplicada_kN': [round(v, 4) for v in aplicada],
            'reaccion_kN': [round(v, 4) for v in reaccion],
            'error_kN': [round(v, 8) for v in error],
            'cargas_sin_convertir': eq['cargas_sin_convertir'],
            'nodos_en_diafragma': eq['nodos_en_diafragma'],
            'confiable': eq['confiable'],
        },
        'error': error, 'cota': cota, 'n': n, 'err_mem': err_mem,
        'reaccion': reaccion,
    }


# ============================================================
# UNA POSICION
# ============================================================
def bloque_posicion(i, pos, P, modelo, mot, pesos, nodos, por_id):
    e = por_id[pos['elemento']]
    base, L = ejes_de(e, nodos)
    (Px, Py, Pz), g = carga_local(base, P)
    res, mem = mot.resolver(puntuales=[(pos['elemento'], Px, Py, Pz, pos['xL'])])

    # --- conservacion ---
    cons = conservacion(modelo, res, mem, g, pesos)

    # --- la viga cargada, con f redondeado como el servidor ---
    f = next(x['f'] for x in res['fuerzas_elementos'] if int(x['id']) == pos['elemento'])
    a = pos['a']
    Vi, Vj = float(f[2]), float(f[8])
    Myi, Myj = float(f[4]), float(f[10])
    suma_V = Vi + Vj + Pz
    cierre = cierre_en_L(f, Px, Py, Pz, a, L)
    M_carga = esfuerzos_con_puntual(f, Px, Py, Pz, a, [a])['My'][0]

    palanca_j = -Pz * a / L
    palanca_i = -Pz - palanca_j
    momentos = (Myi + Myj) / L
    emp = empotramiento(Pz, a, L)
    # [d] Vz_j - palanca = (My_i + My_j)/L: mezcla Vz_j y los dos
    # momentos redondeados (el ultimo dividido por L).
    err_explica = abs((Vj - palanca_j) - momentos)
    cota_explica = es.COTA_REDONDEO * (1.0 + 2.0 / L) + es.FACTOR_COMA_FLOTANTE * (
        abs(Vj) + abs(palanca_j) + (abs(Myi) + abs(Myj)) / L)

    # --- desplazamientos ---
    k = rigidez(modelo, e, nodos)
    u_carga = desplazamiento_en(base, L, k, mem['u'][int(e['n1'])], mem['u'][int(e['n2'])],
                                a, carga=(Py, Pz))
    curva = elastica(xyz(nodos[int(e['n1'])]), xyz(nodos[int(e['n2'])]), base, L, k,
                     mem['u'][int(e['n1'])], mem['u'][int(e['n2'])], Py, Pz, a)
    maximo, nodo_max = 0.0, -1
    uz_min, nodo_uz = 0.0, -1
    for d in res['desplazamientos']:
        norma = math.sqrt(d['ux'] ** 2 + d['uy'] ** 2 + d['uz'] ** 2)
        if norma > maximo:
            maximo, nodo_max = norma, int(d['id'])
        if d['uz'] < uz_min:
            uz_min, nodo_uz = d['uz'], int(d['id'])

    cumple_z = abs(cons['error'][2]) <= cons['cota'][2]
    cumple_h = (abs(cons['error'][0]) <= cons['cota'][0]
                and abs(cons['error'][1]) <= cons['cota'][1])
    cota_V = 2 * es.COTA_REDONDEO + es.FACTOR_COMA_FLOTANTE * (abs(Vi) + abs(Vj) + abs(Pz))
    cumple_V = abs(suma_V) <= cota_V
    cumple_cierre = cierre[0] <= 1.0
    cumple_explica = err_explica <= cota_explica
    cumple = cumple_z and cumple_h and cumple_V and cumple_cierre and cumple_explica

    n_i, n_j = int(e['n1']), int(e['n2'])
    pct_i = 100.0 * Vi / (-Pz) if Pz else 0.0
    explicacion = ('palanca %.1f / %.1f kN; los momentos de extremo (My_i + My_j)/L = %+.2f kN '
                   'corren %.1f kN hacia el nodo %d'
                   % (palanca_i, palanca_j, momentos, abs(momentos),
                      n_i if momentos < 0 else n_j))

    bloque = {
        'indice': i,
        'elemento': pos['elemento'],
        'xL': round(pos['xL'], 6),
        'a_m': round(a, 4),
        'L_m': round(L, 4),
        's_m': round(pos['s'], 4),
        'x': round(pos['punto'][0], 4),
        'y': round(pos['punto'][1], 4),
        'z': round(pos['punto'][2], 4),
        'Px_local_kN': round(Px, 4),
        'Py_local_kN': round(Py, 4),
        'Pz_local_kN': round(Pz, 4),
        'max_desplazamiento_mm': round(maximo * 1000.0, 4),
        'nodo_max_desplazamiento': nodo_max,
        'uz_min_mm': round(uz_min * 1000.0, 4),
        'nodo_uz_min': nodo_uz,
        'u_carga_m': [round(v, 8) for v in u_carga],
        'uz_bajo_carga_mm': round(u_carga[2] * 1000.0, 4),
        'M_bajo_carga_kNm': round(M_carga, 4),
        'elastica': curva,
        'desplazamientos': res['desplazamientos'],
        'reacciones': res['reacciones'],
        'equilibrio': cons['equilibrio'],
        'reparto': {
            'nodo_i': n_i,
            'nodo_j': n_j,
            'llega_a_i': ', '.join(que_llega_a(modelo, n_i)),
            'llega_a_j': ', '.join(que_llega_a(modelo, n_j)),
            'V_i_kN': round(Vi, 4),
            'V_j_kN': round(Vj, 4),
            'porcentaje_i': round(pct_i, 2),
            'porcentaje_j': round(100.0 - pct_i, 2),
            'palanca_i_kN': round(palanca_i, 4),
            'palanca_j_kN': round(palanca_j, 4),
            'empotrado_V_i_kN': round(emp['V_i'], 4),
            'empotrado_V_j_kN': round(emp['V_j'], 4),
            'empotrado_My_i_kNm': round(emp['My_i'], 4),
            'empotrado_My_j_kNm': round(emp['My_j'], 4),
            'My_i_kNm': round(Myi, 4),
            'My_j_kNm': round(Myj, 4),
            'momentos_sobre_L_kN': round(momentos, 4),
            'f': [round(float(v), 4) for v in f],
            'explicacion': explicacion,
        },
        'conservacion': {
            'P_kN': round(P, 4),
            'suma_Rz_kN': round(cons['reaccion'][2], 4),
            'error_kN': round(cons['error'][2], 8),
            'cota_kN': round(cons['cota'][2], 8),
            'apoyos_z': cons['n'][2],
            'suma_Rx_kN': round(cons['reaccion'][0], 4),
            'suma_Ry_kN': round(cons['reaccion'][1], 4),
            'cota_horizontal_kN': round(max(cons['cota'][0], cons['cota'][1]), 8),
            'apoyos_xy': max(cons['n'][0], cons['n'][1]),
            'error_en_memoria_kN': float('%.3e' % cons['err_mem'][2]),
            'suma_V_mas_Pz_kN': round(suma_V, 8),
            'cierre_cociente': round(cierre[0], 6),
            'cierre_componente': cierre[1],
            'cumple': bool(cumple),
        },
    }
    detalle = {
        'mem': mem, 'res': res, 'Pz': Pz, 'Py': Py, 'Px': Px, 'base': base, 'L': L,
        'rigidez': k, 'cumple_z': cumple_z, 'cumple_h': cumple_h,
        'cumple_V': cumple_V, 'cumple_cierre': cumple_cierre,
        'cumple_explica': cumple_explica, 'err_explica': err_explica,
        'cota_explica': cota_explica, 'cons': cons, 'cierre': cierre,
        'cota_V': cota_V,
    }
    return bloque, detalle


# ============================================================
# VERIFICACIONES GLOBALES
# ============================================================
def _max_dif_u(m1, m2, nodos_ids, gdl=range(6)):
    peor, donde = 0.0, None
    for n in nodos_ids:
        for i in gdl:
            d = abs(m1['u'][n][i] - m2['u'][n][i])
            if d > peor:
                peor, donde = d, (n, i)
    return peor, donde


def _max_dif_R(m1, m2):
    peor = 0.0
    for n in m1['R']:
        for i in range(6):
            peor = max(peor, abs(m1['R'][n][i] - m2['R'][n][i]))
    return peor


def _en(bloques, detalles, eid, xL):
    for b, d in zip(bloques, detalles):
        if b['elemento'] == eid and abs(b['xL'] - xL) < 1e-9:
            return b, d
    return None, None


def global_viga_partida(modelo, P, eid, fracciones, globales):
    """
    [e] La viga eid partida en 10 tramos (edificio.subdividir): hay un
    nodo en cada decimo, y la carga NODAL en el que corresponde tiene
    que dar lo mismo que beamPoint en el modelo sin partir. Resuelve
    todo sobre modelos propios, asi que va despues de las posiciones.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    e = por_id[eid]
    base, L = ejes_de(e, nodos)
    (Px, Py, Pz), g = carga_local(base, P)
    k = rigidez(modelo, e, nodos)

    veces = 10
    partido = _ed.subdividir(modelo, [eid], veces)
    ids_orig = [int(n['id']) for n in modelo['nodos']]
    max_nodo = max(ids_orig)

    for xL in fracciones:
        paso = int(round(xL * veces))
        if abs(paso / veces - xL) > 1e-12:
            raise SystemExit('xL = %g no cae en un nodo de la viga partida en %d' % (xL, veces))
        a = xL * L

        m_base = Corridas(modelo)
        _res_b, mem_b = m_base.resolver(puntuales=[(eid, Px, Py, Pz, xL)])
        f_b = mem_b['f'][eid]
        M_b = esfuerzos_con_puntual(f_b, Px, Py, Pz, a, [a])['My'][0]
        u_b = desplazamiento_en(base, L, k, mem_b['u'][int(e['n1'])], mem_b['u'][int(e['n2'])],
                                a, carga=(Py, Pz))

        m_part = Corridas(partido)
        nodo_carga = max_nodo + paso
        # El nodo nuevo de la fraccion 'paso': subdividir los numera en
        # orden desde n1. Se confirma por coordenadas, no se supone.
        pn = next(n for n in partido['nodos'] if int(n['id']) == nodo_carga)
        esperado = [float(nodos[int(e['n1'])][c]) + xL * (float(nodos[int(e['n2'])][c])
                    - float(nodos[int(e['n1'])][c])) for c in 'xyz']
        if max(abs(float(pn[c]) - esperado[i]) for i, c in enumerate('xyz')) > 1e-9:
            raise SystemExit('el nodo %d de la viga partida no esta en xL = %g' % (nodo_carga, xL))
        _res_p, mem_p = m_part.resolver(nodales=[(nodo_carga, g[0], g[1], g[2])])

        du, donde = _max_dif_u(mem_b, mem_p, ids_orig)
        dR = _max_dif_R(mem_b, mem_p)
        # Momento bajo la carga en la partida: el tramo que TERMINA en el
        # nodo cargado, esfuerzo interno en j = +f_j.
        tramo = next(x for x in partido['elementos'] if int(x['n2']) == nodo_carga)
        M_p = float(mem_p['f'][int(tramo['id'])][10])
        tramo_i = next(x for x in partido['elementos']
                       if int(x['id']) == eid)            # el que conserva n1
        V_p = float(mem_p['f'][int(tramo_i['id'])][2])
        V_b = float(f_b[2])
        du_carga = max(abs(u_b[c] - mem_p['u'][nodo_carga][c]) for c in range(3))

        # La elastica que dibuja el visor: en cada decimo de la viga sin
        # partir (Hermite + biempotrada con la carga en a) contra el nodo de
        # la partida que esta ahi. Cubre los dos lados de la carga.
        du_curva, peor_t = 0.0, None
        ui_b, uj_b = mem_b['u'][int(e['n1'])], mem_b['u'][int(e['n2'])]
        for t in range(1, veces):
            nid = max_nodo + t
            pt = next(n for n in partido['nodos'] if int(n['id']) == nid)
            en_t = [float(nodos[int(e['n1'])][c]) + t / veces * (float(nodos[int(e['n2'])][c])
                    - float(nodos[int(e['n1'])][c])) for c in 'xyz']
            if max(abs(float(pt[c]) - en_t[i]) for i, c in enumerate('xyz')) > 1e-9:
                raise SystemExit('el nodo %d de la viga partida no esta en xL = %g' % (nid, t / veces))
            u_t = desplazamiento_en(base, L, k, ui_b, uj_b, t / veces * L, carga=(Py, Pz, a))
            d = max(abs(u_t[c] - mem_p['u'][nid][c]) for c in range(3))
            if d >= du_curva:
                du_curva, peor_t = d, t / veces

        ok = (du <= RESOLUCION_U and dR <= RESOLUCION_F and abs(M_b - M_p) <= RESOLUCION_F
              and abs(V_b - V_p) <= RESOLUCION_F and du_carga <= RESOLUCION_U
              and du_curva <= RESOLUCION_U)
        check(ok, '[e] beamPoint = viga %d partida en %d con carga nodal en el nodo %d (xL = %.2f)'
              % (eid, veces, nodo_carga, xL),
              'max |du| %.1e m en %s de %d nodos; max |dR| %.1e kN; M bajo la carga %.4f / %.4f '
              'kN*m (dif %.1e); V_i %.4f / %.4f; flecha bajo la carga %.6f / %.6f mm (dif %.1e m); '
              'elastica en los %d nodos interiores de la partida: max |du| %.1e m (xL = %.1f)'
              % (du, donde, len(ids_orig), dR, M_b, M_p, abs(M_b - M_p), V_b, V_p,
                 u_b[2] * 1000, mem_p['u'][nodo_carga][2] * 1000, du_carga,
                 veces - 1, du_curva, peor_t))
        globales.append({
            'nombre': 'beamPoint contra viga partida',
            'detalle': 'viga %d, xL = %.2f, partida en %d, carga nodal en el nodo %d'
                       % (eid, xL, veces, nodo_carga),
            'max_dif_desplazamiento_m': du, 'max_dif_reaccion_kN': dR,
            'M_beamPoint_kNm': round(M_b, 6), 'M_partida_kNm': round(M_p, 6),
            'uz_bajo_carga_calculada_mm': round(u_b[2] * 1000, 6),
            'uz_nodo_partida_mm': round(mem_p['u'][nodo_carga][2] * 1000, 6),
            'dif_bajo_carga_m': du_carga,
            'max_dif_elastica_m': du_curva,
            'criterio': 'desplazamientos <= %g m, fuerzas <= %g kN' % (RESOLUCION_U, RESOLUCION_F),
            'cumple': bool(ok)})


def global_continuidad(mot, modelo, P, rec, globales):
    """[f] Cruzar un nodo: fin de una viga, inicio de la siguiente y la
    carga nodal en el nodo comun son la misma carga."""
    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    # El primer nodo interior del recorrido que no tiene columna: donde
    # la pregunta importa (el que cuelga).
    candidatos = [i for i in range(1, len(rec['nodos']) - 1)
                  if not any(t in ('columna', 'muro') for t in que_llega_a(modelo, rec['nodos'][i]))]
    i = candidatos[0] if candidatos else 1
    nid = rec['nodos'][i]
    e1, e2 = por_id[rec['elementos'][i - 1]], por_id[rec['elementos'][i]]
    xL1 = 1.0 if int(e1['n2']) == nid else 0.0
    xL2 = 0.0 if int(e2['n1']) == nid else 1.0
    b1, _ = ejes_de(e1, nodos)
    b2, _ = ejes_de(e2, nodos)
    (px1, py1, pz1), g = carga_local(b1, P)
    (px2, py2, pz2), _ = carga_local(b2, P)
    _r, m1 = mot.resolver(puntuales=[(int(e1['id']), px1, py1, pz1, xL1)])
    _r, m2 = mot.resolver(puntuales=[(int(e2['id']), px2, py2, pz2, xL2)])
    _r, m3 = mot.resolver(nodales=[(nid, g[0], g[1], g[2])])
    ids = list(m1['u'])
    d12, _ = _max_dif_u(m1, m2, ids)
    d13, _ = _max_dif_u(m1, m3, ids)
    dR = max(_max_dif_R(m1, m2), _max_dif_R(m1, m3))
    ok = max(d12, d13) <= RESOLUCION_U and dR <= RESOLUCION_F
    check(ok, '[f] continuidad en el nodo %d: viga %d xL=%g = viga %d xL=%g = carga nodal'
          % (nid, int(e1['id']), xL1, int(e2['id']), xL2),
          'uz(%d) = %.4f / %.4f / %.4f mm; max |du| %.1e y %.1e m; max |dR| %.1e kN'
          % (nid, m1['u'][nid][2] * 1000, m2['u'][nid][2] * 1000, m3['u'][nid][2] * 1000,
             d12, d13, dR))
    globales.append({
        'nombre': 'continuidad al cruzar un nodo',
        'detalle': 'nodo %d (%s): viga %d en xL=%g, viga %d en xL=%g y carga nodal'
                   % (nid, ', '.join(que_llega_a(modelo, nid)), int(e1['id']), xL1,
                      int(e2['id']), xL2),
        'uz_nodo_mm': round(m3['u'][nid][2] * 1000, 6),
        'max_dif_desplazamiento_m': max(d12, d13), 'max_dif_reaccion_kN': dR,
        'criterio': 'desplazamientos <= %g m, fuerzas <= %g kN' % (RESOLUCION_U, RESOLUCION_F),
        'cumple': bool(ok)})


def global_betti(bloques, detalles, modelo, globales, A, B):
    """
    [g] Betti con la misma P en dos puntos interiores A y B:
    u(A | P en B) . e_P = u(B | P en A) . e_P. El desplazamiento en un
    punto interior sale de desplazamiento_en (Hermite): la prueba cubre
    la simetria del solver y esa interpolacion.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    bA, dA = _en(bloques, detalles, *A)
    bB, dB = _en(bloques, detalles, *B)
    if bA is None or bB is None:
        check(False, '[g] Betti: no estan las posiciones %s y %s' % (A, B))
        return
    eA, eB = por_id[A[0]], por_id[B[0]]
    # desplazamiento en A cuando la carga esta en B (A no esta cargado)
    uA_B = desplazamiento_en(dA['base'], dA['L'], dA['rigidez'],
                             dB['mem']['u'][int(eA['n1'])], dB['mem']['u'][int(eA['n2'])],
                             A[1] * dA['L'])
    uB_A = desplazamiento_en(dB['base'], dB['L'], dB['rigidez'],
                             dA['mem']['u'][int(eB['n1'])], dA['mem']['u'][int(eB['n2'])],
                             B[1] * dB['L'])
    # P es la misma y vertical: el trabajo reciproco se reduce a uz.
    dif = abs(uA_B[2] - uB_A[2])
    rel = dif / max(abs(uA_B[2]), 1e-30)
    ok = dif <= RESOLUCION_U
    check(ok, '[g] Betti: uz en %d xL=%.2f con P en %d xL=%.2f = al reves'
          % (A[0], A[1], B[0], B[1]),
          '%.12e / %.12e m, dif %.1e m (%.1e relativo)' % (uA_B[2], uB_A[2], dif, rel))
    globales.append({
        'nombre': 'reciprocidad de Betti',
        'detalle': 'puntos viga %d xL=%.2f y viga %d xL=%.2f' % (A[0], A[1], B[0], B[1]),
        'uz_A_por_B_m': uA_B[2], 'uz_B_por_A_m': uB_A[2],
        'dif_m': dif, 'dif_relativa': rel,
        'criterio': 'dif <= %g m' % RESOLUCION_U, 'cumple': bool(ok)})


def global_superposicion(mot, bloques, detalles, globales, A, B):
    """[h] Las dos cargas en una sola corrida = la suma de las dos corridas."""
    bA, dA = _en(bloques, detalles, *A)
    bB, dB = _en(bloques, detalles, *B)
    _r, mAB = mot.resolver(puntuales=[
        (A[0], dA['Px'], dA['Py'], dA['Pz'], A[1]),
        (B[0], dB['Px'], dB['Py'], dB['Pz'], B[1])])
    peor_u = max(abs(mAB['u'][n][i] - dA['mem']['u'][n][i] - dB['mem']['u'][n][i])
                 for n in mAB['u'] for i in range(6))
    peor_R = max(abs(mAB['R'][n][i] - dA['mem']['R'][n][i] - dB['mem']['R'][n][i])
                 for n in mAB['R'] for i in range(6))
    peor_f = max(abs(mAB['f'][e][i] - dA['mem']['f'][e][i] - dB['mem']['f'][e][i])
                 for e in mAB['f'] for i in range(12))
    ok = peor_u <= RESOLUCION_U and peor_R <= RESOLUCION_F and peor_f <= RESOLUCION_F
    check(ok, '[h] superposicion: %d xL=%.2f + %d xL=%.2f en una corrida = suma de las dos'
          % (A[0], A[1], B[0], B[1]),
          'max |du| %.1e m, max |dR| %.1e kN, max |df| %.1e kN (todos los nodos, apoyos y barras)'
          % (peor_u, peor_R, peor_f))
    globales.append({
        'nombre': 'superposicion de dos posiciones',
        'detalle': 'viga %d xL=%.2f y viga %d xL=%.2f' % (A[0], A[1], B[0], B[1]),
        'max_dif_desplazamiento_m': peor_u, 'max_dif_reaccion_kN': peor_R,
        'max_dif_fuerza_kN': peor_f,
        'criterio': 'desplazamientos <= %g m, fuerzas <= %g kN' % (RESOLUCION_U, RESOLUCION_F),
        'cumple': bool(ok)})


def global_por_que_no(mot, modelo, P, bloques, detalles, globales, eid):
    """
    Dos atajos que NO se usan, medidos (informativo, no bloquea):
      - funciones de forma lineales: P(1-xi) y P xi como cargas nodales;
      - interpolar entre dos posiciones vecinas en vez de resolver.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    e = por_id[eid]
    base, L = ejes_de(e, nodos)
    (Px, Py, Pz), g = carga_local(base, P)
    b5, d5 = _en(bloques, detalles, eid, 0.5)

    # --- lineal ---
    xi = 0.5
    _r, mlin = mot.resolver(nodales=[(int(e['n1']), 0, 0, g[2] * (1 - xi)),
                                     (int(e['n2']), 0, 0, g[2] * xi)])
    f = mlin['f'][eid]
    M_lin = esfuerzos_con_puntual(f, 0, 0, 0, xi * L, [xi * L])['My'][0]
    M_ex = esfuerzos_con_puntual(d5['mem']['f'][eid], Px, Py, Pz, xi * L, [xi * L])['My'][0]
    n_i, n_j = int(e['n1']), int(e['n2'])
    decir('  [--] funciones de forma lineales en la viga %d a mitad: M bajo la carga %.2f kN*m '
          'contra %.2f exacto' % (eid, M_lin, M_ex))
    decir('       uz(%d) %.4f contra %.4f mm; uz(%d) %.4f contra %.4f mm'
          % (n_i, mlin['u'][n_i][2] * 1000, d5['mem']['u'][n_i][2] * 1000,
             n_j, mlin['u'][n_j][2] * 1000, d5['mem']['u'][n_j][2] * 1000))

    # --- interpolar ---
    # Lo que se veria si el visor mezclara dos posiciones vecinas: el
    # promedio de sus DIAGRAMAS y de sus DEFORMADAS en el punto intermedio
    # (no solo el numero "M bajo la carga", que es suave y engana: el
    # diagrama tiene el quiebre donde esta la carga, y al promediar dos
    # quiebres en otros puntos se aplana el pico).
    bajo = [(b, d) for b, d in zip(bloques, detalles) if b['elemento'] == eid]
    bajo.sort(key=lambda bd: bd[0]['xL'])
    (b1, d1), (b2, d2) = bajo[1], bajo[2]
    xm = (b1['xL'] + b2['xL']) / 2.0
    _r, mm = mot.resolver(puntuales=[(eid, Px, Py, Pz, xm)])
    M_real = esfuerzos_con_puntual(mm['f'][eid], Px, Py, Pz, xm * L, [xm * L])['My'][0]
    M_int = (b1['M_bajo_carga_kNm'] + b2['M_bajo_carga_kNm']) / 2.0
    err_pct = 100.0 * abs(M_int - M_real) / max(abs(M_real), 1e-12)
    M_diag = [esfuerzos_con_puntual(d['mem']['f'][eid], Px, Py, Pz, b['xL'] * L, [xm * L])['My'][0]
              for b, d in ((b1, d1), (b2, d2))]
    M_diag_int = (M_diag[0] + M_diag[1]) / 2.0
    err_diag = 100.0 * abs(M_diag_int - M_real) / max(abs(M_real), 1e-12)
    k = rigidez(modelo, e, nodos)
    uz_def = [desplazamiento_en(base, L, k, d['mem']['u'][n_i], d['mem']['u'][n_j], xm * L,
                                carga=(Py, Pz, b['xL'] * L))[2] for b, d in ((b1, d1), (b2, d2))]
    uz_int = (uz_def[0] + uz_def[1]) / 2.0
    uz_real = desplazamiento_en(base, L, k, mm['u'][n_i], mm['u'][n_j], xm * L, carga=(Py, Pz))[2]
    err_uz = 100.0 * abs(uz_int - uz_real) / max(abs(uz_real), 1e-30)
    decir('  [--] interpolar entre xL=%.2f y %.2f de la viga %d, carga en xL=%.2f:'
          % (b1['xL'], b2['xL'], eid, xm))
    decir('       M bajo la carga (el numero) %.2f interpolado contra %.2f resuelto kN*m (%.1f %%)'
          % (M_int, M_real, err_pct))
    decir('       diagrama My en esa seccion %.2f promediado contra %.2f resuelto kN*m (%.1f %%)'
          % (M_diag_int, M_real, err_diag))
    decir('       deformada uz en ese punto %.4f promediada contra %.4f resuelta mm (%.1f %%)'
          % (uz_int * 1000, uz_real * 1000, err_uz))
    globales.append({
        'nombre': 'por que no funciones de forma lineales',
        'detalle': 'viga %d a mitad de vano, P(1-xi) y P xi como cargas nodales' % eid,
        'M_lineal_kNm': round(M_lin, 4), 'M_exacto_kNm': round(M_ex, 4),
        'uz_i_lineal_mm': round(mlin['u'][n_i][2] * 1000, 6),
        'uz_i_exacto_mm': round(d5['mem']['u'][n_i][2] * 1000, 6),
        'uz_j_lineal_mm': round(mlin['u'][n_j][2] * 1000, 6),
        'uz_j_exacto_mm': round(d5['mem']['u'][n_j][2] * 1000, 6),
        'informativo': True})
    globales.append({
        'nombre': 'por que no interpolar entre posiciones',
        'detalle': 'viga %d, xL=%.2f entre %.2f y %.2f' % (eid, xm, b1['xL'], b2['xL']),
        'M_interpolado_kNm': round(M_int, 4), 'M_resuelto_kNm': round(M_real, 4),
        'error_pct': round(err_pct, 2),
        'M_diagrama_promediado_kNm': round(M_diag_int, 4), 'error_diagrama_pct': round(err_diag, 2),
        'uz_promediada_mm': round(uz_int * 1000, 6), 'uz_resuelta_mm': round(uz_real * 1000, 6),
        'error_uz_pct': round(err_uz, 2), 'informativo': True})


def global_empotramiento(P, globales):
    """
    [i] La formula de empotramiento perfecto contra OpenSees: una viga
    aislada biempotrada de 5 m con la carga en xL = 0.3, armada y
    resuelta por el mismo motor (opensees.Resolutor). Borra el modelo del
    edificio (construir_modelo empieza con ops.wipe), por eso va al final.
    """
    L, xL = 5.0, 0.3
    a = xL * L
    # El ux del nodo 2 queda LIBRE: con los 12 GDL fijos el sistema tiene
    # 0 ecuaciones y LAPACK aborta el proceso (DGBSV, parametro 9 ilegal).
    # No cambia nada de lo que se mide: la carga no tiene componente axial
    # y en el elemento elastico lineal el axial no se acopla con la flexion.
    # Las inercias van con la convencion del contrato (Iz la de gravedad):
    # el motor las cruza en una barra horizontal, y ops.element recibe
    # Iy = 0.0256 e Iz = 0.0144.
    viga = {
        'nodos': [{'id': 1, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'restricciones': [1, 1, 1, 1, 1, 1]},
                  {'id': 2, 'x': L, 'y': 0.0, 'z': 0.0, 'restricciones': [0, 1, 1, 1, 1, 1]}],
        'secciones': [{'nombre': 'biempotrada', 'A': 0.48, 'E': 2.5e7, 'G': 1.0e7, 'J': 0.03,
                       'Iy': 0.0144, 'Iz': 0.0256}],
        'elementos': [{'id': 1, 'n1': 1, 'n2': 2, 'seccion': 'biempotrada', 'tipo': 'viga'}],
    }
    aislada = opensees.Resolutor(viga)
    aislada.resolver(puntuales=[(1, 0.0, 0.0, -P, xL)])
    f = aislada.fuerzas([1])[1]
    emp = empotramiento(-P, a, L)
    difs = [abs(f[2] - emp['V_i']), abs(f[8] - emp['V_j']),
            abs(f[4] - emp['My_i']), abs(f[10] - emp['My_j'])]
    ok = max(difs) <= RESOLUCION_F
    check(ok, '[i] empotramiento perfecto: formula = OpenSees (biempotrada L=5, xL=0.3)',
          'V_i %.4f / %.4f, V_j %.4f / %.4f, My_i %.4f / %.4f, My_j %.4f / %.4f; peor %.1e'
          % (f[2], emp['V_i'], f[8], emp['V_j'], f[4], emp['My_i'], f[10], emp['My_j'],
             max(difs)))
    globales.append({
        'nombre': 'fuerzas de empotramiento perfecto',
        'detalle': 'viga biempotrada aislada L = 5 m, P = %g kN en xL = 0.3' % P,
        'opensees': [round(f[2], 6), round(f[8], 6), round(f[4], 6), round(f[10], 6)],
        'formula': [round(emp['V_i'], 6), round(emp['V_j'], 6),
                    round(emp['My_i'], 6), round(emp['My_j'], 6)],
        'max_dif': max(difs), 'criterio': '<= %g' % RESOLUCION_F, 'cumple': bool(ok)})


# ============================================================
# EL MODELO QUE DIBUJA UNITY ES ESTE
# ============================================================
def comparar_con_el_visor(modelo):
    """Los ids y coordenadas de salidas/modelo.json (lo que dibuja el
    visor) tienen que ser los del modelo que se resolvio: si no, la
    deformada se pegaria a otros nodos sin ningun error. Si no calza,
    es salidas/modelo.json el que esta viejo: se avisa, y se arregla
    exportando el modelo."""
    ruta = rutas.salida('modelo')
    try:
        with io.open(ruta, encoding='utf-8') as f:
            vista = json.load(f)
    except (OSError, ValueError) as ex:
        decir('  [AVISO] no pude leer %s (%s): exportarlo con  python sap.py exportar modelo'
              % (rutas.relativa(ruta), ex))
        return
    a = {int(n['id']): xyz(n) for n in modelo['nodos']}
    b = {int(n['id']): xyz(n) for n in vista.get('nodos', [])}
    distintos = [n for n in a if n not in b or max(abs(a[n][c] - b[n][c]) for c in range(3)) > 1e-6]
    ea = {int(e['id']): (int(e['n1']), int(e['n2'])) for e in modelo['elementos']}
    eb = {int(e['id']): (int(e['n1']), int(e['n2'])) for e in vista.get('elementos', [])}
    if set(a) == set(b) and not distintos and ea == eb:
        decir('  [OK  ] el modelo resuelto es el que dibuja Unity (%s): %d nodos y %d elementos '
              'iguales' % (rutas.relativa(ruta), len(a), len(ea)))
    else:
        decir('  [AVISO] %s no es el modelo resuelto (%d nodos y %d elementos contra %d y %d%s): '
              'exportarlo con  python sap.py exportar modelo'
              % (rutas.relativa(ruta), len(b), len(eb), len(a), len(ea),
                 '' if not distintos else '; nodos distintos: %s' % distintos[:10]))


# ============================================================
# ARMAR
# ============================================================
def construir(P=P_POR_DEFECTO, divisiones=DIVISIONES_POR_DEFECTO):
    """
    Resuelve el recorrido y arma salidas/carga_movil.json en memoria,
    imprimiendo la tabla y las verificaciones. No escribe nada. Devuelve
    (anexo, contexto); contexto['fallos'] lista lo que no cerro.
    """
    del FALLOS[:]
    t0 = time.time()
    modelo = _ed.estructura()
    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    decl = RECORRIDO
    rec = recorrido(modelo, decl['z'], decl['eje'], decl['coord'])
    lista = posiciones(modelo, rec, divisiones)

    decir('=' * 76)
    decir('  CARGA MOVIL   %s   P = %g kN hacia abajo' % (_ed.NOMBRE.upper(), P))
    decir('=' * 76)
    decir('  recorrido: cota %.2f, %s, %s = %.4f; %d vigas, %.3f m'
          % (decl['z'], 'a lo largo de ' + decl['eje'], 'y' if decl['eje'] == 'x' else 'x',
             decl['coord'], len(rec['elementos']), rec['largo_m']))
    for eid, L in zip(rec['elementos'], rec['largos']):
        e = por_id[eid]
        decir('    viga %d  %s  nodos %d -> %d  L = %.3f m' % (eid, e['seccion'], int(e['n1']),
                                                            int(e['n2']), L))
    for nid in rec['nodos']:
        decir('    nodo %d: %s' % (nid, ', '.join(que_llega_a(modelo, nid))))
    decir('  posiciones: %d (%d por viga, xL = (k + 1/2)/%d)'
          % (len(lista), divisiones, divisiones))
    decir()

    comparar_con_el_visor(modelo)

    mot = Corridas(modelo)
    pesos = pesos_de_reaccion(modelo, mot.restr)
    n_apoyos = [sum(p[i] for p in pesos.values()) for i in range(3)]
    decir('  apoyos que cuentan (regla de opensees.equilibrio): %d en Fx, %d en Fy, %d en Fz; '
          'de %d nodos con reaccion' % (n_apoyos[0], n_apoyos[1], n_apoyos[2], len(mot.restr)))
    decir()

    bloques, detalles = [], []
    for i, pos in enumerate(lista):
        b, d = bloque_posicion(i, pos, P, modelo, mot, pesos, nodos, por_id)
        bloques.append(b)
        detalles.append(d)

    # --- tabla ---
    decir('  %3s %5s %5s %7s | %8s %8s %6s | %8s %8s | %10s %8s %6s | %9s %8s %8s'
          % ('i', 'viga', 'xL', 's m', 'V_i kN', 'V_j kN', '% i', 'palanca', 'emp.',
             'SumRz kN', 'err kN', 'cierre', 'uz min mm', 'uz P mm', 'M P kNm'))
    for b, d in zip(bloques, detalles):
        r, c = b['reparto'], b['conservacion']
        decir('  %3d %5d %5.2f %7.3f | %8.3f %8.3f %6.1f | %8.3f %8.3f | %10.4f %8.1e %6.3f | '
              '%9.4f %8.4f %8.2f %s'
              % (b['indice'], b['elemento'], b['xL'], b['s_m'], r['V_i_kN'], r['V_j_kN'],
                 r['porcentaje_i'], r['palanca_i_kN'], r['empotrado_V_i_kN'],
                 c['suma_Rz_kN'], abs(c['error_kN']), c['cierre_cociente'],
                 b['uz_min_mm'], b['uz_bajo_carga_mm'], b['M_bajo_carga_kNm'],
                 '' if c['cumple'] else '<-- NO CUMPLE'))
    decir()

    peor_z = max(bloques, key=lambda b: abs(b['conservacion']['error_kN']) /
                 b['conservacion']['cota_kN'])
    peor_h = max(detalles, key=lambda d: max(abs(d['cons']['error'][0]), abs(d['cons']['error'][1])))
    peor_mem = max(abs(d['cons']['err_mem'][2]) for d in detalles)
    peor_cierre = max(detalles, key=lambda d: d['cierre'][0])
    peor_V = max(abs(b['conservacion']['suma_V_mas_Pz_kN']) for b in bloques)
    peor_expl = max(d['err_explica'] / d['cota_explica'] for d in detalles)

    decir('  VERIFICACION POR POSICION (valores redondeados como el servidor)')
    check(all(d['cumple_z'] for d in detalles),
          '[a] conservacion: SumRz = P en las %d posiciones' % len(bloques),
          'peor |error| %.1e kN en la posicion %d, cota %.1e kN (%d apoyos x 5e-5 + coma '
          'flotante); en memoria, sin redondeo, peor %.1e kN'
          % (abs(peor_z['conservacion']['error_kN']), peor_z['indice'],
             peor_z['conservacion']['cota_kN'], n_apoyos[2], peor_mem))
    check(all(d['cumple_h'] for d in detalles),
          '[b] horizontales: SumRx = SumRy = 0',
          'peor |SumRx| %.1e, |SumRy| %.1e kN; cota %.1e kN (%d apoyos)'
          % (abs(peor_h['cons']['error'][0]), abs(peor_h['cons']['error'][1]),
             max(peor_h['cons']['cota'][0], peor_h['cons']['cota'][1]),
             max(n_apoyos[0], n_apoyos[1])))
    check(all(d['cumple_V'] for d in detalles) and all(d['cumple_cierre'] for d in detalles),
          '[c] viga cargada: Vz_i + Vz_j + Pz = 0 y cierre en x = L con el salto H(x-a)',
          'peor |Vz_i+Vz_j+Pz| %.1e kN (cota %.1e); peor cierre %.3f de la cota en %s '
          '(error %.1e, cota %.1e)'
          % (peor_V, detalles[0]['cota_V'], peor_cierre['cierre'][0], peor_cierre['cierre'][1],
             peor_cierre['cierre'][2], peor_cierre['cierre'][3]))
    check(all(d['cumple_explica'] for d in detalles),
          '[d] el reparto se explica: V_j - palanca = (My_i + My_j)/L',
          'peor error / cota %.3f' % peor_expl)
    decir()

    decir('  VERIFICACIONES GLOBALES (en memoria)')
    globales = []
    eid_demo = rec['elementos'][len(rec['elementos']) // 2 - 1]      # la del medio
    global_continuidad(mot, modelo, P, rec, globales)
    xs_viga = sorted(b['xL'] for b in bloques if b['elemento'] == eid_demo)
    A = (eid_demo, xs_viga[len(xs_viga) // 2])
    otra = rec['elementos'][min(len(rec['elementos']) - 1, rec['elementos'].index(eid_demo) + 2)]
    xs_otra = sorted(b['xL'] for b in bloques if b['elemento'] == otra)
    B = (otra, xs_otra[1] if len(xs_otra) > 1 else xs_otra[0])
    global_betti(bloques, detalles, modelo, globales, A, B)
    global_superposicion(mot, bloques, detalles, globales, A, B)
    if divisiones >= 3 and any(abs(b['xL'] - 0.5) < 1e-9 for b in bloques
                               if b['elemento'] == eid_demo):
        global_por_que_no(mot, modelo, P, bloques, detalles, globales, eid_demo)
    t_posiciones = mot.t_resolver
    n_resueltos = mot.n_resueltos
    fracciones = [x for x in (0.3, 0.5) if any(abs(b['xL'] - x) < 1e-9 for b in bloques
                                               if b['elemento'] == eid_demo)]
    global_viga_partida(modelo, P, eid_demo, fracciones, globales)
    global_empotramiento(P, globales)

    # --- escala grafica fija ---
    mayor = max(max(b['max_desplazamiento_mm'] for b in bloques),
                max(math.sqrt(sum(v * v for v in b['u_carga_m'])) * 1000 for b in bloques))
    escala = LARGO_DIBUJO_M * 1000.0 / mayor if mayor > 0 else 1.0
    escala = float('%.2g' % escala)
    peor_uz = min(bloques, key=lambda b: b['uz_bajo_carga_mm'])

    verificaciones = []
    for g in globales:
        if g.get('informativo'):
            continue
        verificaciones.append({'nombre': g['nombre'], 'detalle': g['detalle'],
                               'criterio': g['criterio'], 'cumple': g['cumple']})
    verificaciones[0:0] = [
        {'nombre': 'conservacion SumRz = P', 'detalle': 'peor |error| %.1e kN en %d posiciones; '
         'en memoria %.1e kN' % (abs(peor_z['conservacion']['error_kN']), len(bloques), peor_mem),
         'criterio': '%d apoyos x 5e-5 kN + coma flotante' % n_apoyos[2],
         'cumple': all(d['cumple_z'] for d in detalles)},
        {'nombre': 'horizontales SumRx = SumRy = 0',
         'detalle': 'peor %.1e kN' % max(abs(peor_h['cons']['error'][0]), abs(peor_h['cons']['error'][1])),
         'criterio': '%d apoyos x 5e-5 kN' % max(n_apoyos[0], n_apoyos[1]),
         'cumple': all(d['cumple_h'] for d in detalles)},
        {'nombre': 'viga cargada: Vz_i + Vz_j + Pz = 0 y cierre en x = L',
         'detalle': 'peor cierre %.3f de la cota' % peor_cierre['cierre'][0],
         'criterio': 'cota_de_cierre de calculo/esfuerzos.py',
         'cumple': all(d['cumple_V'] and d['cumple_cierre'] for d in detalles)},
    ]

    anexo = {
        'info': {
            'edificio': _ed.NOMBRE,
            'descripcion': ('Carga puntual vertical que recorre un eje de vigas continuas, '
                            'resuelta en OpenSees posicion por posicion (eleLoad -beamPoint). '
                            'El visor elige una posicion y la dibuja; no interpola.'),
            'unidades': 'm, kN; momentos kN*m; desplazamientos m y rad; *_mm en mm',
            'generado_por': GENERADO_POR,
            'comando': 'python sap.py exportar carga_movil --P %g --divisiones %d'
                       % (P, divisiones),
            'convencion': [
                'P positiva hacia abajo; carga global (0, 0, -P)',
                'Px, Py, Pz locales = producto punto con localX, localY, localZ',
                'f = eleResponse(localForce) de la viga cargada: fuerzas de los nodos SOBRE la barra',
                'V_i, V_j = Vz de f en i y j: lo que la viga le entrega a cada nodo',
                'palanca: P b/L y P a/L (viga simplemente apoyada)',
                'empotrado: fuerzas de empotramiento perfecto (las nodales equivalentes)',
                'V_j = palanca_j + (My_i + My_j)/L',
                'M_bajo_carga = My(a) = -(My_i + a Vz_i); My < 0 tracciona abajo',
                'equilibrio: opensees.equilibrio con la carga puntual sumada a aplicada_kN',
                'u_carga_m: traslacion global del punto cargado (Hermite + flecha biempotrada)',
            ],
            'n_posiciones': len(bloques),
            'escala_deformada': escala,
            '_escala_por_que': ('solo grafica: %.4f mm, el mayor desplazamiento del recorrido, '
                                'se dibuja como %.1f m; la misma para todas las posiciones'
                                % (mayor, LARGO_DIBUJO_M)),
            'max_desplazamiento_recorrido_mm': round(mayor, 4),
            'uz_bajo_carga_min_mm': peor_uz['uz_bajo_carga_mm'],
            'indice_uz_bajo_carga_min': peor_uz['indice'],
            'apoyos_z': n_apoyos[2],
            'cota_redondeo_kN': es.COTA_REDONDEO,
            'verificaciones': verificaciones,
        },
        'P_kN': P,
        '_P_kN_por_que': ('Magnitud de DEMOSTRACION, no normativa: con %g kN la mayor flecha '
                          'bajo la carga del recorrido es %.3f mm y la deformada se ve con la '
                          'escala x%g. El modelo es lineal: otra P escala todo en P/%g '
                          '(se recalcula con --P).' % (P, peor_uz['uz_bajo_carga_mm'], escala, P)),
        'recorrido': {
            'elementos': rec['elementos'],
            'nodos': rec['nodos'],
            'largos_m': [round(L, 4) for L in rec['largos']],
            'largo_m': round(rec['largo_m'], 4),
            'z': decl['z'],
            'eje': decl['eje'],
            'coord': decl['coord'],
            'divisiones': divisiones,
            'descripcion': ('cota %.2f, eje %s = %.2f: vigas %s, del nodo %d al %d (%.2f m)'
                            % (decl['z'], 'y' if decl['eje'] == 'x' else 'x', decl['coord'],
                               ', '.join(str(x) for x in rec['elementos']), rec['nodos'][0],
                               rec['nodos'][-1], rec['largo_m'])),
            '_por_que': decl['_por_que'],
        },
        'posiciones': bloques,
    }

    decir()
    decir('  resueltas %d corridas de OpenSees: construir %.3f s, resolver y extraer %.4f s '
          'por corrida' % (n_resueltos, mot.t_construir, t_posiciones / max(n_resueltos, 1)))
    decir('  escala grafica fija: x%g (%.4f mm -> %.1f m)' % (escala, mayor, LARGO_DIBUJO_M))
    contexto = {'fallos': list(FALLOS), 'bloques': bloques, 'detalles': detalles,
                'globales': globales, 'apoyos': n_apoyos, 'escala': escala, 'mayor_mm': mayor,
                't0': t0}
    return anexo, contexto


def escribir(anexo):
    """salidas/carga_movil.json, compacto y de una vez."""
    texto = json.dumps(anexo, separators=(',', ':'), ensure_ascii=False)
    return rutas.escribir_atomico(rutas.salida('carga_movil'), texto.encode('utf-8'))


def al_dia(anexo):
    """
    salidas/carga_movil.json es lo que se arma ahora, comparado por objetos
    y sin tolerancia (el calculo es determinista). Es lo que mira la suite
    con --no-escribir: un archivo viejo se dibuja igual de "bien".
    """
    ruta = rutas.salida('carga_movil')
    try:
        with io.open(ruta, encoding='utf-8') as f:
            en_disco = json.load(f)
    except (OSError, ValueError) as ex:
        return check(False, '%s esta al dia' % rutas.relativa(ruta),
                     'no pude leerlo (%s): exportarlo con  python sap.py exportar carga_movil' % ex)
    iguales = json.loads(json.dumps(anexo)) == en_disco
    return check(iguales, '%s esta al dia: es lo que se arma ahora' % rutas.relativa(ruta),
                 '' if iguales else
                 'es de otro calculo: exportarlo con  python sap.py exportar carga_movil')


# ============================================================
def main(argv=None):
    """sap.py exportar carga_movil [--P kN] [--divisiones n] [--no-escribir]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='sap.py exportar carga_movil',
                                 description='Carga movil precalculada para el visor.')
    ap.add_argument('--P', type=float, default=P_POR_DEFECTO,
                    help='carga vertical hacia abajo, kN (defecto %g)' % P_POR_DEFECTO)
    ap.add_argument('--divisiones', type=int, default=DIVISIONES_POR_DEFECTO,
                    help='posiciones por viga (defecto %d)' % DIVISIONES_POR_DEFECTO)
    ap.add_argument('--no-escribir', action='store_true',
                    help='verificar sin escribir nada')
    args = ap.parse_args(argv)
    P = float(args.P)
    if P <= 0 or args.divisiones < 1:
        raise SystemExit('P tiene que ser positiva y divisiones >= 1')

    anexo, ctx = construir(P, args.divisiones)

    if ctx['fallos']:
        decir()
        decir('  NO SE ESCRIBE NADA: %d verificacion(es) fallaron:' % len(ctx['fallos']))
        for f in ctx['fallos']:
            decir('    - %s' % f)
        return 1

    if args.no_escribir:
        decir()
        if P == P_POR_DEFECTO and args.divisiones == DIVISIONES_POR_DEFECTO:
            if not al_dia(anexo):
                return 1
        else:
            decir('  (no se compara con %s: P o divisiones no son las de laboratorio.json)'
                  % rutas.relativa(rutas.salida('carga_movil')))
        decir('  todo cierra; --no-escribir: no se escribio nada')
        return 0

    destino = escribir(anexo)
    decir()
    decir('  %.1f KB, %d posiciones, %.1f s en total'
          % (os.path.getsize(destino) / 1024.0, len(anexo['posiciones']), time.time() - ctx['t0']))
    decir('  -> %s' % rutas.relativa(destino))
    return 0


if __name__ == '__main__':
    sys.exit(main())
