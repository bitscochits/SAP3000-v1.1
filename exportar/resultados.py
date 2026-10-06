# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/resultados.py  -  LO QUE EL VISOR MUESTRA DE CADA CASO
================================================================
 Deja en salidas/resultados.json todo lo que el visor necesita para
 responder "que es este elemento y cuanto le llega": sus datos de
 OpenSees, sus esfuerzos internos a lo largo de la barra en cada caso
 y combinacion del laboratorio, y su punto de demanda sobre la curva
 P-M de su familia. Ya resuelto.

 Correr:
   python sap.py exportar resultados
   python sap.py exportar resultados --cs 0.20 --k 2
   python sap.py exportar resultados --combinacion 1.4G

 Acepta los parametros del laboratorio por linea de comandos y exporta
 lo que el laboratorio corre con ellos. Usa los casos del LABORATORIO
 (q de NCh1537), no los del modelo.

 ----------------------------------------------------------------
 QUE LLEVA
 ----------------------------------------------------------------
 info, casos,      los quince casos (4 base + las combinaciones de
 elementos,        entrada/laboratorio.json), los datos OpenSees de cada
 familias          barra y las curvas P-M de cada familia de fierro
 superposicion     E1..E3 de laboratorio.json#superposicion, ya
                   combinados y con su equilibrio: lo mismo que devuelve
                   POST /combinar, para que el visor los muestre sin
                   servidor (calculo/superposicion.caso_combinado)
 cargas_y_armadura las flechas de carga de G, Q, EX, EY y la combinacion
                   activa, las fuerzas sismicas por nivel, la deformada
                   de EX y EY y la jaula de la columna mas cargada,
                   para la capa "Cargas y enfierradura" del visor

 Todo sale de UNA base (esfuerzos.base): los casos se resuelven una
 vez y cada bloque los toma de ahi.

 ----------------------------------------------------------------
 LA REGLA DEL PROYECTO
 ----------------------------------------------------------------
 OpenSees calcula, Unity muestra. Aca se calculan los esfuerzos
 internos, se combinan los casos y se pone la demanda sobre la
 capacidad; el visor solo escala esos numeros para dibujarlos. Nada
 se reimplementa: los casos son los de laboratorio.armar_casos(), la
 seccion la de capacidad.desde_elemento(), la familia la de
 demanda.firma_de_seccion() y la demanda la de demanda.demanda().
 Los diagramas y su autoverificacion contra f_j: calculo/esfuerzos.py.

 ----------------------------------------------------------------
 TRAZABILIDAD
 ----------------------------------------------------------------
 Cada elemento lleva su 'tag_opensees' -- la linea element con los
 E, G e inercias EN EL ORDEN en que el servidor se los pasa a
 OpenSees -- y su 'objeto_unity', el nombre que le pone
 VisorEstructura.Redibujar. Asi se sigue un id desde el plano hasta
 el panel sin adivinar nada.

 Los nombres de las claves son el contrato con el C# del visor:
 JsonUtility ignora EN SILENCIO lo que no calza.
================================================================
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

from calculo import capacidad
from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import rutas
from calculo import superposicion as sp
from calculo.esfuerzos import (CONVENCION, COTA_REDONDEO, FRACCION_DIAGONAL,
                               N_ESTACIONES_CARGADA, bloque_caso, escala_deformada,
                               lista_de_combinaciones)

GENERADO_POR = 'exportar/resultados.py'


# ============================================================
def construir(argv=(), b=None):
    """
    Los resultados completos en memoria, sin escribir nada. Devuelve
    (resultados, contexto); el contexto trae lo intermedio para que las
    verificaciones, el Excel y la AR no tengan que rehacerlo.

    `b` es la base del laboratorio (esfuerzos.base) si quien llama ya la
    tiene armada; si no, se arma aca con los flags de `argv` (con `b`,
    `argv` no se usa). Si un estado E1..E3 no cierra con OpenSees lanza
    superposicion.CasoNoCierra.
    """
    b = es.base(argv) if b is None else b
    p, modelo, arm, datos, resultados = b['p'], b['modelo'], b['arm'], b['datos'], b['resultados']
    cargas_base, familias, familia_de = b['cargas_base'], b['familias'], b['familia_de']
    secciones, curvas, elementos = b['secciones'], b['curvas'], b['elementos']
    por_id, largos, nucleo_de = b['por_id'], b['largos'], b['nucleo_de']

    casos, cargas, combinaciones, cierre = [], {}, [], {}
    for nombre, tipo, texto, factores in lista_de_combinaciones(p):
        descripcion = arm['casos'][nombre].get('descripcion', '') if texto is None else texto
        bloque, w, peor = bloque_caso(nombre, tipo, descripcion, factores, resultados,
                                      elementos, cargas_base, familia_de, curvas, largos,
                                      nucleo_de)
        casos.append(bloque)
        cargas[nombre] = w
        cierre[nombre] = peor
        if tipo == 'combinacion':
            combinaciones.append((nombre, factores))

    # Las demo: la columna y el muro que muestra el visor, elegidos por regla y no a mano.
    axial_G = {int(x['id']): abs(float(x['f'][0]))
               for x in resultados['G']['fuerzas_elementos']}
    columnas = [eid for eid in secciones if por_id[eid].get('tipo') == 'columna']
    muros = [eid for eid in secciones if por_id[eid].get('tipo') == 'muro']
    columna_demo = max(sorted(columnas), key=lambda i: axial_G.get(i, 0.0), default=-1)
    muro_demo = max(sorted(muros), key=lambda i: secciones[i].h, default=-1)
    esc = escala_deformada(modelo, casos)   # la exageracion grafica (esfuerzos.py)

    anexo = {
        'info': {
            'edificio': _ed.NOMBRE,
            'descripcion': 'Resultados del laboratorio para el visor: esfuerzos internos '
                           'por caso y combinacion, datos OpenSees de cada elemento y '
                           'demanda-capacidad P-M',
            'unidades': 'm, kN, kPa; momentos kN*m; desplazamientos m y rad',
            'parametros': [l.strip() for l in lab.describir(p).split('\n')],
            'convencion': CONVENCION,
            'generado_por': GENERADO_POR,
            'caso_por_defecto': p['combinacion']['nombre'],
            'columna_demo': columna_demo,
            'muro_demo': muro_demo,
            'n_estaciones_cargada': N_ESTACIONES_CARGADA,
            'cota_redondeo_kN': COTA_REDONDEO,
            'escala_deformada': esc['escala'], '_escala_deformada_por_que': esc['por_que'],
        },
        'casos': casos,
        'elementos': elementos,
        'familias': familias,
    }

    # E1..E3 con la misma base: calculo/superposicion, igual que /combinar.
    t = time.time()
    anexo['superposicion'], cierre_sup = _superposicion(b)
    segundos_sup = time.time() - t
    anexo['cargas_y_armadura'] = _cargas_y_armadura(b)

    contexto = {
        'modelo': modelo, 'p': p, 'arm': arm, 'datos': datos, 'escala': esc,
        'resultados': resultados, 'combinaciones': combinaciones, 'cargas': cargas,
        'secciones': secciones, 'curvas': curvas, 'cierre': cierre,
        'cierre_superposicion': cierre_sup, 'segundos_superposicion': segundos_sup,
        'base': b,
    }
    return anexo, contexto


# ============================================================
# EL BLOQUE 'superposicion': E1..E3 PRECALCULADOS
# ============================================================
def _superposicion(b, estados=None):
    r"""
    {info, estados[{nombre, descripcion, lambdas, caso, equilibrio}]}. Cada
    caso lleva el nombre del estado ("E1"), no "LIBRE": asi Unity puede
    tener los tres registrados a la vez. Es el mismo calculo que POST
    /combinar (superposicion.caso_combinado sobre la base), hecho una vez
    para que el visor los muestre sin servidor.

    Devuelve (bloque, {estado: peor cierre}). Si un estado no cierra con
    OpenSees, superposicion.CasoNoCierra sube y no se escribe nada.
    """
    estados = estados or sp.cargar_estados()
    salida, cierre = [], {}
    for e in estados['estados']:
        lam = sp.lambdas_de(e['lambdas'])
        caso, peor = sp.caso_combinado(b, lam, nombre=e['nombre'])
        salida.append({
            'nombre': e['nombre'],
            'descripcion': e['descripcion'],
            'lambdas': {c: lam[c] for c in sp.CASOS},
            'caso': caso,
            'equilibrio': sp.equilibrio_combinado(b, lam),
        })
        cierre[e['nombre']] = peor
    bloque = {
        'info': {
            'edificio': _ed.NOMBRE,
            'descripcion': 'Estados de superposicion %s precalculados para el visor sin '
                           'servidor: el mismo calculo que POST /combinar '
                           '(superposicion.caso_combinado sobre los casos base)'
                           % '..'.join([salida[0]['nombre'], salida[-1]['nombre']])
                           if salida else 'sin estados',
            'generado_por': GENERADO_POR,
            'parametros': sp.parametros_de(b),
        },
        'estados': salida,
    }
    return bloque, cierre


# ============================================================
# EL BLOQUE 'cargas_y_armadura': FLECHAS, SISMO, DEFORMADAS, JAULA
# ============================================================
# Las cargas, la deformada sismica y la enfierradura, ya resueltas, para
# que el visor las dibuje sin calcular nada:
#
#   caja        el bounding box del modelo, para ubicar la vista de detalle
#   sismo       la fuerza por nivel, con el patron configurado
#   cargas      G, Q, EX, EY y la combinacion activa, como flechas. Las
#               distribuidas van reducidas a UNA flecha por barra con la
#               resultante w*L: dibujar la carga repartida daria miles de
#               objetos y no se leeria mejor
#   deformadas  los desplazamientos de EX y EY (los mismos de los casos
#               EX y EY de arriba), para "Sismo EX/EY" del visor
#   armadura    la jaula de la columna mas cargada -- barras, estribo
#               exterior y rombo, en coordenadas de seccion -- y la lista
#               de todas las columnas con fierro, para enfierrarlas todas
#
# Los nombres de las claves son el contrato con el C# que los lee:
# JsonUtility ignora lo que no conoce, pero lo que conoce tiene que
# llamarse igual.
def _bloque_caja(modelo):
    xs = [float(n['x']) for n in modelo['nodos']]
    ys = [float(n['y']) for n in modelo['nodos']]
    zs = [float(n['z']) for n in modelo['nodos']]
    return {'x_min': round(min(xs), 3), 'x_max': round(max(xs), 3),
            'y_min': round(min(ys), 3), 'y_max': round(max(ys), 3),
            'z_min': round(min(zs), 3), 'z_max': round(max(zs), 3)}


def _bloque_sismo(arm, nodos, p):
    """La fuerza lateral por nivel, con las coordenadas del maestro
    para que el visor no tenga que cruzar este bloque con el modelo."""
    niveles = []
    for (cota, m), W, f, F in zip(arm['niveles'], arm['pesos_sismicos'],
                                  arm['factores'], arm['fuerzas']):
        n = nodos[m]
        niveles.append({'nodo_maestro': m,
                        'x': round(float(n['x']), 4),
                        'y': round(float(n['y']), 4),
                        'z': round(float(n['z']), 4),
                        'peso_kN': round(W, 3),
                        'fraccion': round(f, 6),
                        'F_kN': round(F, 4)})
    return {'patron': lab.texto_patron(p),
            'Cs': p['coef_sismico'],
            'fraccion_Q_sismica': p['fraccion_Q_sismica'],
            'corte_basal_kN': round(arm['V'], 4),
            'fuerza_maxima_kN': round(max(arm['fuerzas']), 4),
            'niveles': niveles}


def _flechas(modelo, caso, factor=1.0):
    """
    Un caso de carga como lista de flechas: punto de aplicacion, vector
    y magnitud. Las nodales van donde estan; las distribuidas se
    reducen a la resultante w*L en el centro de la barra.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}
    out = []

    for c in caso.get('cargas_nodales', []):
        n = nodos[int(c['nodo'])]
        f = [factor * float(c.get(k, 0.0)) for k in ('fx', 'fy', 'fz')]
        if sum(abs(v) for v in f) > 1e-9:
            out.append(((float(n['x']), float(n['y']), float(n['z'])), f))

    for c in caso.get('cargas_distribuidas', []):
        e = elementos[int(c['elemento'])]
        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        L = _ed.largo(e, nodos)
        f = [factor * float(c.get(k, 0.0)) * L for k in ('wx', 'wy', 'wz')]
        if sum(abs(v) for v in f) > 1e-9:
            centro = tuple((float(a[k]) + float(b[k])) / 2.0 for k in ('x', 'y', 'z'))
            out.append((centro, f))
    return out


def _sumar_en_el_mismo_punto(flechas):
    """Dos flechas en el mismo punto son una sola: se suman los vectores."""
    por_punto = {}
    for punto, f in flechas:
        clave = tuple(round(v, 4) for v in punto)
        acum = por_punto.setdefault(clave, [0.0, 0.0, 0.0])
        for i in range(3):
            acum[i] += f[i]
    return [(p, f) for p, f in por_punto.items()
            if sum(abs(v) for v in f) > 1e-9]


def _caso_de_flechas(nombre, descripcion, flechas):
    filas = []
    for (x, y, z), (fx, fy, fz) in flechas:
        filas.append({'x': round(x, 5), 'y': round(y, 5), 'z': round(z, 5),
                      'fx': round(fx, 5), 'fy': round(fy, 5), 'fz': round(fz, 5),
                      'kN': round(math.sqrt(fx * fx + fy * fy + fz * fz), 5)})
    return {'caso': nombre,
            'descripcion': descripcion,
            'maxima_kN': round(max((f['kN'] for f in filas), default=0.0), 4),
            'total_kN': round(sum(f['kN'] for f in filas), 4),
            'flechas': filas}


def _bloque_cargas(modelo, arm, lambdas, p):
    """G, Q, EX, EY y la combinacion. La combinacion se arma aca, en
    Python, con los lambda de los parametros: no en C#."""
    que = {'G': 'peso propio y carga muerta',
           'Q': 'carga viva q_Q = %g kN/m2, %s' % (p['q_Q'], lab.origen_q(p)),
           'EX': 'sismo en X, %s' % lab.texto_patron(p),
           'EY': 'sismo en Y, %s' % lab.texto_patron(p)}
    salida = [_caso_de_flechas(n, que[n], _flechas(modelo, arm['casos'][n]))
              for n in lab.CASOS]

    comb = []
    for n in lab.CASOS:
        if abs(lambdas.get(n, 0.0)) > 1e-15:
            comb.extend(_flechas(modelo, arm['casos'][n], lambdas[n]))
    salida.append(_caso_de_flechas('COMBINACION', lab.como_texto(lambdas),
                                   _sumar_en_el_mismo_punto(comb)))
    return salida


def _bloque_deformadas(resultados):
    """Los desplazamientos de EX y EY, con los campos que espera
    VisorEstructura.AplicarDeformada()."""
    salida = []
    for caso in ('EX', 'EY'):
        ds = [{'id': int(d['id']),
               'ux': round(float(d.get('ux', 0.0)), 8),
               'uy': round(float(d.get('uy', 0.0)), 8),
               'uz': round(float(d.get('uz', 0.0)), 8),
               'rx': round(float(d.get('rx', 0.0)), 8),
               'ry': round(float(d.get('ry', 0.0)), 8),
               'rz': round(float(d.get('rz', 0.0)), 8)}
              for d in resultados[caso].get('desplazamientos', [])]
        maximo = max((math.hypot(d['ux'], d['uy']) for d in ds), default=0.0)
        salida.append({'caso': caso,
                       'max_horizontal_mm': round(maximo * 1000.0, 3),
                       'desplazamientos': ds})
    return salida


def _bloque_armadura(modelo, resultados):
    """
    La jaula de la columna mas cargada bajo G, leida con la MISMA funcion
    que usa la capacidad (capacidad.desde_elemento). Las coordenadas de
    barras y estribos son de seccion (y, z), con el origen en su centro;
    el visor las pone sobre el eje de la columna.
    """
    columnas = [e for e in modelo['elementos']
                if e.get('tipo') == 'columna' and e.get('enfierradura')]
    if not columnas:
        return None
    axial = {int(f['id']): abs(float(f['f'][0]))
             for f in resultados['G'].get('fuerzas_elementos', [])}
    elegida = max(columnas, key=lambda e: axial.get(int(e['id']), 0.0))
    sec = capacidad.desde_elemento(modelo, int(elegida['id']))

    nodos = {int(n['id']): n for n in modelo['nodos']}
    inferior, superior = sorted((nodos[int(elegida['n1'])], nodos[int(elegida['n2'])]),
                                key=lambda n: float(n['z']))

    # El estribo, medido a su eje: es lo que devuelve nucleo().
    hc, bc = sec.nucleo()
    y, z = hc / 2.0, bc / 2.0
    d_barra = 2.0 * math.sqrt(sec.barras[0][2] / math.pi) if sec.barras else 0.0
    fe = elegida['enfierradura']
    fuente = fe.get('fuente') or {}
    origen = (fe.get('longitudinal') or {}).get('origen', '')

    return {
        'columna_id': int(elegida['id']),
        'n1': int(inferior['id']),
        'n2': int(superior['id']),
        'axial_G_kN': round(axial.get(int(elegida['id']), 0.0), 3),
        'b': sec.b,
        'h': sec.h,
        'recubrimiento': sec.rec,
        'diametro_barra': round(d_barra, 5),
        'diametro_estribo': float(sec.estribo.get('diametro_mm', 0.0)) / 1000.0,
        'espaciamiento_estribo': float(sec.estribo.get('separacion_cm', 10.0)) / 100.0,
        'cuantia_pct': round(100.0 * sec.cuantia, 4),
        'as_total_cm2': round(sec.As * 1e4, 3),
        'procedencia': ('lamina %s; %s' % (fuente.get('lamina', '?'), origen)).strip('; '),
        'barras': [{'y': round(by, 5), 'z': round(bz, 5)} for by, bz, _a in sec.barras],
        'estribo_exterior': [{'y': py, 'z': pz} for py, pz in
                             ((y, z), (y, -z), (-y, -z), (-y, z))],
        'estribo_rombo': [{'y': py, 'z': pz} for py, pz in
                          ((y, 0.0), (0.0, -z), (-y, 0.0), (0.0, z))],
        'nodo_inferior': {k: float(inferior[k]) for k in ('x', 'y', 'z')},
        'nodo_superior': {k: float(superior[k]) for k in ('x', 'y', 'z')},
        # Todas las columnas con fierro, por id de nodo: asi el visor
        # puede moverlas con la deformada sin recalcular nada.
        'columnas': [{'id': int(e['id']), 'n1': int(e['n1']), 'n2': int(e['n2']),
                      'axial_G_kN': round(axial.get(int(e['id']), 0.0), 2)}
                     for e in sorted(columnas, key=lambda c: int(c['id']))],
    }


def _cargas_y_armadura(b):
    """El bloque entero, con los casos ya resueltos de la base: no se resuelve otra vez."""
    p, modelo, arm, resultados = b['p'], b['modelo'], b['arm'], b['resultados']
    nodos = {int(n['id']): n for n in modelo['nodos']}
    return {
        'info': {
            'descripcion': 'Cargas y armadura para el visor: cargas, deformada sismica '
                           'y armadura',
            'edificio': _ed.NOMBRE,
            'unidades': 'm, kN',
            # Con replace('  ', ' ') y no con strip(): es la forma que este
            # bloque siempre llevo, distinta de info.parametros de arriba.
            'parametros': lab.describir(p).replace('  ', ' ').split('\n'),
            'nota': 'Calculado por exportar/resultados.py. Unity solo dibuja; '
                    'el calculo vive en Python.',
        },
        'caja': _bloque_caja(modelo),
        'sismo': _bloque_sismo(arm, nodos, p),
        'cargas': _bloque_cargas(modelo, arm, lab.factores(p['combinacion']), p),
        'deformadas': _bloque_deformadas(resultados),
        'armadura': _bloque_armadura(modelo, resultados),
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    t0 = time.time()
    try:
        anexo, ctx = construir(argv)
    except sp.CasoNoCierra as e:
        print('  NO SE ESCRIBE NADA: %s' % e)
        return 1
    t_calculo = time.time() - t0
    info = anexo['info']

    print('=' * 72)
    print('  RESULTADOS PARA EL VISOR   %s' % _ed.NOMBRE.upper())
    print('=' * 72)
    print(lab.describir(ctx['p']))
    print()
    n_base = sum(1 for c in anexo['casos'] if c['tipo'] == 'caso')
    print('  casos      %d (%d base + %d combinaciones): %s'
          % (len(anexo['casos']), n_base, len(anexo['casos']) - n_base,
             ', '.join(c['nombre'] for c in anexo['casos'])))
    print('  elementos  %d, %d con carga repartida en G o Q'
          % (len(anexo['elementos']), sum(1 for e in anexo['elementos'] if e['cargada'])))
    print('  familias   %d curvas P-M para %d elementos con enfierradura'
          % (len(anexo['familias']), len(ctx['secciones'])))

    defecto = next(c for c in anexo['casos'] if c['nombre'] == info['caso_por_defecto'])
    demandas = {d['id']: d for d in defecto['demandas']}
    for etiqueta, eid in (('columna', info['columna_demo']), ('muro', info['muro_demo'])):
        d = demandas.get(eid)
        if d is None:
            print('  %-8s   (ninguna con enfierradura)' % etiqueta)
            continue
        fam = anexo['familias'][d['familia']]
        print('  %-8s   %d  familia %d (%s), en %s: P = %.1f kN, M = %.1f kN m, '
              'Mn = %.1f, u = %.3f %s'
              % (etiqueta + '_demo', eid, d['familia'], fam['seccion'],
                 defecto['nombre'], d['P'], d['M'], d['Mn'], d['u'],
                 'ok' if d['pasa'] else 'NO PASA'))

    print()
    print('  autoverificacion: esfuerzo(L) contra f_j de OpenSees, error / cota')
    print('  (cota = 5e-5 (2 + L) en My, Mz y 5e-5 * 2 en N, V, T, por sum|lambda|,')
    print('   + 4 eps por el tamano de los terminos: la coma flotante)')
    malos = []
    for c in anexo['casos']:
        cociente, eid, comp = ctx['cierre'][c['nombre']]
        print('    %-18s peor %.3f   elemento %5d, %s   %s'
              % (c['nombre'], cociente, eid, comp, 'ok' if cociente <= 1.0 else '<-- NO CIERRA'))
        if cociente > 1.0:
            malos.append(c['nombre'])
    if malos:
        print()
        print('  NO SE ESCRIBE NADA: %s no cierran con OpenSees' % ', '.join(malos))
        return 1

    _imprimir_cargas_y_armadura(anexo['cargas_y_armadura'])
    _imprimir_superposicion(anexo['superposicion'], ctx)

    salida = escribir(anexo)
    print()
    print('  %.2f MB, calculado en %.1f s'
          % (os.path.getsize(salida) / 1048576.0, t_calculo))
    print('  -> %s' % rutas.relativa(salida))

    esc = ctx['escala']
    print('  escala grafica recomendada x%g: %.2f mm -> %.2f m (%g %% de la diagonal '
          '%.2f m, caso %s)'
          % (esc['escala'], esc['mayor_mm'], esc['escala'] * esc['mayor_mm'] / 1000.0,
             100.0 * FRACCION_DIAGONAL, esc['diagonal_m'], esc['caso']))
    return 0


def _imprimir_cargas_y_armadura(bloque):
    s, a = bloque['sismo'], bloque['armadura']
    print()
    print('  cargas y armadura (bloque cargas_y_armadura)')
    print('  sismo      %s, corte basal %.2f kN en %d niveles'
          % (s['patron'], s['corte_basal_kN'], len(s['niveles'])))
    for n in s['niveles']:
        print('             z = %+6.2f   %6.2f %%   F = %9.2f kN'
              % (n['z'], 100 * n['fraccion'], n['F_kN']))
    print('  cargas     ' + '   '.join('%s: %d' % (c['caso'], len(c['flechas']))
                                     for c in bloque['cargas']))
    for d in bloque['deformadas']:
        print('  deformada  %s  %d nodos, maximo %.2f mm'
              % (d['caso'], len(d['desplazamientos']), d['max_horizontal_mm']))
    if a:
        print('  armadura   columna %d (%.0f kN en G): %d barras D%.0f, '
              'cuantia %.2f %%; %d columnas con fierro'
              % (a['columna_id'], a['axial_G_kN'], len(a['barras']),
                 a['diametro_barra'] * 1000, a['cuantia_pct'], len(a['columnas'])))
    else:
        print('  armadura   (ninguna columna trae enfierradura)')


def _imprimir_superposicion(bloque, ctx):
    b = ctx['base']
    estados = bloque['estados']
    print()
    print('  superposicion (bloque superposicion): %s sobre la misma base '
          '(%d nodos, %d elementos, %d con fierro)'
          % ('..'.join([estados[0]['nombre'], estados[-1]['nombre']]) if estados else 'sin estados',
             len(b['modelo']['nodos']), len(b['largos']),
             sum(1 for f in b['familia_de'].values() if f >= 0)))
    for e in estados:
        sp.imprimir_caso(e['caso'], ctx['cierre_superposicion'][e['nombre']], e['equilibrio'])
    print('  (combinado en %.3f s, sin volver a OpenSees)' % ctx['segundos_superposicion'])


def escribir(anexo):
    """salidas/resultados.json, compacto (pesa ~10 MB) y de una vez."""
    texto = json.dumps(anexo, separators=(',', ':'), ensure_ascii=False)
    return rutas.escribir_atomico(rutas.salida('resultados'), texto.encode('utf-8'))


if __name__ == '__main__':
    sys.exit(main())
