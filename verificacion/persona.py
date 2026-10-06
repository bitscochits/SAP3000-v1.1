# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/persona.py  -  LO QUE SUMA LA PERSONA ES OPENSEES
================================================================
 La pestana Persona suma en C# a lo mas seis casos unitarios de
 salidas/persona.json (la licencia de sumar en C#: combina casos ya
 resueltos por Python, no resuelve). Esta verificacion lee ese archivo
 y lo compara contra OpenSees resolviendo la carga DIRECTO (eleLoad
 -beamPoint en la viga, o la carga nodal en el muro), en posiciones al
 azar con semilla fija. No escribe nada.

   python -m verificacion.persona                        los dos bloques
   python -m verificacion.persona suma_igual_opensees    sin el registro
   python -m verificacion.persona registro [--registro REGISTRO_TXT]

 suma_igual_opensees
   [5] cada region tributaria tiene receptor, y los receptores y su
       flexibilidad son los del modelo de hoy (si no, el archivo es de
       otro modelo: volver a exportarlo);
   [5] fuera de su grupo cada caso vale CERO exacto (la junta es libre);
   [1a] la suma de casos SIN cuantizar = OpenSees directo, en todos los
       GDL de todos los nodos, al decimal del servidor (1e-8). Los casos
       que suman las pruebas se vuelven a resolver aca: el archivo solo
       guarda los enteros;
   [1b] la suma como la hace Unity (int16 + float32) = OpenSees directo,
       dentro de la cota que dan el medio paso y la aritmetica de 32 bits;
   [2] la flecha bajo la carga (Hermite + phi) = elastica.desplazamiento_en
       con la solucion directa;
   [8] los esfuerzos de extremo (casos + empotramiento de la viga
       cargada) = localForce directo: sin cuantizar (a), como los suma
       Unity (b), y el momento bajo la carga (c);
   [6] las escalas de dibujo (deformada y momentos) son las que se calculan.

 registro
   [7] lo que la APP sumo y dibujo (la captura 'persona' deja en su
       registro.txt las lineas 'persona: elemento ...', float en G9)
       contra OpenSees resolviendo esa misma carga directo.

 Lo que LEE el C# -- que copie bien las formulas (N1..N4, FormaLocal, los
 seis Sumar, UzEn, MyEn, MzEn, el empotramiento) y que cada clave del JSON
 tenga su campo -- lo comprueba verificacion.unity (transcripciones y
 contratos), no este archivo.
================================================================
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time

import numpy as np

from calculo import edificio as _ed
from calculo import rutas
from calculo.elastica import (carga_local, desplazamiento_en, ejes_de, empotramiento_local,
                              esfuerzos_con_puntual, hermite, my_en, pesos, rigidez, uz_en)
from exportar import persona
from exportar.carga_movil import RESOLUCION_F, RESOLUCION_U   # el decimal del servidor
from exportar.persona import EPS32, IDX_F, IDX_M, K_F32
from verificacion.comun import Informe

BLOQUES = ('suma_igual_opensees', 'registro')
N_PRUEBAS = 24
SEMILLA = 20261005

# Lo que dejo la app al capturar la persona (sap.py capturar persona).
REGISTRO = os.path.join(rutas.REGISTROS, 'capturas', 'persona', 'registro.txt')


# ============================================================
# LA COTA DE LO QUE SUMA UNITY
# ============================================================
def cota_f(datos, rec, alfa, P):
    """La cota de combinar_f, con las mismas causas que cota()."""
    out = {e: np.zeros(12) for e in rec['elementos_m']}
    for nodo, gdl, w in pesos(rec, alfa, P):
        c = datos.casos[(nodo, gdl)]
        F = datos.F(nodo, gdl, f32=False)
        paso = np.zeros(12)
        paso[IDX_F] = 0.5 * c['escala_f']
        paso[IDX_M] = 0.5 * c['escala_m']
        for e in rec['elementos_m']:
            out[e] += abs(w) * (paso + K_F32 * EPS32 * np.abs(F[e]))
    if rec['tipo'] == 'viga':
        for i, v in empotramiento_local(rec, alfa, P).items():
            out[rec['elemento']][i] += K_F32 * EPS32 * abs(v)
    return out


def cota(datos, rec, alfa, P):
    """
    Por GDL, lo mas que puede separarse lo que suma Unity de la suma
    exacta de los casos sin cuantizar:
      - el MEDIO PASO de cada caso (0.5 escala), por su |peso|;
      - la aritmetica de 32 bits: la escala al leerse, el entero por la
        escala, el peso, el producto y la suma: menos de K_F32 = 8
        redondeos de 2^-24 por termino, sobre |peso * u|.
    """
    out = {}
    for nodo, gdl, w in pesos(rec, alfa, P):
        c = datos.casos[(nodo, gdl)]
        g, U = datos.U(nodo, gdl, f32=False)
        paso = np.array([c['escala_t']] * 3 + [c['escala_r']] * 3) * 0.5
        for n, i in datos.indice[g].items():
            t = abs(w) * (paso + K_F32 * EPS32 * np.abs(U[i]))
            out[n] = t if n not in out else out[n] + t
    return out


# ============================================================
# CONTRA OPENSEES
# ============================================================
def posiciones_al_azar(recs, n):
    rnd = random.Random(SEMILLA)
    vigas = [r for r in recs if r['tipo'] == 'viga']
    muros = [r for r in recs if r['tipo'] == 'nodo']
    lista = []
    for k in range(n):
        if muros and k % 6 == 5:
            lista.append((rnd.choice(muros), 0.0))
            continue
        r = rnd.choice(vigas)
        # los bordes van a proposito: en alfa = 0 y 1 la carga cae en un nodo
        alfa = (0.0, 1.0)[k % 2] if k % 8 == 3 else rnd.random()
        lista.append((r, alfa))
    return lista


def directo(sol, modelo, rec, alfa, P):
    if rec['tipo'] == 'nodo':
        return persona.resolver(sol, nodales=[(rec['nodo'], (0, 0, -P, 0, 0, 0))])
    nodos = {int(n['id']): n for n in modelo['nodos']}
    e = next(x for x in modelo['elementos'] if int(x['id']) == rec['elemento'])
    base, _ = ejes_de(e, nodos)
    (Px, Py, Pz), _ = carga_local(base, P)
    return persona.resolver(sol, puntuales=[(rec['elemento'], Px, Py, Pz, alfa)])


def casos_de_las_pruebas(recs, n_pruebas):
    """Los (nodo, gdl) que suman las posiciones de prueba, en el orden en que aparecen."""
    claves = []
    for rec, alfa in posiciones_al_azar(recs, n_pruebas):
        for nodo, gdl, _w in pesos(rec, alfa, persona.P_POR_DEFECTO):
            if (nodo, gdl) not in claves:
                claves.append((nodo, gdl))
    return claves


def casos_sin_cuantizar(js, sol, claves, informe):
    """
    Los casos unitarios `claves` resueltos OTRA VEZ, sin cuantizar: lo que
    exportar.persona.armar tiene antes de pasarlos a int16 (el archivo
    guarda solo los enteros). Con ellos [1a] y [8a] miden la linealidad al
    decimal del servidor, y [5] que fuera de su grupo cada caso vale cero.
    """
    grupos = [g['nodos'] for g in js['grupos']]
    grupo_de = {n: g for g, ns in enumerate(grupos) for n in ns}
    casos = {(c['nodo'], c['gdl']): c for c in js['casos']}
    salida, fuera = {}, 0.0
    for nodo, gdl in claves:
        c = casos[(nodo, gdl)]
        u = persona.resolver(sol, nodales=[(nodo, persona.CARGA_UNITARIA[gdl])])
        g = grupo_de[nodo]
        U = np.array([u[n] for n in grupos[g]])
        otros = [np.abs(u[n]).max() for n in u if grupo_de[n] != g]
        if otros:
            fuera = max(fuera, max(otros))
        f = persona.fuerzas_de(sol, c['elementos'])
        F = np.array([f[e] for e in c['elementos']]).reshape(len(c['elementos']), 12)
        salida[(nodo, gdl)] = {'grupo': g, 'elementos': c['elementos'], '_U': U, '_F': F}
    informe.check(fuera == 0.0, '[5] fuera de su grupo, cada caso vale CERO exacto (la junta es libre)',
                  'mayor |u| fuera del grupo: %.3e, en los %d casos que suman las pruebas'
                  % (fuera, len(claves)))
    return salida


def verificar(js, modelo, sol, fallas, n_pruebas, sin_cuantizar=None):
    datos = persona.Datos(js)
    recs = js['receptores']
    P = persona.P_POR_DEFECTO
    peor_a, peor_b, peor_b_rel, peor_f = 0.0, 0.0, 0.0, 0.0
    detalle_b, detalle_f = '', ''
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elems = {int(e['id']): e for e in modelo['elementos']}
    peor_fa, peor_fb, peor_mc = 0.0, 0.0, 0.0
    detalle_fb, detalle_mc = '', ''
    for rec, alfa in posiciones_al_azar(recs, n_pruebas):
        u_d = directo(sol, modelo, rec, alfa, P)
        f_d = persona.fuerzas_de(sol, rec['elementos_m'])
        mayor = max(float(np.abs(v[:3]).max()) for v in u_d.values())
        # [8] los esfuerzos de extremo
        if sin_cuantizar is not None:
            suma = {e: np.zeros(12) for e in rec['elementos_m']}
            for nodo, gdl, w in pesos(rec, alfa, P):
                c = sin_cuantizar[(nodo, gdl)]
                fila = {e: i for i, e in enumerate(c['elementos'])}
                for e in rec['elementos_m']:
                    suma[e] += w * c['_F'][fila[e]]
            if rec['tipo'] == 'viga':
                for i, v in empotramiento_local(rec, alfa, P).items():
                    suma[rec['elemento']][i] += v
            for e in rec['elementos_m']:
                peor_fa = max(peor_fa, float(np.abs(suma[e] - f_d[e]).max()))
        f_u = persona.combinar_f(datos, rec, alfa, P, f32=True)
        cf = cota_f(datos, rec, alfa, P)
        for e in rec['elementos_m']:
            err = np.abs(f_u[e].astype(float) - f_d[e])
            c = cf[e] + 1e-12
            j = int(np.argmax(err / c))
            if err[j] / c[j] > peor_fb:
                peor_fb = float(err[j] / c[j])
                detalle_fb = ('peor: carga en %d alfa %.3f, barra %d, %s: error %.2e contra cota %.2e'
                              % (rec['elemento'], alfa, e, ('N_i Vy_i Vz_i T_i My_i Mz_i N_j Vy_j Vz_j '
                                                            'T_j My_j Mz_j').split()[j],
                                 float(err[j]), float(c[j])))
        if rec['tipo'] == 'viga':
            a = alfa * rec['L']
            ref = esfuerzos_con_puntual(f_d[rec['elemento']], 0.0, 0.0, -P, a, [a])['My'][0]
            got = my_en(f_u[rec['elemento']].astype(float), a, a, P)
            cc = cf[rec['elemento']]
            c = cc[4] + a * cc[2] + K_F32 * EPS32 * abs(ref) + 1e-12
            if abs(got - ref) / c > peor_mc:
                peor_mc = abs(got - ref) / c
                detalle_mc = ('peor: viga %d, alfa %.3f: M bajo la carga %.4f contra %.4f kN m'
                              % (rec['elemento'], alfa, got, ref))
        # (a) sin cuantizar: la linealidad, al decimal del servidor
        if sin_cuantizar is not None:
            suma = {}
            for nodo, gdl, w in pesos(rec, alfa, P):
                c = sin_cuantizar[(nodo, gdl)]
                for i, n in enumerate(js['grupos'][c['grupo']]['nodos']):
                    suma[n] = suma.get(n, 0.0) + w * c['_U'][i]
            for n, v in u_d.items():
                peor_a = max(peor_a, float(np.abs(suma.get(n, np.zeros(6)) - v).max()))
        # (b) como lo suma Unity, contra su cota
        u_u = persona.combinar(datos, rec, alfa, P, f32=True)
        cotas = cota(datos, rec, alfa, P)
        for n, v in u_d.items():
            got = u_u.get(n, np.zeros(6, dtype=np.float32)).astype(float)
            err = np.abs(got - v)
            c = cotas.get(n, np.zeros(6)) + 1e-15
            j = int(np.argmax(err / c))
            r = float(err[j] / c[j])
            if r > peor_b:
                peor_b = r
                detalle_b = ('peor: elemento %d, alfa %.3f, nodo %d, gdl %s: error %.2e contra cota %.2e'
                             % (rec['elemento'], alfa, n, ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')[j],
                                float(err[j]), float(c[j])))
            peor_b_rel = max(peor_b_rel, float(err[:3].max()) / mayor if mayor > 0 else 0.0)
        # [2] la flecha bajo la carga
        if rec['tipo'] == 'viga':
            e = elems[rec['elemento']]
            base, L = ejes_de(e, nodos)
            k = rigidez(modelo, e, nodos)
            (Px, Py, Pz), _ = carga_local(base, P)
            for xi in (alfa, 0.25, 0.5, 0.75):
                ref = desplazamiento_en(base, L, k, list(u_d[rec['n1']]),
                                        list(u_d[rec['n2']]), xi * L,
                                        carga=(Py, Pz, alfa * L))[2]
                got = uz_en(rec, u_u[rec['n1']].astype(float), u_u[rec['n2']].astype(float),
                            xi, alfa, P)
                N1, N2, N3, N4 = hermite(xi)
                ci, cj = cotas[rec['n1']], cotas[rec['n2']]
                c = (N1 * ci[2] + abs(N2) * L * (ci[3] + ci[4]) + N3 * cj[2]
                     + abs(N4) * L * (cj[3] + cj[4]) + K_F32 * EPS32 * abs(ref) + 1e-15)
                r = abs(got - ref) / c
                if r > peor_f:
                    peor_f = r
                    detalle_f = ('peor: viga %d, carga en alfa %.3f, punto xi %.3f: %.6f mm contra '
                                 '%.6f mm (cota %.1e m)' % (rec['elemento'], alfa, xi, got * 1000,
                                                            ref * 1000, c))
    if sin_cuantizar is not None:
        fallas.check(peor_a <= RESOLUCION_U,
                     '[1a] la suma de casos = OpenSees directo (beamPoint o nodal), sin cuantizar, '
                     'en %d posiciones' % n_pruebas,
                     'peor diferencia %.2e (m o rad); el servidor escribe 1e-8' % peor_a)
    fallas.check(peor_b <= 1.0,
                 '[1b] lo que suma Unity (int16 + float32) = OpenSees directo, dentro de su cota, '
                 'en todos los GDL de todos los nodos (%d posiciones)' % n_pruebas,
                 '%s; cociente %.3f; el error mayor es el %.4f %% del mayor desplazamiento'
                 % (detalle_b, peor_b, 100 * peor_b_rel))
    fallas.check(peor_f <= 1.0,
                 '[2] la elastica de la viga cargada (Hermite + phi; bajo la carga y en 1/4, 1/2, '
                 '3/4) = elastica.desplazamiento_en con la solucion directa',
                 '%s; cociente %.3f' % (detalle_f, peor_f))
    if sin_cuantizar is not None:
        fallas.check(peor_fa <= RESOLUCION_F,
                     '[8a] los esfuerzos de extremo (casos + empotramiento) = localForce de OpenSees '
                     'directo, sin cuantizar', 'peor diferencia %.2e (kN o kN m); el servidor escribe '
                     '1e-4' % peor_fa)
    fallas.check(peor_fb <= 1.0,
                 '[8b] los esfuerzos de extremo como los suma Unity = localForce directo, dentro de su '
                 'cota (la viga cargada y las barras de sus nodos)', '%s; cociente %.3f'
                 % (detalle_fb, peor_fb))
    fallas.check(peor_mc <= 1.0,
                 '[8c] el momento bajo la carga = elastica.esfuerzos_con_puntual con localForce directo',
                 '%s; cociente %.3f' % (detalle_mc, peor_mc))


def escalas(js, modelo, fallas):
    """[6] Las dos escalas de dibujo del archivo son las que se calculan hoy."""
    esc, peor, donde = persona.escala_de_dibujo(persona.Datos(js), js['receptores'],
                                                persona.P_POR_DEFECTO)
    fallas.check(abs(esc - js['info']['escala_deformada']) <= 1e-9 * esc,
                 '[6] la escala de dibujo es la que se calcula: x%g (%.3f mm con la carga a media '
                 'viga en el elemento %s -> %.2f m)' % (esc, peor * 1000, donde, peor * esc))
    escm, peorm, dondem = persona.escala_de_momentos(persona.Datos(js), js['receptores'],
                                                     persona.P_POR_DEFECTO,
                                                     persona.largos_dibujables(modelo))
    fallas.check(abs(escm - js['info']['escala_momento']) <= 1e-9 * escm,
                 '[6] la escala de los momentos es la que se calcula: %g m por kN m (%.1f kN m en '
                 'la barra %s -> %.2f m)' % (escm, peorm, dondem, peorm * escm))


# ============================================================
# [7] LO QUE SUMO LA APP
# ============================================================
def lineas_de_la_persona(ruta):
    """Las lineas 'persona: elemento ...' del registro de la captura."""
    # MOVER A verificacion/comun.py: leer_registro devuelve solo las lineas
    # 'DATO clave = valor' y los avisos, y la captura de la persona escribe
    # sus sumas en lineas propias.
    with io.open(ruta, encoding='utf-8') as f:
        return [l.strip() for l in f if l.startswith('persona: elemento')]


def cruzar_registro(ruta, js, modelo, sol, fallas):
    """
    [7] Lo que la APP sumo y dibujo (la captura 'persona' deja en
    registro.txt las lineas de VisorPersona.Captura_Registro, float en G9)
    contra OpenSees resolviendo esa misma carga directo. La cota es la de
    [1b] mas la impresion en G9 (medio digito en la novena cifra).
    """
    if not os.path.isfile(ruta):
        fallas.check(False, '[7] existe el registro de la app (%s)' % rutas.relativa(ruta),
                     'capturarlo con  python sap.py capturar persona')
        return
    lineas = lineas_de_la_persona(ruta)
    if not fallas.check(bool(lineas), '[7] el registro de la app trae lineas de la persona (%s)'
                        % rutas.relativa(ruta)):
        return
    datos = persona.Datos(js)
    peor, detalle, n_ok = 0.0, '', 0
    for l in lineas:
        cab, *nodos_txt = l.split(' | ')
        t = cab.split()
        kv = {t[i]: t[i + 1] for i in range(1, len(t) - 1, 2)}
        eid, alfa, P = int(kv['elemento']), float(kv['alfa']), float(kv['P'])
        rec = next(r for r in js['receptores'] if r['elemento'] == eid and r['tipo'] == kv['tipo'])
        u_d = directo(sol, modelo, rec, alfa, P)
        cotas = cota(datos, rec, alfa, P)
        esperados = 1 if rec['tipo'] == 'nodo' else 6
        fallas.check(int(kv['casos']) == esperados, '[7] la app sumo %d casos para %s %d (se esperan %d)'
                     % (int(kv['casos']), rec['tipo'], eid, esperados))
        barras_txt = [t for t in nodos_txt if t.startswith('barra ')]
        nodos_txt = [t for t in nodos_txt if t.startswith('nodo ')]
        for nt in nodos_txt:
            v = nt.split()
            nid, got = int(v[1]), np.array([float(c) for c in v[2:8]])
            c = cotas.get(nid, np.zeros(6)) + 5e-9 * np.abs(got) + 1e-15
            r = float((np.abs(got - u_d[nid]) / c).max())
            if r > peor:
                peor, detalle = r, 'elemento %d alfa %.4f nodo %d' % (eid, alfa, nid)
        if barras_txt:
            f_d = persona.fuerzas_de(sol, [int(t.split()[1]) for t in barras_txt])
            cf = cota_f(datos, rec, alfa, P)
            for t in barras_txt:
                v = t.split()
                eid_b, got = int(v[1]), np.array([float(c) for c in v[2:14]])
                c = cf[eid_b] + 5e-9 * np.abs(got) + 1e-12
                r = float((np.abs(got - f_d[eid_b]) / c).max())
                if r > peor:
                    peor, detalle = r, 'localForce de la barra %d (carga en %d)' % (eid_b, eid)
            if 'M_carga' in kv and rec['tipo'] == 'viga':
                a = alfa * rec['L']
                ref = esfuerzos_con_puntual(f_d[eid], 0.0, 0.0, -P, a, [a])['My'][0]
                cc = cf[eid]
                c = cc[4] + a * cc[2] + (K_F32 * EPS32 + 5e-9) * abs(ref) + 1e-12
                r = abs(float(kv['M_carga']) - ref) / c
                if r > peor:
                    peor, detalle = r, 'M bajo la carga en %d: app %s, OpenSees %.6g kN m' \
                        % (eid, kv['M_carga'], ref)
        if rec['tipo'] == 'viga':
            ref = uz_en(rec, u_d[rec['n1']], u_d[rec['n2']], alfa, alfa, P)
            N1, N2, N3, N4 = hermite(alfa)
            ci, cj = cotas[rec['n1']], cotas[rec['n2']]
            c = (N1 * ci[2] + abs(N2) * rec['L'] * (ci[3] + ci[4]) + N3 * cj[2]
                 + abs(N4) * rec['L'] * (cj[3] + cj[4]) + (K_F32 * EPS32 + 5e-9) * abs(ref) + 1e-15)
            r = abs(float(kv['uz_carga']) - ref) / c
            if r > peor:
                peor, detalle = r, ('flecha bajo la carga, elemento %d alfa %.4f: app %s m, '
                                    'OpenSees %.9g m' % (eid, alfa, kv['uz_carga'], ref))
        n_ok += 1
    fallas.check(peor <= 1.0, '[7] lo que la app sumo (%d posiciones: nodos de la viga, el que mas se mueve, '
                 'la flecha bajo la carga y, si vienen, los esfuerzos de extremo y el momento bajo la '
                 'carga) = OpenSees directo, dentro de su cota' % n_ok,
                 'peor cociente %.3f (%s)' % (peor, detalle))


# ============================================================
# MAIN
# ============================================================
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='python -m verificacion.persona',
                                 description='La suma de casos de la persona contra OpenSees directo.')
    ap.add_argument('bloques', nargs='*', metavar='bloque',
                    help='%s (sin nada: los dos)' % ', '.join(BLOQUES))
    ap.add_argument('--pruebas', type=int, default=N_PRUEBAS,
                    help='posiciones al azar (semilla fija; defecto %d)' % N_PRUEBAS)
    ap.add_argument('--registro', metavar='REGISTRO_TXT', default=REGISTRO,
                    help='el registro de la captura persona (defecto %s)' % rutas.relativa(REGISTRO))
    args = ap.parse_args(argv)
    desconocidos = [b for b in args.bloques if b not in BLOQUES]
    if desconocidos:
        ap.error('bloque desconocido %s (son: %s)' % (', '.join(desconocidos), ', '.join(BLOQUES)))
    bloques = args.bloques or list(BLOQUES)

    t0 = time.time()
    informe = Informe()
    edificio = _ed.cargar()
    modelo = _ed.estructura(edificio)
    vista = _ed.vista(edificio)
    print('=' * 76)
    print('  DEFORMADA DE LA PERSONA   %s   verificar (%s)' % (_ed.NOMBRE.upper(), ', '.join(bloques)))
    print('=' * 76)

    ruta = rutas.salida('persona')
    if not os.path.isfile(ruta):
        informe.check(False, 'existe %s' % rutas.relativa(ruta),
                      'exportarlo con  python sap.py exportar persona')
        return informe.cerrar()
    with io.open(ruta, encoding='utf-8') as f:
        js = json.load(f)
    informe.check(js['info']['n_nodos'] == len(modelo['nodos'])
                  and js['info']['n_elementos'] == len(modelo['elementos']),
                  'el JSON es de este modelo (%d nodos, %d elementos)'
                  % (js['info']['n_nodos'], js['info']['n_elementos']))
    ahora = persona.receptores(vista, modelo, informe)
    clave = lambda r: (r['elemento'], r['tipo'], r['nodo'], r['n1'], r['n2'], tuple(r['elementos_m']))  # noqa: E731
    iguales = (sorted(map(clave, ahora)) == sorted(map(clave, js['receptores']))
               and all(abs(a['flex'] - b['flex']) <= 1e-9 * max(a['flex'], 1e-30)
                       for a, b in zip(sorted(ahora, key=clave),
                                       sorted(js['receptores'], key=clave))))
    informe.check(iguales, 'los receptores y su flexibilidad son los del modelo de hoy '
                  '(si cambio una seccion, hay que volver a exportarla:  python sap.py exportar persona)')

    sol = persona.motor(modelo)
    if 'suma_igual_opensees' in bloques:
        claves = casos_de_las_pruebas(js['receptores'], args.pruebas)
        sin_cuantizar = casos_sin_cuantizar(js, sol, claves, informe)
        verificar(js, modelo, sol, informe, args.pruebas, sin_cuantizar)
    if 'registro' in bloques:
        cruzar_registro(args.registro, js, modelo, sol, informe)
    if 'suma_igual_opensees' in bloques:
        escalas(js, modelo, informe)
    print('  (%.0f s)' % (time.time() - t0))
    return informe.cerrar()


if __name__ == '__main__':
    sys.exit(main())
