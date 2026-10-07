# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/laboratorio.py  -  LO QUE EL LABORATORIO LE PIDE AL EDIFICIO
================================================================
 Dos cosas, en este orden:

   1. LOS PARAMETROS que define el profesor (entrada/laboratorio.json,
      bloque "parametros"): la sobrecarga q_Q de NCh1537, el
      coeficiente sismico, cuanta Q entra al peso sismico, el patron
      en altura y las combinaciones. Cualquiera se sobreescribe por
      linea de comandos (--q, --uso, --cs, --fq, --patron, --k,
      --fracciones, --comb, --combinacion) sin tocar el archivo.

   2. LOS CASOS DEL LABORATORIO, armados EN MEMORIA con esos
      parametros sobre la estructura del edificio:

        G    el del edificio, tal cual
        Q    cada elemento con losa a q_Q * A_i, por la misma via
             (repartida o puntual) que el caso Q del edificio
        EX   V = Cs * W, con W = G + f * Q por diafragma, repartido
        EY   en altura segun el patron y aplicado en los maestros

 OJO: hay DOS fuentes de casos de carga y las dos se conservan. Los
 "casos del modelo" (casos_de_carga de edificio.json: Q 2.0 kN/m2 en
 un cuerpo y del plano en el otro, sismo 0.10 por cuerpo) los resuelve
 /analizar cuando Unity reanaliza. Los "casos del laboratorio" (estos)
 alimentan los resultados, la superposicion, el Excel y la AR. Solo G
 coincide: el corte basal del modelo es 10021.35 kN y el del
 laboratorio 10907.08 kN, y no es un error.

 ----------------------------------------------------------------
 COMO SE CONSTRUYE Q
 ----------------------------------------------------------------
 El caso Q del edificio dice DONDE va cada carga: repartida sobre una
 viga, o puntual en la cabeza del muro que recibe la losa. Eso se
 conserva; lo que se reemplaza es la intensidad: cada elemento pasa a
 q_Q * A_i, con el A_i que trae sellado. No se escala el caso entero
 por un factor: el plano del LT2 trae dos intensidades (500 kgf/m2 en
 los pisos y 300 en el techo) y un factor unico dejaria cada uno a una
 presion distinta de q_Q.

 ----------------------------------------------------------------
 EL PESO SISMICO SE REPARTE POR DIAFRAGMA, NO POR COTA
 ----------------------------------------------------------------
 El edificio tiene DOS diafragmas por nivel (uno por cuerpo), a la
 misma altura. Buscar el nivel de una carga por su cota mas cercana
 metia todo el peso en el primero de cada par y dejaba al otro cuerpo
 sin sismo. Un diafragma ya identifica cuerpo y nivel, asi que el
 reparto es por pertenencia.
================================================================
"""
from __future__ import annotations

import copy
import io
import json
import math
import os

from calculo import edificio as _ed
from calculo import opensees
from calculo import rutas

CASOS_BASE = ('G', 'Q', 'EX', 'EY')
CASOS = CASOS_BASE

# Si el archivo no esta, se cae a estos valores para no dejar de correr.
POR_DEFECTO = {
    'q_Q': 3.0,                  # NCh1537 Of.2009 Tabla 4, salas de clases
    'uso': 'salas_de_clases',
    'usos': {},                  # la Tabla 4, cuando el archivo esta
    'norma_q': 'NCh1537 Of.2009, Tabla 4',
    'coef_sismico': 0.10,
    'fraccion_Q_sismica': 0.50,
    'patron': 'potencia',
    'k_patron': 1.0,
    'fracciones_patron': [],
    'combinacion': {'nombre': 'S3', 'G': 1.0, 'Q': 0.5, 'EX': 1.0, 'EY': 0.0},
    'combinaciones': [],
}


# ============================================================
# EL ARCHIVO
# ============================================================
def leer_archivo(ruta: str = None) -> dict:
    """entrada/laboratorio.json entero (cada llamada, un objeto nuevo)."""
    with io.open(ruta or rutas.LABORATORIO, encoding='utf-8') as f:
        return json.load(f)


def bloque(nombre: str, ruta: str = None):
    """Un bloque de laboratorio.json: 'parametros', 'superposicion', 'carga_movil', 'ar'..."""
    return leer_archivo(ruta)[nombre]


# ============================================================
# 1. LOS PARAMETROS
# ============================================================
def _leer(ruta=None):
    ruta = ruta or rutas.LABORATORIO
    if not os.path.isfile(ruta):
        return dict(POR_DEFECTO)
    d = leer_archivo(ruta).get('parametros', {})
    combos = [c for c in d.get('combinaciones', []) if 'nombre' in c]
    nombre = d.get('combinacion_por_defecto')
    elegida = next((c for c in combos if c['nombre'] == nombre),
                   combos[0] if combos else POR_DEFECTO['combinacion'])
    cv = d.get('carga_viva', {})
    norma = cv.get('nch1537', {})
    return {
        'q_Q': float(cv.get('q_kNm2', POR_DEFECTO['q_Q'])),
        'uso': str(cv.get('uso', POR_DEFECTO['uso'])),
        'usos': {k: float(v)
                 for k, v in norma.get('valores_kNm2', {}).items()},
        'norma_q': str(norma.get('norma', POR_DEFECTO['norma_q'])),
        'coef_sismico': float(d.get('sismo', {}).get(
            'coeficiente', POR_DEFECTO['coef_sismico'])),
        'fraccion_Q_sismica': float(d.get('sismo', {}).get(
            'fraccion_Q', POR_DEFECTO['fraccion_Q_sismica'])),
        'patron': str(d.get('sismo', {}).get(
            'patron', POR_DEFECTO['patron'])),
        'k_patron': float(d.get('sismo', {}).get(
            'k_patron', POR_DEFECTO['k_patron'])),
        'fracciones_patron': [
            float(x) for x in d.get('sismo', {}).get(
                'fracciones_patron', POR_DEFECTO['fracciones_patron'])],
        'combinacion': dict(elegida),
        'combinaciones': combos,
    }


def validar(p):
    """
    Rechaza lo que no tiene sentido fisico. Vale la pena aunque los valores
    vengan de un archivo: un q negativo o una fraccion mayor que uno no dan
    error en ninguna parte, dan resultados.
    """
    if p['q_Q'] < 0:
        raise ValueError('q_Q no puede ser negativo')
    if p['uso'] != 'dictado' and p['usos']:
        if p['uso'] not in p['usos']:
            raise ValueError("uso %r no esta en la tabla de NCh1537 del "
                             "JSON. Hay: %s"
                             % (p['uso'], ', '.join(sorted(p['usos']))))
        if abs(p['q_Q'] - p['usos'][p['uso']]) > 1e-9:
            raise ValueError(
                'q_kNm2 = %g no es el valor de NCh1537 para %r (%g kN/m2): '
                'cambie el uso, o declare uso "dictado"'
                % (p['q_Q'], p['uso'], p['usos'][p['uso']]))
    if p['coef_sismico'] < 0:
        raise ValueError('el coeficiente sismico no puede ser negativo')
    if not 0.0 <= p['fraccion_Q_sismica'] <= 1.0:
        raise ValueError('la fraccion de Q para el peso sismico va entre '
                         '0 y 1')
    if p['patron'] not in ('potencia', 'nch433', 'manual'):
        raise ValueError("patron %r desconocido: use 'potencia', 'nch433' "
                         "o 'manual'" % p['patron'])
    if p['patron'] == 'potencia' and p['k_patron'] < 0:
        raise ValueError('k_patron no puede ser negativo')
    if p['patron'] == 'manual':
        if not p['fracciones_patron']:
            raise ValueError("patron 'manual' exige fracciones_patron")
        if any(float(f) < 0 for f in p['fracciones_patron']):
            raise ValueError('fracciones_patron no admite negativos')
    return p


def cargar(argv=None, ruta=None):
    """
    Los parametros, con lo que venga por linea de comandos encima.

        --q  <kN/m2>              sobrecarga de uso, un numero cualquiera
        --uso <nombre>            una fila de la Tabla 4 de NCh1537
        --cs <fraccion>           coeficiente sismico
        --fq <fraccion>           cuanta Q entra al peso sismico
        --comb <G> <Q> <EX> <EY>  factores de la combinacion
        --patron <potencia|nch433|manual>  reparto del corte en altura
        --k <exponente>              k de "potencia"
        --fracciones <f1> <f2> ...   reparto manual, se normaliza solo
        --combinacion <nombre>    una de las declaradas

    Los argumentos que no reconoce los ignora, para poder convivir con los
    de cada comando.
    """
    p = _leer(ruta)
    a = list(argv or [])

    def numero(bandera):
        if bandera in a:
            i = a.index(bandera)
            try:
                return float(a[i + 1])
            except (IndexError, ValueError):
                raise SystemExit('%s necesita un numero' % bandera)
        return None

    if '--uso' in a:
        i = a.index('--uso')
        nombre = a[i + 1] if i + 1 < len(a) else ''
        if nombre not in p['usos']:
            raise SystemExit('no hay uso %r en la tabla de NCh1537. Hay: %s'
                             % (nombre, ', '.join(sorted(p['usos']))))
        p['uso'] = nombre
        p['q_Q'] = p['usos'][nombre]
    v = numero('--q')
    if v is not None:
        p['q_Q'] = v
        p['uso'] = 'dictado'
    v = numero('--cs')
    if v is not None:
        p['coef_sismico'] = v
    v = numero('--fq')
    if v is not None:
        p['fraccion_Q_sismica'] = v
    v = numero('--k')
    if v is not None:
        p['k_patron'] = v

    if '--patron' in a:
        i = a.index('--patron')
        p['patron'] = a[i + 1] if i + 1 < len(a) else ''
    if '--fracciones' in a:
        i = a.index('--fracciones')
        crudas = []
        for x in a[i + 1:]:
            try:
                crudas.append(float(x))
            except ValueError:
                break
        if not crudas:
            raise SystemExit('--fracciones necesita al menos un numero')
        p['fracciones_patron'] = crudas
        p['patron'] = 'manual'

    if '--combinacion' in a:
        i = a.index('--combinacion')
        nombre = a[i + 1] if i + 1 < len(a) else ''
        elegida = next((c for c in p['combinaciones']
                        if c['nombre'] == nombre), None)
        if elegida is None:
            raise SystemExit(
                'no existe la combinacion %r. Declaradas: %s'
                % (nombre, ', '.join(c['nombre'] for c in p['combinaciones'])))
        p['combinacion'] = dict(elegida)

    if '--comb' in a:
        i = a.index('--comb')
        try:
            f = [float(x) for x in a[i + 1:i + 5]]
        except (IndexError, ValueError):
            raise SystemExit('--comb necesita cuatro numeros: G Q EX EY')
        if len(f) < 4:
            raise SystemExit('--comb necesita cuatro numeros: G Q EX EY')
        p['combinacion'] = dict(zip(CASOS, f))
        p['combinacion']['nombre'] = 'a mano'

    return validar(p)


def factores(combinacion):
    """Solo los cuatro factores, sin el nombre ni los comentarios."""
    return {c: float(combinacion.get(c, 0.0)) for c in CASOS}


def como_texto(combinacion):
    """'1.20 G + 1.60 Q + 1.00 EX' -- sin los terminos en cero."""
    partes = ['%.2f %s' % (v, c)
              for c, v in factores(combinacion).items() if abs(v) > 1e-12]
    return ' + '.join(partes) if partes else '(nula)'


def origen_q(p):
    """'NCh1537 Of.2009, Tabla 4: salas de clases'  o  'dictado, --q'."""
    if p['uso'] == 'dictado':
        return 'dictado, --q'
    return '%s: %s' % (p['norma_q'], p['uso'].replace('_', ' '))


def texto_patron(p):
    """'potencia k = 1 (triangular invertido)' o 'manual: 5, 10, ...'."""
    if p['patron'] == 'manual':
        return 'manual: ' + ', '.join('%g' % f for f in p['fracciones_patron'])
    if p['patron'] == 'nch433':
        return 'NCh433 6.2.6'
    k = p['k_patron']
    apodo = {0.0: ' (uniforme)', 1.0: ' (triangular invertido)'}.get(float(k), '')
    return 'potencia k = %g%s' % (k, apodo)


def describir(p):
    """
    Las cinco lineas que identifican los parametros. Es la HUELLA que viaja
    en info.parametros de cada salida y con la que Unity reconoce que una
    respuesta del servidor es de los mismos parametros: su formato no se toca.
    """
    L = ['q_Q                 = %.4f kN/m2   (%s)' % (p['q_Q'], origen_q(p)),
         'coeficiente sismico = %.4f' % p['coef_sismico'],
         'fraccion de Q       = %.2f' % p['fraccion_Q_sismica'],
         'patron en altura    = %s' % texto_patron(p),
         'combinacion %-8s= %s' % ('(%s)' % p['combinacion'].get('nombre', ''),
                                   como_texto(p['combinacion']))]
    return '\n'.join('  ' + x for x in L)


# ============================================================
# 2. LOS CASOS DEL LABORATORIO
# ============================================================
def caso_del_modelo(modelo, nombre):
    c = next((c for c in modelo.get('casos_de_carga', [])
              if c.get('nombre') == nombre), None)
    if c is None:
        raise SystemExit('el modelo no trae el caso %s' % nombre)
    return c


def peso_vertical_por_nivel(modelo, caso, de_nodo=None):
    """
    La carga vertical de un caso, sumada como peso positivo, por diafragma.
    Devuelve una lista alineada con edificio.niveles(modelo). Se reparte por
    PERTENENCIA al diafragma; la cota mas cercana queda solo de respaldo,
    para nodos sueltos que no cuelgan de ninguno.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}
    orden = _ed.niveles(modelo)
    cotas = [c for c, _m in orden]
    # El indice de indice_de_diafragma es el del JSON, no el ordenado por
    # cota: se traduce.
    de_nodo = de_nodo if de_nodo is not None else _ed.indice_de_diafragma(modelo)
    maestros_ordenados = [m for _c, m in orden]
    posicion = {int(d['nodo_maestro']): maestros_ordenados.index(int(d['nodo_maestro']))
                for d in modelo.get('diafragmas', [])}
    json_a_orden = {i: posicion[int(d['nodo_maestro'])]
                    for i, d in enumerate(modelo.get('diafragmas', []))}

    def mas_cercano(z):
        return min(range(len(cotas)), key=lambda i: abs(z - cotas[i]))

    pesos = [0.0] * len(cotas)
    for c in caso.get('cargas_nodales', []):
        nid = int(c['nodo'])
        i = de_nodo.get(nid)
        i = json_a_orden[i] if i is not None else mas_cercano(float(nodos[nid]['z']))
        pesos[i] += -float(c.get('fz', 0.0))

    for c in caso.get('cargas_distribuidas', []):
        e = elementos[int(c['elemento'])]
        a, b = int(e['n1']), int(e['n2'])
        i = de_nodo.get(a, de_nodo.get(b))
        if i is not None:
            i = json_a_orden[i]
        else:
            z = (float(nodos[a]['z']) + float(nodos[b]['z'])) / 2.0
            i = mas_cercano(z)
        pesos[i] += -float(c.get('wz', 0.0)) * _ed.largo(e, nodos)
    return pesos


def caso_q_uniforme(modelo, q, base, con_area):
    r"""
    El caso Q con cada elemento a la misma intensidad q: se conserva por
    donde baja cada carga y se reemplaza cuanto vale. Devuelve el caso y,
    aparte, que elementos bajan como carga puntual y en que nodo.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}

    repartidos = {int(c['elemento']) for c in base.get('cargas_distribuidas', [])}
    # Un elemento con losa que no la baja repartida la baja puntual, en su
    # cabeza (n2). Es como el LT2 arma los muros.
    puntuales = {}
    for t in con_area:
        if t not in repartidos:
            puntuales.setdefault(int(elementos[t]['n2']), []).append(t)

    caso = {'nombre': 'Q',
            'descripcion': 'sobrecarga de uso q_Q = %g kN/m2, uniforme, por '
                           'las areas tributarias del modelo' % q,
            _ed.CAMPO_PESO_PROPIO: False,
            'cargas_nodales': [], 'cargas_distribuidas': []}

    for c in base.get('cargas_distribuidas', []):
        t = int(c['elemento'])
        if t not in con_area:
            raise SystemExit('el caso Q del modelo carga el elemento %d, que '
                             'no tiene area tributaria: esa carga no es losa '
                             'y no se sabe que es' % t)
        caso['cargas_distribuidas'].append(
            {'elemento': t, 'wx': 0.0, 'wy': 0.0,
             'wz': -q * con_area[t] / _ed.largo(elementos[t], nodos)})

    pendientes = dict(puntuales)
    for c in base.get('cargas_nodales', []):
        n = int(c['nodo'])
        ids = pendientes.pop(n, None)
        if not ids:
            raise SystemExit('el caso Q del modelo pone una carga puntual en '
                             'el nodo %d y ningun elemento con area la '
                             'explica' % n)
        caso['cargas_nodales'].append(
            {'nodo': n, 'fx': 0.0, 'fy': 0.0,
             'fz': -q * sum(con_area[t] for t in ids),
             'mx': 0.0, 'my': 0.0, 'mz': 0.0})
    if pendientes:
        sobran = sorted(t for ids in pendientes.values() for t in ids)
        raise SystemExit('%d elemento(s) con area de losa no bajan ni '
                         'repartidos ni como carga puntual: %s'
                         % (len(sobran), sobran[:8]))
    return caso, puntuales


def intensidades_del_modelo(modelo, base, con_area, puntuales):
    """
    Con que presion viene el caso Q del modelo, carga por carga, para poder
    decir de donde se partio. Devuelve {q: cuantas cargas}.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}
    cuenta = {}
    for c in base.get('cargas_distribuidas', []):
        t = int(c['elemento'])
        A = con_area.get(t, 0.0)
        if A > 0:
            q = round(-float(c.get('wz', 0.0)) * _ed.largo(elementos[t], nodos) / A, 4)
            cuenta[q] = cuenta.get(q, 0) + 1
    for c in base.get('cargas_nodales', []):
        A = sum(con_area[t] for t in puntuales.get(int(c['nodo']), []))
        if A > 0:
            q = round(-float(c.get('fz', 0.0)) / A, 4)
            cuenta[q] = cuenta.get(q, 0) + 1
    return dict(sorted(cuenta.items(), key=lambda kv: -kv[1]))


def factores_nch433(pesos, alturas):
    r"""
    El reparto en altura de NCh433 Of.1996 Mod.2009, articulo 6.2.6. NO es
    la forma de exponente:

        A_k = raiz(1 - Z_(k-1)/H) - raiz(1 - Z_k/H)
        F_k = A_k P_k / suma(A_j P_j) * Q_0

    El coeficiente se calcula por ALTURA DISTINTA y no por indice: el
    edificio tiene dos diafragmas por nivel, a la misma cota, y tomar "el
    anterior de la lista" le daria A = 0 al segundo de cada par.
    """
    H = max(alturas)
    if H <= 0:
        raise SystemExit('el edificio no tiene altura sobre la base')

    cotas = sorted(set(alturas))
    A = {}
    anterior = 0.0
    for z in cotas:
        A[z] = math.sqrt(max(0.0, 1.0 - anterior / H)) \
             - math.sqrt(max(0.0, 1.0 - z / H))
        anterior = z
    return [A[h] * W for W, h in zip(pesos, alturas)]


def factores_patron(pesos, alturas, p):
    """
    Fraccion del corte basal que toma cada nivel, de abajo hacia arriba:

        'potencia'  F_i proporcional a W_i * h_i**k (ASCE 7 12.8.3): k = 0
                    uniforme, k = 1 el triangular clasico, k = 2 el tope
        'nch433'    el reparto de NCh433 6.2.6 (factores_nch433)
        'manual'    el reparto explicito que se dicte
    """
    if p['patron'] == 'manual':
        if len(p['fracciones_patron']) != len(pesos):
            raise SystemExit(
                'fracciones_patron trae %d valores y el edificio tiene %d '
                'niveles' % (len(p['fracciones_patron']), len(pesos)))
        crudos = [float(f) for f in p['fracciones_patron']]
    elif p['patron'] == 'nch433':
        crudos = factores_nch433(pesos, alturas)
    else:
        crudos = [W * h ** p['k_patron'] for W, h in zip(pesos, alturas)]
    total = sum(crudos)
    if total <= 0.0:
        raise SystemExit('el patron da fuerza nula en todos los niveles: '
                         'revise k_patron o fracciones_patron')
    return [c / total for c in crudos]


def caso_sismico(nombre, maestros, fuerzas):
    """El caso EX o EY: una fuerza horizontal en cada nodo maestro."""
    eje = 'fx' if nombre == 'EX' else 'fy'
    return {'nombre': nombre,
            'descripcion': 'sismo pseudoestatico en %s' % nombre[-1],
            'cargas_nodales': [{'nodo': m, eje: F}
                               for m, F in zip(maestros, fuerzas)],
            'cargas_distribuidas': []}


def armar_casos(modelo, p):
    r"""
    Los cuatro casos del laboratorio, construidos en memoria con los
    parametros, mas todo lo intermedio que hace falta para mostrarlos.
    """
    elementos = {int(e['id']): e for e in modelo['elementos']}
    con_area = {t: float(e[_ed.CAMPO_AREA]) for t, e in elementos.items()
                if float(e.get(_ed.CAMPO_AREA, 0.0)) > 0}
    if not con_area:
        raise SystemExit('el modelo no trae areas tributarias; sin ellas no '
                         'hay caso Q del laboratorio.')
    area = sum(con_area.values())

    orden = _ed.niveles(modelo)
    if not orden:
        raise SystemExit('el modelo no trae diafragmas; sin ellos no hay '
                         'nodos maestros donde aplicar el sismo')
    maestros = [m for _c, m in orden]
    cota_base = min(float(n['z']) for n in modelo['nodos'])
    alturas = [c - cota_base for c, _m in orden]

    caso_g = caso_del_modelo(modelo, 'G')
    q_del_modelo = caso_del_modelo(modelo, 'Q')
    caso_q, puntuales = caso_q_uniforme(modelo, p['q_Q'], q_del_modelo, con_area)
    intensidades = intensidades_del_modelo(modelo, q_del_modelo, con_area, puntuales)

    pesos_G = peso_vertical_por_nivel(modelo, caso_g)
    pesos_Q = peso_vertical_por_nivel(modelo, caso_q)
    pesos = [g + p['fraccion_Q_sismica'] * q for g, q in zip(pesos_G, pesos_Q)]
    factores_ = factores_patron(pesos, alturas, p)
    V = p['coef_sismico'] * sum(pesos)
    fuerzas = [V * f for f in factores_]

    return {
        'casos': {'G': caso_g, 'Q': caso_q,
                  'EX': caso_sismico('EX', maestros, fuerzas),
                  'EY': caso_sismico('EY', maestros, fuerzas)},
        'con_area': con_area, 'area': area, 'puntuales': puntuales,
        'intensidades_del_modelo': intensidades,
        'niveles': orden, 'alturas': alturas,
        'pesos_G': pesos_G, 'pesos_Q': pesos_Q, 'pesos_sismicos': pesos,
        'factores': factores_, 'V': V, 'fuerzas': fuerzas,
    }


def resolver(modelo, casos):
    """Los casos resueltos en memoria, por nombre. El modelo no se toca."""
    datos = copy.deepcopy(modelo)
    datos['casos_de_carga'] = list(casos.values())
    salida = opensees.construir_y_resolver(datos)
    return datos, {r['nombre']: r for r in salida['casos']}
