# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/superposicion.py  -  SUPERPOSICION, Y LA PRUEBA DE QUE VALE
================================================================
 Combina los casos ya resueltos, R = sum(lambda_i * R_i), y comprueba
 el resultado contra una corrida de OpenSees con la carga combinada.
 Los casos que se combinan son los DEL MODELO (los del edificio,
 resueltos en memoria) con los factores de las combinaciones del
 laboratorio.

 Correr:
   python sap.py revisar superposicion --explicita          todas las declaradas
   python sap.py revisar superposicion --explicita --comb 1.2 1.6 1.0 0.3
   python sap.py revisar superposicion --explicita --combinacion 1.2G+1.6Q

 POR QUE FUNCIONA. El modelo es lineal: K u = F con K constante, asi
 que K(a u1 + b u2) = a F1 + b F2. Fuerzas y reacciones salen de u por
 operaciones lineales y se combinan igual.

 CUANDO DEJARIA DE FUNCIONAR. En cuanto K dependa de u: material no
 lineal (es lo que pasa en capacidad.py, por eso la capacidad no se
 superpone), P-Delta, contacto o despegue, friccion.

 HASTA DONDE SE PUEDE COMPROBAR. El servidor redondea su salida --
 desplazamientos a 8 decimales, fuerzas a 4 -- asi que el criterio no
 es un numero a mano sino la COTA de ese redondeo:

     cota = 0.5 * 10^-d * (suma de |lambda| + 1)

 con el +1 por la corrida explicita, que tambien viene redondeada. El
 peor caso da 1.000 veces la cota y ninguno la supera.

 Se compara CADA GDL de CADA nodo, CADA reaccion y las doce
 componentes de fuerza de CADA elemento, no tres escalares.
================================================================
"""
from __future__ import annotations

import copy
import math
import sys
import time

from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import opensees

CASOS = lab.CASOS_BASE

# Campos de cada tipo de resultado. El identificador va aparte porque
# no se combina: se usa para emparejar.
CAMPOS = {
    'desplazamientos': ('ux', 'uy', 'uz', 'rx', 'ry', 'rz'),
    'reacciones': ('fx', 'fy', 'fz', 'mx', 'my', 'mz'),
}


# ============================================================
# COMBINAR LO YA RESUELTO
# ============================================================
def combinar_cargas(modelo, lambdas, nombre='COMBINACION'):
    """
    Un caso de carga que es la suma pesada de los del modelo. Es lo
    que se le pasa a OpenSees para la corrida explicita.
    """
    casos = {c['nombre']: c for c in modelo.get('casos_de_carga', [])}
    nodales, distribuidas = {}, {}
    for caso, factor in lambdas.items():
        c = casos.get(caso)
        if not c or abs(factor) < 1e-15:
            continue
        for x in c.get('cargas_nodales', []):
            d = nodales.setdefault(int(x['nodo']), {})
            for k in ('fx', 'fy', 'fz', 'mx', 'my', 'mz'):
                d[k] = d.get(k, 0.0) + factor * float(x.get(k, 0.0))
        for x in c.get('cargas_distribuidas', []):
            d = distribuidas.setdefault(int(x['elemento']), {})
            for k in ('wx', 'wy', 'wz'):
                d[k] = d.get(k, 0.0) + factor * float(x.get(k, 0.0))
    return {
        'nombre': nombre,
        'descripcion': 'suma pesada de %s' % ', '.join(
            '%g %s' % (v, k) for k, v in lambdas.items() if v),
        'cargas_nodales': [dict(nodo=n, **v) for n, v in nodales.items()],
        'cargas_distribuidas': [dict(elemento=e, **v)
                                for e, v in distribuidas.items()],
    }


def combinar_resultados(por_caso, lambdas):
    """
    Suma algebraica de los resultados. Devuelve un dict con la misma
    forma que un resultado normal.
    """
    salida = {}
    for clave, campos in CAMPOS.items():
        acum = {}
        for caso, factor in lambdas.items():
            r = por_caso.get(caso)
            if not r or abs(factor) < 1e-15:
                continue
            for fila in r.get(clave, []):
                d = acum.setdefault(int(fila['id']), {})
                for k in campos:
                    d[k] = d.get(k, 0.0) + factor * float(fila.get(k, 0.0))
        salida[clave] = [dict(id=i, **v) for i, v in sorted(acum.items())]

    acum = {}
    for caso, factor in lambdas.items():
        r = por_caso.get(caso)
        if not r or abs(factor) < 1e-15:
            continue
        for fila in r.get('fuerzas_elementos', []):
            f = [float(v) for v in fila['f']]
            d = acum.setdefault(int(fila['id']), [0.0] * len(f))
            for i, v in enumerate(f):
                d[i] += factor * v
    salida['fuerzas_elementos'] = [{'id': i, 'f': v}
                                   for i, v in sorted(acum.items())]
    return salida


# ============================================================
# LA CORRIDA EXPLICITA
# ============================================================
def resolver_explicito(modelo, lambdas, nombre='COMBINACION'):
    """
    Arma la carga combinada y la resuelve de verdad. Es la referencia
    contra la que se compara la superposicion.
    """
    datos = copy.deepcopy(modelo)
    datos['casos_de_carga'] = [combinar_cargas(modelo, lambdas, nombre)]
    salida = opensees.construir_y_resolver(datos)
    casos = salida.get('casos')
    return casos[0] if casos else salida


# ============================================================
# CUANTA PRECISION TIENE LO QUE HAY EN DISCO
# ============================================================
def decimales_de(resultados, clave, campos):
    r"""
    Con cuantos decimales se guardo esta familia de resultados.

    Hace falta porque los resultados del motor NO son doubles completos:
    los desplazamientos van redondeados a 8 decimales y las fuerzas a
    4. Sumar cuatro casos redondeados y compararlos contra una corrida
    en doble precision no puede dar mejor que ese redondeo, y exigir
    1e-12 marcaria como error algo que es el formato del archivo.

    Se MIDE en vez de declararse: si alguien cambia el redondeo, el
    piso se mueve solo.
    """
    d = 0
    for fila in resultados.get(clave, []):
        valores = (fila['f'] if campos is None
                   else [fila.get(k, 0.0) for k in campos])
        for v in valores:
            t = repr(float(v))
            if 'e' in t or 'E' in t or '.' not in t:
                continue
            d = max(d, len(t.split('.')[1]))
    return d


def piso_de_redondeo(por_caso, lambdas, clave, campos):
    """
    El error mas grande que puede meter el redondeo del archivo.

    Cada valor esta a lo mas a medio ultimo digito del real, y al
    combinarlos ese error se multiplica por el factor de su caso y se
    suma. Pero hay un termino mas que es facil olvidar: la corrida
    EXPLICITA, contra la que se compara, tambien viene redondeada. Por
    eso el peso es  suma|lambda| + 1  y no solo la suma.

    Sin ese +1 la cota queda corta y la comparacion marca como error
    algo que sigue siendo redondeo: para 1.2G + 1.0Q + 1.4EX daba
    1.8e-8 contra un desacuerdo real de 2.0e-8.
    """
    d = max((decimales_de(r, clave, campos)
             for c, r in por_caso.items() if abs(lambdas.get(c, 0.0)) > 1e-15),
            default=0)
    if d == 0:
        return 0.0
    peso = sum(abs(v) for v in lambdas.values()) + 1.0
    return 0.5 * (10.0 ** -d) * peso


# ============================================================
# COMPARAR
# ============================================================
def comparar(algebraico, explicito):
    """
    El peor desacuerdo de cada familia de resultados, en absoluto y
    relativo al mayor valor de esa familia.

    El relativo se escala con el MAXIMO de la familia y no con el
    valor de cada fila: dividir por un numero que puede ser cero --y
    en una estructura hay muchos ceros exactos-- convierte un error
    de 1e-16 en un infinito y esconde el error de verdad.
    """
    informe = {}
    for clave, campos in list(CAMPOS.items()) + [('fuerzas_elementos', None)]:
        filas_a = {int(x['id']): x for x in algebraico.get(clave, [])}
        filas_b = {int(x['id']): x for x in explicito.get(clave, [])}
        comunes = sorted(set(filas_a) & set(filas_b))
        peor, donde, escala, n = 0.0, None, 0.0, 0

        for i in comunes:
            a, b = filas_a[i], filas_b[i]
            if campos is None:
                va = [float(v) for v in a['f']]
                vb = [float(v) for v in b['f']]
                pares = list(zip(range(len(va)), va, vb))
            else:
                pares = [(k, float(a.get(k, 0.0)), float(b.get(k, 0.0)))
                         for k in campos]
            for k, x, y in pares:
                n += 1
                escala = max(escala, abs(y))
                if abs(x - y) > peor:
                    peor, donde = abs(x - y), (i, k)

        informe[clave] = {
            'n_comparados': n,
            'solo_en_uno': len(set(filas_a) ^ set(filas_b)),
            'peor_absoluto': peor,
            'peor_relativo': peor / escala if escala > 1e-12 else 0.0,
            'donde': donde,
            'escala': escala,
        }
    return informe


def resolver_todos(modelo):
    """Los cuatro casos del modelo resueltos ahora, en una sola corrida, por nombre."""
    salida = opensees.construir_y_resolver(copy.deepcopy(modelo))
    return {r['nombre']: r for r in salida.get('casos', [])}


def verificar(lambdas, tol=1.0e-9, por_caso=None, modelo=None, margen=1.05):
    """
    Superpone, resuelve explicito y compara. Devuelve el informe y si
    paso.

    El criterio no es un numero fijo: es la COTA DE REDONDEO, con un
    margen de 5%. El margen es tan chico porque la cota resulto ser
    exacta: el peor desacuerdo da 1.000 veces la cota y ninguno la
    supera. Un margen de 4 -- que era lo que habia antes --
    dejaria pasar un error de superposicion cuatro veces mayor que
    todo el redondeo junto sin decir nada. Si los resultados vienen en doble
    precision ese piso es cero y manda `tol`, que es donde se ve la
    superposicion de verdad.
    """
    modelo = modelo or _ed.estructura()
    if por_caso is None:
        por_caso = resolver_todos(modelo)

    faltan = [c for c, f in lambdas.items()
              if abs(f) > 1e-15 and c not in por_caso]
    if faltan:
        raise SystemExit('la combinacion usa %s y el edificio no trae ese caso'
                         % ', '.join(faltan))

    algebraico = combinar_resultados(por_caso, lambdas)
    explicito = resolver_explicito(modelo, lambdas)
    informe = comparar(algebraico, explicito)

    paso = True
    for clave, v in informe.items():
        campos = CAMPOS.get(clave)
        piso = piso_de_redondeo(por_caso, lambdas, clave, campos)
        limite = max(margen * piso, tol * max(v['escala'], 1.0))
        v['piso_de_redondeo'] = piso
        v['limite'] = limite
        v['pasa'] = v['peor_absoluto'] <= limite
        paso = paso and v['pasa']

    return {'informe': informe, 'paso': paso,
            'algebraico': algebraico, 'explicito': explicito}


# ============================================================
def main(argv):
    if '--lambdas' in argv:
        return main_lambdas(argv)
    p = lab.cargar(argv)

    modelo = _ed.estructura()
    por_caso = resolver_todos(modelo)

    # Si se pidio una combinacion concreta se revisa esa; si no, todas
    # las declaradas, que es lo que pide el avance ("al menos tres").
    pedida = ('--comb' in argv or '--combinacion' in argv)
    combos = ([p['combinacion']] if pedida
              else (p['combinaciones'] or [p['combinacion']]))

    print('=' * 72)
    print('  SUPERPOSICION EN %s' % _ed.NOMBRE.upper())
    print('=' * 72)
    print('  casos disponibles: %s' % ', '.join(sorted(por_caso)))
    print('  origen: los casos del modelo, resueltos ahora en memoria')
    print('  la salida del servidor viene redondeada a 8 decimales los')
    print('  desplazamientos y 4 las fuerzas: ese es el piso de la')
    print('  comparacion, y el limite de cada fila sale de ahi.')

    fallaron = []
    for combo in combos:
        lambdas = lab.factores(combo)
        r = verificar(lambdas, por_caso=por_caso, modelo=modelo)
        print()
        print('  %-18s %s' % (combo.get('nombre', ''),
                              lab.como_texto(combo)))
        for clave, v in r['informe'].items():
            piso = v['piso_de_redondeo']
            print('    %-20s %5d valores   peor %.3e   cota de redondeo '
                  '%.3e   %s'
                  % (clave, v['n_comparados'], v['peor_absoluto'], piso,
                     'ok' if v['pasa'] else '<-- REVISAR'))
        print('    %s' % ('OK' if r['paso'] else 'REVISAR'))
        if not r['paso']:
            fallaron.append(combo.get('nombre'))

    print()
    print('=' * 72)
    if fallaron:
        print('  NO CIERRA en: %s' % ', '.join(str(x) for x in fallaron))
        print('=' * 72)
        return 1
    print('  LA SUPERPOSICION COINCIDE CON LA CORRIDA EXPLICITA EN LAS %d '
          'COMBINACIONES' % len(combos))
    print('=' * 72)
    return 0


# ============================================================
# LA COMBINACION CON LAMBDAS LIBRES (los casos del LABORATORIO)
# ============================================================
# Lo de arriba combina los casos DEL MODELO para probar la superposicion
# contra una corrida explicita. Lo de aca combina los casos DEL
# LABORATORIO (esfuerzos.base: q de NCh1537, Cs, el patron en altura)
# para CUALQUIER juego de factores (lambda_G, lambda_Q, lambda_EX,
# lambda_EY), y arma el mismo bloque que salidas/resultados.json trae por
# cada caso: desplazamientos de todos los nodos, esfuerzos de todas las
# barras con sus estaciones y la demanda sobre la curva P-M de cada
# elemento con fierro. Es lo que devuelve POST /combinar
# (exportar/servidor.py) y lo que queda precalculado para E1..E3 en el
# bloque 'superposicion' de salidas/resultados.json.
#
# Correr:
#   python sap.py revisar superposicion --lambdas 1.2 1.0 -1.4 0
#   python sap.py revisar superposicion --lambdas 0.9 0 -1.4 0 --cs 0.20
#   (los demas argumentos son flags de los parametros del laboratorio)
#
# NO SE REIMPLEMENTA NADA. La base son los cuatro casos del laboratorio
# resueltos UNA vez con esfuerzos.base (casos, familias P-M, elementos,
# largos y nucleos, todo calculado ahi). La combinacion es
# esfuerzos.bloque_caso, la misma funcion que arma los quince casos de
# los resultados: suma lineal de f, u y w con demanda.combinar,
# estaciones con esfuerzos_internos y la demanda con demanda.demanda +
# capacidad_en. Por eso E2 (1.2G+1.6Q, que ya es un caso de los
# resultados) tiene que salir identico a ese caso, y la verificacion de
# la superposicion lo exige.
#
# POR QUE LA D/C VIENE CALCULADA Y NO SE SUMA EN UNITY. u, f y las
# estaciones son lineales en lambda; la demanda-capacidad no: el extremo
# que manda cambia, M de una columna es hypot(My, Mz) y Mn depende de P.
# Sumar lambda * u_caso daria otro numero. Regla de oro: Python calcula,
# Unity muestra.
#
# AUTOVERIFICACION. bloque_caso devuelve el peor cociente de cierre
# (esfuerzo(L) contra f_j de OpenSees, sobre la cota de redondeo). Si pasa
# de 1, el caso NO se entrega: CasoNoCierra, igual que los resultados no
# se escriben.

# El bloque de entrada/laboratorio.json con E1..E3, los rangos de los
# sliders y los elementos de control.
ESTADOS = 'superposicion'
NOMBRE_LIBRE = 'LIBRE'
TIPO = 'superposicion'


class CasoNoCierra(RuntimeError):
    """El caso combinado no cierra con OpenSees: no se entrega."""


def cargar_estados():
    """
    E1..E3, los rangos de los sliders y los elementos de control: el bloque
    ESTADOS de entrada/laboratorio.json tal cual, con sus '_por_que'. Se
    lee en cada llamada, asi GET /estados ve un cambio del archivo sin
    reiniciar el servidor.
    """
    return lab.bloque(ESTADOS)


def sin_explicacion(valor):
    """Quita las claves '_...': son para quien lee el JSON, no para Unity
    (JsonUtility las ignoraria, pero el contrato con el C# las marcaria
    como claves sin campo)."""
    if isinstance(valor, dict):
        return {k: sin_explicacion(v) for k, v in valor.items() if not k.startswith('_')}
    if isinstance(valor, list):
        return [sin_explicacion(v) for v in valor]
    return valor


def lambdas_de(pedido):
    r"""
    {G, Q, EX, EY} como float desde un dict. Una clave ausente vale 0 (un
    caso que no entra). Lanza ValueError con el motivo si un factor no es
    un numero finito: un NaN o un infinito no dan error en la suma, dan
    un caso lleno de NaN que Unity dibujaria como nada.
    """
    if not isinstance(pedido, dict):
        raise ValueError('los factores tienen que venir en un objeto {G, Q, EX, EY}')
    salida = {}
    for c in CASOS:
        v = pedido.get(c, 0.0)
        # bool es int en Python: true no es un factor.
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError('el factor %s tiene que ser un numero, vino %r' % (c, v))
        v = float(v)
        if not math.isfinite(v):
            raise ValueError('el factor %s tiene que ser finito, vino %r' % (c, v))
        salida[c] = v
    return salida


def texto_combinacion(lambdas):
    """'1.20 G + 1.00 Q - 1.40 EX'. laboratorio.como_texto escribiria
    '+ -1.40 EX' con un factor negativo; esto pone el signo."""
    partes = []
    for c in CASOS:
        v = float(lambdas.get(c, 0.0))
        if abs(v) <= 1e-12:
            continue
        if not partes:
            partes.append('%s%.2f %s' % ('-' if v < 0 else '', abs(v), c))
        else:
            partes.append('%s %.2f %s' % ('-' if v < 0 else '+', abs(v), c))
    return ' '.join(partes) if partes else '(nula)'


def parametros_de(b):
    """
    Las lineas de laboratorio.describir() con que se armo la base, como las
    lleva info.parametros de los resultados. Son la HUELLA con que Unity
    reconoce que un caso combinado es de los mismos parametros que su
    resultados.json.
    """
    return [l.strip() for l in lab.describir(b['p']).split('\n')]


def base(argv=(), silenciar=True):
    r"""
    La base del laboratorio (esfuerzos.base) y cuanto tardo: todo lo que
    hace falta para combinar sin volver a OpenSees. No calcula nada mas
    que esfuerzos.base; agrega 'segundos' y 'avisos_opensees'.

    Toca OpenSees (resolver y las curvas P-M): quien la llame desde un
    servidor tiene que tomar opensees.LOCK y pasar silenciar=False (ver
    exportar/servidor.obtener_base).
    """
    argv = list(argv or ())
    t0 = time.time()
    avisos = opensees.AvisosDeOpenSees() if silenciar else None
    if avisos is not None:
        with avisos:
            b = es.base(argv)
    else:
        b = es.base(argv)
    b = dict(b)
    b['segundos'] = time.time() - t0
    b['avisos_opensees'] = avisos.resumen() if avisos is not None else None
    return b


# ============================================================
# UN CASO COMBINADO
# ============================================================
def caso_combinado(b, lambdas, nombre=NOMBRE_LIBRE, tipo=TIPO, descripcion=None):
    r"""
    Un caso completo para esos factores, con la forma de los casos de
    resultados.json: nombre, tipo, descripcion, factores [G, Q, EX, EY],
    max_desplazamiento_mm, desplazamientos de todos los nodos, esfuerzos
    de todas las barras con estaciones y demandas de las barras con fierro.
    `b` es la base del laboratorio (esfuerzos.base o base()).

    Devuelve (caso, peor_cierre) con peor_cierre = (cociente, id, comp).
    """
    lambdas = lambdas_de(lambdas)
    caso, _cargas, peor = es.bloque_caso(
        nombre, tipo, descripcion if descripcion is not None else texto_combinacion(lambdas),
        lambdas, b['resultados'], b['elementos'], b['cargas_base'],
        b['familia_de'], b['curvas'], b['largos'], b.get('nucleo_de'))

    if not caso['desplazamientos']:
        # Con todos los lambda en cero bloque_caso no recorre ningun caso
        # y deja la lista vacia. La combinacion nula es u = 0 en todos los
        # nodos (K u = 0), y Unity espera la lista COMPLETA: un nodo que
        # falta se dibuja sin mover, pero un visor que cuenta nodos no
        # sabria que es a proposito.
        caso['desplazamientos'] = [
            {'id': i, 'ux': 0.0, 'uy': 0.0, 'uz': 0.0, 'rx': 0.0, 'ry': 0.0, 'rz': 0.0}
            for i in sorted(int(n['id']) for n in b['modelo']['nodos'])]

    if peor[0] > 1.0:
        raise CasoNoCierra(
            '%s (%s) no cierra con OpenSees: elemento %d, %s, error %.3f veces la cota '
            'de redondeo. No se entrega.' % (nombre, texto_combinacion(lambdas),
                                              peor[1], peor[2], peor[0]))
    return caso, peor


def equilibrio_combinado(b, lambdas):
    r"""
    opensees.equilibrio de la combinacion: la carga combinada
    (combinar_cargas) contra las reacciones combinadas
    (combinar_resultados). Es la UNICA suma de reacciones valida (CLAUDE.md,
    "Reacciones"): en un nodo de diafragma nodeReaction trae la fuerza
    interna de la restriccion, y sumar todas las filas dobla el corte.
    Viaja calculado para que Unity no sume nada.
    """
    lambdas = lambdas_de(lambdas)
    carga = combinar_cargas(b['datos'], lambdas, NOMBRE_LIBRE)
    reacciones = combinar_resultados(b['resultados'], lambdas)
    return opensees.equilibrio(b['datos'], carga, reacciones)


def respuesta_combinar(b, lambdas):
    """El cuerpo de POST /combinar con ok = true (CONTRATO.md, servidor)."""
    caso, _peor = caso_combinado(b, lambdas)
    return {
        'ok': True,
        'error': '',
        'edificio': _ed.NOMBRE,
        'parametros': parametros_de(b),
        'caso': caso,
        # Agregado a lo del contrato (no cambia nada de lo que ya estaba):
        # el equilibrio de la combinacion con la regla de opensees.equilibrio.
        'equilibrio': equilibrio_combinado(b, lambdas),
    }


def respuesta_estados(estados=None):
    """El cuerpo de GET /estados: los estados sin caso y los rangos."""
    estados = estados or cargar_estados()
    return {
        'ok': True,
        'error': '',
        'estados': [sin_explicacion({k: e[k] for k in ('nombre', 'descripcion', 'lambdas')})
                    for e in estados['estados']],
        'rangos': sin_explicacion(estados['rangos']),
    }


# ============================================================
# POR CONSOLA
# ============================================================
def imprimir_caso(caso, peor, eq):
    """El maximo, el NO PASA, los fuera de curva, el cierre, el equilibrio
    y los elementos que no pasan de un caso combinado."""
    dem = caso['demandas']
    no_pasan = sum(1 for d in dem if not d['pasa'])
    fuera = sum(1 for d in dem if d['u'] >= 9999.0)
    print('  %-6s %-24s max %8.4f mm   NO PASA %d/%d (%d fuera de curva)   cierre %.3f'
          % (caso['nombre'], caso['descripcion'], caso['max_desplazamiento_mm'], no_pasan,
             len(dem), fuera, peor[0]))
    print('         equilibrio: aplicada [%s] kN, reaccion [%s] kN, error [%s]'
          % (', '.join('%.4f' % v for v in eq['aplicada_kN']),
             ', '.join('%.4f' % v for v in eq['reaccion_kN']),
             ', '.join('%.1e' % v for v in eq['error_kN'])))
    for d in dem:
        if not d['pasa']:
            print('         elemento %4d  P %10.4f  M %10.4f  Mn %10.4f  u %s'
                  % (d['id'], d['P'], d['M'], d['Mn'],
                     'fuera de curva' if d['u'] >= 9999.0 else '%.6f' % d['u']))


def main_lambdas(argv):
    """sap.py revisar superposicion --lambdas G Q EX EY [flags de los parametros]"""
    argv = list(argv)
    i = argv.index('--lambdas')
    try:
        valores = [float(x) for x in argv[i + 1:i + 5]]
    except ValueError:
        raise SystemExit('--lambdas necesita cuatro numeros: G Q EX EY')
    if len(valores) != 4:
        raise SystemExit('--lambdas necesita cuatro numeros: G Q EX EY')
    pedidos = dict(zip(CASOS, valores))
    argv = argv[:i] + argv[i + 5:]

    print('=' * 72)
    print('  SUPERPOSICION CON LAMBDAS LIBRES   %s' % _ed.NOMBRE.upper())
    print('=' * 72)
    b = base(argv)
    print('  base: esfuerzos.base en %.1f s (%d nodos, %d elementos, %d con fierro)'
          % (b['segundos'], len(b['modelo']['nodos']), len(b['largos']),
             sum(1 for f in b['familia_de'].values() if f >= 0)))
    if b['avisos_opensees']:
        print('  %s' % b['avisos_opensees'])
    for linea in parametros_de(b):
        print('  %s' % linea)
    print()

    t = time.time()
    caso, peor = caso_combinado(b, pedidos, nombre=NOMBRE_LIBRE)
    imprimir_caso(caso, peor, equilibrio_combinado(b, pedidos))
    print('  (combinado en %.3f s, sin volver a OpenSees)' % (time.time() - t))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
