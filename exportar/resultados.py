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
import os
import sys
import time

from calculo import capacidad
from calculo import demanda as dc
from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import rutas
from calculo.esfuerzos import (CASOS_BASE, CONVENCION, COTA_REDONDEO, DECIMALES_FUERZA,
                               DECIMALES_ESTACION, FRACCION_DIAGONAL, N_ESTACIONES_CARGADA,
                               bloque_caso, cargas_por_elemento, escala_deformada,
                               lista_de_combinaciones, restricciones_como_el_servidor,
                               rigidez_como_el_servidor)

ORIGEN_RESULTADOS = ('laboratorio.resolver() en memoria, con los parametros de '
                     'entrada/laboratorio.json')


def _texto_vecxz(v):
    return '(%s)' % ','.join('%g' % c for c in v)


def _texto_restr(r):
    return '[%s]' % ' '.join(str(v) for v in r)


# ============================================================
# FAMILIAS P-M
# ============================================================
def _fuente(fe):
    fu = fe.get('fuente') or {}
    partes = []
    if fu.get('lamina'):
        partes.append('lamina %s' % fu['lamina'])
    if fu.get('elevacion'):
        partes.append(str(fu['elevacion']))
    if fu.get('eje'):
        partes.append('eje %s' % fu['eje'])
    return ', '.join(partes) or '(sin fuente declarada)'


def _refuerzo(e, sec):
    fe = e.get('enfierradura') or {}
    if fe.get('tipo') == 'muro':
        mv = (fe.get('malla_vertical') or {}).get('texto') or '-'
        return ('malla vertical %s en %d capas + %d barras de borde (%d barras)'
                % (mv, int(fe.get('capas', 2)), len(fe.get('barras_de_borde') or []),
                   len(sec.barras)))
    lon = fe.get('longitudinal') or {}
    return ('%d D%g (%s por cara), estribo %s'
            % (len(sec.barras), float(lon.get('diametro_mm', 0.0)),
               lon.get('por_cara', '?'), (sec.estribo or {}).get('texto', '-')))


def _clave_legible(firma):
    seccion, b, h, n, As, estribo, malla = firma
    return ('%s | %.2f x %.2f m | %d barras | As = %.2f cm2 | estribo %s | malla %s'
            % (seccion, b, h, n, As * 1e4, estribo or '-', malla or '-'))


def bloque_familias(modelo):
    """
    Una curva por familia de enfierradura, en orden de aparicion por id.
    Agrupa con demanda.firma_de_seccion, la misma clave que usa la
    revision (--todas): dos elementos con la misma firma comparten curva.
    """
    con_fierro = sorted((e for e in modelo['elementos'] if e.get('enfierradura')),
                        key=lambda e: int(e['id']))
    familias, indice_de, familia_de, secciones, curvas = [], {}, {}, {}, {}
    for e in con_fierro:
        eid = int(e['id'])
        sec = capacidad.desde_elemento(modelo, eid)
        secciones[eid] = sec
        firma = dc.firma_de_seccion(e, sec)
        if firma not in indice_de:
            i = len(familias)
            indice_de[firma] = i
            puntos = capacidad.interaccion(sec)
            curvas[i] = puntos
            familias.append({
                'indice': i,
                'clave': _clave_legible(firma),
                'tipo': e.get('tipo', ''),
                'seccion': e.get('seccion', ''),
                'b': round(sec.b, 4),
                'h': round(sec.h, 4),
                'As_cm2': round(sec.As * 1e4, 4),
                'cuantia_pct': round(100.0 * sec.cuantia, 4),
                'refuerzo': _refuerzo(e, sec),
                'fuente': _fuente(e['enfierradura']),
                'P': [round(float(p['P_kN']), DECIMALES_FUERZA) for p in puntos],
                'Mn': [round(float(p['M_kNm']), DECIMALES_FUERZA) for p in puntos],
                'Mmax': [round(float(p.get('M_max_kNm', 0.0)), DECIMALES_FUERZA)
                         for p in puntos],
                'de': [str(p.get('de', '')) for p in puntos],
                'elementos': [],
            })
        familia_de[eid] = indice_de[firma]
        familias[indice_de[firma]]['elementos'].append(eid)
    return familias, familia_de, secciones, curvas


# ============================================================
# ELEMENTOS
# ============================================================
def bloque_elementos(modelo, cargas, familia_de):
    """Lo fijo de cada elemento: ids, seccion, material, ejes, apoyos."""
    nodos = {int(n['id']): (float(n['x']), float(n['y']), float(n['z']))
             for n in modelo['nodos']}
    secciones = {s['nombre']: s for s in modelo['secciones']}
    material = modelo.get('material', {})
    restr = restricciones_como_el_servidor(modelo)
    de_nodo = _ed.indice_de_diafragma(modelo)
    maestros = [int(d['nodo_maestro']) for d in modelo.get('diafragmas', [])]

    def maestro_de(n):
        i = de_nodo.get(n)
        return maestros[i] if i is not None else -1

    salida = []
    for e in sorted(modelo['elementos'], key=lambda e: int(e['id'])):
        eid, n1, n2 = int(e['id']), int(e['n1']), int(e['n2'])
        tipo = e.get('tipo', '')
        s = secciones[e['seccion']]
        k = rigidez_como_el_servidor(e, s, nodos[n1], nodos[n2], material)

        if k['propio']:
            texto_mat = 'E y G propios de la seccion'
            if s.get('E_del_cuerpo'):
                texto_mat += ' (cuerpo %s)' % s['E_del_cuerpo']
        else:
            texto_mat = "hormigon f'c %g MPa, Ec = 4700 sqrt(f'c)" % k['fpc_MPa']

        es_brazo = tipo in ('brazo', 'brazo_rigido')
        r1, r2 = restr.get(n1, [0] * 6), restr.get(n2, [0] * 6)
        d1, d2 = maestro_de(n1), maestro_de(n2)
        condiciones = []
        for nombre, n, r, d in (('n1', n1, r1, d1), ('n2', n2, r2, d2)):
            if any(r):
                condiciones.append('%s %d: %s %s' % (
                    nombre, n, 'empotrado' if all(r) else 'apoyo', _texto_restr(r)))
            if d >= 0:
                condiciones.append('%s %d: diafragma rigido, maestro %d' % (nombre, n, d))
        if es_brazo:
            condiciones.append('brazo rigido: barra de rigidez x100 hasta la cara del muro')
        if not condiciones:
            condiciones.append('nodos libres: sin apoyo ni diafragma')

        cargada = any(any(v != 0.0 for v in cargas[c].get(eid, (0.0, 0.0, 0.0)))
                      for c in ('G', 'Q'))

        salida.append({
            'id': eid, 'n1': n1, 'n2': n2,
            'tipo': tipo, 'seccion': e['seccion'],
            # El momento que se compara con la curva: el de inercia mayor.
            'momento_en_el_plano': (dc.momento_en_el_plano(s['Iy'], s['Iz'])
                                    if tipo == 'muro' else ''),
            'L': round(k['L'], DECIMALES_ESTACION),
            'objeto_unity': 'Elem_%d_%s' % (eid, tipo),
            'tag_opensees': ('element elasticBeamColumn %d %d %d A=%.4f E=%.4e '
                             'G=%.4e J=%.3e Iy=%.3e Iz=%.3e vecxz=%s'
                             % (eid, n1, n2, float(s['A']), k['E'], k['G'],
                                float(s['J']), k['Iy_pasa'], k['Iz_pasa'],
                                _texto_vecxz(k['vecxz']))),
            'material': texto_mat,
            'fpc_MPa': k['fpc_MPa'],
            'E_kPa': round(k['E'], 4), 'G_kPa': round(k['G'], 4),
            'poisson': round(k['poisson'], 6),
            'gamma': float(s.get('gamma', material.get('gamma', 25.0))),
            'A': float(s['A']), 'Iy': float(s['Iy']), 'Iz': float(s['Iz']),
            'J': float(s['J']),
            # Los muros del cuerpo antiguo declaran largo/espesor en vez de h/b.
            'b': float(s.get('b') or s.get('espesor') or 0.0),
            'h': float(s.get('h') or s.get('largo') or 0.0),
            'vecxz': list(k['vecxz']),
            'restr_n1': r1, 'restr_n2': r2,
            'diafragma_n1': d1, 'diafragma_n2': d2,
            'es_brazo_rigido': es_brazo,
            'condiciones': '; '.join(condiciones),
            'cargada': cargada,
            'familia': familia_de.get(eid, -1),
            'resultados': ORIGEN_RESULTADOS,
        })
    return salida


# ============================================================
def construir(argv=()):
    """
    Los resultados completos en memoria, sin escribir nada. Devuelve
    (resultados, contexto); el contexto trae lo intermedio para que las
    verificaciones, el Excel y la AR no tengan que rehacerlo.
    """
    p = lab.cargar(list(argv))
    modelo = _ed.estructura()
    arm = lab.armar_casos(modelo, p)
    datos, resultados = lab.resolver(modelo, arm['casos'])

    cargas_base = {c: cargas_por_elemento(arm['casos'][c]) for c in CASOS_BASE}
    familias, familia_de, secciones, curvas = bloque_familias(modelo)
    elementos = bloque_elementos(modelo, cargas_base, familia_de)

    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    largos = {eid: _ed.largo(e, nodos) for eid, e in por_id.items()}

    # Los grupos de nucleo y el As*fy de cada uno se calculan UNA vez
    # (cada As*fy arma una seccion de fibras); despues cada caso solo
    # suma los P de las patas. Ver demanda.grupos_de_nucleo.
    _cache = {}
    nucleo_de = {}
    for eid, patas in dc.grupos_de_nucleo(modelo).items():
        asfy, sin_fierro = dc.asfy_de(modelo, patas, _cache)
        nucleo_de[eid] = {'patas': patas, 'Asfy_kN': asfy,
                          'sin_fierro': len(sin_fierro)}

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
            'generado_por': 'exportar/resultados.py',
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
    contexto = {
        'modelo': modelo, 'p': p, 'arm': arm, 'datos': datos, 'escala': esc,
        'resultados': resultados, 'combinaciones': combinaciones, 'cargas': cargas,
        'secciones': secciones, 'curvas': curvas, 'cierre': cierre,
    }
    return anexo, contexto


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    t0 = time.time()
    anexo, ctx = construir(argv)
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




def escribir(anexo):
    """salidas/resultados.json, compacto (pesa ~8 MB) y de una vez."""
    texto = json.dumps(anexo, separators=(',', ':'), ensure_ascii=False)
    return rutas.escribir_atomico(rutas.salida('resultados'), texto.encode('utf-8'))


if __name__ == '__main__':
    sys.exit(main())
