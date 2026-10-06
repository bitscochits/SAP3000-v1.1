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
import sys

from calculo import edificio as _ed
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


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
