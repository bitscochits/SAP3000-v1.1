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

from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import rutas
from calculo.esfuerzos import (CONVENCION, COTA_REDONDEO, FRACCION_DIAGONAL,
                               N_ESTACIONES_CARGADA, bloque_caso, escala_deformada,
                               lista_de_combinaciones)

# ============================================================
def construir(argv=()):
    """
    Los resultados completos en memoria, sin escribir nada. Devuelve
    (resultados, contexto); el contexto trae lo intermedio para que las
    verificaciones, el Excel y la AR no tengan que rehacerlo.
    """
    b = es.base(argv)
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
