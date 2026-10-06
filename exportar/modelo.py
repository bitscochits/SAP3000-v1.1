# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/modelo.py  -  EL EDIFICIO RESUELTO Y LO QUE DIBUJA EL VISOR
================================================================
 Dos salidas, las dos del edificio tal cual (los casos DEL MODELO, no
 los del laboratorio):

   salidas/casos_del_modelo.json   G, Q, EX y EY de edificio.json
                                   resueltos en OpenSees, cada uno con
                                   su equilibrio por grado de libertad.
                                   Es la prueba tangible de "OpenSees
                                   calculo": lo mismo que devuelve
                                   /analizar cuando Unity reanaliza.

   salidas/modelo.json             lo que dibuja el visor: la estructura
                                   + la vista (losas, terreno) + la G
                                   pegada en cada nodo (traslaciones Y
                                   giros, para curvar las barras) + los
                                   ejes locales de cada barra + el b x h
                                   de dibujo de las secciones que no lo
                                   traen. Unity lo edita en memoria y lo
                                   reenvia tal cual a /analizar.

 Correr:
   python sap.py calcular              -> salidas/casos_del_modelo.json
   python sap.py exportar modelo       -> salidas/modelo.json

 Nada de esto vuelve al edificio: los ejes sellados, los b/h deducidos
 y los desplazamientos son DERIVADOS. Congelarlos en edificio.json
 cambiaria lo que leen el equilibrio y el solver (el equilibrio usa
 localX si viene, redondeado a 6 decimales).
================================================================
"""
from __future__ import annotations

import json
import math
import sys

from calculo import edificio as _ed
from calculo import opensees
from calculo import rutas

CASO_PRECALCULADO = 'G'

NOTA = ('Los dos cuerpos del edificio en un solo modelo (entrada/edificio.json): '
        'el antiguo, tags 1xxxxx, y el LT2, tags 2xxxxx. La junta de dilatacion '
        'es LIBRE: ningun elemento la cruza, los dos cuerpos se resuelven '
        'independientes.')


# ============================================================
# LOS CASOS DEL MODELO
# ============================================================
def casos_del_modelo(solo_caso=None):
    """
    {'edificio', 'casos': [...]} con los casos de edificio.json resueltos.
    Cada caso es el diccionario que devuelve opensees.resolver_edificio:
    desplazamientos, reacciones, fuerzas_elementos (ejes locales),
    max_desplazamiento (mayor componente), equilibrio, nombre y
    descripcion.
    """
    resueltos, avisos = opensees.resolver_edificio(solo_caso=solo_caso)
    return {'edificio': _ed.NOMBRE, 'avisos': avisos, 'casos': resueltos}


def escribir_casos_del_modelo(datos):
    texto = json.dumps(datos, indent=1, ensure_ascii=False)
    return rutas.escribir_atomico(rutas.salida('casos_del_modelo'), texto.encode('utf-8'))


def imprimir_casos(datos):
    """Por caso: la mayor componente y el peor error de equilibrio, absoluto y relativo."""
    for a in datos.get('avisos', [])[:5]:
        print('  aviso: %s' % a)
    for res in datos['casos']:
        eq = res['equilibrio']
        # Es el maximo de |ux|, |uy| y |uz|, no solo el vertical: bajo un
        # caso sismico el que manda es horizontal.
        print('  caso %-4s  desplaz. max %9.4f mm'
              % (res['caso'], res['max_desplazamiento'] * 1000))
        if not eq['confiable']:
            print('           equilibrio: NO SE PUEDE AFIRMAR NADA -- %d '
                  'carga(s) distribuida(s) no se pudieron pasar a ejes '
                  'globales' % eq['cargas_sin_convertir'])
            continue
        # El error se informa tambien RELATIVO a la MAYOR de las tres
        # componentes: en un caso horizontal la vertical es cero por
        # construccion y dividir por ella inventaria un 100 %.
        escala = max(max(abs(eq['aplicada_kN'][i]),
                         abs(eq['reaccion_kN'][i])) for i in range(3))
        escala = max(escala, 1e-9)
        peor = max(range(3), key=lambda i: abs(eq['error_kN'][i]))
        comp = 'FxFyFz'[peor * 2:peor * 2 + 2]
        print('           equilibrio %s: aplicada %.3f  reaccion %.3f'
              % (comp, eq['aplicada_kN'][peor], eq['reaccion_kN'][peor]))
        print('           peor error %.1e kN sobre %.1f kN  (%.1e relativo)'
              % (abs(eq['error_kN'][peor]), escala,
                 abs(eq['error_kN'][peor]) / escala))


# ============================================================
# LO QUE DIBUJA EL VISOR
# ============================================================
def completar_b_h(modelo):
    r"""
    Rellena `b` y `h` en las secciones que no los traen: primero con el
    `espesor`/`largo` que declare la propia seccion y, si no los trae,
    deduciendolos de A, Iy e Iz. Devuelve (cuantas salieron del tamano
    declarado, cuantas se dedujeron de las inercias).

    PRIMERO EL DATO DEL CUERPO, DESPUES LA DEDUCCION. Deducir b y h de
    las inercias necesita saber CUAL de las dos es la grande, y eso
    cambia de cuerpo en cuerpo: en el LT2 la grande es Iz y en el cuerpo
    antiguo Iy. Con la regla del LT2 -- b = sqrt(12 Iy/A), h = sqrt(12 Iz/A)
    -- los muros del cuerpo antiguo salian CRUZADOS (b = 9.65 m, h = 0.30 m)
    sin que se viera: las dos lecturas dan el mismo A, Iy e Iz. Por eso
    se prefiere el `largo`/`espesor` que la seccion trae: b = espesor,
    h = largo. La deduccion queda para las que no declaran ninguno (hoy,
    solo 'ingenieria:brazo_rigido': b = h = 0.70).

    ES SOLO PARA DIBUJAR: no toca A, Iy, Iz ni J. El visor dibuja una
    barra con su seccion real solo si la seccion trae b y h; si no, la
    pinta como una barrita fina.
    """
    del_tamano, completadas = 0, 0
    for s in modelo.get('secciones', []):
        if s.get('b', 0) > 1e-3 and s.get('h', 0) > 1e-3:
            continue
        # El dato del cuerpo manda: b = espesor, h = largo.
        if s.get('largo', 0) > 1e-3 and s.get('espesor', 0) > 1e-3:
            s['b'] = round(float(s['espesor']), 4)
            s['h'] = round(float(s['largo']), 4)
            s['b_h_deducidos'] = True
            del_tamano += 1
            continue
        A, Iy, Iz = s.get('A', 0), s.get('Iy', 0), s.get('Iz', 0)
        if min(A, Iy, Iz) <= 0:
            continue
        b = math.sqrt(12.0 * Iy / A)
        h = math.sqrt(12.0 * Iz / A)
        if abs(b * h - A) > 1e-6 * max(A, 1.0):
            continue                       # no es un rectangulo lleno
        s['b'], s['h'] = round(b, 4), round(h, 4)
        s['b_h_deducidos'] = True
        completadas += 1
    return del_tamano, completadas


def construir(caso_G=None):
    """
    salidas/modelo.json en memoria. `caso_G` es el resultado del caso G
    del modelo (si no viene, se resuelve). Devuelve (modelo_visor, notas).
    """
    edificio = _ed.cargar()
    estructura = _ed.estructura(edificio)
    vista = _ed.vista(edificio)
    if caso_G is None:
        caso_G = opensees.resolver_edificio(estructura, solo_caso=CASO_PRECALCULADO)[0][0]

    completo = _ed.unir(estructura, {'areas_tributarias': vista['areas_tributarias']},
                        resultados=caso_G)
    completo = json.loads(json.dumps(completo))      # no tocar el edificio
    del_tamano, deducidas = completar_b_h(completo)
    _ed.sellar_ejes_locales(completo)
    completo['info'] = dict(completo.get('info', {}))
    completo['info'].update({
        'unidades': 'm, kN, kPa',
        'caso_precalculado': CASO_PRECALCULADO,
        'nota': NOTA,
        'cota_terreno': vista['cota_terreno'],
        'terrenos': vista['terrenos'],
    })
    eq = caso_G.get('equilibrio', {})
    uz = min((n.get('uz', 0.0) for n in completo['nodos']), default=0.0)
    completo['resumen'] = {
        'n_nodos': len(completo['nodos']),
        'n_elementos': len(completo['elementos']),
        'n_diafragmas': len(completo.get('diafragmas', [])),
        'caso': CASO_PRECALCULADO,
        'carga_total_kN': eq.get('aplicada_kN'),
        'reaccion_kN': eq.get('reaccion_kN'),
        'uz_max_mm': round(uz * 1000, 4),
    }
    return completo, {'del_tamano': del_tamano, 'deducidas': deducidas, 'uz_mm': uz * 1000}


def escribir(modelo_visor):
    texto = json.dumps(modelo_visor, indent=1, ensure_ascii=False)
    return rutas.escribir_atomico(rutas.salida('modelo'), texto.encode('utf-8'))


def main(argv=None):
    """sap.py exportar modelo"""
    modelo_visor, notas = construir()
    ruta = escribir(modelo_visor)
    print('  caso %s   %s' % (CASO_PRECALCULADO, _ed.resumen(modelo_visor)))
    print('  %d poligonos tributarios' % len(modelo_visor['areas_tributarias']))
    if notas['del_tamano']:
        print('  %d seccion(es) sin b/h: se tomaron de su propio espesor/largo '
              '(b = espesor, h = largo)' % notas['del_tamano'])
    if notas['deducidas']:
        print('  %d seccion(es) sin b/h ni tamano declarado: se dedujeron de A, Iy, Iz '
              'para poder dibujarlas' % notas['deducidas'])
    info = modelo_visor['info']
    print('  base del terreno %+.2f m' % info['cota_terreno'])
    for t in info['terrenos'][1:]:
        print('  terraza "%s" en %+.2f m (%d vertices)' % (t['nombre'], t['z'], len(t['vertices'])))
    print('  UZ maximo: %.3f mm' % notas['uz_mm'])
    print('  -> %s' % rutas.relativa(ruta))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
