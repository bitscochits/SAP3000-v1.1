# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/laboratorio.py  -  LO QUE EL LABORATORIO LE PIDE AL EDIFICIO
================================================================
 Cinco bloques; sin bloque corre los cinco:

   python -m verificacion.laboratorio parametros               # L1
   python -m verificacion.laboratorio partes_abc [flags]       # L2
   python -m verificacion.laboratorio sismo                    # L3
   python -m verificacion.laboratorio superposicion_explicita  # L4 (lenta)
   python -m verificacion.laboratorio m2 [--cs 0.20]           # L5

 PARAMETROS. entrada/laboratorio.json es valido, y describir() --la
 HUELLA que viaja en info.parametros de cada salida y con la que Unity
 reconoce una respuesta del servidor-- sale igual caracter a caracter,
 con y sin flags. Los flags malos se rechazan con su mensaje.

 PARTES_ABC. Carga viva (Q = q_Q * A_i, que cubra toda la losa y llegue
 entera al suelo), sismo pseudoestatico (V = Cs * W, repartido por
 diafragma con el patron, revisado con calculo/sismo.py) y superposicion
 (la combinacion algebraica contra la corrida explicita, sobre TODO el
 modelo, con calculo/superposicion.py). Y las filas de equilibrio G y Q
 y de corte basal EX y EY de la tabla QA, con la cota del redondeo.

 SISMO. Los casos EX y EY DEL MODELO (los del edificio, los que resuelve
 /analizar): corte basal = aplicada por grado de libertad, sentido,
 crecimiento con la altura dentro de cada cuerpo, direccion y torsion.
 Y POR CUERPO: cada uno con su propio corte, que tiene que sumar el del
 edificio (la junta es libre, cada cuerpo baja su propio sismo).

 SUPERPOSICION_EXPLICITA. Las 11 combinaciones de laboratorio.json
 sobre los casos del modelo contra OpenSees resuelto con la carga
 combinada, en cada GDL, cada reaccion y las doce fuerzas de cada barra.
 Y la fila de la tabla QA, con la cota medida (sin el margen de 5 %).

 M2. Cambiar el coeficiente sismico (un DATO que dicta el profesor) y
 seguirlo hasta lo que muestra el panel de Unity, en memoria: G y Q
 identicos, EX y EY escalados por k, cada combinacion = sum lambda caso.

 Ninguno escribe en salidas/.
================================================================
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import math
import os
import sys
import time
from decimal import Decimal, ROUND_HALF_UP

from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo import sismo
from calculo import superposicion as sup
from verificacion.comun import Informe, titulo
from verificacion.suite import consola_tolerante, Fila, calza

BLOQUES = ('parametros', 'partes_abc', 'sismo', 'superposicion_explicita', 'm2')

CASOS = lab.CASOS_BASE
EPS = sys.float_info.epsilon

# opensees.extraer_resultados devuelve las fuerzas con 4 decimales: cada
# reaccion llega con hasta medio ultimo digito de error.
R_KN = 0.5e-4
# opensees.equilibrio devuelve error_kN redondeado a 8 decimales.
R_EQ = 0.5e-8


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


# ============================================================
# PARAMETROS
# ============================================================
# describir() es la HUELLA: su texto viaja en info.parametros de cada
# salida y en la respuesta del servidor, y Unity compara uno contra otro.
# Por eso se exige caracter a caracter, con y sin flags. Los textos de
# abajo son los que imprime con laboratorio.json tal como esta.
DESCRIBIR = {
    (): ['q_Q                 = 3.0000 kN/m2   (NCh1537 Of.2009, Tabla 4: salas de clases)',
         'coeficiente sismico = 0.1000',
         'fraccion de Q       = 0.50',
         'patron en altura    = potencia k = 1 (triangular invertido)',
         'combinacion (S3)    = 1.00 G + 0.50 Q + 1.00 EX'],
    ('--q', '2.5'): ['q_Q                 = 2.5000 kN/m2   (dictado, --q)'],
    ('--uso', 'oficinas'): ['q_Q                 = 2.5000 kN/m2   (NCh1537 Of.2009, Tabla 4: oficinas)'],
    ('--cs', '0.15', '--k', '2', '--comb', '1.2', '1.6', '1.0', '0.3'):
        ['coeficiente sismico = 0.1500',
         'patron en altura    = potencia k = 2',
         'combinacion (a mano)= 1.20 G + 1.60 Q + 1.00 EX + 0.30 EY'],
    ('--combinacion', '1.2G+1.6Q'): ['combinacion (1.2G+1.6Q)= 1.20 G + 1.60 Q'],
    ('--patron', 'manual', '--fracciones', '1', '2', '3'): ['patron en altura    = manual: 1, 2, 3'],
}

# Las once combinaciones de laboratorio.json, en su orden (es el de los
# casos de los resultados).
COMBINACIONES = [
    'S3                 1.00 G + 0.50 Q + 1.00 EX',
    '1.4G               1.40 G',
    '1.2G+1.6Q          1.20 G + 1.60 Q',
    '1.2G+1.0Q+1.4EX    1.20 G + 1.00 Q + 1.40 EX',
    '1.2G+1.0Q+1.4EY    1.20 G + 1.00 Q + 1.40 EY',
    '1.2G+1.0Q-1.4EX    1.20 G + 1.00 Q + -1.40 EX',
    '1.2G+1.0Q-1.4EY    1.20 G + 1.00 Q + -1.40 EY',
    '0.9G+1.4EX         0.90 G + 1.40 EX',
    '0.9G-1.4EX         0.90 G + -1.40 EX',
    '0.9G+1.4EY         0.90 G + 1.40 EY',
    '0.9G-1.4EY         0.90 G + -1.40 EY',
]

# Lo que no tiene sentido fisico se rechaza, con su mensaje. El ultimo
# no lo ve cargar() sino armar_casos(): el reparto manual tiene que traer
# una fraccion por diafragma.
ERRORES = [
    (('--q', '-1'), 'q_Q no puede ser negativo'),
    (('--uso', 'inexistente'), None),          # el mensaje lista la tabla de NCh1537
    (('--patron', 'raro'), "patron 'raro' desconocido: use 'potencia', 'nch433' o 'manual'"),
    (('--fq', '1.5'), 'la fraccion de Q para el peso sismico va entre 0 y 1'),
    (('--cs', 'x'), '--cs necesita un numero'),
    (('--comb', '1', '2'), '--comb necesita cuatro numeros: G Q EX EY'),
]
ERROR_AL_ARMAR = (('--patron', 'manual', '--fracciones', '1', '2', '3'),
                  'fracciones_patron trae 3 valores y el edificio tiene 10 niveles')


def _lineas(p):
    return [l.strip() for l in lab.describir(p).split('\n')]


def _error_de(argv, armar=None):
    """El mensaje con que se rechaza argv, o None si no se rechaza."""
    try:
        p = lab.cargar(list(argv))
        if armar is not None:
            lab.armar_casos(armar, p)
    except (ValueError, SystemExit) as e:
        return str(e)
    return None


def parametros(inf, args=None):
    """L1: laboratorio.json, describir() con y sin flags, y los errores."""
    p = lab.cargar([])
    print('PARAMETROS DEL LABORATORIO')
    print(lab.describir(p))
    if p['combinaciones']:
        print()
        print('  combinaciones declaradas:')
        for c in p['combinaciones']:
            print('    %-18s %s' % (c['nombre'], lab.como_texto(c)))

    titulo('DESCRIBIR(), LA HUELLA: igual caracter a caracter')
    base = _lineas(p)
    inf.check(base == DESCRIBIR[()], 'sin flags: las cinco lineas de siempre',
              [] if base == DESCRIBIR[()] else ['%r' % l for l in base])
    declaradas = ['%-18s %s' % (c['nombre'], lab.como_texto(c)) for c in p['combinaciones']]
    inf.check(declaradas == COMBINACIONES,
              'las %d combinaciones, en su orden y con sus factores' % len(declaradas))
    for argv, cambian in DESCRIBIR.items():
        if not argv:
            continue
        lineas = _lineas(lab.cargar(list(argv)))
        nuevas = [l for l, b in zip(lineas, base) if l != b]
        print('  %-48s %s' % (' '.join(argv), ' | '.join(nuevas)))
        inf.check(nuevas == cambian, '%s: cambia solo lo que tiene que cambiar' % ' '.join(argv),
                  [] if nuevas == cambian else ['esperaba %r' % cambian])

    titulo('LO QUE NO TIENE SENTIDO FISICO SE RECHAZA')
    usos = ', '.join(sorted(p['usos']))
    for argv, esperado in ERRORES:
        if esperado is None:
            esperado = 'no hay uso %r en la tabla de NCh1537. Hay: %s' % (argv[1], usos)
        msg = _error_de(argv)
        inf.check(msg == esperado, '%s -> %s' % (' '.join(argv), msg))
    argv, esperado = ERROR_AL_ARMAR
    msg = _error_de(argv, armar=_ed.estructura())
    inf.check(msg == esperado, '%s -> %s (al armar los casos: hay %d diafragmas)'
              % (' '.join(argv), msg, len(_ed.estructura().get('diafragmas', []))))


# ============================================================
# PARTES A, B Y C
# ============================================================
# Tolerancias de las verificaciones, relativas.
TOL_REACCIONES = 1e-6      # carga aplicada contra reacciones
TOL_CONSTRUCCION_Q = 1e-9  # autocontrol: cada carga de Q a q_Q exacto


def parte_a(modelo, arm, resultados, p):
    """Carga viva: Q se construyo a q_Q en cada elemento; lo que se
    verifica es que cubra toda la losa y que llegue entera al suelo."""
    q = p['q_Q']
    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}
    caso_q = arm['casos']['Q']
    aplicada = sum(lab.peso_vertical_por_nivel(modelo, caso_q))
    reacciones = sum(float(r['fz']) for r in resultados['Q']['reacciones'])
    err_reac = abs(aplicada - reacciones) / max(abs(aplicada), 1e-12)

    # Autocontrol de la construccion: cada carga, leida de vuelta, tiene
    # que dar q_Q. Si esto falla es un error del codigo, no del modelo.
    peor = 0.0
    for c in caso_q['cargas_distribuidas']:
        e = elementos[int(c['elemento'])]
        q_i = -float(c['wz']) * _ed.largo(e, nodos) / arm['con_area'][int(e['id'])]
        peor = max(peor, abs(q_i - q) / q)
    for c in caso_q['cargas_nodales']:
        A = sum(arm['con_area'][t] for t in arm['puntuales'][int(c['nodo'])])
        peor = max(peor, abs(-float(c['fz']) / A - q) / q)

    n_puntuales = sum(len(v) for v in arm['puntuales'].values())
    venia = '  y  '.join('%.4f kN/m2 en %d cargas' % (qq, n)
                         for qq, n in arm['intensidades_del_modelo'].items())

    print()
    print('[A] CARGA VIVA   q_Q = %.2f kN/m2   (%s)'
          % (q, lab.origen_q(p)))
    print('  elementos con losa  %4d   %d bajan repartidos sobre la barra, %d '
          'como carga puntual en la cabeza del muro'
          % (len(arm['con_area']), len(caso_q['cargas_distribuidas']), n_puntuales))
    print('  area tributaria     %.4f m2' % arm['area'])
    print('  el modelo traia Q a %s' % venia)
    print('  se reconstruye con q_Q en cada elemento; leida de vuelta, peor '
          'desvio %.1e' % peor)
    print('  q_Q * A                            %14.4f kN   lo que se pide'
          % (q * arm['area']))
    print('  aplicada, sum(w L) + sum(F)        %14.4f kN   identidad: asi se '
          'construyo' % aplicada)
    print('  reacciones Rz de OpenSees          %14.4f kN   lo que llega al '
          'suelo' % reacciones)
    print('  error aplicada vs reacciones       %14.3e relativo' % err_reac)
    print('  Q por diafragma [kN]: ' + ', '.join('%.2f' % w for w in arm['pesos_Q']))
    ok = err_reac < TOL_REACCIONES and peor < TOL_CONSTRUCCION_Q
    print('  %s' % ('OK' if ok else 'REVISAR'))
    return ok


def parte_b(datos, arm, resultados, p):
    """
    Sismo: carga total, corte basal, sentido de la deformada y torsion.
    La revision la hace calculo/sismo.py; aca solo se le entregan los
    casos que se acaban de construir y resolver.
    """
    print()
    print('[B] SISMO PSEUDOESTATICO   Cs = %.4f   W = G + %.2f Q   patron: %s'
          % (p['coef_sismico'], p['fraccion_Q_sismica'],
             lab.texto_patron(p)))
    print('  %8s %14s %14s %12s %12s'
          % ('cota', 'W sismico [kN]', 'reparto [%]', 'F [kN]', 'maestro'))
    for (cota, m), W, f, F in zip(arm['niveles'], arm['pesos_sismicos'],
                                  arm['factores'], arm['fuerzas']):
        print('  %+8.2f %14.2f %14.2f %12.2f %12d' % (cota, W, 100 * f, F, m))
    print('  corte basal V = Cs * sum(W) = %.4f kN;  sum(F) = %.4f kN;  '
          'diferencia %.1e' % (arm['V'], sum(arm['fuerzas']),
                               abs(arm['V'] - sum(arm['fuerzas']))))

    malos = []
    for caso in ('EX', 'EY'):
        inf = sismo.analizar(datos, arm['casos'][caso], resultados[caso], caso)
        print()
        sismo.imprimir(inf)
        malos += sismo.problemas(inf)

    print()
    if malos:
        print('  %d PROBLEMA(S):' % len(malos))
        for m in malos:
            print('    - %s' % m)
        print('  REVISAR')
        return False
    print('  la carga aplicada baja entera al suelo, cada piso va hacia donde')
    print('  lo empujan y el desplazamiento crece con la altura.')
    print('  OK')
    return True


def parte_c(datos, resultados, lambdas):
    """
    Superposicion: la combinacion algebraica contra la corrida
    explicita, sobre TODO el modelo, y los tres numeros del enunciado
    a la vista.
    """
    r = sup.verificar(lambdas, por_caso=resultados, modelo=datos)
    alg, exp = r['algebraico'], r['explicito']

    # Un nodo, un apoyo y una barra representativos: el maestro del
    # techo, el primer apoyo de la base y la primera viga.
    techo = _ed.niveles(datos)[-1][1]
    z0 = min(float(n['z']) for n in datos['nodos'])
    apoyo = next(int(n['id']) for n in datos['nodos']
                 if any(n.get('restricciones', [])) and abs(float(n['z']) - z0) < 1e-6)
    viga = next(int(e['id']) for e in datos['elementos']
                if e.get('tipo', '').startswith('viga'))

    def de(lista, i, k):
        f = next(x for x in lista if int(x['id']) == i)
        return float(f[k]) if k != 'My' else float(f['f'][4])

    print()
    print('[C] SUPERPOSICION   R = %s' % lab.como_texto(lambdas))
    print('  los tres del enunciado:')
    print('    %-34s %14s %14s %10s'
          % ('', 'superposicion', 'corrida', 'error'))
    for etiqueta, lista, i, k in (
            ('desplazamiento ux, techo (nodo %d)' % techo, 'desplazamientos', techo, 'ux'),
            ('reaccion fz, apoyo (nodo %d)' % apoyo, 'reacciones', apoyo, 'fz'),
            ('momento My, viga (elem %d)' % viga, 'fuerzas_elementos', viga, 'My')):
        a, b = de(alg[lista], i, k), de(exp[lista], i, k)
        print('    %-34s %14.8g %14.8g %10.2e' % (etiqueta, a, b, abs(a - b)))

    print('  y sobre todo el modelo (calculo/superposicion.py):')
    for clave, v in r['informe'].items():
        print('    %-20s %5d valores   peor %.2e   cota de redondeo %.2e   %s'
              % (clave, v['n_comparados'], v['peor_absoluto'],
                 v['piso_de_redondeo'], 'ok' if v['pasa'] else '<-- REVISAR'))
    print('  el desacuerdo queda bajo lo que mete el redondeo del motor: la')
    print('  superposicion no aporta error medible. K u = F es lineal.')
    print('  %s' % ('OK' if r['paso'] else 'REVISAR'))
    return r['paso']


def partes_abc(inf, args=None):
    """L2: las Partes A, B y C, y las filas de equilibrio y corte de la tabla QA."""
    argv = list(getattr(args, 'flags', None) or [])
    p = lab.cargar(argv)
    lambdas = lab.factores(p['combinacion'])
    modelo = _ed.estructura()

    print('=' * 72)
    print('  LABORATORIO   %s' % _ed.NOMBRE.upper())
    print('=' * 72)
    print('  %s' % _ed.resumen(modelo))
    print(lab.describir(p))

    arm = lab.armar_casos(modelo, p)
    datos, resultados = lab.resolver(modelo, arm['casos'])

    ok_a = parte_a(modelo, arm, resultados, p)
    ok_b = parte_b(datos, arm, resultados, p)
    ok_c = parte_c(datos, resultados, lambdas)
    ok = ok_a and ok_b and ok_c

    print()
    print('=' * 72)
    print('  %s' % ('LAS TRES PARTES CIERRAN' if ok else 'HAY ALGO QUE REVISAR'))
    print('=' * 72)
    inf.check(ok_a, '[A] carga viva: cubre toda la losa y llega entera al suelo')
    inf.check(ok_b, '[B] sismo: V = Cs W baja entero, cada piso va hacia donde lo empujan')
    inf.check(ok_c, '[C] superposicion = corrida explicita, bajo el redondeo del motor')
    if argv:
        # Con otros parametros los numeros cambian a proposito: no se
        # comparan con los de control ni se arma la tabla QA.
        return
    inf.check(calza(round(arm['area'], 4), 'laboratorio', 'area_tributaria_m2')
              and calza(round(p['q_Q'] * arm['area'], 4), 'laboratorio', 'Q_kN')
              and calza(round(arm['V'], 4), 'laboratorio', 'V_kN'),
              'A = %.4f m2, Q = %.4f kN, V = %.4f kN: los numeros de control'
              % (arm['area'], p['q_Q'] * arm['area'], arm['V']))
    # Las filas de la tabla QA con estos mismos casos: no se vuelven a resolver.
    ctx = {'modelo': modelo, 'p': p, 'arm': arm,
           'casos': {n: arm['casos'][n] for n in CASOS}, 'res': resultados}
    abiertos = []
    for nombre, hacer in (('Equilibrio G', lambda: fila_equilibrio(ctx, 'G')),
                          ('Equilibrio Q', lambda: fila_equilibrio(ctx, 'Q')),
                          ('Corte basal EX', lambda: fila_corte(ctx, 'EX')),
                          ('Corte basal EY', lambda: fila_corte(ctx, 'EY'))):
        titulo(nombre.upper())
        _sumar_fila(inf, hacer(), abiertos)


def _sumar_fila(inf, fila, abiertos):
    """Lo que una fila de la tabla QA no cumplio pasa al informe del bloque."""
    inf.fallas.extend('%s: %s' % (fila.prueba, x) for x in fila.fallas)
    abiertos.extend('%s: %s' % (fila.prueba, x) for x in fila.abiertos)


# ============================================================
# LA TABLA QA: equilibrio G y Q, corte basal EX y EY, superposicion
# ============================================================
def g_por_cuerpo(modelo):
    """{cuerpo: G aplicada} con el caso G de cada cuerpo, partido por rango de tag."""
    salida = {}
    for cuerpo, sub in _ed.por_cuerpo(modelo).items():
        caso = next(c for c in sub['casos_de_carga'] if c['nombre'] == 'G')
        salida[cuerpo] = -opensees.equilibrio(sub, caso, {'reacciones': []})['aplicada_kN'][2]
    return salida


def fila_equilibrio(ctx, nombre):
    f = Fila('Equilibrio %s' % nombre, 'python -m verificacion.laboratorio partes_abc')
    modelo, caso, res = ctx['modelo'], ctx['casos'][nombre], ctx['res'][nombre]
    eq = opensees.equilibrio(modelo, caso, res)
    nx, ny, nz = opensees.filas_que_cuentan(modelo, res['reacciones'])
    a, r, e = eq['aplicada_kN'], eq['reaccion_kN'], eq['error_kN']
    cota = [n * R_KN + R_EQ for n in (nx, ny, nz)]
    f.check(eq['confiable'], 'opensees.equilibrio convirtio todas las cargas '
            '(%d sin convertir)' % eq['cargas_sin_convertir'])
    f.check(all(abs(e[i]) <= cota[i] for i in range(3)),
            'aplicada %.4f kN, reaccion %.4f kN, error %.2e kN (cota del '
            'redondeo %.2e: %d apoyos x 0.5e-4)' % (a[2], r[2], abs(e[2]), cota[2], nz),
            'en x e y: error %.1e / %.1e kN (cotas %.1e / %.1e)'
            % (abs(e[0]), abs(e[1]), cota[0], cota[1]))
    if nombre == 'G':
        # El edificio es la suma de sus cuerpos: el G de cada uno sale de
        # sus propias cargas (por rango de tag), y los tres tienen que ser
        # los numeros de control.
        g = g_por_cuerpo(modelo)
        g['conjunto'] = -a[2]
        f.check(calza(g['ingenieria'], 'edificio', 'G_por_cuerpo_kN', 'ingenieria')
                and calza(g['lt2'], 'edificio', 'G_por_cuerpo_kN', 'lt2')
                and calza(g['conjunto'], 'edificio', 'G_kN')
                and abs(g['conjunto'] - g['lt2'] - g['ingenieria']) <= 0.005,
                'G = %.2f kN = %.2f (Ingenieria) + %.2f (LT2), cada cuerpo por su rango de tag; '
                'los tres son los numeros de control (verificacion/numeros_de_control.json)'
                % (g['conjunto'], g['ingenieria'], g['lt2']))
    else:
        f.info('Q del laboratorio: q = %.1f kN/m2 uniforme por area tributaria '
               '(entrada/laboratorio.json), el que muestra Unity' % ctx['p']['q_Q'])
    f.numero = 'error %.1e kN de %.2f kN (cota %.1e)' % (abs(e[2]), -a[2], cota[2])
    f.criterio = '|aplicada + reaccion| <= apoyos que cuentan x 0.5e-4 kN'
    return f


def fila_corte(ctx, nombre):
    f = Fila('Corte basal %s' % nombre, 'python -m verificacion.laboratorio partes_abc')
    modelo, p, arm = ctx['modelo'], ctx['p'], ctx['arm']
    caso, res = ctx['casos'][nombre], ctx['res'][nombre]
    i = 0 if nombre == 'EX' else 1
    eq = opensees.equilibrio(modelo, caso, res)
    n = opensees.filas_que_cuentan(modelo, res['reacciones'])
    a, r, e = eq['aplicada_kN'], eq['reaccion_kN'], eq['error_kN']
    cota = n[i] * R_KN + R_EQ
    f.check(abs(e[i]) <= cota,
            'carga lateral %.4f kN, corte en los apoyos %.4f kN, error %.2e kN '
            '(cota %.2e: %d apoyos fuera de diafragma x 0.5e-4)'
            % (a[i], r[i], abs(e[i]), cota, n[i]))

    # El peso sismico, controlado por fuera de armar_casos: G y Q se
    # suman de sus propios casos y V tiene que ser Cs * (G + fQ * Q).
    G = -opensees.equilibrio(modelo, ctx['casos']['G'], ctx['res']['G'])['aplicada_kN'][2]
    Q = -opensees.equilibrio(modelo, ctx['casos']['Q'], ctx['res']['Q'])['aplicada_kN'][2]
    W = G + p['fraccion_Q_sismica'] * Q
    V = sum(float(c.get('fx' if i == 0 else 'fy', 0.0)) for c in caso['cargas_nodales'])
    cota_v = len(caso['cargas_nodales']) * 4 * EPS * W
    f.check(abs(V - p['coef_sismico'] * W) <= max(cota_v, 5e-5),
            'V = %.4f kN = Cs x W = %.2f x (%.4f + %.2f x %.4f) = %.2f x %.4f'
            % (V, p['coef_sismico'], G, p['fraccion_Q_sismica'], Q, p['coef_sismico'], W),
            'G y Q sumados de sus propios casos: no se pierde peso al repartirlo por nivel')

    # El reparto en altura: el patron declarado (potencia, k = 1) es
    # F_i proporcional a W_i * h_i. El equilibrio no ve un reparto
    # equivocado mientras el total se conserve.
    k = p['k_patron']
    cte = [F / (w * h ** k) for F, w, h in zip(arm['fuerzas'], arm['pesos_sismicos'],
                                               arm['alturas']) if w * h > 0]
    desvio = max(rel(c, cte[0]) for c in cte)
    f.check(desvio <= 1e-12,
            'reparto %s k = %g: F_i / (W_i h_i^k) = %.7f en los %d diafragmas '
            '(desvio %.1e)' % (p['patron'], k, cte[0], len(cte), desvio))

    todo = sum(float(x.get('fx' if i == 0 else 'fy', 0.0)) for x in res['reacciones'])
    f.info('sumar la columna entera de reacciones daria %.2f kN (x%.2f): los nodos '
           'de diafragma reaccionan tambien a su restriccion, y no se hace' % (todo, abs(todo / r[i])))
    disco = rutas.salida('casos_del_modelo')
    if os.path.isfile(disco):
        with io.open(disco, encoding='utf-8') as fh:
            del_modelo = {c['nombre']: c for c in json.load(fh)['casos']}
        if nombre in del_modelo:
            c_mod = next(c for c in modelo['casos_de_carga'] if c['nombre'] == nombre)
            eq_m = opensees.equilibrio(modelo, c_mod, del_modelo[nombre])
            f.info('el %s de los casos del modelo (%s, el que imprime revisar sismo) aplica %.3f kN '
                   'y tambien cierra (error %.1e kN): otro peso sismico, ver '
                   'supuestos.casos_del_modelo' % (nombre, rutas.relativa(disco).replace(os.sep, '/'),
                                                    eq_m['aplicada_kN'][i], abs(eq_m['error_kN'][i])))
    f.numero = 'V = %.2f kN = 0.10 W; error %.1e kN (cota %.1e)' % (a[i], abs(e[i]), cota)
    f.criterio = '|V + corte| <= apoyos x 0.5e-4; V = Cs(G + fQ Q); F_i ~ W_i h_i'
    return f


def fila_superposicion(ctx, por_caso=None):
    f = Fila('Superposicion', 'python -m verificacion.laboratorio superposicion_explicita')
    modelo, p = ctx['modelo'], ctx['p']
    if por_caso is None:
        por_caso = sup.resolver_todos(modelo)
    peor = (0.0, None)
    n_comp = pasa_margen = 0
    for comb in p['combinaciones']:
        lam = {c: float(comb.get(c, 0.0)) for c in CASOS}
        with contextlib.redirect_stdout(io.StringIO()), opensees.AvisosDeOpenSees():
            v = sup.verificar(lam, por_caso=por_caso, modelo=modelo)
        suma = sum(abs(x) for x in lam.values())
        for familia, inf in v['informe'].items():
            n_comp += 1
            # La cota de superposicion.verificar (piso_de_redondeo) mas la
            # coma flotante de sumar con esos factores. Sin el margen de 5 %
            # que verificar() elige a mano.
            cota = inf['piso_de_redondeo'] + 4 * EPS * suma * max(inf['escala'], 1.0)
            cociente = inf['peor_absoluto'] / cota if cota else 0.0
            if inf['peor_absoluto'] > inf['piso_de_redondeo']:
                pasa_margen += 1
            if cociente > peor[0]:
                peor = (cociente, '%s, %s: %.2e contra %.2e'
                        % (comb['nombre'], familia, inf['peor_absoluto'], cota))
            if inf['peor_absoluto'] > cota:
                f.check(False, '%s %s: %.3e > cota %.3e'
                        % (comb['nombre'], familia, inf['peor_absoluto'], cota))
    f.check(not f.fallas,
            '%d combinaciones x 3 familias (desplazamientos, reacciones, fuerzas '
            'localForce) = %d comparaciones con OpenSees resuelto con la carga '
            'combinada, todas dentro del redondeo del servidor + coma flotante'
            % (len(p['combinaciones']), n_comp),
            'peor cociente error/cota = %.6f (%s)' % peor)
    if pasa_margen:
        f.info('%d de %d pasan el piso de redondeo solo por coma flotante (menos de 1 '
               'ulp): superposicion.verificar los deja pasar con un margen de 5 %% elegido a '
               'mano; aca se usa la cota medida' % (pasa_margen, n_comp))
    f.numero = '%d/%d dentro de la cota; peor %.3f de la cota' % (n_comp - len(f.fallas), n_comp, peor[0])
    f.criterio = '|suma - explicita| <= 0.5x10^-d (sum|lambda| + 1) + 4 eps sum|lambda| |valor|'
    return f


# ============================================================
# EL SISMO DEL MODELO, Y POR CUERPO
# ============================================================
def _del_cuerpo(res, sub):
    """El resultado del edificio restringido a los nodos de un cuerpo."""
    ids = {int(n['id']) for n in sub['nodos']}
    out = dict(res)
    for k in ('desplazamientos', 'reacciones'):
        out[k] = [x for x in res.get(k, []) if int(x['id']) in ids]
    return out


def sismo_del_modelo(inf, args=None):
    """L3: el sismo de los casos del modelo, en el edificio y en cada cuerpo."""
    casos = list(sismo.LATERALES)
    print('=' * 74)
    print('  SISMO PSEUDOESTATICO EN %s' % _ed.NOMBRE.upper())
    print('=' * 74)

    malos = []
    modelo = _ed.estructura()
    resueltos, _avisos = opensees.resolver_edificio(modelo)
    informes = {}
    for caso in casos:
        informes[caso] = sismo.revisar(caso, modelo, resueltos)
        print()
        sismo.imprimir(informes[caso])
        malos += sismo.problemas(informes[caso])

    print()
    print('=' * 74)
    if malos:
        print('  %d PROBLEMA(S)' % len(malos))
        for m in malos:
            print('    - %s' % m)
    else:
        print('  LA DEFORMADA VA HACIA DONDE EMPUJA, CRECE CON LA ALTURA Y EL')
        print('  CORTE BASAL CIERRA')
    print('=' * 74)
    for m in malos:
        inf.check(False, m)
    if not malos:
        inf.check(True, 'EX y EY del modelo: corte = aplicada, sentido, crecimiento por cuerpo, direccion')

    # ---- POR CUERPO --------------------------------------------------
    # La junta es libre: cada cuerpo baja SU sismo por SUS apoyos. Se parte
    # el edificio por rango de tag y se revisa cada cuerpo con su propia
    # carga y los resultados de sus nodos (los mismos del edificio).
    por_caso = {r['caso']: r for r in resueltos}
    partes = _ed.por_cuerpo(modelo)
    suma = {c: [0.0, 0.0] for c in casos}
    for cuerpo, sub in partes.items():
        print()
        print('=' * 74)
        print('  SISMO PSEUDOESTATICO EN %s (tags %dxxxxx, del edificio)'
              % (cuerpo.upper(), next(k for k, v in _ed.CUERPOS.items() if v == cuerpo)))
        print('=' * 74)
        for caso in casos:
            c_sub = next(c for c in sub['casos_de_carga'] if c['nombre'] == caso)
            r_sub = _del_cuerpo(por_caso[caso], sub)
            i_sub = sismo.analizar(sub, c_sub, r_sub, caso, cuerpo)
            print()
            sismo.imprimir(i_sub)
            malos_sub = sismo.problemas(i_sub)
            idx = 0 if caso == 'EX' else 1
            n = opensees.filas_que_cuentan(sub, r_sub['reacciones'])[idx]
            cota = n * R_KN + R_EQ
            err = abs(i_sub['aplicado_kN'] + i_sub['corte_basal_kN'])
            suma[caso][0] += i_sub['aplicado_kN']
            suma[caso][1] += i_sub['corte_basal_kN']
            inf.check(not malos_sub and err <= cota,
                      '%s %s: corte basal = aplicada %.4f kN (error %.1e <= cota %.1e: %d apoyos '
                      'x 0.5e-4); sentido, crecimiento y direccion'
                      % (cuerpo, caso, i_sub['aplicado_kN'], err, cota, n), malos_sub[:3])
            inf.check(calza(round(i_sub['aplicado_kN'], 4), 'edificio', 'V_del_modelo_por_cuerpo_kN', cuerpo),
                      '%s %s: %.4f kN es el corte del modelo de este cuerpo (numero de control)'
                      % (cuerpo, caso, i_sub['aplicado_kN']))
    print()
    for caso in casos:
        ap, co = suma[caso]
        e = informes[caso]
        inf.check(abs(ap - e['aplicado_kN']) <= 1e-6 and abs(co - e['corte_basal_kN']) <= 1e-6,
                  '%s: la suma de los cuerpos es el edificio: aplicada %.4f = %.4f, corte %.4f = %.4f kN'
                  % (caso, ap, e['aplicado_kN'], co, e['corte_basal_kN']))


# ============================================================
# SUPERPOSICION CONTRA LA CORRIDA EXPLICITA
# ============================================================
def superposicion_explicita(inf, args=None):
    """L4: las 11 combinaciones contra OpenSees resuelto con la carga combinada."""
    rc = sup.main([])
    inf.check(rc == 0, 'superposicion.main: las %d combinaciones de laboratorio.json bajo su cota'
              % len(lab.cargar([])['combinaciones']))
    modelo = _ed.estructura()
    ctx = {'modelo': modelo, 'p': lab.cargar([])}
    titulo('SUPERPOSICION (la fila de la tabla QA: la cota medida, sin margen)')
    abiertos = []
    _sumar_fila(inf, fila_superposicion(ctx), abiertos)


# ============================================================
# M2: EL COEFICIENTE SISMICO, POR DATO
# ============================================================
# Arma en memoria dos juegos de resultados con exportar/resultados.construir
# --la MISMA funcion que escribe salidas/resultados.json--, uno con los
# parametros de laboratorio.json y otro con --cs, y los compara. SIN
# ESCRIBIR NADA. Para verlo EN Unity (eso si escribe salidas/):
#
#   python sap.py exportar resultados --cs 0.20 && python sap.py sincronizar
#
# QUE COMPRUEBA. El caso EX es V = Cs * W repartido en altura
# (laboratorio.armar_casos): Cs no entra en G ni en Q, y entra LINEAL en
# EX y EY. El modelo es elastico lineal, asi que:
#
# - G y Q salen IDENTICOS (desplazamientos, f de cada barra, estaciones y
#   demandas), bit a bit;
# - EX y EY se escalan por k = Cs nuevo / Cs base. Cota: cada numero viene
#   redondeado (fuerzas a 4 decimales, desplazamientos a 8), y el escalado
#   multiplica el redondeo de la base por k: 5e-5 (1 + k) kN en f y w,
#   5e-9 (1 + k) m; en las estaciones del diagrama My(x) lleva ademas
#   x * V_i, la cota de esfuerzos.cota_de_cierre (ver diferencias());
# - cada combinacion es la suma lambda * caso de SUS resultados. Cota: el
#   redondeo de la combinacion mas el de cada termino, 5e-5 (1 + sum|lambda|);
# - los resultados base en memoria son los que Unity lee hoy
#   (salidas/resultados.json), si son de los mismos parametros;
# - G de POST /analizar (el modelo del visor, salidas/modelo.json) es el G
#   de los resultados. Q, EX y EY NO lo son (la otra fuente de casos): se
#   imprimen para declararlo, no se exigen.
#
# Despues imprime, para la columna demo y el muro demo (los elige
# construir() por regla: la columna de mayor axial en G y el muro mas
# largo), las lineas del panel del visor --P, M, Mn, u = M/Mn (el D/C) y
# PASA-- antes y despues, en todos los casos.
COTA_REDONDEO_kN = es.COTA_REDONDEO                         # 5e-5: 4 decimales
COTA_REDONDEO_m = 0.5 * 10.0 ** -es.DECIMALES_DESPLAZAMIENTO    # 5e-9: 8 decimales
MAGNITUDES = ('N', 'Vy', 'Vz', 'T', 'My', 'Mz')


def armar(argv):
    """(resultados, contexto, segundos, lineas que OpenSees escribio por stderr)."""
    from exportar import resultados
    t0 = time.time()
    with opensees.AvisosDeOpenSees() as avisos:
        anexo, ctx = resultados.construir(argv)
    return anexo, ctx, time.time() - t0, avisos.texto.splitlines()


# MOVER A verificacion/comun.py (texto_net): tambien lo usan las capturas y M1.
def F(v, formato):
    """
    VisorResultados.Panel.F: v.ToString(formato, InvariantCulture) con v
    float de 32 bits. .NET redondea los digitos de la forma corta del
    float, con la mitad hacia afuera.
    """
    decimales = len(formato.split('.')[1]) if '.' in formato else 0
    try:
        import numpy as np
        corto = np.format_float_positional(np.float32(v), unique=True, trim='-')
    except ImportError:                                  # sin numpy: doble
        corto = repr(float(v))
    q = Decimal(corto).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    return format(q, 'f')


def lineas_del_panel(d, e, fam):
    """Las dos lineas de '--- demanda / capacidad ---' del panel."""
    cual = (' (|%s|, en su plano)' % e['momento_en_el_plano']) if e['tipo'] == 'muro' else ''
    l1 = 'P %s kN   M %s kN*m%s   extremo %s' % (F(d['P'], '0.0'), F(d['M'], '0.0'),
                                                  cual, d['extremo'])
    if d['u'] >= 9999.0:
        l2 = 'fuera de la curva P-M (u = 9999)'
    else:
        l2 = 'Mn %s kN*m   u %s   %s' % (F(d['Mn'], '0.0'), F(d['u'], '0.000'),
                                         'PASA' if d['pasa'] else 'NO PASA')
    return ['familia %d: %s' % (fam['indice'], fam['clave']), l1, l2]


def por_id(lista):
    return {int(x['id']): x for x in lista}


def diferencias(a, b, k=1.0):
    """
    b contra k*a, dos bloques de caso. Devuelve
    {'m': (cociente, error, cota, donde), 'kN': (...), 'max_m', 'max_kN'}
    con el peor error/cota y el peor error absoluto.

    Cotas, por su causa: b y a vienen redondeados, a lo mas 5e-5 kN
    (5e-9 m) cada uno, y el de a queda multiplicado por k:
      - desplazamientos, f y w:  redondeo * (1 + k);
      - estaciones (N, V, T, My, Mz en x): se calculan con f ya
        redondeado y se redondean otra vez, y My y Mz llevan x*V_i, que
        multiplica el redondeo de V_i por x. Es la cota con que el
        exportador exige que el diagrama llegue a f_j, en cada x y con
        sum|lambda| = 1 + k: esfuerzos.cota_de_cierre(x, 1 + k).
    Mas 4 eps del tamano de los terminos (esfuerzos.FACTOR_COMA_FLOTANTE).
    """
    eps = es.FACTOR_COMA_FLOTANTE
    salida = {'m': (0.0, 0.0, 0.0, None), 'kN': (0.0, 0.0, 0.0, None),
              'max_m': 0.0, 'max_kN': 0.0}

    def anotar(tipo, vb, va, cota, donde):
        error = abs(vb - k * va)
        cota = cota + eps * (abs(vb) + abs(k * va))
        salida['max_' + tipo] = max(salida['max_' + tipo], error)
        if error / cota > salida[tipo][0]:
            salida[tipo] = (error / cota, error, cota, donde)

    da, db = por_id(a['desplazamientos']), por_id(b['desplazamientos'])
    ea, eb = por_id(a['esfuerzos']), por_id(b['esfuerzos'])
    if set(da) != set(db) or set(ea) != set(eb):
        salida['m'] = salida['kN'] = (math.inf, math.inf, 0.0, 'nodos o elementos distintos')
        return salida
    for nid, x in da.items():
        for c in ('ux', 'uy', 'uz', 'rx', 'ry', 'rz'):
            anotar('m', db[nid][c], x[c], COTA_REDONDEO_m * (1 + k), (nid, c))
    for eid, x in ea.items():
        y = eb[eid]
        if x['x'] != y['x']:
            salida['kN'] = (math.inf, math.inf, 0.0, (eid, 'estaciones distintas'))
            return salida
        for c in ('f', 'w'):
            for i, (va, vb) in enumerate(zip(x[c], y[c])):
                anotar('kN', vb, va, COTA_REDONDEO_kN * (1 + k), (eid, c, i))
        for i, xs in enumerate(x['x']):
            cotas = es.cota_de_cierre(xs, 1 + k)
            for j, c in enumerate(MAGNITUDES):
                anotar('kN', y[c][i], x[c][i], cotas[j], (eid, c, 'x = %.2f' % xs))
    return salida


def demandas_iguales(a, b):
    """Cuantas demandas difieren en algo (P, M, Mn, u, pasa, extremo)."""
    da, db = por_id(a['demandas']), por_id(b['demandas'])
    if set(da) != set(db):
        return -1
    return sum(1 for i in da if da[i] != db[i])


def combinacion_menos_suma(anexo, combo):
    """
    Peor |combinacion - sum lambda * caso| dentro de UNOS resultados, en f y
    en desplazamientos. Devuelve (peor_m, peor_kN, sum|lambda|).
    """
    casos = {c['nombre']: c for c in anexo['casos']}
    lambdas = dict(zip(es.CASOS_BASE, combo['factores']))
    activos = {c: l for c, l in lambdas.items() if l != 0.0}
    base_d = {c: por_id(casos[c]['desplazamientos']) for c in activos}
    base_e = {c: por_id(casos[c]['esfuerzos']) for c in activos}
    pm = pk = 0.0
    for d in combo['desplazamientos']:
        for k in ('ux', 'uy', 'uz', 'rx', 'ry', 'rz'):
            suma = sum(l * base_d[c][int(d['id'])][k] for c, l in activos.items())
            pm = max(pm, abs(d[k] - suma))
    for s in combo['esfuerzos']:
        for i, v in enumerate(s['f']):
            suma = sum(l * base_e[c][int(s['id'])]['f'][i] for c, l in activos.items())
            pk = max(pk, abs(v - suma))
    return pm, pk, sum(abs(l) for l in activos.values())


def flask_contra_anexo(ctx, check):
    """
    Lo que resuelve POST /analizar (el modelo del visor, salidas/modelo.json,
    el que Unity manda al editar) contra los casos base de los resultados. Es
    la limitacion que se declara: los dos arman G igual, pero Q y el sismo
    salen de fuentes distintas (el visor: los casos del modelo; los
    resultados: entrada/laboratorio.json). Solo G se exige igual. Cota: cada
    lado viene redondeado a 8 decimales por el servidor, 2 * 5e-9 m.
    """
    ruta = rutas.salida('modelo')
    if not os.path.isfile(ruta):
        print('    [AVISO] no existe %s: no se compara con /analizar'
              % os.path.relpath(ruta, rutas.RAIZ))
        return
    with open(ruta, encoding='utf-8') as f:
        modelo_u = json.load(f)
    with opensees.LOCK:
        rf = opensees.construir_y_resolver(copy.deepcopy(modelo_u))
    flask = {c['nombre']: c for c in rf.get('casos') or []}
    casos_u = {c['nombre']: c for c in modelo_u.get('casos_de_carga') or []}
    print()
    print('  /analizar (%s, lo que manda Unity) CONTRA LOS CASOS BASE DE LOS RESULTADOS'
          % os.path.relpath(ruta, rutas.RAIZ))
    print('    (max = mayor componente en mm; peor dif = mayor |u /analizar - u resultados| en m)')
    print('    %-4s  %-32s | %-32s   %9s | %9s   %s'
          % ('caso', 'aplicada /analizar [Fx,Fy,Fz]', 'aplicada result. [Fx,Fy,Fz] kN',
             'max /anal', 'max resul', 'peor dif'))
    peor_G = math.inf
    for c in es.CASOS_BASE:
        if c not in flask or c not in ctx['resultados']:
            print('    %-4s  (falta en uno de los dos)' % c)
            continue
        a = por_id(ctx['resultados'][c]['desplazamientos'])
        b = por_id(flask[c]['desplazamientos'])
        peor = (max(abs(float(a[i][k]) - float(b[i][k]))
                    for i in a for k in ('ux', 'uy', 'uz'))
                if set(a) == set(b) else math.inf)
        ea = opensees.equilibrio(ctx['modelo'], ctx['arm']['casos'][c],
                                 ctx['resultados'][c])['aplicada_kN']
        eb = opensees.equilibrio(modelo_u, casos_u[c], flask[c])['aplicada_kN']
        print('    %-4s  [%8.2f, %8.2f, %10.2f] | [%8.2f, %8.2f, %10.2f]   %9.5f | %9.5f   %.1e'
              % (c, *eb, *ea, flask[c]['max_desplazamiento'] * 1000,
                 ctx['resultados'][c]['max_desplazamiento'] * 1000, peor))
        if c == 'G':
            peor_G = peor
    check(peor_G <= 2 * COTA_REDONDEO_m,
          'G de /analizar = G de los resultados (Q, EX y EY no: ver la tabla)',
          'peor %.1e m <= %.1e' % (peor_G, 2 * COTA_REDONDEO_m))


def m2(inf, args=None):
    """L5: el coeficiente sismico cambiado por dato, en memoria."""
    flags = list(getattr(args, 'flags', None) or [])
    cs = float(flags[flags.index('--cs') + 1]) if '--cs' in flags else 0.20
    print('=' * 78)
    print('  M2 POR DATO  %s   resultados base  vs  resultados con --cs %.2f   (en memoria)'
          % (_ed.NOMBRE.upper(), cs))
    print('=' * 78)
    base, ctx0, t0, ruido0 = armar([])
    nuevo, ctx1, t1, ruido1 = armar(['--cs', repr(cs)])
    cs0, cs1 = ctx0['p']['coef_sismico'], ctx1['p']['coef_sismico']
    k = cs1 / cs0
    print('  exportar/resultados.construir: base %.1f s, nuevo %.1f s' % (t0, t1))
    n_avisos = sum(1 for l in ruido0 + ruido1 if 'converge' in l.lower())
    print('  avisos de OpenSees desviados: %d lineas (%d con "converge"), '
          'de la busqueda de curvas P-M' % (len(ruido0) + len(ruido1), n_avisos))

    def check(cond, texto, detalle=''):
        print('    [%s] %s%s' % ('OK  ' if cond else 'FALLA', texto,
                                 ('   ' + detalle) if detalle else ''))
        if not cond:
            inf.fallas.append(texto)

    # ---------------------------------------------------------- el dato
    print()
    print('  EL DATO QUE CAMBIA  (info.parametros de los resultados, lo que Unity deserializa)')
    for a, b in zip(base['info']['parametros'], nuevo['info']['parametros']):
        print('    %-58s | %s%s' % (a, b, '   <-- cambia') if a != b else '    %s' % a)
    print('    corte basal V = Cs * W:  %.2f kN  ->  %.2f kN   (x %.4f)'
          % (ctx0['arm']['V'], ctx1['arm']['V'], ctx1['arm']['V'] / ctx0['arm']['V']))

    # ---------------------------------------------------------- casos
    c0 = {c['nombre']: c for c in base['casos']}
    c1 = {c['nombre']: c for c in nuevo['casos']}
    print()
    print('  MAXIMO POR CASO  (max_desplazamiento_mm de los resultados: la NORMA del desplazamiento)')
    for nombre in c0:
        m0, m1 = c0[nombre]['max_desplazamiento_mm'], c1[nombre]['max_desplazamiento_mm']
        n0 = sum(1 for d in c0[nombre]['demandas'] if not d['pasa'])
        n1 = sum(1 for d in c1[nombre]['demandas'] if not d['pasa'])
        print('    %-18s %10.4f -> %10.4f mm  (x %.4f)   NO PASA %3d -> %3d de %d'
              % (nombre, m0, m1, m1 / m0 if m0 else 0.0, n0, n1, len(c1[nombre]['demandas'])))

    # ---------------------------------------------------------- comprobaciones
    print()
    print('  COMPROBACIONES')
    check(list(c0) == list(c1)
          and [e['id'] for e in base['elementos']] == [e['id'] for e in nuevo['elementos']]
          and len(base['familias']) == len(nuevo['familias']),
          'mismos casos, elementos y familias P-M',
          '%d casos, %d elementos, %d familias'
          % (len(c1), len(nuevo['elementos']), len(nuevo['familias'])))
    for nombre in ('G', 'Q'):
        dif = diferencias(c0[nombre], c1[nombre])
        nd = demandas_iguales(c0[nombre], c1[nombre])
        check(dif['max_m'] == 0.0 and dif['max_kN'] == 0.0 and nd == 0,
              '%s identico (no depende de Cs)' % nombre,
              'peor %.1e m, %.1e kN; demandas distintas %d' % (dif['max_m'], dif['max_kN'], nd))
    for nombre in ('EX', 'EY'):
        dif = diferencias(c0[nombre], c1[nombre], k)
        check(dif['m'][0] <= 1.0 and dif['kN'][0] <= 1.0,
              '%s nuevo = %.4g * %s base' % (nombre, k, nombre),
              'peor error/cota: %.2f en m (%.1e en %s), %.2f en kN (%.1e <= %.1e en %s)'
              % (dif['m'][0], dif['m'][1], dif['m'][3],
                 dif['kN'][0], dif['kN'][1], dif['kN'][2], dif['kN'][3]))
    for anexo, etiqueta in ((base, 'base'), (nuevo, 'nuevo')):
        # El peor se elige por cociente error / cota: cada combinacion
        # tiene su propia cota (su sum|lambda|).
        peor = (-1.0, 0.0, 0.0, 0.0, '')
        for combo in anexo['casos']:
            if combo['tipo'] != 'combinacion':
                continue
            pm, pk, sl = combinacion_menos_suma(anexo, combo)
            cociente = max(pm / (COTA_REDONDEO_m * (1 + sl)),
                           pk / (COTA_REDONDEO_kN * (1 + sl)))
            if cociente > peor[0]:
                peor = (cociente, pm, pk, COTA_REDONDEO_kN * (1 + sl), combo['nombre'])
        check(0.0 <= peor[0] <= 1.0,
              'resultados %s: cada combinacion = sum lambda * casos' % etiqueta,
              'peor %s: %.1e m, %.1e kN <= %.1e = 5e-5 (1 + sum|lambda|); error/cota %.2f'
              % (peor[4], peor[1], peor[2], peor[3], peor[0]))

    # ---------------------------------------------------------- Unity hoy
    ruta_hoy = rutas.salida('resultados')
    if os.path.isfile(ruta_hoy):
        with open(ruta_hoy, encoding='utf-8') as f:
            hoy = json.load(f)
        mismo = (hoy['info'].get('edificio') == _ed.NOMBRE
                 and hoy['info'].get('parametros') == base['info']['parametros'])
        if not mismo:
            print('    [AVISO] %s es de %r con otros parametros: el "antes" de Unity no es '
                  'este. Exportar: python sap.py exportar resultados'
                  % (rutas.relativa(ruta_hoy), hoy['info'].get('edificio')))
        else:
            h = {c['nombre']: c for c in hoy['casos']}
            distintos = [n for n in c0 if n not in h
                         or h[n]['max_desplazamiento_mm'] != c0[n]['max_desplazamiento_mm']
                         or demandas_iguales(h[n], c0[n]) != 0]
            check(not distintos,
                  'los resultados base son los que Unity lee hoy (%s)'
                  % rutas.relativa(ruta_hoy).replace(os.sep, '/'),
                  'maximos y demandas de los %d casos iguales' % len(c0) if not distintos
                  else 'difieren: %s' % ', '.join(distintos))
    else:
        print('    [AVISO] no hay %s: no se compara con lo que lee Unity' % rutas.relativa(ruta_hoy))

    # ---------------------------------------------------------- /analizar contra los resultados
    flask_contra_anexo(ctx0, check)

    # ---------------------------------------------------------- el panel
    info = nuevo['info']
    elementos = por_id(nuevo['elementos'])
    for etiqueta, eid in (('COLUMNA DEMO', info['columna_demo']), ('MURO DEMO', info['muro_demo'])):
        print()
        e = elementos.get(eid)
        if e is None or e['familia'] < 0:
            print('  %s %s: sin enfierradura, no hay demanda-capacidad' % (etiqueta, eid))
            continue
        fam = nuevo['familias'][e['familia']]
        print('  %s %d  (%s %s, familia %d)   D/C = u = M / Mn(P)'
              % (etiqueta, eid, e['tipo'], e['seccion'], e['familia']))
        print('    caso                P antes -> despues     M antes -> despues'
              '      Mn antes -> despues      u antes -> despues')
        peor_caso, peor_u = None, -1.0
        for nombre in c1:
            d0 = por_id(c0[nombre]['demandas']).get(eid)
            d1 = por_id(c1[nombre]['demandas']).get(eid)
            if d0 is None or d1 is None:
                continue
            if d1['u'] > peor_u:
                peor_caso, peor_u = nombre, d1['u']
            print('    %-18s %9.1f -> %9.1f  %9.1f -> %9.1f  %8.1f -> %8.1f  %6.3f -> %6.3f  %s'
                  % (nombre, d0['P'], d1['P'], d0['M'], d1['M'], d0['Mn'], d1['Mn'],
                     d0['u'], d1['u'], 'PASA' if d1['pasa'] else 'NO PASA'))
        for nombre in dict.fromkeys([info['caso_por_defecto'], peor_caso]):
            d0 = por_id(c0[nombre]['demandas'])[eid]
            d1 = por_id(c1[nombre]['demandas'])[eid]
            print('    panel de Unity, caso %s%s:' % (nombre, ' (el que abre el visor)'
                                                      if nombre == info['caso_por_defecto']
                                                      else ' (el mayor u con el Cs nuevo)'))
            for a, b in zip(lineas_del_panel(d0, e, fam), lineas_del_panel(d1, e, fam)):
                if b == a:
                    print('      igual   %s' % a)
                else:
                    print('      antes   %s' % a)
                    print('      despues %s' % b)

    print()
    print('  No se escribio nada en salidas/ ni en StreamingAssets/.')


# ============================================================
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='python -m verificacion.laboratorio',
                                 description='Lo que el laboratorio le pide al edificio: parametros, '
                                             'partes A/B/C, sismo, superposicion y M2')
    ap.add_argument('bloques', nargs='*', metavar='bloque',
                    help='%s (sin bloque: los cinco)' % ', '.join(BLOQUES))
    # Los flags de los parametros (--q --uso --cs --fq --patron --k --fracciones
    # --comb --combinacion) los toma partes_abc; m2 toma solo --cs (el
    # coeficiente de los resultados nuevos, 0.20 si no viene); los demas
    # bloques usan los de laboratorio.json.
    # Los bloques primero: un flag desconocido para argparse (--cs 0.2) le
    # dejaria su valor como si fuera un bloque.
    argv = [x for x in argv if x in BLOQUES] + [x for x in argv if x not in BLOQUES]
    a, resto = ap.parse_known_args(argv)
    malos = [b for b in a.bloques if b not in BLOQUES]
    if malos:
        ap.error('bloque desconocido: %s (son: %s)' % (', '.join(malos), ', '.join(BLOQUES)))
    a.flags = resto
    hacer = {'parametros': parametros, 'partes_abc': partes_abc, 'sismo': sismo_del_modelo,
             'superposicion_explicita': superposicion_explicita, 'm2': m2}
    consola_tolerante()
    t0 = time.time()
    inf = Informe()
    for b in (a.bloques or BLOQUES):
        hacer[b](inf, a)
    print('  (%.0f s)' % (time.time() - t0))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
