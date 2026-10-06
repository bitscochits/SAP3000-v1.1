# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/persona.py  -  LA DEFORMADA QUE PRODUCE LA PERSONA, AL INSTANTE
================================================================
 La pestana Persona del visor deja caminar una carga por cualquier
 losa del edificio y dice a que elemento le llega. Este archivo hace
 que ademas se vea lo que esa carga le HACE al edificio -- la deformada
 entera, la flecha de la viga cargada y sus momentos -- mientras camina,
 sin servidor y sin que Unity calcule nada. Deja salidas/persona.json.

 ----------------------------------------------------------------
 LA IDEA: casos unitarios y linealidad
 ----------------------------------------------------------------
 El modelo es elastico lineal. Una carga puntual P en la abscisa a de
 una viga (Euler-Bernoulli, prismatica) le entrega a sus dos nodos las
 FUERZAS NODALES EQUIVALENTES, que son P por las funciones de forma de
 Hermite evaluadas en alfa = a/L:

     en n1:  Fz = -P N1(alfa)      M = P L N2(alfa) (z x d)
     en n2:  Fz = -P N3(alfa)      M = P L N4(alfa) (z x d)

 (d = versor de la viga en planta; z x d = (-dy, dx, 0) es el eje de
 giro de la flexion). Con esas cargas OpenSees da los desplazamientos
 nodales EXACTOS de eleLoad -beamPoint: es lo que hace por dentro. Asi
 que basta resolver UNA vez, en OpenSees, cada carga unitaria posible
 -- Fz = 1 kN hacia abajo, Mx = 1 kN m y My = 1 kN m en cada nodo que
 puede recibir a la persona -- y la deformada de la persona en
 cualquier punto es la suma de a lo mas SEIS de esos casos con esos
 pesos. Es lo mismo que los sliders instantaneos (combinar casos ya
 resueltos), con pesos que dependen de donde esta parada.

 DENTRO de la viga cargada, ademas, esta la flecha de la viga
 biempotrada (elastica.flecha_biempotrada). Python exporta su
 flexibilidad L^3/(E I) y el C# solo evalua la forma ADIMENSIONAL

     uz_local = -P (L^3/EI) phi(xi, alfa)

 que es a la carga puntual lo que las funciones de forma son a los
 nodos: el E y la I no entran al C#. Las formulas (pesos, phi, M(x))
 son las de calculo/elastica.py; la guardia de las transcripciones lee
 el C# y las compara.

 ----------------------------------------------------------------
 LA REGLA DE DONDE CAE (supuestos, declarados abajo en SUPUESTOS)
 ----------------------------------------------------------------
 - A QUE ELEMENTO: el dueno de la region tributaria donde esta parada,
   la misma regla que ya usa VisorPersona (y el modelo para la losa).
 - EN QUE PUNTO DE UNA VIGA: la proyeccion de la persona sobre su eje.
 - UN MURO: la losa que apoya directo en un muro llega a su nodo de
   esa cota como carga puntual; la persona, igual.

 ----------------------------------------------------------------
 EL ARCHIVO (salidas/persona.json)
 ----------------------------------------------------------------
 Un caso por (nodo, gdl). Sus desplazamientos se guardan solo en el
 GRUPO de nodos conectados donde esta el nodo (el LT2 y el cuerpo
 antiguo no se tocan: la junta es libre, y fuera del grupo la respuesta
 es CERO exacto, [5]). Cada caso va como enteros de 16 bits en base64
 con dos escalas (traslaciones y giros): un error de a lo mas medio
 paso, que la verificacion lleva a la cota. En float serian 2.5 veces
 mas bytes para dibujar lo mismo.

 Correr:
   python sap.py exportar persona                 resuelve (~150 s) y escribe
   python sap.py exportar persona --no-escribir   arma y comprueba sin escribir

 Termina con 1 si una comprobacion de [5] falla, y entonces NO escribe.
 Que la suma de casos sea OpenSees directo ([1a], [1b]), la elastica
 ([2]), los esfuerzos de extremo ([8]), la escala de dibujo ([6]) y lo
 que la app sumo ([7]) lo comprueba verificacion/persona.py sobre el
 archivo escrito; que el C# copie bien las formulas y lea todas las
 claves, la verificacion del visor (verificacion.unity).

 LOS MOMENTOS
   Cada caso guarda tambien los esfuerzos de extremo de las barras que
   muestra algun receptor que lo usa: la viga y las que llegan a sus
   dos nodos (columnas y vigas vecinas). Sumados con los mismos pesos dan
   k u de cada barra, exacto; la viga cargada lleva ademas sus fuerzas
   de empotramiento perfecto, que son P por las mismas N1..N4. A lo largo
   de una barra sin carga M es lineal entre sus extremos; en la cargada
   tiene el quiebre de P bajo la carga (elastica.esfuerzos_con_puntual).
================================================================
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import time

import numpy as np

from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo.elastica import (carga_local, ejes_de, empotramiento_local, flecha_bajo_carga,
                              my_en, mz_en, pesos, rigidez, xyz)

GENERADO_POR = 'exportar/persona.py'

# ------------------------------------------------------------
# LO DECLARADO
# ------------------------------------------------------------
# La carga y el largo de dibujo son los de la carga movil (entrada/
# laboratorio.json, bloque 'carga_movil'), para que las dos pestanas se
# puedan comparar a la misma escala.
_MOVIL = lab.bloque('carga_movil')
P_POR_DEFECTO = float(_MOVIL['P_kN'])                # kN
LARGO_DIBUJO_M = float(_MOVIL['largo_dibujo_m'])     # m

SUPUESTOS = {
    'receptor': ('El elemento dueno de la region tributaria donde esta parada: la regla del '
                 'modelo para la losa, la misma que ya aplica VisorPersona.'),
    'punto_en_la_viga': ('La proyeccion de la persona sobre el eje de la viga, acotada a [0, L]. '
                         'La losa reparte la carga G pareja (q A / L) porque es un AREA; un punto '
                         'no tiene area, y le llega a la viga cerca de donde esta. La regla '
                         'pareja haria que caminar a lo largo de una viga no cambie nada.'),
    'muro': ('La losa que apoya directo en un muro llega a su nodo de esa cota como carga '
             'puntual (asi viene la losa sobre muro en las cargas del edificio): la persona '
             'tambien.'),
    'P': ('%g kN hacia abajo por defecto, la misma P de la pestana Carga movil; el panel la '
          'cambia (una persona son 0.80 kN y su deformada no se ve a ninguna escala util).'
          % P_POR_DEFECTO),
}

GDL = ('Fz', 'Mx', 'My')
# El vector de carga de cada caso unitario, (fx, fy, fz, mx, my, mz).
CARGA_UNITARIA = {
    'Fz': (0.0, 0.0, -1.0, 0.0, 0.0, 0.0),     # 1 kN hacia abajo
    'Mx': (0.0, 0.0, 0.0, 1.0, 0.0, 0.0),      # 1 kN m
    'My': (0.0, 0.0, 0.0, 0.0, 1.0, 0.0),      # 1 kN m
}

ENTERO = 32767                 # el mayor de cada escala se guarda como +-32767
EPS32 = 2.0 ** -24             # redondeo relativo de un float
K_F32 = 8                      # redondeos por termino en la suma de Unity (ver verificacion.persona.cota)
TAG_BASE = 8000

# Los momentos se dibujan con el mayor |M| (carga a media viga, en las
# barras que se dibujan) llevado a este largo, como la deformada.
LARGO_MOMENTO_M = 1.2
# localForce = [N, Vy, Vz, T, My, Mz] en i y en j: fuerzas y momentos
IDX_F = [0, 1, 2, 6, 7, 8]
IDX_M = [3, 4, 5, 9, 10, 11]
# Las barras que se dibujan con diagrama (los muros y brazos no: un muro
# es una placa y un brazo rigido no es una barra que se vea).
NO_DIBUJAR = ('muro', 'brazo', 'brazo_rigido')


# ============================================================
# AVISOS
# ============================================================
class Fallas:
    def __init__(self):
        self.lista = []

    def check(self, cond, msg, detalle=''):
        print('  [%s] %s' % ('OK  ' if cond else 'FALLA', msg))
        if detalle:
            print('         ' + detalle)
        if not cond:
            self.lista.append(msg)
        return cond


# ============================================================
# EL MOTOR: el modelo armado una vez (opensees.Resolutor)
# ============================================================
def motor(modelo):
    """El modelo armado una vez para resolver miles de casos unitarios."""
    return opensees.Resolutor(modelo, tag_base=TAG_BASE)


def resolver(sol, nodales=(), puntuales=()):
    """
    Un patron sobre el modelo ya armado: {nodo: u[6]} sin redondear. Las
    nodales se definen antes que las puntuales (el orden de siempre de la
    persona).
    """
    sol.resolver(puntuales=puntuales, nodales=nodales, nodales_primero=True)
    return {n: np.array(u, dtype=float) for n, u in sol.desplazamientos().items()}


def fuerzas_de(sol, elementos):
    """localForce de esas barras, del ultimo caso resuelto."""
    return {e: np.array(f, dtype=float) for e, f in sol.fuerzas(elementos).items()}


# ============================================================
# LO QUE PUEDE RECIBIR A LA PERSONA
# ============================================================
def incidentes(modelo):
    inc = {}
    for e in modelo['elementos']:
        for n in (int(e['n1']), int(e['n2'])):
            inc.setdefault(n, []).append(int(e['id']))
    return inc


def receptores(vista, modelo, fallas):
    """Un receptor por (elemento, cota) de las areas tributarias del visor."""
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elems = {int(e['id']): e for e in modelo['elementos']}
    inc = incidentes(modelo)
    salida, malos = {}, []
    for a in vista['areas_tributarias']:
        eid, z = int(a['elemento']), float(a['z'])
        clave = (eid, round(z, 2))
        if clave in salida:
            continue
        e = elems.get(eid)
        if e is None:
            malos.append('%d: no esta en el modelo' % eid)
            continue
        n1, n2 = int(e['n1']), int(e['n2'])
        pi, pj = xyz(nodos[n1]), xyz(nodos[n2])
        if abs(pi[2] - pj[2]) < 0.01:
            if abs(pi[2] - z) > 0.02:
                malos.append('%d: la viga esta en z = %.2f y su area en %.2f' % (eid, pi[2], z))
                continue
            base, L = ejes_de(e, nodos)
            (Px, Py, Pz), _ = carga_local(base, 1.0)
            if abs(Px) > 1e-9 or abs(Py) > 1e-9:
                malos.append('%d: la vertical no cae en su eje local z' % eid)
                continue
            k = rigidez(modelo, e, nodos)
            if base['wz'][2] < 1.0 - 1e-9:
                malos.append('%d: su z local no apunta hacia arriba' % eid)
                continue
            salida[clave] = {
                'elemento': eid, 'z': round(z, 4), 'tipo': 'viga', 'nodo': 0,
                'n1': n1, 'n2': n2, 'L': L,
                'flex': L ** 3 / (k['E'] * k['Iy_pasa']),
                'dx': (pj[0] - pi[0]) / L, 'dy': (pj[1] - pi[1]) / L,
                # las barras cuyos momentos se muestran: la viga y las que
                # llegan a sus dos nodos
                'elementos_m': sorted(set(inc[n1]) | set(inc[n2])),
            }
        else:
            en_z = [n for n in (n1, n2) if abs(nodos[n]['z'] - z) < 0.02]
            if len(en_z) != 1:
                malos.append('%d: el muro no tiene un nodo en z = %.2f' % (eid, z))
                continue
            salida[clave] = {'elemento': eid, 'z': round(z, 4), 'tipo': 'nodo', 'nodo': en_z[0],
                             'n1': n1, 'n2': n2, 'L': 0.0, 'flex': 0.0, 'dx': 0.0, 'dy': 0.0,
                             'elementos_m': sorted(inc[en_z[0]])}
    fallas.check(not malos, '[5] cada region tributaria del visor tiene a donde mandar la carga '
                 '(%d receptores: %d vigas, %d muros)'
                 % (len(salida), sum(r['tipo'] == 'viga' for r in salida.values()),
                    sum(r['tipo'] == 'nodo' for r in salida.values())),
                 '; '.join(malos[:5]))
    return [salida[k] for k in sorted(salida)]


def casos_necesarios(recs):
    casos = set()
    for r in recs:
        if r['tipo'] == 'nodo':
            casos.add((r['nodo'], 'Fz'))
        else:
            for n in (r['n1'], r['n2']):
                for g in GDL:
                    casos.add((n, g))
    return sorted(casos, key=lambda c: (c[0], GDL.index(c[1])))


def grupos_conectados(modelo):
    """Los nodos que se tocan por elementos o diafragmas (union-find)."""
    padre = {int(n['id']): int(n['id']) for n in modelo['nodos']}

    def raiz(a):
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    def unir(a, b):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[max(ra, rb)] = min(ra, rb)

    for e in modelo['elementos']:
        unir(int(e['n1']), int(e['n2']))
    for d in modelo.get('diafragmas', []):
        for n in d['nodos']:
            unir(int(d['nodo_maestro']), int(n))
    for br in modelo.get('brazos_rigidos', []):
        unir(int(br['maestro']), int(br['esclavo']))
    por_raiz = {}
    for n in sorted(padre):
        por_raiz.setdefault(raiz(n), []).append(n)
    return sorted(por_raiz.values(), key=lambda g: g[0])


# ============================================================
# CODIFICAR Y DECODIFICAR (lo mismo que hace el C#)
# ============================================================
def codificar(U):
    """U (n, 6) -> (escala_t, escala_r, base64 de int16 little-endian)."""
    st = float(np.abs(U[:, :3]).max()) / ENTERO
    sr = float(np.abs(U[:, 3:]).max()) / ENTERO
    q = np.zeros(U.shape, dtype=np.int64)
    if st > 0:
        q[:, :3] = np.rint(U[:, :3] / st)
    if sr > 0:
        q[:, 3:] = np.rint(U[:, 3:] / sr)
    assert np.abs(q).max() <= ENTERO
    return st, sr, base64.b64encode(q.astype('<i2').tobytes()).decode('ascii')


def codificar_f(F):
    """F (k, 12) de localForce -> (escala_f, escala_m, base64 de int16)."""
    sf = float(np.abs(F[:, IDX_F]).max()) / ENTERO if F.size else 0.0
    sm = float(np.abs(F[:, IDX_M]).max()) / ENTERO if F.size else 0.0
    q = np.zeros(F.shape, dtype=np.int64)
    if sf > 0:
        q[:, IDX_F] = np.rint(F[:, IDX_F] / sf)
    if sm > 0:
        q[:, IDX_M] = np.rint(F[:, IDX_M] / sm)
    assert q.size == 0 or np.abs(q).max() <= ENTERO
    return sf, sm, base64.b64encode(q.astype('<i2').tobytes()).decode('ascii')


def decodificar_f(caso, f32=True):
    k = len(caso['elementos'])
    q = np.frombuffer(base64.b64decode(caso['fuerzas']), dtype='<i2').reshape(k, 12)
    tipo = np.float32 if f32 else float
    F = q.astype(tipo)
    F[:, IDX_F] *= tipo(caso['escala_f'])
    F[:, IDX_M] *= tipo(caso['escala_m'])
    return F


def decodificar(caso, n, f32=True):
    """El caso como (n, 6). f32: como lo deja Unity (float del JSON y producto en float)."""
    q = np.frombuffer(base64.b64decode(caso['datos']), dtype='<i2').reshape(n, 6)
    if f32:
        st, sr = np.float32(caso['escala_t']), np.float32(caso['escala_r'])
        U = q.astype(np.float32)
        U[:, :3] *= st
        U[:, 3:] *= sr
        return U
    U = q.astype(float)
    U[:, :3] *= caso['escala_t']
    U[:, 3:] *= caso['escala_r']
    return U


class Datos:
    """El JSON ya armado, indexado como lo indexa el C#."""

    def __init__(self, js):
        self.js = js
        self.grupos = [g['nodos'] for g in js['grupos']]
        self.indice = [{n: i for i, n in enumerate(g)} for g in self.grupos]
        self.casos = {(c['nodo'], c['gdl']): c for c in js['casos']}
        self._cache = {}

    def U(self, nodo, gdl, f32=True):
        c = self.casos[(nodo, gdl)]
        k = (nodo, gdl, f32)
        if k not in self._cache:
            self._cache[k] = decodificar(c, len(self.grupos[c['grupo']]), f32)
        return c['grupo'], self._cache[k]

    def F(self, nodo, gdl, f32=True):
        """{barra: localForce[12]} de un caso."""
        c = self.casos[(nodo, gdl)]
        k = ('F', nodo, gdl, f32)
        if k not in self._cache:
            M = decodificar_f(c, f32)
            self._cache[k] = {e: M[i] for i, e in enumerate(c['elementos'])}
        return self._cache[k]


def combinar(datos, rec, alfa, P, f32=True):
    """{nodo: u[6]} como lo arma el C#: suma de a lo mas seis casos."""
    tipo = np.float32 if f32 else float
    suma = {}
    for nodo, gdl, w in pesos(rec, alfa, P):
        g, U = datos.U(nodo, gdl, f32)
        w = tipo(w)
        for n, i in datos.indice[g].items():
            prev = suma.get(n)
            suma[n] = (U[i] * w) if prev is None else (prev + U[i] * w)
    return suma


def combinar_f(datos, rec, alfa, P, f32=True):
    """{barra: localForce[12]} de las barras del receptor, como el C#: la
    suma de los casos y, en la viga cargada, su empotramiento."""
    tipo = np.float32 if f32 else float
    out = {e: np.zeros(12, dtype=tipo) for e in rec['elementos_m']}
    for nodo, gdl, w in pesos(rec, alfa, P):
        F = datos.F(nodo, gdl, f32)
        w = tipo(w)
        for e in rec['elementos_m']:
            out[e] = out[e] + F[e] * w
    if rec['tipo'] == 'viga':
        f = out[rec['elemento']]
        for i, v in empotramiento_local(rec, alfa, P).items():
            f[i] = f[i] + tipo(v)
    return out


# ============================================================
# ARMAR
# ============================================================
def armar(modelo, vista, fallas):
    t0 = time.time()
    recs = receptores(vista, modelo, fallas)
    casos = casos_necesarios(recs)
    grupos = grupos_conectados(modelo)
    grupo_de = {n: g for g, ns in enumerate(grupos) for n in ns}
    print('  %d casos unitarios en %d nodos; %d grupo(s) de nodos conectados (%s)'
          % (len(casos), len({c[0] for c in casos}), len(grupos),
             ', '.join(str(len(g)) for g in grupos)))

    # Las barras de cada caso: las que muestra algun receptor que lo usa.
    barras = {c: set() for c in casos}
    for r in recs:
        for nodo, gdl, _w in pesos(r, 0.5, 1.0):
            barras[(nodo, gdl)] |= set(r['elementos_m'])

    sol = motor(modelo)
    salida, fuera = [], 0.0
    for k, (nodo, gdl) in enumerate(casos):
        u = resolver(sol, nodales=[(nodo, CARGA_UNITARIA[gdl])])
        g = grupo_de[nodo]
        U = np.array([u[n] for n in grupos[g]])
        otros = [np.abs(u[n]).max() for n in u if grupo_de[n] != g]
        if otros:
            fuera = max(fuera, max(otros))
        st, sr, datos = codificar(U)
        ids = sorted(barras[(nodo, gdl)])
        f = fuerzas_de(sol, ids)
        F = np.array([f[e] for e in ids]).reshape(len(ids), 12)
        sf, sm, fuerzas = codificar_f(F)
        salida.append({'nodo': nodo, 'gdl': gdl, 'grupo': g,
                       'escala_t': st, 'escala_r': sr, 'datos': datos,
                       'elementos': ids, 'escala_f': sf, 'escala_m': sm, 'fuerzas': fuerzas,
                       '_U': U, '_F': F})
        if (k + 1) % 200 == 0:
            print('    %d de %d (%.0f s)' % (k + 1, len(casos), time.time() - t0), flush=True)
    t_casos = time.time() - t0
    fallas.check(fuera == 0.0, '[5] fuera de su grupo, cada caso vale CERO exacto (la junta es libre)',
                 'mayor |u| fuera del grupo: %.3e' % fuera)

    js = {
        'info': {
            'edificio': _ed.NOMBRE,
            'n_nodos': len(modelo['nodos']),
            'n_elementos': len(modelo['elementos']),
            'generado_por': GENERADO_POR,
            'unidades': ('casos: Fz = 1 kN hacia abajo, Mx = My = 1 kN m, en ejes OpenSees; '
                         'desplazamientos en m y giros en rad; flex en m/kN'),
            'P_por_defecto_kN': P_POR_DEFECTO,
            'escala_deformada': 0.0,
            'largo_dibujo_m': LARGO_DIBUJO_M,
            'escala_momento': 0.0,
            'largo_momento_m': LARGO_MOMENTO_M,
            'n_casos': len(salida),
            'segundos_opensees': round(t_casos, 1),
            '_por_que': ('Cada caso es UNA carga unitaria resuelta por OpenSees. La deformada de la '
                         'persona es la suma de a lo mas seis, con los pesos de Hermite de donde '
                         'esta parada, mas la flecha biempotrada dentro de la viga cargada: Unity '
                         'combina, no resuelve. Los datos de cada caso son int16 en base64 por '
                         'escala_t (traslaciones) y escala_r (giros), solo de los nodos de su grupo. '
                         'fuerzas: localForce de las barras de elementos (int16 por escala_f y '
                         'escala_m); la viga cargada suma su empotramiento perfecto. escala_momento '
                         'en m por kN m.'),
            '_supuesto_receptor': SUPUESTOS['receptor'],
            '_supuesto_punto_en_la_viga': SUPUESTOS['punto_en_la_viga'],
            '_supuesto_muro': SUPUESTOS['muro'],
            '_supuesto_P': SUPUESTOS['P'],
        },
        'grupos': [{'nodos': g} for g in grupos],
        'casos': salida,
        'receptores': recs,
    }
    return js, sol


def escala_de_dibujo(datos, recs, P):
    """La mayor traslacion con la carga a media viga (o en el nodo del
    muro), en todo el edificio y en el punto cargado; la escala la lleva
    a LARGO_DIBUJO_M, con 2 cifras como la escala de resultados.json."""
    peor, donde = 0.0, None
    for r in recs:
        alfa = 0.5
        u = combinar(datos, r, alfa, P, f32=False)
        m = max(float(np.linalg.norm(v[:3])) for v in u.values())
        if r['tipo'] == 'viga':
            m = max(m, abs(flecha_bajo_carga(r, u[r['n1']], u[r['n2']], alfa, P)))
        if m > peor:
            peor, donde = m, r['elemento']
    bruta = LARGO_DIBUJO_M / peor
    cifras = 10 ** (math.floor(math.log10(bruta)) - 1)
    return round(bruta / cifras) * cifras, peor, donde


def escala_de_momentos(datos, recs, P, dibujables):
    """El mayor |M| de las barras que se dibujan, con la carga a media viga;
    la escala (m por kN m) lo lleva a LARGO_MOMENTO_M, con 2 cifras."""
    peor, donde = 0.0, None
    for r in recs:
        alfa = 0.5
        F = combinar_f(datos, r, alfa, P, f32=False)
        for e, f in F.items():
            if e not in dibujables:
                continue
            L = dibujables[e]
            cargada = r['tipo'] == 'viga' and e == r['elemento']
            for k in range(11):
                x = L * k / 10.0
                m = max(abs(my_en(f, x, alfa * L, P if cargada else 0.0)), abs(mz_en(f, x)))
                if m > peor:
                    peor, donde = m, e
            if cargada:
                m = abs(my_en(f, alfa * L, alfa * L, P))
                if m > peor:
                    peor, donde = m, e
    bruta = LARGO_MOMENTO_M / peor
    cifras = 10 ** (math.floor(math.log10(bruta)) - 1)
    return round(bruta / cifras) * cifras, peor, donde


def largos_dibujables(modelo):
    """{barra: L} de las que llevan diagrama."""
    nodos = {int(n['id']): xyz(n) for n in modelo['nodos']}
    out = {}
    for e in modelo['elementos']:
        if e.get('tipo') in NO_DIBUJAR:
            continue
        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        out[int(e['id'])] = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))
    return out


def escribir(js):
    """salidas/persona.json, compacto (pesa ~6 MB) y de una vez."""
    texto = json.dumps(js, ensure_ascii=False, separators=(',', ':'))
    return rutas.escribir_atomico(rutas.salida('persona'), texto.encode('utf-8'))


# ============================================================
# MAIN
# ============================================================
def main(argv=None):
    """sap.py exportar persona [--no-escribir]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='sap.py exportar persona',
                                 description='Casos unitarios para la deformada de la persona.')
    ap.add_argument('--no-escribir', action='store_true',
                    help='armar y comprobar sin escribir salidas/persona.json')
    args = ap.parse_args(argv)
    t0 = time.time()
    fallas = Fallas()
    edificio = _ed.cargar()
    modelo = _ed.estructura(edificio)
    vista = _ed.vista(edificio)
    print('=' * 76)
    print('  DEFORMADA DE LA PERSONA   %s   armar' % _ed.NOMBRE.upper())
    print('=' * 76)

    js, _sol = armar(modelo, vista, fallas)
    datos = Datos(js)
    esc, peor, donde = escala_de_dibujo(datos, js['receptores'], P_POR_DEFECTO)
    js['info']['escala_deformada'] = esc
    print('  escala de dibujo: x%g (el peor, %.3f mm con %g kN a media viga en el elemento %s, '
          'se dibuja %.2f m)' % (esc, peor * 1000, P_POR_DEFECTO, donde, peor * esc))
    escm, peorm, dondem = escala_de_momentos(datos, js['receptores'], P_POR_DEFECTO,
                                             largos_dibujables(modelo))
    js['info']['escala_momento'] = escm
    print('  escala de momentos: %g m por kN m (el mayor, %.1f kN m en la barra %s, se dibuja '
          '%.2f m)' % (escm, peorm, dondem, peorm * escm))
    for c in js['casos']:
        c.pop('_U', None)
        c.pop('_F', None)
    if not fallas.lista and not args.no_escribir:
        ruta = escribir(js)
        print('  escrito %s (%.1f MB)' % (rutas.relativa(ruta), os.path.getsize(ruta) / 1e6))
    print('  (%.0f s)' % (time.time() - t0))
    if fallas.lista:
        print('  FALLARON %d: %s' % (len(fallas.lista), '; '.join(fallas.lista)))
        print('  NO se escribio nada.')
        return 1
    if args.no_escribir:
        print('  --no-escribir: no se escribio nada')
    print('  TODO OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
