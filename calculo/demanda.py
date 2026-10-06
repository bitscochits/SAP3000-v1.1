# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/demanda.py  -  EL PUNTO SOBRE LA CURVA
================================================================
 Toma cualquier columna o muro del edificio, saca su (P, M) de los
 casos del laboratorio y lo pone sobre SU curva de interaccion
 (calculo/capacidad.py). Tambien define las FAMILIAS de seccion (los
 elementos que comparten curva) y los NUCLEOS (los muros que son pata
 de una caja de ascensores o de escalera).

 Correr:
   python sap.py revisar demanda --lista
   python sap.py revisar demanda 200005            columna
   python sap.py revisar demanda 100537            muro
   python sap.py revisar demanda 200005 --comb 1.2 1.6 1.0 0.3
   python sap.py revisar demanda 100018 --uso oficinas
                                          con otra carga viva de NCh1537
   python sap.py revisar demanda 200005 --grafico
   python sap.py revisar demanda 200005 --mphi     M-phi a SUS axiales
   python sap.py revisar demanda --todas

 ----------------------------------------------------------------
 LA DEMANDA SALE DE LOS CASOS DEL LABORATORIO
 ----------------------------------------------------------------
 Q, EX y EY se arman en memoria con los parametros (q_Q de NCh1537, Cs
 y el patron en altura; calculo/laboratorio.py) y se resuelven UNA vez
 por corrida. Asi el punto que se pone sobre la curva es del mismo
 edificio que se acaba de verificar, y cambiar --q lo mueve.

 La COMBINACION no se resuelve de nuevo: el modelo es lineal elastico,
 asi que las fuerzas se suman algebraicamente. La CAPACIDAD si se
 calcula cada vez, porque es no lineal y no se puede superponer.

 ----------------------------------------------------------------
 QUE ES P Y QUE ES M EN UNA BARRA
 ----------------------------------------------------------------
 De eleResponse(tag, 'localForce') salen doce numeros, seis por
 extremo:

     [N, Vy, Vz, T, My, Mz]  en el nudo i, y lo mismo en el j

 En una columna el eje local x es vertical, asi que N es la carga
 axial: POSITIVA EN COMPRESION en el extremo i. Y hay DOS momentos,
 My y Mz, uno por cada direccion de flexion.

 En una COLUMNA cuadrada con armadura perimetral se compara con el
 momento RESULTANTE, sqrt(My^2 + Mz^2): su capacidad es practicamente
 la misma en cualquier direccion.

 En un MURO no. Un M 0.25x7.95 tiene mil veces mas inercia en un eje
 que en el otro, asi que se toma solo el momento EN SU PLANO -- el del
 eje de inercia mayor, My o Mz segun el muro -- y el de fuera de plano
 se informa aparte. Ver demanda() y momento_en_el_plano().
================================================================
"""
from __future__ import annotations

import collections
import math
import os
import sys

from calculo import capacidad
from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import rutas

CASOS = ('G', 'Q', 'EX', 'EY')


def casos_resueltos(modelo, p):
    """
    G, Q, EX y EY resueltos con los parametros: los MISMOS casos que
    arma laboratorio.armar_casos, para que la demanda sea la del
    edificio que se acaba de verificar y no la de un Q guardado con
    otro q. Una vez por corrida; _todas() la comparte entre columnas.
    """
    arm = lab.armar_casos(modelo, p)
    _datos, resultados = lab.resolver(modelo, arm['casos'])
    return resultados


def fuerzas_por_caso(resultados, elemento_id, casos=CASOS):
    """El vector de fuerza local del elemento, en cada caso."""
    salida = {}
    for c in casos:
        r = resultados.get(c)
        if not r:
            continue
        for f in r.get('fuerzas_elementos', []):
            if int(f['id']) == int(elemento_id):
                salida[c] = [float(v) for v in f['f']]
                break
    return salida


def combinar(por_caso, lambdas):
    """
    Suma algebraica de las fuerzas de varios casos. Es valida porque
    el modelo es lineal: K u = F, y por lo tanto la respuesta a una
    suma de cargas es la suma de las respuestas.
    """
    n = max((len(v) for v in por_caso.values()), default=12)
    out = [0.0] * n
    for caso, factor in lambdas.items():
        f = por_caso.get(caso)
        if not f:
            continue
        for i, v in enumerate(f):
            out[i] += factor * v
    return out


def momento_en_el_plano(Iy, Iz):
    """'My' o 'Mz': el momento que flecta un muro en su plano, el del eje
    de inercia mayor. Un muro es una barra vertical y el servidor le pasa
    Iy e Iz tal cual, sin cruzarlas: la flexion alrededor del eje local y
    la resiste Iy, la de z la resiste Iz."""
    return 'My' if float(Iy) > float(Iz) else 'Mz'


def momento_en_el_plano_de(modelo, e):
    """momento_en_el_plano() con las inercias de la seccion del elemento.
    Sin valores por defecto: una seccion sin Iy o Iz es un error."""
    s = next(s for s in modelo['secciones'] if s['nombre'] == e['seccion'])
    return momento_en_el_plano(s['Iy'], s['Iz'])


def demanda(f, tipo='columna', plano=None):
    r"""
    (P, M) de un vector de fuerza local. P positivo en COMPRESION.

    Se mira en los DOS extremos y gana el que tenga mayor momento: el
    maximo de una columna no siempre esta arriba.

    ----------------------------------------------------------------
    UNA COLUMNA Y UN MURO NO SE MIDEN IGUAL
    ----------------------------------------------------------------
    COLUMNA: seccion cuadrada con armadura perimetral, capacidad
    practicamente igual en cualquier direccion. Se compara con el
    momento RESULTANTE, sqrt(My^2 + Mz^2).

    MURO: la capacidad es enorme en su plano y ridicula fuera de el
    -- un M 0.25x7.95 tiene mil veces mas inercia en un eje que en el
    otro. Componer los dos momentos en uno resultante y compararlo
    contra la curva del plano fuerte diria que el muro aguanta fuera
    de su plano lo mismo que dentro, que es falso. Se toma solo el
    momento EN EL PLANO, y el fuera de plano se informa aparte.

    ----------------------------------------------------------------
    CUAL ES EL DEL PLANO LO DICEN LAS INERCIAS
    ----------------------------------------------------------------
    plano = 'My' o 'Mz', obligatorio en un muro: sale de
    momento_en_el_plano_de(modelo, e), el eje de inercia mayor. Una
    regla fija ('Mz') valia solo para los muros del LT2.

    Los dos cuerpos eligieron distinto el vecxz de sus muros. En el LT2
    es la normal y la inercia grande queda en Iz: el muro 200009 bajo EY
    da Mz = 9661 kN m y My = 24. En el cuerpo antiguo es la direccion
    del largo y la grande queda en Iy: el muro 100537 bajo EY da
    My = 30 352 kN m y Mz = 46. Con la regla fija, en el cuerpo antiguo
    se comparaba el momento FUERA de plano contra la curva del plano.
    """
    if not f or len(f) < 12:
        return None
    if tipo == 'muro' and plano not in ('My', 'Mz'):
        # Sin default a proposito: un default silencioso es justo lo que
        # escondio el error en los muros de Ingenieria.
        raise ValueError("demanda() de un muro necesita plano='My' o 'Mz': "
                         "usa momento_en_el_plano_de(modelo, e)")
    extremos = [
        {'P_kN': f[0], 'My': f[4], 'Mz': f[5], 'extremo': 'i (inferior)'},
        {'P_kN': -f[6], 'My': f[10], 'Mz': f[11], 'extremo': 'j (superior)'},
    ]
    for d in extremos:
        if tipo == 'muro':
            fuera = 'Mz' if plano == 'My' else 'My'
            d['M_kNm'] = abs(d[plano])
            d['M_fuera_de_plano_kNm'] = abs(d[fuera])
            d['plano'] = plano
        else:
            d['M_kNm'] = math.hypot(d['My'], d['Mz'])
            d['M_fuera_de_plano_kNm'] = None
    return max(extremos, key=lambda d: d['M_kNm'])


def capacidad_en(P, curva):
    """
    Momento que la curva admite para esa compresion, interpolando
    entre los dos puntos que la rodean. Fuera del rango de la curva
    devuelve 0: una compresion mayor que la de compresion pura no la
    resiste nadie.
    """
    pts = sorted(((p['P_kN'], p['M_kNm']) for p in curva),
                 key=lambda t: t[0])
    if not pts or P <= pts[0][0] or P >= pts[-1][0]:
        return 0.0
    for (p1, m1), (p2, m2) in zip(pts, pts[1:]):
        if p1 <= P <= p2:
            if abs(p2 - p1) < 1e-9:
                return max(m1, m2)
            t = (P - p1) / (p2 - p1)
            return m1 + t * (m2 - m1)
    return 0.0


def firma_de_seccion(e, sec):
    """
    La clave de FAMILIA de un elemento con enfierradura: dos elementos
    con la misma firma comparten curva de interaccion. Vive a nivel de
    modulo para que _todas() y los resultados agrupen igual.
    """
    # La clave tiene que incluir la SECCION. Sin ella, dos muros
    # distintos con el mismo numero de barras -- un M 0.30x1.45 y
    # un M 0.25x7.95 con cinco barras de borde cada uno -- caian en
    # la misma entrada y el segundo se comparaba contra la curva
    # del primero. Mismo numero de barras no es la misma seccion.
    fe = e.get('enfierradura') or {}
    return (e.get('seccion'), round(sec.b, 4), round(sec.h, 4),
            len(sec.barras), round(sec.As, 8),
            (sec.estribo or {}).get('texto'),
            (fe.get('malla_vertical') or {}).get('texto'))


def revisar(elemento_id, lambdas=None, curva=None, modelo=None,
            resultados=None, p=None):
    """Demanda, capacidad y utilizacion de una columna o un muro."""
    modelo = modelo or _ed.estructura()
    if resultados is None:
        resultados = casos_resueltos(modelo, p or lab.cargar([]))
    sec = capacidad.desde_elemento(modelo, elemento_id)
    curva = curva if curva is not None else capacidad.interaccion(sec)

    elemento = next((e for e in modelo['elementos']
                     if int(e['id']) == int(elemento_id)), {})
    tipo = elemento.get('tipo', 'columna')
    plano = momento_en_el_plano_de(modelo, elemento) if tipo == 'muro' else None
    por_caso = fuerzas_por_caso(resultados, elemento_id)
    puntos = {}
    for c, f in por_caso.items():
        puntos[c] = demanda(f, tipo, plano)
    if lambdas:
        puntos['COMB'] = demanda(combinar(por_caso, lambdas), tipo, plano)

    for nombre, d in puntos.items():
        if not d:
            continue
        Mc = capacidad_en(d['P_kN'], curva)
        d['M_capacidad_kNm'] = Mc
        d['utilizacion'] = (d['M_kNm'] / Mc) if Mc > 1e-9 else float('inf')
        d['pasa'] = d['utilizacion'] <= 1.0
    return {'seccion': sec, 'curva': curva, 'puntos': puntos}


def grafico(res, destino):
    """Dibuja la curva y los puntos de demanda."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    pts = sorted(((p['P_kN'], p['M_kNm']) for p in res['curva']),
                 key=lambda t: t[0])
    P = [p for p, _m in pts]
    M = [m for _p, m in pts]

    fig, ax = plt.subplots(figsize=(7.5, 6))
    # Las dos ramas: la seccion es simetrica, el momento puede ir en
    # cualquier sentido.
    ax.plot(M, P, '-', color='#1f4e79', lw=2, label='capacidad nominal')
    ax.plot([-m for m in M], P, '-', color='#1f4e79', lw=2)
    ax.fill_betweenx(P, [-m for m in M], M, color='#1f4e79', alpha=0.07)

    colores = {'G': '#2e7d32', 'Q': '#f9a825', 'EX': '#c62828',
               'EY': '#6a1b9a', 'COMB': '#000000'}
    for nombre, d in res['puntos'].items():
        if not d:
            continue
        ax.plot(d['M_kNm'], d['P_kN'], 'o', ms=9,
                color=colores.get(nombre, '#555'),
                markeredgecolor='white', zorder=5,
                label='%s   u = %.2f' % (nombre, d['utilizacion']))

    ax.axhline(0, color='#999', lw=0.8)
    ax.axvline(0, color='#999', lw=0.8)
    ax.set_xlabel('Momento M [kN m]')
    ax.set_ylabel('Compresion P [kN]')
    ax.set_title('%s\ndemanda contra capacidad' % res['seccion'].nombre)
    ax.grid(alpha=0.25)
    ax.legend(loc='upper right', fontsize=9)
    fig.tight_layout()
    fig.savefig(destino, dpi=150)
    plt.close(fig)
    return destino


# ============================================================
# LA LINEA DE COMANDOS (sap.py revisar demanda)
# ============================================================
def _lista():
    modelo = _ed.estructura()
    nodos = {int(n['id']): n for n in modelo['nodos']}
    filas = []
    for e in modelo['elementos']:
        fe = e.get('enfierradura')
        if not fe:
            continue
        n1 = nodos[int(e['n1'])]
        if fe.get('tipo') == 'muro':
            cuantas = len(fe.get('barras_de_borde') or [])
        else:
            cuantas = fe['longitudinal']['cantidad']
        filas.append((int(e['id']), float(n1['x']), float(n1['y']),
                      float(n1['z']), e['seccion'], cuantas,
                      (fe.get('fuente') or {}).get('eje')))
    print('%d elementos con enfierradura' % len(filas))
    print('  %5s %9s %9s %8s  %-14s %7s  %s'
          % ('elem', 'x', 'y', 'z', 'seccion', 'barras', 'eje'))
    for f in sorted(filas, key=lambda t: (t[1], t[2], t[3])):
        print('  %5d %9.2f %9.2f %+8.2f  %-14s %7d  %s' % f)
    return 0


def _todas(lambdas, p):
    modelo = _ed.estructura()
    resultados = casos_resueltos(modelo, p)
    ids = [int(e['id']) for e in modelo['elementos'] if 'enfierradura' in e]
    # Una curva por FAMILIA de enfierradura, no una por elemento: las
    # 40 columnas del LT2 son solo dos secciones distintas, y calcular
    # cuarenta veces la misma curva es tirar el tiempo.
    curvas = {}

    print('  %5s %10s %10s %10s %7s  %s'
          % ('elem', 'P [kN]', 'M [kN m]', 'Mn [kN m]', 'u', ''))
    peor = None
    for eid in ids:
        e = next(x for x in modelo['elementos'] if int(x['id']) == eid)
        sec = capacidad.desde_elemento(modelo, eid)
        clave = firma_de_seccion(e, sec)
        if clave not in curvas:
            curvas[clave] = capacidad.interaccion(sec)
        res = revisar(eid, lambdas, curva=curvas[clave],
                      modelo=modelo, resultados=resultados)
        d = res['puntos'].get('COMB') or res['puntos'].get('G')
        if not d:
            continue
        print('  %5d %10.1f %10.1f %10.1f %7.3f  %s'
              % (eid, d['P_kN'], d['M_kNm'], d['M_capacidad_kNm'],
                 d['utilizacion'], '' if d['pasa'] else '<-- NO PASA'))
        if peor is None or d['utilizacion'] > peor[1]['utilizacion']:
            peor = (eid, d)
    print()
    print('  %d curvas distintas para %d elementos' % (len(curvas), len(ids)))
    if peor:
        print('  la mas exigida es la %d, con u = %.3f'
              % (peor[0], peor[1]['utilizacion']))
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    resto = list(argv)
    p = lab.cargar(argv)             # --q, --uso, --cs, --k, --patron ...

    lambdas = None
    if '--comb' in resto:
        i = resto.index('--comb')
        try:
            f = [float(x) for x in resto[i + 1:i + 5]]
        except (ValueError, IndexError):
            raise SystemExit('--comb necesita cuatro numeros: G Q EX EY')
        lambdas = dict(zip(CASOS, f))
        resto = resto[:i] + resto[i + 5:]

    if '--lista' in resto:
        return _lista()
    if '--todas' in resto:
        print('  casos: Q a %.2f kN/m2 (%s); sismo Cs = %.2f, %s'
              % (p['q_Q'], lab.origen_q(p), p['coef_sismico'],
                 lab.texto_patron(p)))
        return _todas(lambdas or {'G': 1.0, 'Q': 1.0,
                                  'EX': 0.0, 'EY': 0.0}, p)

    if not resto:
        raise SystemExit('falta el numero de elemento (o --lista / --todas)')
    elem = resto[0]

    modelo = _ed.estructura()
    res = revisar(elem, lambdas, modelo=modelo,
                  resultados=casos_resueltos(modelo, p))
    sec = res['seccion']

    print('=' * 72)
    print('  DEMANDA CONTRA CAPACIDAD   %s, elemento %s' % (_ed.NOMBRE, elem))
    print('=' * 72)
    print('  casos: Q a %.2f kN/m2 (%s); sismo Cs = %.2f, %s'
          % (p['q_Q'], lab.origen_q(p), p['coef_sismico'],
             lab.texto_patron(p)))
    print()
    print(sec.resumen())
    if sec.origen:
        print('  del plano   %s, %s' % (sec.origen.get('lamina'),
                                        sec.origen.get('elevacion')))
    print()
    if lambdas:
        print('  combinacion  ' + ' + '.join(
            '%.2f %s' % (v, k) for k, v in lambdas.items() if v))
        print()
    print('  %-6s %10s %10s %10s %10s %8s  %s'
          % ('caso', 'P [kN]', 'My', 'Mz', 'M', 'Mn', 'utilizacion'))
    for nombre in list(CASOS) + ['COMB']:
        d = res['puntos'].get(nombre)
        if not d:
            continue
        print('  %-6s %10.1f %10.1f %10.1f %10.1f %8.1f  %6.3f  %s'
              % (nombre, d['P_kN'], d['My'], d['Mz'], d['M_kNm'],
                 d['M_capacidad_kNm'], d['utilizacion'],
                 'ok' if d['pasa'] else 'NO PASA'))

    if '--grafico' in resto:
        destino = rutas.asegurar(os.path.join(rutas.FIGURAS, 'pm_%s.png' % elem))
        grafico(res, destino)
        print()
        print('  -> %s' % os.path.relpath(destino, rutas.RAIZ))

    if '--mphi' in resto:
        # Las M-phi de ESTA columna a los axiales que le pone cada caso,
        # mas la de P = 0 como referencia. Es el "por que P cambia M"
        # con los numeros del edificio y no con fracciones genericas.
        # Dos axiales que difieren menos del 2 % de la compresion pura
        # darian curvas encimadas: se deja uno.
        Pc = sec.P_compresion
        niveles = [0.0]
        for d in sorted((d for d in res['puntos'].values() if d),
                        key=lambda d: d['P_kN']):
            if d['P_kN'] > 0 and all(abs(d['P_kN'] - q) > 0.02 * Pc for q in niveles):
                niveles.append(d['P_kN'])
        destino = rutas.asegurar(os.path.join(rutas.FIGURAS,
                                              'mphi_%s_demanda.png' % elem))
        curvas = capacidad.dibujar_momento_curvatura(sec, destino, niveles)
        print()
        print('  M-phi a los axiales de la demanda -> %s'
              % os.path.relpath(destino, rutas.RAIZ))
        for r in curvas:
            casos = [n for n, d in res['puntos'].items()
                     if d and abs(d['P_kN'] - r['P_kN']) < 1e-6]
            print('    P = %8.1f kN %-8s M max = %7.1f   nominal = %7s   %s'
                  % (r['P_kN'], '(%s)' % ','.join(casos) if casos else '',
                     r['M_max'], ('%.1f' % r['M_aci']) if r['M_aci'] else '-',
                     r['motivo_termino']))
    return 0


# ============================================================
# LOS NUCLEOS
# ============================================================
# Un nucleo (caja de ascensores, de escalera) se modela como varias
# COLUMNAS ANCHAS unidas en cada piso por brazos rigidos (CLAUDE.md
# seccion 4). Asi resiste el volcamiento como un PAR de axiales entre
# sus patas: una se comprime y la otra se tracciona.
#
# Despues, la revision de demanda/capacidad compara cada pata SOLA
# contra su propia curva P-M. La traccionada se pasa casi siempre, y
# cuando la traccion neta supera el As*fy de esa pata el cociente ni
# siquiera existe: la demanda cae fuera de la curva y se informa
# u = 9999.
#
# ESO NO MIDE QUE EL NUCLEO FALLE. La traccion que saca a la pata de
# su curva es el PAR INTERNO del grupo, no carga externa que el grupo
# tenga que tomar. Medido sobre el conjunto (24-09, 15 combinaciones),
# de las 119 filas que no pasan, 103 son patas de nucleo:
#
#     92 (77 % del total)  el grupo esta en COMPRESION NETA
#     11 ( 9 %)            traccionado, pero DENTRO de su As*fy
#      0 ( 0 %)            el grupo se pasa de su propio As*fy
#
# O sea: ni un solo grupo esta sobrepasado en axial. Las 103 salen de
# mirar la pata sola. Las 16 que quedan no son patas: 9 filas en 5
# muros sueltos y 7 en 2 columnas.
#
# ----------------------------------------------------------------
# LO QUE ESTE MODULO NO HACE
# ----------------------------------------------------------------
# NO cambia ningun veredicto. `pasa` se sigue decidiendo con la curva
# de la pata, porque revisar pata por pata es un procedimiento
# aceptado (asi revisan los "piers" los programas comerciales) y
# porque el ala traccionada de un nucleo tiene que llevar su traccion
# con su propio fierro tambien en la seccion compuesta.
#
# Lo que hace es DECIR de donde viene ese axial, para que el mapa no
# presente como una falla de capacidad lo que es un reparto interno.
# La revision de verdad --una seccion de fibras del nucleo completo,
# con flexion biaxial porque 12 de los 17 grupos que fallan tienen
# muros cruzados a 0 y 90 grados-- es harina de otro costal y esta
# anotada como pendiente (CLAUDE.md, trampas: "un u enorme casi nunca
# es la capacidad: es el axial").
#
# ----------------------------------------------------------------
# COMO SE ARMA UN GRUPO
# ----------------------------------------------------------------
# Muros unidos por una cadena de brazos rigidos SIN viga ni columna
# en el medio. La condicion del medio importa: un brazo tambien va
# del baricentro del muro a sus caras, donde llega una viga, y sin
# ella el recorrido se escapa por el marco y termina uniendo medio
# edificio (87 de 96 muros en un solo grupo en vez de 77 en 36).
# ============================================================

# Los tipos de barra que ATRAVIESAN un grupo. 'brazo' es el nombre del
# LT2 y 'brazo_rigido' el del cuerpo antiguo: son lo mismo (CLAUDE.md 4).
BRAZOS = ('brazo', 'brazo_rigido')

# Lo que CORTA el grupo: si una punta del brazo tiene una de estas, ese
# brazo va del muro a su cara y no a otra pata.
CORTAN = ('viga_x', 'viga_y', 'viga', 'columna', 'pilar_metal',
          'viga_metal', 'diagonal')

COMPRIMIDO = 'comprimido'
TRACCION_DENTRO = 'traccion_dentro'
TRACCION_FUERA = 'traccion_fuera'


def grupos_de_nucleo(modelo):
    """
    {id de muro: [ids del grupo]} para los muros que son pata de un
    nucleo. Un muro que no comparte grupo con ningun otro NO aparece.
    """
    elementos = modelo.get('elementos', [])
    corta = set()
    for e in elementos:
        if e.get('tipo') in CORTAN:
            corta.add(e['n1'])
            corta.add(e['n2'])

    padre = {}

    def raiz(a):
        while padre.setdefault(a, a) != a:
            a = padre[a]
        return a

    def unir(a, b):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[ra] = rb

    for e in elementos:
        if e.get('tipo') not in BRAZOS:
            continue
        if e['n1'] in corta or e['n2'] in corta:
            continue
        unir(e['n1'], e['n2'])

    # UN GRUPO ES UN PISO DE UN NUCLEO, no el nucleo entero.
    #
    # Un muro comparte nodo con los del piso de ARRIBA y con los de
    # ABAJO, asi que agrupar por nodo juntaba las patas de dos pisos y
    # la suma de axiales doblaba el grupo (grupos de 8 que eran 4 + 4).
    # Lo que tiene sentido sumar es el axial de las patas de UN piso:
    # eso es lo que el nucleo baja por ese tramo. Por eso la clave
    # lleva, ademas del nudo por el que se conectan, las dos cotas del
    # muro: solo se agrupan patas que cubren el MISMO tramo.
    nodos = {int(x['id']): x for x in modelo.get('nodos', [])}

    def cota(nid):
        n = nodos.get(int(nid))
        return round(float(n['z']), 2) if n else None

    por_clave = collections.defaultdict(set)
    for e in elementos:
        if e.get('tipo') != 'muro':
            continue
        z1, z2 = cota(e['n1']), cota(e['n2'])
        if z1 is None or z2 is None:
            continue
        tramo = (min(z1, z2), max(z1, z2))
        # Se conecta por cualquiera de sus dos nudos; el tramo decide
        # que no se mezclen pisos.
        for nid in (e['n1'], e['n2']):
            por_clave[(raiz(nid), tramo)].add(e['id'])

    # Un muro puede aparecer por su nudo de abajo y por el de arriba;
    # se queda con el grupo MAYOR, que es el que tiene a todas sus
    # companeras de piso, y despues se cierra para que la relacion sea
    # simetrica (si i esta con j, j esta con i).
    mejor = {}
    for miembros in por_clave.values():
        if len(miembros) < 2:
            continue
        for i in miembros:
            if i not in mejor or len(miembros) > len(mejor[i]):
                mejor[i] = miembros
    salida = {}
    for i, miembros in mejor.items():
        lista = sorted(m for m in miembros if mejor.get(m) is miembros)
        if len(lista) > 1:
            salida[i] = lista
    return {i: v for i, v in salida.items() if i in v}


def estado(P_grupo, asfy_grupo):
    """
    Que le pasa al grupo en axial. Convencion de las demandas:
    P > 0 es COMPRESION.
    """
    if P_grupo > 0:
        return COMPRIMIDO
    return TRACCION_DENTRO if -P_grupo <= asfy_grupo else TRACCION_FUERA


def asfy_de(modelo, ids, cache=None):
    """
    Suma de As*fy (kN) de esos muros: la traccion que el grupo puede
    tomar con su propio fierro. Un muro sin enfierradura aporta 0 y se
    cuenta aparte, para no inventarle acero al grupo.
    """
    total, sin_fierro = 0.0, []
    for i in ids:
        if cache is not None and i in cache:
            v = cache[i]
        else:
            try:
                v = -capacidad.desde_elemento(modelo, i).P_traccion
            except BaseException:
                v = None
            if cache is not None:
                cache[i] = v
        if v is None:
            sin_fierro.append(i)
        else:
            total += v
    return total, sin_fierro


def bloque_de_nucleo(modelo, ids, P_por_elemento, cache=None):
    """
    El dato que viaja con cada fila de demanda de una pata:
    de que grupo es, cuanto axial tiene el grupo entero en ESE caso, y
    cuanto puede tomar con su fierro. None si el muro no es pata.
    """
    if not ids:
        return None
    P = sum(P_por_elemento.get(i, 0.0) for i in ids)
    asfy, sin_fierro = asfy_de(modelo, ids, cache)
    return {
        'patas': len(ids),
        'P_kN': round(P, 4),
        'Asfy_kN': round(asfy, 4),
        'estado': estado(P, asfy),
        'sin_fierro': len(sin_fierro),
    }


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
