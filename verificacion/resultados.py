# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/resultados.py  -  LOS RESULTADOS DEL VISOR CONTRA OPENSEES
================================================================
 Cinco bloques; sin bloque corre los cinco:

   python -m verificacion.resultados al_dia [flags]                       # R1
   python -m verificacion.resultados bloques_1_8 [flags]                  # R2
   python -m verificacion.resultados trazabilidad [elem] [--caso C] [flags]   # R3
   python -m verificacion.resultados superposicion_4_vias [flags]         # R4
   python -m verificacion.resultados instantanea [--casos N] [flags]      # R5

 Los flags son los de los parametros del laboratorio (--q, --cs,
 --patron, --combinacion ...: calculo.laboratorio.cargar). Los
 resultados se arman UNA vez por proceso, en memoria, con la misma
 funcion que los escribe (exportar.resultados.construir), y ninguno de
 los bloques escribe nada: Unity solo muestra, y si un numero del panel
 esta mal tiene que caerse aca y no en la defensa.

 AL_DIA. salidas/resultados.json es, bloque por bloque y por objetos sin
 tolerancia, lo que se arma ahora; el peor cierre de la autoverificacion
 es <= 1 y es el de control (Q, 100277, Vz, al filo a proposito); y los
 numeros del laboratorio (15 casos, escala, columna y muro demo, NO
 PASA) son los de verificacion/numeros_de_control.json.

 BLOQUES_1_8. Los resultados contra OpenSees, el modelo, lo que dibuja
 Unity y la capacidad:
   [1] reconstruccion   estacion(L) = f_j y estacion(0) = -f_i
   [2] superposicion    cada combinacion = sum(lambda * caso base)
   [3] corrida explicita 1.2G+1.0Q+1.4EX resuelta de verdad
   [4] E y A del panel  N = E A / L * alargamiento, en G
   [5] trazabilidad     id -> GameObject -> resultados -> familia P-M
   [6] signos           voladizos y viga simple resueltos aca, y una
                        seccion de fibras que dice que fibra tracciona
   [7] u = 9999         P fuera de la curva de su familia
   [8] muros            el momento del plano es el mayor bajo sismo, y
                        es el que usa la demanda

 TRAZABILIDAD. La cadena de UN elemento sacada de Python: el
 'element elasticBeamColumn' tal como llega al motor (capturado en la
 llamada, no rearmado), lo que OpenSees guardo, el modelo, el GameObject,
 las fuerzas del caso y la capacidad; y despues, numero por numero,
 contra salidas/resultados.json en float32 (lo que lee Unity).

 SUPERPOSICION_4_VIAS. E1..E3 (entrada/laboratorio.json, superposicion)
 por cuatro vias contra la corrida explicita: (2) caso_combinado, (3)
 POST /combinar por el test_client de exportar/servidor.py y (4) el
 bloque 'superposicion' de salidas/resultados.json; (3) y (4) = (2) bit
 a bit, E2 = el caso '1.2G+1.6Q' de los resultados, y los elementos de
 control que da la regla = los declarados.

 INSTANTANEA. La replica en Python, con la aritmetica de 32 bits de
 Unity, de lo que hace el C# al mover los sliders (retabular a la malla
 comun, escalar y sumar, rehacer la demanda), contra caso_combinado, en
 10 juegos de lambdas. Prueba el ALGORITMO; lo que la app de verdad
 calculo lo cruza verificacion/capturas.py con su registro.

 ----------------------------------------------------------------
 LAS COTAS SALEN DE SU CAUSA
 ----------------------------------------------------------------
 El servidor redondea fuerzas a 4 decimales y desplazamientos a 8; los
 resultados vuelven a redondear lo que escriben. Cada comparacion suma
 esos medios ultimos decimales, escalados por lo que multiplica a cada
 valor, y un termino de coma flotante de 4 eps por el tamano de los
 terminos (FACTOR_COMA_FLOTANTE). Los decimales se MIDEN sobre los datos
 con superposicion.decimales_de: si alguien cambia un redondeo, la
 verificacion lo dice en vez de pasar o fallar a ciegas. Unity guarda
 float32: medio intervalo entre floats vecinos se suma donde se compara
 contra lo que lee.
================================================================
"""
from __future__ import annotations

import filecmp
import io
import json
import math
import os
import re
import sys
import time

from calculo import capacidad
from calculo import demanda as dc
from calculo import edificio as _ed
from calculo import esfuerzos as es
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo import superposicion as sp
from verificacion.comun import Informe, comparar_json, f32, medio_digito, titulo
from verificacion.suite import calza, consola_tolerante, control

BLOQUES = ('al_dia', 'bloques_1_8', 'trazabilidad', 'superposicion_4_vias', 'instantanea')

CASOS = es.CASOS_BASE
COMP = ('N', 'Vy', 'Vz', 'T', 'My', 'Mz')
CAMPOS_U = sp.CAMPOS['desplazamientos']
CAMPOS_R = sp.CAMPOS['reacciones']
FP = es.FACTOR_COMA_FLOTANTE
EPS64 = sys.float_info.epsilon
U_FUERA = 9999.0

# La regla con que VisorEstructura nombra cada barra. Se busca LITERAL en
# el C#: si alguien la cambia alla, objeto_unity de los resultados deja de
# apuntar a un GameObject que exista y nada falla.
LITERAL_NOMBRE = '"Elem_" + e.id + "_" + e.tipo'

# Medio ultimo decimal de lo que escriben los resultados: el redondeo que
# se agrega al comparar valores de los resultados entre si o contra OpenSees.
R_ANEXO_F = 0.5 * 10.0 ** -es.DECIMALES_FUERZA
R_ANEXO_X = 0.5 * 10.0 ** -es.DECIMALES_ESTACION
R_ANEXO_U = 0.5 * 10.0 ** -es.DECIMALES_DESPLAZAMIENTO


def rel(ruta):
    return rutas.relativa(ruta)


# ============================================================
# UTILIDADES
# ============================================================
def por_id(lista):
    return {int(x['id']): x for x in lista}


def medio_decimal(valores):
    r"""
    Medio ultimo decimal con que viene escrita una FAMILIA de valores,
    medido con superposicion.decimales_de (la misma que mide el redondeo
    del servidor). Se mide sobre la familia entera y no valor por valor:
    0.25 tiene dos decimales porque es 0.25, no porque este redondeado.
    0 si son todos enteros o no hay valores.
    """
    vals = [float(v) for v in valores if not isinstance(v, bool)]
    d = sp.decimales_de({'v': [{'f': vals}]}, 'v', None)
    return 0.5 * 10.0 ** -d if d else 0.0


def medio_ulp32(x):
    r"""
    Lo mas que se mueve un double al guardarlo en float32: medio
    intervalo entre floats vecinos. Con mantisa de 24 bits el intervalo
    en |x| en [2^(e-1), 2^e) es 2^(e-24), asi que el error relativo es a
    lo mas 2^-24 = 6e-8.
    """
    f = abs(f32(x))
    if f == 0.0:
        return 2.0 ** -150
    _m, e = math.frexp(f)
    return 2.0 ** (e - 24) / 2.0


def dentro(a, b, cota):
    """|a - b| <= cota, con el piso de la aritmetica doble encima."""
    return abs(float(a) - float(b)) <= cota + 2.0 * EPS64 * max(abs(float(a)), abs(float(b)))


class SilenciarStderr(opensees.AvisosDeOpenSees):
    r"""
    El stderr de C (descriptor 2) a un temporal mientras corre OpenSees:
    capacidad.momento_curvatura empuja cada curva M-phi hasta que el
    analisis deja de converger y lo anota en su 'motivo'; OpenSees ademas
    imprime un WARNING por cada una. Se cuentan los 'failed to converge'
    y se informan en una linea; si hay una excepcion, se muestran enteros.
    """

    def __exit__(self, tipo, valor, traza):
        super(SilenciarStderr, self).__exit__(tipo, valor, traza)
        self.avisos = self.texto.count('failed to converge')
        if tipo is not None:
            sys.stderr.write(self.texto)
        return False


def nombre_objeto(e):
    """El nombre que le pone VisorEstructura a la barra."""
    return 'Elem_%d_%s' % (int(e['id']), e['tipo'])


def regla_de_nombre_en_visor():
    r"""
    (numero de linea, linea) donde VisorEstructura.cs nombra la barra con
    LITERAL_NOMBRE, fuera de comentarios, o (None, None). Los comentarios
    se vacian conservando los saltos de linea, para que un ejemplo en una
    nota no cuente como codigo.
    """
    try:
        ruta = rutas.cs('VisorEstructura.cs')
    except FileNotFoundError:
        return None, None
    with io.open(ruta, encoding='utf-8') as fh:
        src = fh.read()
    src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), src, flags=re.S)
    for i, linea in enumerate(src.splitlines(), 1):
        codigo = linea.split('//', 1)[0]
        if LITERAL_NOMBRE in codigo and '.name' in codigo:
            return i, codigo.strip()
    return None, None


def leer_resultados():
    """(salidas/resultados.json, ruta), o (None, ruta) si no existe."""
    ruta = rutas.salida('resultados')
    if not os.path.isfile(ruta):
        return None, ruta
    with io.open(ruta, encoding='utf-8') as fh:
        return json.load(fh), ruta


# ============================================================
# LOS RESULTADOS EN MEMORIA, UNA VEZ POR PROCESO
# ============================================================
_BASES = {}


def base_del_laboratorio(flags=()):
    r"""
    La base del laboratorio (esfuerzos.base: los casos resueltos en
    OpenSees, las familias P-M con sus curvas, los datos de cada barra),
    una vez por juego de flags y por proceso. Es lo que piden
    superposicion.caso_combinado y equilibrio_combinado. Encima lleva
    'parametros' (las lineas de describir(), la huella), 'ids_nodos',
    'segundos' y 'avisos' (los 'failed to converge' de las curvas M-phi).
    """
    clave = tuple(flags)
    if clave not in _BASES:
        t0 = time.time()
        with SilenciarStderr() as s:
            b = dict(es.base(list(flags)))
        b.update({
            'parametros': sp.parametros_de(b),
            'ids_nodos': sorted(int(n['id']) for n in b['modelo']['nodos']),
            'segundos': time.time() - t0,
            'avisos': s.avisos,
        })
        _BASES[clave] = b
    return _BASES[clave]


def contexto(flags=()):
    r"""
    La base y, sobre ella, los resultados armados en memoria con
    exportar.resultados.construir (la funcion que los escribe, sin
    escribirlos): 'anexo' (los resultados) y 'ctx' (su contexto) se
    agregan a la base, que se arma una sola vez.
    """
    from exportar.resultados import construir
    b = base_del_laboratorio(flags)
    if 'anexo' not in b:
        t0 = time.time()
        with SilenciarStderr() as s:
            anexo, ctx = construir(list(flags), b=b)
        b['segundos'] += time.time() - t0
        b['avisos'] += s.avisos
        b['anexo'], b['ctx'] = anexo, ctx
    return b


# ============================================================
# R1: AL DIA
# ============================================================
def al_dia(inf, args):
    titulo('AL DIA: %s = exportar.resultados.construir() ahora, y el cierre f_j'
           % rel(rutas.salida('resultados')))
    b = contexto(args.flags)
    anexo, ctx = b['anexo'], b['ctx']
    print('  construidos en memoria en %.1f s (no se escribe nada)' % b['segundos'])
    disco, ruta = leer_resultados()
    if inf.check(disco is not None, 'existe %s' % rel(ruta)):
        nuevo = json.loads(json.dumps(anexo, separators=(',', ':'), ensure_ascii=False))
        inf.check(sorted(disco) == sorted(nuevo),
                  'la raiz trae los mismos bloques: %s' % ', '.join(nuevo),
                  [] if sorted(disco) == sorted(nuevo) else
                  ['en el archivo: %s' % ', '.join(disco)])
        malos = 0
        for k in nuevo:
            difs = (comparar_json(disco[k], nuevo[k], ruta='$.' + k) if k in disco
                    else ['$.%s: falta en el archivo' % k])
            if not inf.check(not difs, '%-17s = el de ahora (por objetos, tolerancia 0)' % k,
                             difs[:4]):
                malos += 1
        if malos:
            print('         -> corre: python sap.py preparar')
        inf.check(nuevo['info']['edificio'] == _ed.NOMBRE,
                  'info.edificio = %r' % nuevo['info']['edificio'])

    print()
    print('  autoverificacion de exportar.resultados: esfuerzo(L) contra f_j de OpenSees,')
    print('  error / cota (la cota de esfuerzos.cota_de_cierre: redondeo y coma flotante)')
    for c in anexo['casos']:
        q, eid, comp = ctx['cierre'][c['nombre']]
        print('    %-18s peor %.10f   elemento %6d, %s' % (c['nombre'], q, eid, comp))
    peor_caso, (q, eid, comp) = max(ctx['cierre'].items(), key=lambda kv: kv[1][0])
    valor, cota = control('laboratorio', 'peor_cierre')
    inf.check(q <= 1.0 and calza(q, 'laboratorio', 'peor_cierre'),
              'el peor cierre es <= 1 y es el de control: %.10f en %s, elemento %d, %s '
              '(control %.10f, cota %.0e)' % (q, peor_caso, eid, comp, valor, cota),
              'al filo de 1 a proposito: es el redondeo mismo, no un desvio')

    print()
    print('  numeros de control del laboratorio (verificacion/numeros_de_control.json):')
    info = anexo['info']
    n_casos, _c = control('laboratorio', 'casos')
    inf.check(len(anexo['casos']) == n_casos, '%d casos (4 base + combinaciones)'
              % len(anexo['casos']))
    esc, _c = control('laboratorio', 'escala_deformada')
    inf.check(info['escala_deformada'] == esc, 'escala de la deformada recomendada x%g'
              % info['escala_deformada'])
    for clave in ('columna_demo', 'muro_demo'):
        v, _c = control('laboratorio', clave)
        inf.check(info[clave] == v, '%s = %d (por regla)' % (clave, info[clave]))
    con_fierro = sum(1 for e in anexo['elementos'] if int(e['familia']) >= 0)
    v, _c = control('laboratorio', 'elementos_con_fierro')
    inf.check(con_fierro == v, '%d elementos con fierro (con curva P-M)' % con_fierro)
    casos = {c['nombre']: c for c in anexo['casos']}
    for nombre in control('laboratorio', 'no_pasa')[0]:
        v, _c = control('laboratorio', 'no_pasa', nombre)
        caso = casos.get(nombre)
        n = sum(1 for d in caso['demandas'] if not d['pasa']) if caso else -1
        inf.check(n == v, '%s: NO PASA %d de %d' % (nombre, n, con_fierro))


# ============================================================
# R2: BLOQUES [1] A [8]
# ============================================================
def activos_de(caso):
    lam = dict(zip(CASOS, [float(v) for v in caso['factores']]))
    return lam, {c: l for c, l in lam.items() if l != 0.0}


def bloque_1(anexo, ctx, inf):
    titulo('[1] RECONSTRUCCION: estacion(L) = f_j y estacion(0) = -f_i, '
           'en cada caso y elemento')
    resultados = ctx['resultados']
    nodos = por_id(ctx['modelo']['nodos'])
    largos = {int(e['id']): _ed.largo(e, nodos) for e in ctx['modelo']['elementos']}
    w_base = {c: es.cargas_por_elemento(ctx['arm']['casos'][c]) for c in CASOS}
    f_base = {c: {int(x['id']): [float(v) for v in x['f']]
                  for x in resultados[c]['fuerzas_elementos']} for c in CASOS}

    r_srv = medio_decimal(v for c in CASOS for f in f_base[c].values() for v in f)
    r_est = medio_decimal(v for caso in anexo['casos'] for s in caso['esfuerzos']
                          for k in COMP + ('f',) for v in s[k])
    print('  Las estaciones del panel salen de f_i y w por equilibrio; en x = L')
    print('  tienen que dar f_j, que OpenSees calculo por su lado. La cota es la de')
    print('  los resultados, esfuerzos.cota_de_cierre(L, sum|lambda|, magnitudes):')
    print('    N, Vy, Vz, T   5e-5 * 2 * sum|lambda|      (f_i y f_j del servidor)')
    print('    My, Mz         5e-5 * (2 + L) * sum|lambda| (ademas x * V_i)')
    print('    + 4 eps * tamano de los terminos            (coma flotante)')
    print('  mas 2 * %.0e porque aca se comparan dos valores YA ESCRITOS en los'
          % R_ANEXO_F)
    print('  resultados (la estacion y f_j), cada uno redondeado a %d decimales.'
          % es.DECIMALES_FUERZA)
    inf.check(r_srv == es.COTA_REDONDEO == anexo['info']['cota_redondeo_kN'],
              'redondeo del servidor medido en f = %.1e = esfuerzos.COTA_REDONDEO = '
              'info.cota_redondeo_kN (%g)' % (r_srv, anexo['info']['cota_redondeo_kN']))
    inf.check(r_est <= R_ANEXO_F,
              'los resultados escriben f y estaciones con a lo mas %d decimales (medido: '
              'medio decimal %.1e)' % (es.DECIMALES_FUERZA, r_est))

    peores = {}
    malos, mal_x, malas_w, n = [], [], [], 0
    n_carg = anexo['info']['n_estaciones_cargada']
    for caso in anexo['casos']:
        lam, activos = activos_de(caso)
        suma = sum(abs(l) for l in activos.values())
        # Cargada o no se decide con superposicion.combinar_cargas, no con
        # los resultados: es la carga que OpenSees recibiria combinada.
        w_comb = {int(x['elemento']): x for x in
                  sp.combinar_cargas(ctx['datos'], lam)['cargas_distribuidas']}
        for s in caso['esfuerzos']:
            eid = int(s['id'])
            L = largos[eid]
            # La w que dibujan los resultados tiene que ser la que usan las
            # formulas: la combinacion de las cargas de los casos base.
            w_json = [float(v) for v in s.get('w', [])]
            w_ref = [sum(l * w_base[c].get(eid, (0.0, 0.0, 0.0))[k]
                         for c, l in activos.items()) for k in range(3)]
            if len(w_json) != 3 or any(
                    abs(a - b) > R_ANEXO_F + FP * abs(b)
                    for a, b in zip(w_json, w_ref)):
                malas_w.append('%s elem %d: w %s, esperada %s'
                               % (caso['nombre'], eid, w_json,
                                  [round(v, 4) for v in w_ref]))
            mag = [0.0] * 6
            for c, l in activos.items():
                m_c = es.magnitudes_de_cierre(f_base[c][eid],
                                              w_base[c].get(eid, (0.0, 0.0, 0.0)), L)
                mag = [a + abs(l) * b for a, b in zip(mag, m_c)]
            cotas = [c + 2.0 * R_ANEXO_F for c in es.cota_de_cierre(L, suma, mag)]
            for k, comp in enumerate(COMP):
                for extremo, calc, ref in (('x = L', s[comp][-1], s['f'][6 + k]),
                                           ('x = 0', s[comp][0], -s['f'][k])):
                    err = abs(float(calc) - float(ref))
                    q = err / cotas[k]
                    n += 1
                    clave = (comp, extremo)
                    # Con error 0 en todos se muestra la cota mas chica.
                    ant = peores.get(clave, (-1.0, 0.0, math.inf))
                    if q > ant[0] or (q == ant[0] == 0.0 and cotas[k] < ant[2]):
                        peores[clave] = (q, err, cotas[k], caso['nombre'], eid)
                    if q > 1.0:
                        malos.append('%s elem %d %s en %s: %.2e > %.2e'
                                     % (caso['nombre'], eid, comp, extremo, err, cotas[k]))

            wv = w_comb.get(eid)
            cargada = wv is not None and any(float(wv[k]) != 0.0 for k in ('wx', 'wy', 'wz'))
            xs = [float(x) for x in s['x']]
            cuantas = n_carg if cargada else 2
            ok = (len(xs) == cuantas and all(len(s[k]) == cuantas for k in COMP)
                  and all(abs(x - L * i / (cuantas - 1)) <= R_ANEXO_X + FP * L
                          for i, x in enumerate(xs)))
            if not ok:
                mal_x.append('%s elem %d: %d estaciones (esperadas %d), L = %.4f, x = %s'
                             % (caso['nombre'], eid, len(xs), cuantas, L, xs[:3]))

    print()
    print('  %-4s %-6s %10s %10s %8s   %s' % ('', '', 'peor err', 'su cota',
                                             'err/cota', 'donde'))
    for comp in COMP:
        for extremo in ('x = L', 'x = 0'):
            q, err, cota, nombre, eid = peores[(comp, extremo)]
            print('  %-4s %-6s %10.2e %10.2e %8.3f   %s, elemento %d'
                  % (comp, extremo, err, cota, q, nombre, eid))
    print('  (en x = 0 la formula es -f_i sin ninguna operacion: el error es 0 exacto)')
    inf.check(not malas_w, 'la carga repartida de los resultados (w) es la combinacion '
              'de las de los casos base, la misma que usan las formulas del '
              'cierre', malas_w[:6])
    inf.check(not malos, '%d comparaciones (%d casos x %d elementos x 6 esfuerzos x '
              '2 extremos) dentro de su cota' % (n, len(anexo['casos']),
                                                 len(anexo['elementos'])), malos[:6])
    peor_exp = max(ctx['cierre'].items(), key=lambda kv: kv[1][0])
    inf.check(peor_exp[1][0] <= 1.0,
              'la autoverificacion de exportar.resultados (antes de redondear) cerro: peor '
              '%.3f en %s, elemento %d, %s' % (peor_exp[1][0], peor_exp[0],
                                              peor_exp[1][1], peor_exp[1][2]))
    inf.check(not mal_x, 'estaciones equiespaciadas de 0 a L: %d si la combinacion '
              'trae carga repartida, 2 si no (cota %.0e del redondeo de x)'
              % (n_carg, R_ANEXO_X), mal_x[:6])


def bloque_2(anexo, ctx, inf):
    titulo('[2] SUPERPOSICION: cada combinacion = sum(lambda * caso base), '
           'rehecha aca')
    p, resultados = ctx['p'], ctx['resultados']

    # La lista esperada sale de entrada/laboratorio.json, no de los resultados.
    esperados, vistos = [], set()
    for c in CASOS:
        esperados.append((c, 'caso', [1.0 if k == c else 0.0 for k in CASOS]))
        vistos.add(c)
    for combo in list(p['combinaciones']) + [p['combinacion']]:
        if combo['nombre'] not in vistos:
            vistos.add(combo['nombre'])
            lam = lab.factores(combo)
            esperados.append((combo['nombre'], 'combinacion', [lam[k] for k in CASOS]))
    hay = [(c['nombre'], c['tipo'], [float(v) for v in c['factores']])
           for c in anexo['casos']]
    inf.check(hay == esperados, 'los %d casos de los resultados, en orden, con tipo y '
              'factores [lG lQ lEX lEY], son los de laboratorio.json' % len(esperados),
              [] if hay == esperados else ['resultados %s' % hay, 'esperado %s' % esperados])
    inf.check(anexo['info']['caso_por_defecto'] == p['combinacion']['nombre'],
              'caso_por_defecto = %s, la combinacion activa de los parametros'
              % anexo['info']['caso_por_defecto'])

    f_base = {c: por_id(resultados[c]['fuerzas_elementos']) for c in CASOS}
    u_base = {c: por_id(resultados[c]['desplazamientos']) for c in CASOS}
    r_mm = medio_decimal(c['max_desplazamiento_mm'] for c in anexo['casos'])
    print('  Referencia: superposicion.combinar_resultados(resultados del servidor, lambda),')
    print('  otra implementacion de la suma que la de los resultados (demanda.combinar).')
    print('  Los resultados escriben esa suma redondeada: la diferencia es a lo mas su medio')
    print('  ultimo decimal, f %.0e kN y u %.0e m, + 4 eps * sum|lambda| |valor|.'
          % (R_ANEXO_F, R_ANEXO_U))
    print('  max_desplazamiento_mm: norma de (ux, uy, uz) rehecha, cota %.0e mm '
          '(medida).' % r_mm)
    print()
    print('  %-18s %6s %10s %10s %10s %10s %9s  %s'
          % ('', 'sum|l|', 'peor f', 'cota f', 'peor u', 'cota u', 'umax mm', ''))
    no_cierran = []
    for caso in anexo['casos']:
        lam, activos = activos_de(caso)
        ref = sp.combinar_resultados(resultados, lam)
        f_ref = {int(x['id']): x['f'] for x in ref['fuerzas_elementos']}
        u_ref = por_id(ref['desplazamientos'])
        esf, desp = por_id(caso['esfuerzos']), por_id(caso['desplazamientos'])
        ids_ok = set(esf) == set(f_ref) and set(desp) == set(u_ref)

        peor_f = (0.0, 0.0, R_ANEXO_F)
        for eid, s in (esf.items() if ids_ok else ()):
            for k, v in enumerate(s['f']):
                mag = sum(abs(l) * abs(float(f_base[c][eid]['f'][k]))
                          for c, l in activos.items())
                err, cota = abs(float(v) - f_ref[eid][k]), R_ANEXO_F + FP * mag
                if err / cota > peor_f[0]:
                    peor_f = (err / cota, err, cota)
        peor_u = (0.0, 0.0, 0.0)
        u_max = 0.0
        for nid, d in (desp.items() if ids_ok else ()):
            for k in CAMPOS_U:
                mag = sum(abs(l) * abs(float(u_base[c][nid][k])) for c, l in activos.items())
                err, cota = abs(float(d[k]) - u_ref[nid][k]), R_ANEXO_U + FP * mag
                if err / cota > peor_u[0]:
                    peor_u = (err / cota, err, cota)
            u_max = max(u_max, math.sqrt(sum(u_ref[nid][k] ** 2 for k in ('ux', 'uy', 'uz'))))
        u_max_mm = 1000.0 * u_max
        ok_mm = abs(caso['max_desplazamiento_mm'] - u_max_mm) <= r_mm + FP * u_max_mm
        suma = sum(abs(l) for l in activos.values())
        ok = ids_ok and peor_f[0] <= 1.0 and peor_u[0] <= 1.0 and ok_mm
        print('  %-18s %6.2f %10.2e %10.2e %10.2e %10.2e %9.4f  %s'
              % (caso['nombre'], suma, peor_f[1], peor_f[2], peor_u[1], peor_u[2],
                 caso['max_desplazamiento_mm'], 'ok' if ok else '<-- NO CALZA'))
        if not ok:
            no_cierran.append('%s: ids %s, f %.3f, u %.3f, umax %.4f contra %.4f'
                              % (caso['nombre'], ids_ok, peor_f[0], peor_u[0],
                                 caso['max_desplazamiento_mm'], u_max_mm))
    inf.check(not no_cierran, 'los %d casos: las 12 fuerzas de cada elemento, los 6 '
              'GDL de cada nodo y el desplazamiento maximo = la suma rehecha'
              % len(anexo['casos']), no_cierran)


COMBINACION_EXPLICITA = '1.2G+1.0Q+1.4EX'
FACTORES_EXPLICITA = {'G': 1.2, 'Q': 1.0, 'EX': 1.4, 'EY': 0.0}


def bloque_3(anexo, ctx, inf):
    titulo('[3] CORRIDA EXPLICITA: %s resuelta en OpenSees con la carga combinada'
           % COMBINACION_EXPLICITA)
    caso = next((c for c in anexo['casos'] if c['nombre'] == COMBINACION_EXPLICITA), None)
    if not inf.check(caso is not None, '%s esta en los resultados' % COMBINACION_EXPLICITA):
        return
    lam, activos = activos_de(caso)
    inf.check(lam == FACTORES_EXPLICITA, 'sus factores son %s' % caso['factores'])
    datos, arm = ctx['datos'], ctx['arm']
    inf.check(datos['casos_de_carga'] == list(arm['casos'].values()),
              'los casos que se combinan son los del laboratorio (laboratorio.armar_casos: '
              '%s), no los del modelo' % ', '.join(c['nombre'] for c in datos['casos_de_carga']))

    carga = sp.combinar_cargas(datos, lam, COMBINACION_EXPLICITA)
    t = time.time()
    explicito = sp.resolver_explicito(datos, lam, COMBINACION_EXPLICITA)
    print('  superposicion.resolver_explicito: %d cargas nodales y %d repartidas combinadas, '
          'resuelto en %.1f s' % (len(carga['cargas_nodales']),
                                  len(carga['cargas_distribuidas']), time.time() - t))
    inf.check(explicito.get('ok', False), 'OpenSees resolvio la corrida explicita')
    algebraico = sp.combinar_resultados(ctx['resultados'], lam)
    piso = {'fuerzas_elementos': sp.piso_de_redondeo(
                ctx['resultados'], lam, 'fuerzas_elementos', None),
            'desplazamientos': sp.piso_de_redondeo(
                ctx['resultados'], lam, 'desplazamientos', CAMPOS_U)}
    print('  cota = superposicion.piso_de_redondeo = 0.5 10^-d (sum|lambda| + 1) = %.2e kN '
          'y %.2e m' % (piso['fuerzas_elementos'], piso['desplazamientos']))
    print('  (d medido en los resultados; el +1 porque la explicita tambien viene')
    print('   redondeada), + 4 eps * tamano. Contra los RESULTADOS se suma su propio')
    print('   redondeo: %.0e kN y %.0e m.' % (R_ANEXO_F, R_ANEXO_U))

    def valores(res, clave):
        if clave == 'fuerzas_elementos':
            return {int(x['id']): [float(v) for v in x['f']] for x in res[clave]}
        return {int(x['id']): [float(x[k]) for k in CAMPOS_U] for x in res[clave]}

    anexo_res = {'fuerzas_elementos': [{'id': s['id'], 'f': s['f']} for s in caso['esfuerzos']],
                 'desplazamientos': caso['desplazamientos']}
    print()
    print('  %-17s %6s %11s %11s %11s %11s  %s'
          % ('', 'valores', 'superpos.', 'cota', 'result.', 'cota', 'peor en'))
    for clave, r_anx in (('fuerzas_elementos', R_ANEXO_F), ('desplazamientos', R_ANEXO_U)):
        exp, alg, anx = (valores(explicito, clave), valores(algebraico, clave),
                         valores(anexo_res, clave))
        base_ = {c: valores(ctx['resultados'][c], clave) for c in activos}
        ids_ok = set(exp) == set(alg) == set(anx)
        n, peor_a, peor_x = 0, (0.0, 0.0, 0.0, None), (0.0, 0.0, 0.0, None)
        for i in (exp if ids_ok else ()):
            for k, e in enumerate(exp[i]):
                n += 1
                mag = abs(e) + sum(abs(l) * abs(base_[c][i][k]) for c, l in activos.items())
                c_a = piso[clave] + FP * mag
                c_x = c_a + r_anx
                err_a, err_x = abs(alg[i][k] - e), abs(anx[i][k] - e)
                if err_a / c_a > peor_a[0]:
                    peor_a = (err_a / c_a, err_a, c_a, (i, k))
                if err_x / c_x > peor_x[0]:
                    peor_x = (err_x / c_x, err_x, c_x, (i, k))
        print('  %-17s %6d %11.3e %11.3e %11.3e %11.3e  %s / %s'
              % (clave, n, peor_a[1], peor_a[2], peor_x[1], peor_x[2], peor_a[3], peor_x[3]))
        inf.check(ids_ok and peor_a[0] <= 1.0 and peor_x[0] <= 1.0,
                  '%s: superposicion y resultados = corrida explicita (peores %.3f y %.3f '
                  'de su cota)' % (clave, peor_a[0], peor_x[0]))


def bloque_4(anexo, ctx, inf):
    titulo('[4] E y A DEL PANEL SON LOS DE OPENSEES: N(0) = E A / L * alargamiento, en G')
    modelo = ctx['modelo']
    nodos = por_id(modelo['nodos'])
    coords = {i: (float(n['x']), float(n['y']), float(n['z'])) for i, n in nodos.items()}
    G = next(c for c in anexo['casos'] if c['nombre'] == 'G')
    esf, desp = por_id(G['esfuerzos']), por_id(G['desplazamientos'])
    wx_G = {int(x['elemento']): float(x['wx']) for x in
            sp.combinar_cargas(ctx['datos'], {'G': 1.0})['cargas_distribuidas']}
    elems = anexo['elementos']
    r_u = medio_decimal(d[k] for d in G['desplazamientos'] for k in CAMPOS_U)
    r_N = medio_decimal(s['N'][0] for s in G['esfuerzos'])
    r_E = medio_decimal(e['E_kPa'] for e in elems)
    r_L = medio_decimal(e['L'] for e in elems)
    raiz = 2.0 * math.sqrt(3.0)
    print('  N(0) es el N interno del panel en x = 0 (traccion +); alargamiento =')
    print('  (u_j - u_i) . x_local con x_local de edificio.ejes_locales y el vecxz de')
    print('  los resultados; E_kPa, A y L de los resultados. Cota propagada del redondeo:')
    print('    (E A / L) 2 sqrt(3) r_u   dos nodos, tres componentes, r_u = %.0e m' % r_u)
    print('    + r_N                    N_i del servidor, r_N = %.0e kN' % r_N)
    print('    + |N| (r_E/E + r_L/L)    E y L escritos en los resultados, r_E = %.0e kPa, '
          'r_L = %.0e m' % (r_E, r_L))
    print('  Columna "L geom": la cota del enunciado sola, con el L sin redondear.')

    por_tipo, malos, saltados = {}, [], {'brazo rigido': 0, 'carga axial wx': 0}
    for e in elems:
        eid = int(e['id'])
        if e['es_brazo_rigido']:
            saltados['brazo rigido'] += 1
            continue
        if wx_G.get(eid, 0.0) != 0.0:
            saltados['carga axial wx'] += 1
            continue
        n1, n2 = int(e['n1']), int(e['n2'])
        ejes, _L = _ed.ejes_locales(coords[n1], coords[n2], [float(v) for v in e['vecxz']])
        alarg = sum((float(desp[n2][k]) - float(desp[n1][k])) * ejes['wx'][m]
                    for m, k in enumerate(('ux', 'uy', 'uz')))
        E, A, L = float(e['E_kPa']), float(e['A']), float(e['L'])
        N_os = float(esf[eid]['N'][0])
        k_ax = E * A / L
        N_el = k_ax * alarg
        cota = k_ax * raiz * r_u + r_N + abs(N_el) * (r_E / E + r_L / L) + FP * (abs(N_os) + abs(N_el))
        L_g = _ed.largo(e, nodos)
        k_g = E * A / L_g
        cota_g = k_g * raiz * r_u + r_N + abs(N_os) * r_E / E + FP * (abs(N_os) + abs(k_g * alarg))
        q, q_g = abs(N_os - N_el) / cota, abs(N_os - k_g * alarg) / cota_g
        t = por_tipo.setdefault(e['tipo'], {'n': 0, 'util': 0, 'q': -1.0, 'q_g': 0.0, 'd': None})
        t['n'] += 1
        # Un N menor que diez veces su cota no dice nada de E A: se cuenta aparte.
        t['util'] += abs(N_os) >= 10.0 * cota
        t['q_g'] = max(t['q_g'], q_g)
        if q > t['q']:
            t['q'], t['d'] = q, (eid, N_os, N_el, abs(N_os - N_el), cota)
        if q > 1.0 or q_g > 1.0:
            malos.append('elem %d (%s): N %.4f contra EA/L*d %.4f, err %.2e, cota %.2e, '
                         'con L geom %.3f' % (eid, e['tipo'], N_os, N_el, abs(N_os - N_el),
                                              cota, q_g))
    print()
    print('  %-12s %4s %6s %8s %8s   %s' % ('tipo', 'n', '|N|>10c', 'err/cota', 'L geom',
                                           'peor: elemento, N(0), EA/L*d, err, cota'))
    for tipo, t in sorted(por_tipo.items()):
        print('  %-12s %4d %6d %8.3f %8.3f   %d, %.3f, %.3f, %.2e, %.2e'
              % ((tipo, t['n'], t['util'], t['q'], t['q_g']) + t['d']))
    mudos = sorted(tipo for tipo, t in por_tipo.items() if t['util'] == 0)
    if mudos:
        print('  %s: ningun |N| llega a 10 veces su cota (en el diafragma rigido no se'
              % ', '.join(mudos))
        print('  alargan), asi que calzan pero no dicen nada de su E A.')
    print('  fuera: %d brazos rigidos (rigidez x100, no es la del panel), %d con carga '
          'axial repartida' % (saltados['brazo rigido'], saltados['carga axial wx']))
    inf.check(not malos, '%d elementos: el N de OpenSees es E A / L de los resultados por el '
              'alargamiento' % sum(t['n'] for t in por_tipo.values()), malos[:6])


def bloque_5(anexo, ctx, inf):
    titulo('[5] TRAZABILIDAD: elementTag <-> objeto Unity <-> resultados <-> '
           'seccion y capacidad')
    modelo = ctx['modelo']
    elems, m_elems = por_id(anexo['elementos']), por_id(modelo['elementos'])
    familias = anexo['familias']

    # --- lo que dibuja Unity ---
    ruta_u = rutas.salida('modelo')
    u_elems, u_nodos = {}, set()
    if inf.check(os.path.isfile(ruta_u), 'existe %s' % rel(ruta_u)):
        with io.open(ruta_u, encoding='utf-8') as fh:
            vista = json.load(fh)
        u_elems, u_nodos = por_id(vista['elementos']), {int(n['id']) for n in vista['nodos']}
    faltan = sorted(set(elems) - set(u_elems))
    distintos = sorted(eid for eid, e in elems.items() if eid in u_elems and any(
        e[c] != u_elems[eid][c] for c in ('n1', 'n2', 'seccion', 'tipo')))
    inf.check(not faltan and not distintos and set(elems) == set(m_elems),
              'los %d ElementoOpenSees = los del modelo, y cada uno existe en %s con los '
              'mismos n1, n2, seccion y tipo' % (len(elems), os.path.basename(ruta_u)),
              ['faltan en Unity: %s' % faltan[:8] if faltan else '',
               'distintos: %s' % distintos[:8] if distintos else ''])
    linea, texto = regla_de_nombre_en_visor()
    inf.check(linea is not None, 'VisorEstructura.cs linea %s: %s' % (linea, texto)
              if linea else 'VisorEstructura.cs nombra la barra con %s' % LITERAL_NOMBRE)
    mal_nombre = sorted(eid for eid, e in elems.items()
                        if e['objeto_unity'] != 'Elem_%d_%s' % (eid, e['tipo'])
                        or not e['tag_opensees'].startswith('element elasticBeamColumn %d %d %d '
                                                            % (eid, e['n1'], e['n2'])))
    ej = elems[anexo['info']['columna_demo']] if anexo['info']['columna_demo'] in elems \
        else anexo['elementos'][0]
    inf.check(not mal_nombre, 'objeto_unity == "Elem_<id>_<tipo>" y tag_opensees empieza con '
              'el mismo id y nodos, en los %d' % len(elems),
              ['ej. %s <-> %s' % (ej['objeto_unity'], ej['tag_opensees'])]
              + (['distintos: %s' % mal_nombre[:8]] if mal_nombre else []))

    # --- resultados: cada id apunta a algo que existe ---
    con_fierro = {eid for eid, e in elems.items() if e['familia'] >= 0}
    ids_nodos = {int(n['id']) for n in modelo['nodos']}
    malos = []
    for c in anexo['casos']:
        ids_e = [int(s['id']) for s in c['esfuerzos']]
        ids_d = [int(d['id']) for d in c['demandas']]
        ids_u = {int(d['id']) for d in c['desplazamientos']}
        if len(ids_e) != len(set(ids_e)) or set(ids_e) != set(elems):
            malos.append('%s: esfuerzos no son los %d elementos' % (c['nombre'], len(elems)))
        if len(ids_d) != len(set(ids_d)) or set(ids_d) != con_fierro or any(
                d['familia'] != elems[int(d['id'])]['familia'] for d in c['demandas']):
            malos.append('%s: demandas no son los %d con familia' % (c['nombre'], len(con_fierro)))
        if ids_u != ids_nodos or (u_nodos and not ids_u <= u_nodos):
            malos.append('%s: desplazamientos no son los nodos del modelo y de Unity' % c['nombre'])
    inf.check(not malos, 'en los %d casos: esfuerzos de los %d elementos, demandas de los '
              '%d con familia (y la misma familia), desplazamientos de los %d nodos'
              % (len(anexo['casos']), len(elems), len(con_fierro), len(ids_nodos)), malos[:6])

    # --- familias = firmas de demanda.firma_de_seccion ---
    firma_de = {eid: dc.firma_de_seccion(me, capacidad.desde_elemento(modelo, eid))
                for eid, me in m_elems.items() if me.get('enfierradura')}
    fams_de_firma, firmas_de_fam, malas = {}, {}, []
    for eid, firma in firma_de.items():
        fams_de_firma.setdefault(firma, set()).add(elems[eid]['familia'])
        firmas_de_fam.setdefault(elems[eid]['familia'], set()).add(firma)
    if set(firma_de) != con_fierro:
        malas.append('con enfierradura %d, con familia %d' % (len(firma_de), len(con_fierro)))
    malas += ['firma %s en familias %s' % (f[0], sorted(v)) for f, v in fams_de_firma.items()
              if len(v) != 1]
    for i, fam in enumerate(familias):
        if fam['indice'] != i or sorted(fam['elementos']) != sorted(
                eid for eid in con_fierro if elems[eid]['familia'] == i):
            malas.append('familia %d: indice o lista de elementos distinta' % i)
        if len(firmas_de_fam.get(i, ())) != 1:
            malas.append('familia %d junta %d firmas' % (i, len(firmas_de_fam.get(i, ()))))
    inf.check(not malas, '%d elementos con fierro en %d familias = %d firmas de '
              'demanda.firma_de_seccion, una a una'
              % (len(firma_de), len(familias), len(fams_de_firma)), malas[:6])

    for etiqueta, tipo in (('columna_demo', 'columna'), ('muro_demo', 'muro')):
        demo_pm(etiqueta, tipo, anexo, ctx, inf)


def demo_pm(etiqueta, tipo, anexo, ctx, inf):
    r"""
    La columna o el muro de demostracion: su curva en los resultados es
    la de capacidad.interaccion sobre SU seccion (no solo la del primer
    elemento de la familia), y su demanda es la de demanda.revisar.
    """
    info, elems = anexo['info'], por_id(anexo['elementos'])
    eid = int(info[etiqueta])
    if not inf.check(eid in elems and elems[eid]['tipo'] == tipo and elems[eid]['familia'] >= 0,
                     '%s = %d es de tipo %s y tiene familia P-M' % (etiqueta, eid, tipo)):
        return
    e = elems[eid]
    fam = anexo['familias'][e['familia']]
    with SilenciarStderr():
        sec = capacidad.desde_elemento(ctx['modelo'], eid)
        curva = capacidad.interaccion(sec)
        res = dc.revisar(eid, modelo=ctx['modelo'], resultados=ctx['resultados'])
    print()
    print('  %s -> %s -> %s' % (etiqueta, e['objeto_unity'], e['tag_opensees']))
    print('    seccion %s, familia %d (%d elementos, la curva se calculo con el %d): %s'
          % (e['seccion'], e['familia'], len(fam['elementos']), fam['elementos'][0], fam['clave']))
    peor = [0.0, 0.0, 0.0]
    ok = len(curva) == len(fam['P'])
    for i, pt in enumerate(curva if ok else ()):
        pares = ((pt['P_kN'], fam['P'][i]), (pt['M_kNm'], fam['Mn'][i]),
                 (pt.get('M_max_kNm', 0.0), fam['Mmax'][i]))
        for k, (a, b) in enumerate(pares):
            err = abs(float(a) - float(b))
            peor[k] = max(peor[k], err)
            ok = ok and err <= R_ANEXO_F + FP * abs(float(a)) and pt.get('de', '') == fam['de'][i]
    inf.check(ok, '%s %d: familia de los resultados (%d puntos) == capacidad.interaccion('
              'capacidad.desde_elemento(modelo, %d)) (peor dif P %.1e, Mn %.1e, Mmax %.1e; '
              'cota %.0e, el redondeo de los resultados)'
              % (etiqueta, eid, len(fam['P']), eid, peor[0], peor[1], peor[2], R_ANEXO_F))

    casos = {c['nombre']: c for c in anexo['casos']}
    r_u = medio_decimal(d['u'] for c in anexo['casos'] for d in c['demandas'])
    print('    %-6s %10s %10s %10s %9s %-13s | revisar(): %s'
          % ('caso', 'P [kN]', 'M [kNm]', 'Mn [kNm]', 'u', 'extremo', 'P, M, Mn, u'))
    bien = True
    for nombre in list(CASOS) + [info['caso_por_defecto']]:
        x = next(y for y in casos[nombre]['demandas'] if int(y['id']) == eid)
        d = res['puntos'].get(nombre)
        if d is None:          # el caso activo: revisar no lo trae, se muestra
            print('    %-6s %10.1f %10.1f %10.1f %9.3f %-13s | caso activo del visor'
                  % (nombre, x['P'], x['M'], x['Mn'], x['u'], x['extremo']))
            continue
        u_ref = d['utilizacion'] if math.isfinite(d['utilizacion']) else 9999.0
        pares = ((x['P'], d['P_kN']), (x['M'], d['M_kNm']),
                 (x['M_fuera_plano'], d['M_fuera_de_plano_kNm'] or 0.0),
                 (x['Mn'], d['M_capacidad_kNm']))
        ok = (all(abs(float(a) - float(b)) <= R_ANEXO_F + FP * abs(float(b)) for a, b in pares)
              and abs(float(x['u']) - u_ref) <= r_u + FP * u_ref
              and x['extremo'] == d['extremo'] and x['pasa'] == d['pasa'])
        bien = bien and ok
        print('    %-6s %10.1f %10.1f %10.1f %9.3f %-13s | %.4f, %.4f, %.4f, %.6f %s'
              % (nombre, x['P'], x['M'], x['Mn'], x['u'], x['extremo'], d['P_kN'], d['M_kNm'],
                 d['M_capacidad_kNm'], u_ref, 'calza' if ok else '<-- NO CALZA'))
    inf.check(bien, '%s %d: P, M, M fuera de plano, Mn, u, extremo y pasa de G, Q, EX, EY '
              '== demanda.revisar (cota %.0e en fuerzas, %.0e en u)'
              % (etiqueta, eid, R_ANEXO_F, r_u))


# [6] SIGNOS, CON MODELOS CHICOS
L_S, Q_S, B_S, H_S, E_S = 6.0, 10.0, 0.30, 0.50, 2.5e7


def barra_en_servidor(restr_i, restr_j, wy, wz):
    """Una barra de L_S m a lo largo de X global, resuelta con el motor."""
    data = {
        'material': {'fpc_MPa': 25.0, 'poisson': 0.2},
        'secciones': [{'nombre': 'r', 'A': B_S * H_S, 'Iy': H_S * B_S ** 3 / 12.0,
                       'Iz': B_S * H_S ** 3 / 12.0, 'J': 0.0026}],
        'nodos': [{'id': 1, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'restricciones': restr_i},
                  {'id': 2, 'x': L_S, 'y': 0.0, 'z': 0.0, 'restricciones': restr_j}],
        'elementos': [{'id': 1, 'n1': 1, 'n2': 2, 'seccion': 'r', 'tipo': 'viga'}],
        'cargas_distribuidas': [{'elemento': 1, 'wx': 0.0, 'wy': wy, 'wz': wz}],
    }
    salida = opensees.construir_y_resolver(data)
    return ([float(v) for v in salida['fuerzas_elementos'][0]['f']],
            por_id(salida['desplazamientos'])[2], salida['ok'])


def voladizo_de_fibras(wy, wz):
    r"""
    El mismo voladizo en OpenSees puro, SIN el motor ni las formulas:
    6 dispBeamColumn de 1 m con una seccion de fibras elastica (b en y
    local, h en z local), el mismo vecxz (0,0,1) y la misma -beamUniform.
    Devuelve la tension de las fibras extremas y la fuerza de la seccion
    en el primer punto de Gauss del elemento del empotramiento.
    """
    import openseespy.opensees as ops
    n = int(L_S)
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)
    for i in range(n + 1):
        ops.node(i + 1, L_S * i / n, 0.0, 0.0)
    ops.fix(1, 1, 1, 1, 1, 1, 1)
    ops.uniaxialMaterial('Elastic', 1, E_S)
    ops.section('Fiber', 1, '-GJ', 1.0e6)
    ops.patch('rect', 1, 10, 10, -B_S / 2.0, -H_S / 2.0, B_S / 2.0, H_S / 2.0)
    ops.geomTransf('Linear', 1, 0.0, 0.0, 1.0)
    ops.beamIntegration('Legendre', 1, 1, 3)
    for i in range(n):
        ops.element('dispBeamColumn', i + 1, i + 1, i + 2, 1, 1)
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    for i in range(n):
        ops.eleLoad('-ele', i + 1, '-type', '-beamUniform', wy, wz, 0.0)
    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Plain')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    if ops.analyze(1) != 0:
        raise RuntimeError('el voladizo de fibras no convergio')
    tension = {}
    for nombre, (y, z) in (('+z', (0.0, H_S / 2.0)), ('-z', (0.0, -H_S / 2.0)),
                           ('+y', (B_S / 2.0, 0.0)), ('-y', (-B_S / 2.0, 0.0))):
        r = ops.eleResponse(1, 'section', 1, 'fiber', y, z, 'stressStrain')
        if not r:
            raise RuntimeError('eleResponse(section, fiber, %g, %g) vino vacio' % (y, z))
        tension[nombre] = float(r[0])
    fuerza = ops.eleResponse(1, 'section', 1, 'force')      # [P, Mz, My, T]
    x_ip = float(ops.sectionLocation(1)[0])                  # elemento de 1 m
    return tension, {'Mz': float(fuerza[1]), 'My': float(fuerza[2])}, x_ip


def bloque_6(inf):
    titulo('[6] CONVENCION DE SIGNOS: modelos chicos resueltos con '
           'opensees.construir_y_resolver')
    ejes, _L = _ed.ejes_locales((0.0, 0.0, 0.0), (L_S, 0.0, 0.0), (0.0, 0.0, 1.0))
    print('  barra de %.0f m a lo largo de X, q = %.0f kN/m. Ejes locales (edificio.ejes_locales'
          % (L_S, Q_S))
    print('  con vecxz (0,0,1)): x = %s, y = %s, z = %s. Asi wz < 0 va hacia -Z (abajo)'
          % (ejes['wx'], ejes['wy'], ejes['wz']))
    print('  y wy < 0 hacia -Y. Cotas: esfuerzos.cota_de_cierre y el redondeo del servidor, %.0e.'
          % es.COTA_REDONDEO)
    fijo, libre = [1] * 6, [0] * 6
    xs = es.estaciones(L_S, True)
    r = es.COTA_REDONDEO
    modelos = (('voladizo wz = -q', fijo, libre, 0.0, -Q_S),
               ('voladizo wy = -q', fijo, libre, -Q_S, 0.0),
               ('simple wz = -q', [1, 1, 1, 1, 0, 0], [0, 1, 1, 0, 0, 0], 0.0, -Q_S))
    internos = {}
    for nombre, ri, rj, wy, wz in modelos:
        f, u2, ok = barra_en_servidor(ri, rj, wy, wz)
        w = (0.0, wy, wz)
        esf = es.esfuerzos_internos(f, w, xs)
        internos[nombre] = (f, w)
        q, comp = es.cociente_de_cierre(f, w, L_S, 1.0, es.magnitudes_de_cierre(f, w, L_S))
        print()
        print('  %s: f = [%s]' % (nombre, ', '.join('%.4f' % v for v in f)))
        inf.check(ok and q <= 1.0, '%s: esfuerzos_internos(x = L) reproduce f_j (peor %.3f de la '
                  'cota, en %s)' % (nombre, q, comp))
        if nombre == 'voladizo wz = -q':
            M0, ref = esf['My'][0], Q_S * L_S ** 2 / 2.0
            inf.check(M0 > 0 and abs(M0 - ref) <= r + FP * ref and u2['uz'] < 0,
                      'My(0) = %+.4f > 0 en el empotramiento = q L^2/2 = %.4f (cota %.0e, My_i '
                      'redondeado); la punta baja, uz = %.3e m' % (M0, ref, r, u2['uz']),
                      'fibra superior traccionada: el visor dibuja +My hacia +z local (arriba)')
        elif nombre == 'voladizo wy = -q':
            M0, ref = esf['Mz'][0], -Q_S * L_S ** 2 / 2.0
            inf.check(M0 < 0 and abs(M0 - ref) <= r + FP * abs(ref) and u2['uy'] < 0,
                      'Mz(0) = %+.4f < 0 en el empotramiento = -q L^2/2 = %.4f (cota %.0e); la '
                      'punta va a -Y, uy = %.3e m' % (M0, ref, r, u2['uy']),
                      'fibra +y traccionada: el visor dibuja -Mz hacia +y local')
        else:
            i_c = xs.index(L_S / 2.0)
            Mc, ref = esf['My'][i_c], -Q_S * L_S ** 2 / 8.0
            cota = r * (1.0 + L_S / 2.0) + FP * (abs(ref) + abs(f[4]) + L_S / 2.0 * abs(f[2]))
            inf.check(abs(Mc - ref) <= cota and all(esf['My'][i] < 0 for i in range(1, len(xs) - 1)),
                      'My(L/2) = %+.4f = -q L^2/8 = %.4f (cota %.1e = 5e-5 (1 + L/2): My_i y '
                      'Vz_i redondeados); My < 0 en todo el tramo' % (Mc, ref, cota),
                      'fibra inferior traccionada: +My * z_local lo dibuja hacia abajo')
    bloque_6_fibras(internos, inf)


def bloque_6_fibras(internos, inf):
    print()
    print('  Prueba INDEPENDIENTE de las formulas: el mismo voladizo en OpenSees puro con')
    print('  dispBeamColumn y una seccion de fibras elastica; se lee la tension de las')
    print('  fibras extremas en el primer punto de Gauss junto al empotramiento.')
    for nombre, clave, mas, menos in (('voladizo wz = -q', 'My', '+z', '-z'),
                                      ('voladizo wy = -q', 'Mz', '+y', '-y')):
        f, w = internos[nombre]
        try:
            tension, seccion, x_ip = voladizo_de_fibras(w[1], w[2])
        except Exception as ex:           # noqa: BLE001 - se informa y cuenta como falla
            inf.check(False, '%s: no se pudo leer la fibra (%s): sin esa lectura no hay prueba '
                      'independiente de que lado tracciona' % (nombre, ex))
            continue
        formula = es.esfuerzos_internos(f, w, [x_ip])[clave][0]
        exacto = (1.0 if clave == 'My' else -1.0) * Q_S * (L_S - x_ip) ** 2 / 2.0
        inf.check(tension[mas] > 0 > tension[menos],
                  '%s: fibra %s en traccion (%+.1f kPa) y %s en compresion (%+.1f kPa), en '
                  'x = %.4f m' % (nombre, mas, tension[mas], menos, tension[menos], x_ip))
        inf.check(seccion[clave] * formula > 0,
                  '%s: %s de la seccion de fibras = %+.2f y %s(x) de la formula = %+.2f: mismo '
                  'signo (exacto %+.2f)' % (nombre, clave, seccion[clave], clave, formula, exacto),
                  'OpenSees: %s > 0 tracciona +z, %s < 0 tracciona +y; los resultados usan esa '
                  'misma convencion' % ('My', 'Mz'))


def bloque_7(anexo, inf):
    titulo('[7] DEMANDAS CON u = 9999: su P cae fuera de la curva de su familia')
    familias, elems = anexo['familias'], por_id(anexo['elementos'])
    rango = {i: (min(f['P']), max(f['P'])) for i, f in enumerate(familias)}
    # P y los extremos de la curva vienen escritos a 4 decimales: un P a
    # menos de 2 medios decimales del borde no se puede ubicar de que lado.
    r = 2.0 * R_ANEXO_F
    print('  demanda.capacidad_en devuelve Mn = 0 si P <= P min o P >= P max de la curva, y')
    print('  los resultados ponen u = 9999 cuando Mn <= 1e-9. Se exige que cada u = 9999 tenga')
    print('  Mn = 0 y P fuera de [P min, P max] de SU familia (a %.0e, dos redondeos), y' % r)
    print('  al reves, que ningun P claramente fuera tenga un u finito.')
    por_elem, malos, inversos, n = {}, [], [], 0
    for c in anexo['casos']:
        for d in c['demandas']:
            n += 1
            lo, hi = rango[d['familia']]
            P = float(d['P'])
            if float(d['u']) >= 9999.0:
                if not (P <= lo + r or P >= hi - r) or float(d['Mn']) != 0.0:
                    # Que puntos de la curva rodean a P: si Mn = 0 adentro, la
                    # curva tiene un cero interior y ahi esta la causa.
                    fam = familias[d['familia']]
                    pts = sorted(zip(fam['P'], fam['Mn'], fam['de']))
                    par = next(((a, b) for a, b in zip(pts, pts[1:]) if a[0] <= P <= b[0]),
                               (pts[0], pts[-1]))
                    malos.append('%s elem %d: P %.1f dentro de [%.1f, %.1f] con Mn %.1f; la '
                                 'curva de la familia %d entre P %.1f (Mn %.1f, %s) y P %.1f '
                                 '(Mn %.1f, %s)' % (c['nombre'], d['id'], P, lo, hi, d['Mn'],
                                                    d['familia'], par[0][0], par[0][1], par[0][2],
                                                    par[1][0], par[1][1], par[1][2]))
                por_elem.setdefault(int(d['id']), []).append((c['nombre'], P))
            elif P < lo - r or P > hi + r:
                inversos.append('%s elem %d: P %.1f fuera de [%.1f, %.1f] con u %.3f'
                                % (c['nombre'], d['id'], P, lo, hi, d['u']))
    print()
    for eid, lista in sorted(por_elem.items()):
        e = elems[eid]
        lo, hi = rango[e['familia']]
        nombre, P = min(lista, key=lambda t: t[1]) if lista[0][1] < lo + r else \
            max(lista, key=lambda t: t[1])
        lado = ('traccion mas alla de la traccion pura' if P < lo + r
                else 'compresion mas alla de la compresion pura')
        print('  elemento %d (%s %s, familia %d): P de la curva en [%.1f, %.1f]; u = 9999 en %s'
              % (eid, e['tipo'], e['seccion'], e['familia'], lo, hi,
                 ', '.join(x for x, _p in lista)))
        print('      peor %s: P = %.1f kN, %s (%.1f kN afuera)'
              % (nombre, P, lado, (lo - P) if P < lo + r else (P - hi)))
    inf.check(not malos, '%d de %d demandas con u = 9999, en %d elementos: todas con Mn = 0 y '
              'P fuera de la curva de su familia' % (sum(len(v) for v in por_elem.values()), n,
                                                    len(por_elem)), malos[:6])
    inf.check(not inversos, 'ninguna demanda con P fuera de la curva tiene u finito', inversos[:6])


def bloque_8(anexo, inf):
    titulo('[8] MUROS: el momento que se compara con la curva es el de su plano')
    print('  demanda.momento_en_el_plano(Iy, Iz) lo elige por inercias. Aca se')
    print('  comprueba con lo que respondio OpenSees, sin mirar las inercias: bajo EX y EY,')
    print('  el momento declarado del plano tiene que ser el mayor de los dos en cada muro.')
    print('  Y la demanda de los resultados tiene que haber usado ese: M = max(|M_i|, |M_j|).')
    casos = {c['nombre']: por_id(c['esfuerzos']) for c in anexo['casos']}
    muros = [e for e in anexo['elementos'] if e['tipo'] == 'muro']
    filas, sin_plano, menores = [], [], []
    for e in muros:
        plano = e.get('momento_en_el_plano')
        if plano not in ('My', 'Mz'):
            sin_plano.append('muro %d: momento_en_el_plano = %r' % (e['id'], plano))
            continue
        fuera = 'Mz' if plano == 'My' else 'My'
        m_p = max(abs(v) for c in ('EX', 'EY') for v in casos[c][e['id']][plano])
        m_f = max(abs(v) for c in ('EX', 'EY') for v in casos[c][e['id']][fuera])
        filas.append((m_p / m_f if m_f > 0 else float('inf'), e['id'], plano, m_p, m_f))
        if m_p <= m_f:
            menores.append('muro %d: max |%s| %.1f <= max |%s| %.1f bajo EX y EY'
                           % (e['id'], plano, m_p, fuera, m_f))
    print()
    print('  %d muros: el del plano es My en %d y Mz en %d'
          % (len(muros), sum(1 for f in filas if f[2] == 'My'),
             sum(1 for f in filas if f[2] == 'Mz')))
    for q, eid, plano, m_p, m_f in sorted(filas)[:3]:
        print('    de los mas justos: muro %d, max |%s| = %.1f contra %.1f fuera de plano '
              '(%.1f veces)' % (eid, plano, m_p, m_f, q))
    inf.check(not sin_plano, 'los %d muros traen momento_en_el_plano = My o Mz' % len(muros),
              sin_plano[:6])
    inf.check(filas and not menores, 'en los %d muros el momento del plano es el mayor bajo '
              'EX y EY' % len(filas), menores[:6])

    # La demanda: el M de los resultados es el del plano en el extremo que gana.
    elems = por_id(anexo['elementos'])
    r = 2.0 * R_ANEXO_F
    malas, n = [], 0
    for c in anexo['casos']:
        esf = casos[c['nombre']]
        for d in c['demandas']:
            e = elems[int(d['id'])]
            if e['tipo'] != 'muro' or e.get('momento_en_el_plano') not in ('My', 'Mz'):
                continue
            n += 1
            k = 4 if e['momento_en_el_plano'] == 'My' else 5
            f = esf[int(d['id'])]['f']
            m_plano = max(abs(f[k]), abs(f[6 + k]))
            m_otro = abs(f[9 - k]) if abs(f[k]) >= abs(f[6 + k]) else abs(f[15 - k])
            if abs(float(d['M']) - m_plano) > r + FP * m_plano or \
                    abs(float(d['M_fuera_plano']) - m_otro) > r + FP * m_otro:
                malas.append('%s muro %d: M %.4f y fuera %.4f; |%s| da %.4f y el otro %.4f'
                             % (c['nombre'], d['id'], d['M'], d['M_fuera_plano'],
                                e['momento_en_el_plano'], m_plano, m_otro))
    inf.check(n > 0 and not malas, '%d demandas de muro: M = max(|M_i|, |M_j|) del momento de su '
              'plano, y M fuera de plano = el otro en ese extremo (cota %.0e, dos redondeos)'
              % (n, r), malas[:6])


def bloques_1_8(inf, args):
    fallas_antes = len(inf.fallas)
    print('=' * 78)
    print('  LOS RESULTADOS CONTRA OPENSEES   %s' % _ed.NOMBRE.upper())
    print('=' * 78)
    b = contexto(args.flags)
    anexo, ctx = b['anexo'], b['ctx']
    print('  exportar.resultados.construir() EN MEMORIA (no escribe archivos): %.1f s'
          % b['segundos'])
    print('  %d casos (%s), %d elementos, %d familias P-M'
          % (len(anexo['casos']), ', '.join(c['nombre'] for c in anexo['casos']),
             len(anexo['elementos']), len(anexo['familias'])))
    print('  (%d avisos de no convergencia de OpenSees: son el final de cada curva'
          % b['avisos'])
    print('   M-phi de capacidad.momento_curvatura, que corta ahi y lo anota)')
    print(lab.describir(ctx['p']))

    for nombre, bloque in (
            ('1', lambda: bloque_1(anexo, ctx, inf)),
            ('2', lambda: bloque_2(anexo, ctx, inf)),
            ('3', lambda: bloque_3(anexo, ctx, inf)),
            ('4', lambda: bloque_4(anexo, ctx, inf)),
            ('5', lambda: bloque_5(anexo, ctx, inf)),
            ('6', lambda: bloque_6(inf)),
            ('7', lambda: bloque_7(anexo, inf)),
            ('8', lambda: bloque_8(anexo, inf))):
        t = time.time()
        bloque()
        print('  (bloque [%s]: %.1f s)' % (nombre, time.time() - t))
    print()
    print('=' * 78)
    print('  TODO CALZA' if len(inf.fallas) == fallas_antes else
          '  NO CALZA (%d)' % (len(inf.fallas) - fallas_antes))
    print('=' * 78)


# ============================================================
# R3: TRAZABILIDAD DE UN ELEMENTO
# ============================================================
# Una columna tipica del cuerpo antiguo, de la familia mas numerosa: la
# cadena se mira donde mas barras comparten curva.
ELEMENTO_TRAZABILIDAD = 100018


def capturar_opensees(datos):
    r"""
    Corre opensees.construir_modelo(datos) anotando cada geomTransf y
    cada elasticBeamColumn TAL COMO LLEGAN al motor. El motor decide tres
    cosas por elemento que no estan escritas en el edificio: el E y el G
    (los del material o los propios de la seccion), el vecxz (por
    geometria) y el ORDEN de las inercias (las cruza en los no
    verticales). Rearmar esas reglas aca seria una segunda copia que puede
    divergir en silencio; se envuelve ops.element y ops.geomTransf y se
    anota lo que recibio.

    Devuelve {'elementos': {id: {n1, n2, A, E, G, J, Iy, Iz, transf,
    vecxz}}, 'restringidos': {nodo: [6]}, 'coords', 'avisos'}. Iy e Iz
    son las de la POSICION en que el motor las pasa. El modelo queda
    armado en OpenSees, para poder preguntarle su rigidez.
    """
    ops = opensees.ops
    original_elem, original_transf = ops.element, ops.geomTransf
    transf, elementos = {}, {}

    def geom(*a):
        transf[int(a[1])] = tuple(float(v) for v in a[2:5])
        return original_transf(*a)

    def elem(*a):
        if a[0] == 'elasticBeamColumn':
            eid, n1, n2, A, E, G, J, Iy, Iz, t = a[1:11]
            elementos[int(eid)] = {
                'n1': int(n1), 'n2': int(n2), 'A': float(A), 'E': float(E),
                'G': float(G), 'J': float(J), 'Iy': float(Iy),
                'Iz': float(Iz), 'transf': int(t)}
        return original_elem(*a)

    ops.element, ops.geomTransf = elem, geom
    try:
        coords, avisos, restringidos = opensees.construir_modelo(datos)
    finally:
        ops.element, ops.geomTransf = original_elem, original_transf
    for d in elementos.values():
        d['vecxz'] = transf[d['transf']]
    return {'elementos': elementos, 'restringidos': restringidos,
            'coords': coords, 'avisos': avisos}


def rigidez_basica(eid):
    r"""
    La rigidez basica 6x6 que OpenSees guarda para el elemento, en el
    orden [axial, flexion z (2), flexion y (2), torsion]. Hay que
    llamarla con el modelo de capturar_opensees() todavia armado.
    """
    k = opensees.ops.eleResponse(int(eid), 'basicStiffness')
    return {'EA_L': k[0], '4EIz_L': k[7], '4EIy_L': k[21], 'GJ_L': k[35]}


def maestro_de_nodo(modelo):
    """{nodo: nodo maestro del diafragma al que pertenece}."""
    salida = {}
    for d in modelo.get('diafragmas', []):
        m = int(d['nodo_maestro'])
        salida[m] = m
        for n in d.get('nodos', []):
            salida.setdefault(int(n), m)
    return salida


def casos_y_factores(p):
    """[(nombre, {G, Q, EX, EY})]: los cuatro casos y las combinaciones."""
    salida = [(c, {k: (1.0 if k == c else 0.0) for k in dc.CASOS}) for c in dc.CASOS]
    combos = list(p['combinaciones'])
    if p['combinacion'].get('nombre') not in [c['nombre'] for c in combos]:
        combos.append(p['combinacion'])
    return salida + [(c['nombre'], lab.factores(c)) for c in combos]


def _v(v):
    return ' '.join('%d' % x for x in v)


def explicar_restriccion(nid, r, maestro, nodo):
    r"""
    Por que un nodo tiene esas restricciones, en palabras. r es la lista
    [ux uy uz rx ry rz] que el motor le pasa a ops.fix; maestro es el
    nodo maestro de su diafragma o None. Un nodo de losa con uz, rx y ry
    fijos es un apoyo en el terreno: se nombra el terreno de la vista
    (vista.terrenos) que esta a su cota.
    """
    r = [int(v) for v in r]
    if not any(r):
        return 'libre' + ('' if maestro is None else
                          ': ux, uy y rz los manda el diafragma rigido')
    if all(r):
        return 'empotrado: apoyo en la fundacion'
    if r == [0, 0, 1, 1, 1, 0]:
        if maestro == nid:
            return ('nodo maestro del diafragma: el motor fija los GDL '
                    'fuera del plano del piso (uz, rx, ry)')
        texto = ('fija uz, rx, ry, los GDL que el diafragma NO toca; ux, uy '
                 'y rz los sigue mandando el piso rigido')
        terreno = next((t for t in _ed.vista().get('terrenos', [])
                        if abs(float(t['z']) - float(nodo['z'])) <= 0.01), None)
        if maestro is not None and terreno is not None:
            texto += ('. Es la losa apoyada en el terreno "%s" (z %+.2f), donde no hay '
                      'subterraneo: real, no un error' % (terreno['nombre'], float(terreno['z'])))
        return texto
    return 'apoyo parcial [%s]' % _v(r)


def ancho_y_espesor(s):
    """(b, h) de la seccion; los muros del cuerpo antiguo declaran espesor/largo."""
    return (float(s.get('b') or s.get('espesor') or 0.0),
            float(s.get('h') or s.get('largo') or 0.0))


def momento_en_el_plano(o):
    r"""
    'My' o 'Mz': el momento que flexiona un muro EN SU PLANO, leido de
    las inercias que de verdad recibe OpenSees. Flexion alrededor del
    eje local y la resiste Iy; la inercia grande es la del plano del
    muro. No depende de como cada cuerpo eligio el vecxz: el LT2 da la
    normal (Iz grande) y el cuerpo antiguo la direccion del largo (Iy
    grande).
    """
    return 'My' if o['Iy'] > o['Iz'] else 'Mz'


def fpc_de_E(E_kPa):
    """El f'c (MPa) que corresponde a un Ec = 4700 sqrt(f'c) 1000 kPa."""
    return (float(E_kPa) / 4.7e6) ** 2


def _tabla_de_comparacion(filas):
    """Imprime (etiqueta, python, json, cota) y devuelve cuantas no calzan."""
    malas = 0
    print('    %-28s %19s %19s %19s  %s' % ('', 'Python', 'JSON', 'Unity (float32)', ''))
    for etiqueta, py, js, cota in filas:
        if isinstance(py, (str, bool)) or py is None or js is None:
            ok = (py == js)
            print('    %-28s %19s %19s %19s  %s'
                  % (etiqueta, py, js, js, 'calza' if ok else 'NO CALZA'))
        else:
            u32 = f32(js)
            ok = dentro(py, u32, cota + medio_ulp32(js))
            print('    %-28s %19.10g %19.10g %19.10g  %s'
                  % (etiqueta, py, js, u32, 'calza' if ok else
                     'NO CALZA (dif %.2e, cota %.2e)' % (abs(py - u32), cota)))
        if not ok:
            malas += 1
    return malas


def cadena(eid, caso_pedido=None, flags=()):
    r"""
    La cadena de UN elemento, sacada de Python y no del JSON, y despues
    comparada con salidas/resultados.json, lo que Unity lee:

      (a) OpenSees    el 'element elasticBeamColumn' tal como lo recibe
                      el motor (capturado en la llamada) y lo que guardo
                      (su rigidez basica)
      (b) modelo      tipo, seccion, nodos con coordenadas, restricciones
                      y diafragma, ejes locales
      (c) Unity       el GameObject "Elem_<id>_<tipo>" y su DatoElemento
      (d) resultados  f del caso pedido y N, V, T, M en i y en j
      (e) capacidad   familia, curva P-M y la demanda con su u

    Sin caso, el caso por defecto de los parametros (el que abre el
    visor). Si salidas/resultados.json se armo con otros parametros, se
    compara contra los resultados armados en memoria, sin escribirlos.
    Devuelve el numero de fallas (numeros que no calzan o un cierre > 1).
    """
    p = lab.cargar(list(flags))
    modelo = _ed.estructura()
    elementos = {int(e['id']): e for e in modelo['elementos']}
    if eid not in elementos:
        raise SystemExit('el elemento %d no existe en %s' % (eid, _ed.NOMBRE))
    e = elementos[eid]
    nodos = {int(n['id']): n for n in modelo['nodos']}
    secciones = {s['nombre']: s for s in modelo['secciones']}
    sec_c = secciones[e['seccion']]

    casos = dict(casos_y_factores(p))
    caso_pedido = caso_pedido or p['combinacion']['nombre']
    if caso_pedido not in casos:
        raise SystemExit('no hay caso %r. Hay: %s' % (caso_pedido, ', '.join(casos)))
    lambdas = casos[caso_pedido]

    arm = lab.armar_casos(modelo, p)
    datos, resultados = lab.resolver(modelo, arm['casos'])

    print('=' * 78)
    print('  TRAZABILIDAD   %s, elemento %d, caso %s' % (_ed.NOMBRE, eid, caso_pedido))
    print('=' * 78)
    print(lab.describir(p))

    # ------------------------------------------------------------ (a)
    cap = capturar_opensees(datos)
    o = cap['elementos'][eid]
    k = rigidez_basica(eid)
    pi = cap['coords'][o['n1']]
    pj = cap['coords'][o['n2']]
    ejes, L = _ed.ejes_locales(pi, pj, o['vecxz'])
    print()
    print('(a) OPENSEES   capturado en la llamada de opensees.construir_modelo()')
    print('    ops.geomTransf(\'Linear\', %d, %r, %r, %r)' % ((o['transf'],) + o['vecxz']))
    print('    ops.element(\'elasticBeamColumn\', tag, iNode, jNode, A, E, G, '
          'J, Iy, Iz, transfTag)')
    print('    ops.element(\'elasticBeamColumn\', %d, %d, %d, %r, %r, %r, %r, %r, %r, %d)'
          % (eid, o['n1'], o['n2'], o['A'], o['E'], o['G'], o['J'],
             o['Iy'], o['Iz'], o['transf']))
    # Segunda lectura de las mismas reglas: la replica de los resultados.
    # Si la captura y la replica no dicen lo mismo, los resultados estan
    # mostrando un elemento distinto del que resolvio OpenSees.
    k_eu = es.rigidez_como_el_servidor(e, sec_c, pi, pj, modelo['material'])
    replica = [('E', k_eu['E'], o['E']), ('G', k_eu['G'], o['G']),
               ('Iy', k_eu['Iy_pasa'], o['Iy']),
               ('Iz', k_eu['Iz_pasa'], o['Iz'])] + [
        ('vecxz[%d]' % i, k_eu['vecxz'][i], o['vecxz'][i]) for i in range(3)]
    distintos = [n for n, a, b in replica if not dentro(a, b, 0.0)]
    print('    %s: vertical=%s  %s'
          % ('elemento vertical (proyeccion horizontal / L < 1e-6)'
             if k_eu['vertical'] else 'elemento NO vertical',
             k_eu['vertical'],
             'la replica de los resultados (rigidez_como_el_servidor) da lo mismo'
             if not distintos else
             'la replica de los resultados NO CALZA en %s' % ', '.join(distintos)))
    if k_eu['vertical'] or float(sec_c['Iy']) == float(sec_c['Iz']):
        print('    inercias en su posicion: Iy e Iz del edificio van donde '
              'OpenSees las espera')
    else:
        print('    inercias CRUZADAS: en la posicion Iy va la Iz del edificio '
              '(gravedad, b h^3/12), porque')
        print('    el elemento no es vertical y vecxz=(0,0,1) deja el z local vertical')
    print('    E y G: %s' % ('propios de la seccion %r' % e['seccion']
                            if 'E' in sec_c else
                            'del material, Ec = 4700 sqrt(%g) * 1000 kPa'
                            % float(modelo['material']['fpc_MPa'])))
    print('    lo que OpenSees guardo (eleResponse basicStiffness):')
    print('      EA/L = %.6g   4EIz/L = %.6g   4EIy/L = %.6g   GJ/L = %.6g'
          % (k['EA_L'], k['4EIz_L'], k['4EIy_L'], k['GJ_L']))
    print('      de vuelta: E*A %.6g (pasado %.6g)  E*Iz %.6g (%.6g)  '
          'E*Iy %.6g (%.6g)  G*J %.6g (%.6g)'
          % (k['EA_L'] * L, o['E'] * o['A'], k['4EIz_L'] * L / 4,
             o['E'] * o['Iz'], k['4EIy_L'] * L / 4, o['E'] * o['Iy'],
             k['GJ_L'] * L, o['G'] * o['J']))

    # ------------------------------------------------------------ (b)
    maestros = maestro_de_nodo(modelo)
    print()
    print('(b) MODELO   %s' % rel(rutas.EDIFICIO))
    b_s, h_s = ancho_y_espesor(sec_c)
    print('    tipo %s, seccion %s: A=%.6g Iy=%.6g (lateral) Iz=%.6g '
          '(gravedad) J=%.6g  b=%.3g h=%.3g m'
          % (e['tipo'], e['seccion'], sec_c['A'], sec_c['Iy'], sec_c['Iz'],
             sec_c['J'], b_s, h_s))
    restr_eu = es.restricciones_como_el_servidor(modelo)
    for extremo, nid in (('i', o['n1']), ('j', o['n2'])):
        n = nodos[nid]
        m = maestros.get(nid)
        r = cap['restringidos'].get(nid, [0] * 6)
        print('    nodo %s = %-6d (%9.3f, %9.3f, %8.3f)  [ux uy uz rx ry rz] = [%s]  %s'
              % (extremo, nid, n['x'], n['y'], n['z'], _v(r),
                 'diafragma de maestro %d' % m if m is not None else 'sin diafragma'))
        print('        %s' % explicar_restriccion(nid, r, m, n))
        if list(r) != list(restr_eu.get(nid, [0] * 6)):
            print('        OJO: restricciones_como_el_servidor da [%s]'
                  % _v(restr_eu.get(nid, [0] * 6)))
    print('    L = %.6f m;  vecxz = (%g, %g, %g) %s'
          % ((L,) + o['vecxz'] + ('del elemento' if e.get('vecxz') else 'por geometria',)))
    for eje in ('wx', 'wy', 'wz'):
        print('    %s local = (%+.6f, %+.6f, %+.6f)' % ((eje[1],) + tuple(ejes[eje])))
    if e['tipo'] in ('brazo', 'brazo_rigido'):
        print('    brazo rigido: barra x100 hasta la cara del muro, no rigidLink')

    # ------------------------------------------------------------ (c)
    unity = {}
    ruta_u = rutas.salida('modelo')
    if os.path.isfile(ruta_u):
        with io.open(ruta_u, encoding='utf-8') as fh:
            unity = {int(x['id']): x for x in json.load(fh)['elementos']}
    eu_el = unity.get(eid)
    linea, texto = regla_de_nombre_en_visor()
    print()
    print('(c) UNITY   %s -> VisorEstructura' % rel(ruta_u))
    if eu_el is None:
        print('    el elemento NO esta en %s: Unity no lo dibuja' % rel(ruta_u))
    else:
        print('    GameObject "%s"   DatoElemento.idElemento = %d'
              % (nombre_objeto(eu_el), int(eu_el['id'])))
        print('    n1 %s, n2 %s, tipo %s, seccion %s: %s con el modelo'
              % (eu_el['n1'], eu_el['n2'], eu_el['tipo'], eu_el['seccion'],
                 'iguales' if all(eu_el[c] == e[c] for c in ('n1', 'n2', 'tipo', 'seccion'))
                 else 'DISTINTOS'))
    print('    regla en VisorEstructura.cs linea %s: %s'
          % (linea, texto or 'NO ENCONTRADA (%s)' % LITERAL_NOMBRE))

    # ------------------------------------------------------------ (d)
    por_caso = dc.fuerzas_por_caso(resultados, eid)
    f = dc.combinar(por_caso, lambdas)
    w = [0.0, 0.0, 0.0]
    for c, lam in lambdas.items():
        wc = es.cargas_por_elemento(arm['casos'][c]).get(eid, (0.0, 0.0, 0.0))
        for i in range(3):
            w[i] += lam * wc[i]
    cargada = any(abs(v) > 0.0 for v in w)
    xs = es.estaciones(L, cargada)
    esf = es.esfuerzos_internos(f, tuple(w), xs)
    desp = {int(d['id']): d for d in sp.combinar_resultados(resultados, lambdas)['desplazamientos']}
    print()
    print('(d) RESULTADOS   laboratorio.resolver() en memoria; caso %s = %s'
          % (caso_pedido, lab.como_texto(lambdas)))
    print('    f (localForce, sobre el elemento, ejes locales):')
    print('      i: ' + '  '.join('%s=%.4f' % (c, v) for c, v in zip(COMP, f[:6])))
    print('      j: ' + '  '.join('%s=%.4f' % (c, v) for c, v in zip(COMP, f[6:])))
    print('    w local combinado (wx, wy, wz) = (%.4f, %.4f, %.4f) kN/m;  %d estaciones'
          % (w[0], w[1], w[2], len(xs)))
    print('    esfuerzos INTERNOS (N traccion +; My > 0 tracciona +z; Mz < 0 tracciona +y):')
    print('      %-10s' % 'x [m]' + ''.join('%12s' % c for c in COMP))
    for idx in sorted({0, len(xs) // 2, len(xs) - 1}):
        print('      %-10.4f' % xs[idx] + ''.join('%12.4f' % esf[c][idx] for c in COMP))
    # El cierre: las formulas evaluadas en x = L tienen que devolver f_j,
    # que OpenSees calculo por su lado. La cota es la de los resultados,
    # medida contra su causa (redondeo del servidor por caso, x*V_i en los
    # momentos, y la coma flotante), no elegida a ojo.
    activos = {c: lam for c, lam in lambdas.items() if lam != 0.0}
    suma_lambdas = sum(abs(lam) for lam in activos.values())
    magnitudes = [0.0] * 6
    for c, lam in activos.items():
        wc = es.cargas_por_elemento(arm['casos'][c]).get(eid, (0.0, 0.0, 0.0))
        m_c = es.magnitudes_de_cierre(por_caso[c], wc, L)
        magnitudes = [a + abs(lam) * b for a, b in zip(magnitudes, m_c)]
    cotas = es.cota_de_cierre(L, suma_lambdas, magnitudes)
    cociente, peor = es.cociente_de_cierre(f, tuple(w), L, suma_lambdas, magnitudes)
    print('    cierre en x = L: las formulas en x = L tienen que devolver f_j, '
          'que OpenSees calculo aparte')
    print('      cota = 5e-5 * 2 (N, V, T) o 5e-5 * (2 + L) (My, Mz), por '
          'sum|lambda| = %g, + 4 eps * magnitud' % suma_lambdas)
    for kk, c in enumerate(COMP):
        err = abs(esf[c][-1] - f[6 + kk])
        print('      %-3s  esfuerzo(L) = %12.5f   f_j = %12.5f   error %.2e   cota %.2e  %s'
              % (c, esf[c][-1], f[6 + kk], err, cotas[kk],
                 'ok' if err <= cotas[kk] else 'NO CIERRA'))
    print('      peor error/cota = %.3f en %s  -> %s'
          % (cociente, peor, 'cierra' if cociente <= 1.0 else 'NO CIERRA'))
    for extremo, nid in (('i', o['n1']), ('j', o['n2'])):
        d = desp[nid]
        print('    u nodo %s: ux %.3e  uy %.3e  uz %.3e  rx %.3e  ry %.3e  rz %.3e'
              % (extremo, d['ux'], d['uy'], d['uz'], d['rx'], d['ry'], d['rz']))

    # ------------------------------------------------------------ (e)
    print()
    print('(e) SECCION Y CAPACIDAD')
    demanda = curva = firma = None
    if not e.get('enfierradura'):
        print('    sin enfierradura: no tiene curva P-M (familia -1)')
    else:
        sec = capacidad.desde_elemento(modelo, eid)
        firma = dc.firma_de_seccion(e, sec)
        miembros = sorted(
            int(x['id']) for x in modelo['elementos']
            if x.get('enfierradura') and dc.firma_de_seccion(
                x, capacidad.desde_elemento(modelo, int(x['id']))) == firma)
        with opensees.AvisosDeOpenSees() as avisos:
            curva = capacidad.interaccion(sec)
        demanda = dc.demanda(f, e['tipo'],
                             dc.momento_en_el_plano_de(modelo, e) if e['tipo'] == 'muro' else None)
        Mn = dc.capacidad_en(demanda['P_kN'], curva)
        demanda['Mn'] = Mn
        # El mismo umbral que demanda.revisar y los resultados.
        demanda['u'] = demanda['M_kNm'] / Mn if Mn > 1e-9 else 9999.0
        print('\n'.join('    ' + x for x in sec.resumen().splitlines()))
        if avisos.resumen():
            print('    (%s)' % avisos.resumen())
        # f'c de la capacidad contra el E con que se resolvio: si la
        # seccion trae E propio, el f'c que le corresponde es
        # (E / 4700 / 1000)^2. La cota es lo que mueve el redondeo a 4
        # decimales del E escrito: d f'c = 2 f'c dE / E.
        if sec_c.get('E'):
            fpc_E = fpc_de_E(sec_c['E'])
            cota_fpc = 2.0 * fpc_E * 5e-5 / float(sec_c['E']) + 1e-9
            fpc_cap = sec.fpc / 1000.0
            if abs(fpc_cap - fpc_E) > cota_fpc:
                print('    OJO: la seccion se resuelve con E = %.1f kPa, que '
                      "es f'c = %.2f MPa, pero la curva usa f'c = %.2f MPa"
                      % (float(sec_c['E']), fpc_E, fpc_cap))
                print("         (calculo/capacidad.py toma el f'c de la seccion o, si no "
                      "lo trae, el de modelo['material'])")
        print('    familia (demanda.firma_de_seccion): %s' % (firma,))
        print('    %d elementos la comparten: %s%s'
              % (len(miembros), miembros[:12], ' ...' if len(miembros) > 12 else ''))
        print('    curva (capacidad.interaccion):')
        for pt in curva:
            print('      P = %10.1f kN   Mn = %9.1f kN m   %s' % (pt['P_kN'], pt['M_kNm'], pt['de']))
        print('    demanda en %s: P = %.1f kN, M = %.1f kN m%s, extremo %s'
              % (caso_pedido, demanda['P_kN'], demanda['M_kNm'],
                 ('' if demanda['M_fuera_de_plano_kNm'] is None else
                  ', fuera de plano %.1f' % demanda['M_fuera_de_plano_kNm']),
                 demanda['extremo']))
        P_min = min(float(pt['P_kN']) for pt in curva)
        P_max = max(float(pt['P_kN']) for pt in curva)
        if Mn > 1e-9:
            print('    Mn(P) = %.1f kN m  ->  u = M / Mn = %.3f  %s'
                  % (Mn, demanda['u'],
                     'pasa' if demanda['u'] <= 1 else 'NO PASA (nominal, sin phi)'))
        elif demanda['P_kN'] < P_min:
            print('    NO PASA, y no por flexion: P = %.1f kN es TRACCION y '
                  'supera la traccion pura' % demanda['P_kN'])
            print('    de la seccion (%.1f kN = fy * As). Con esa axial no '
                  'queda momento resistente,' % P_min)
            print('    Mn = 0 y M / Mn no se define. Los resultados lo marcan con u = '
                  '9999: es una bandera, no un cociente.')
        elif demanda['P_kN'] > P_max:
            print('    NO PASA, y no por flexion: P = %.1f kN supera la '
                  'compresion pura (%.1f kN).' % (demanda['P_kN'], P_max))
            print('    Mn = 0 y M / Mn no se define; los resultados lo marcan con u = 9999.')
        else:
            print('    Mn(P) = 0 dentro de la curva: u no se define (resultados: 9999)')
        if e['tipo'] == 'muro':
            # Dos lecturas independientes del mismo eje: las inercias que
            # recibe OpenSees (el elementTag) y la seccion del modelo que
            # usa demanda.
            eje = momento_en_el_plano(o)
            usado = demanda['plano']
            fuera = 'Mz' if usado == 'My' else 'My'
            print('    muro: OpenSees recibe Iy = %.4g e Iz = %.4g, asi que el '
                  'momento EN SU PLANO es %s' % (o['Iy'], o['Iz'], eje))
            print('    demanda compara |%s| con la curva; |%s| es el '
                  'fuera de plano y se informa aparte' % (usado, fuera))
            if eje != usado:
                print('    OJO: el elementTag dice %s y demanda usa %s' % (eje, usado))

    # ------------------------------------------------ contra el JSON
    print()
    anexo, motivo = None, None
    mias = [x.strip() for x in lab.describir(p).split('\n')]
    disco, ruta = leer_resultados()
    if disco is None:
        motivo = '%s no existe' % rel(ruta)
    else:
        anexo = disco
        if anexo['info']['edificio'] != _ed.NOMBRE:
            motivo = '%s es de %s, no de %s' % (rel(ruta), anexo['info']['edificio'], _ed.NOMBRE)
        elif [x.strip() for x in anexo['info'].get('parametros', [])] != mias:
            motivo = ('%s se exporto con otros parametros: %s'
                      % (rel(ruta), ' | '.join(anexo['info'].get('parametros', []))))
    if motivo is None:
        print('CONTRA %s (lo que lee VisorResultados; la copia de StreamingAssets es la misma)'
              % rel(ruta))
    else:
        from exportar.resultados import construir
        print('CONTRA LOS RESULTADOS EN MEMORIA: %s.' % motivo)
        print('    Se arman con exportar.resultados.construir y se pasan por json.dumps/loads,')
        print('    sin escribirlos: es lo que Unity leeria si se exportaran. El archivo no se toca.')
        with opensees.AvisosDeOpenSees() as avisos_anexo:
            anexo, _ctx = construir(list(flags))
        anexo = json.loads(json.dumps(anexo, separators=(',', ':')))
        if avisos_anexo.resumen():
            print('    (%s)' % avisos_anexo.resumen())
    el = next((x for x in anexo['elementos'] if int(x['id']) == eid), None)
    if el is None:
        print('    el elemento %d NO esta en los resultados' % eid)
        return 1

    def cota_campo(lista, campo):
        return medio_decimal(v for x in lista for v in (
            x[campo] if isinstance(x[campo], list) else [x[campo]]))

    filas = [('objeto_unity', nombre_objeto(eu_el or e), el['objeto_unity'], 0),
             ('tipo', e['tipo'], el['tipo'], 0),
             ('seccion', e['seccion'], el['seccion'], 0),
             ('n1', o['n1'], el['n1'], 0), ('n2', o['n2'], el['n2'], 0)]
    # tag_opensees es TEXTO: cada numero se compara contra lo capturado en
    # ops.element con medio ultimo digito escrito de cota.
    m_tag = re.match(r'element elasticBeamColumn (\d+) (\d+) (\d+) ', el['tag_opensees'])
    filas.append(('tag: tag n1 n2', '%d %d %d' % (eid, o['n1'], o['n2']),
                  ' '.join(m_tag.groups()) if m_tag else el['tag_opensees'], 0))
    pares = dict(re.findall(r'(\w+)=([^\s]+)', el['tag_opensees']))
    for clave in ('A', 'E', 'G', 'J', 'Iy', 'Iz'):
        if clave in pares:
            filas.append(('tag: %s (posicion OpenSees)' % clave, o[clave],
                          float(pares[clave]), medio_digito(pares[clave])))
        else:
            filas.append(('tag: %s' % clave, 'escrito', 'falta', 0))
    # El vecxz va con '%g': seis cifras SIGNIFICATIVAS, no decimales fijos.
    # '1' no esta redondeado a la unidad; la cota es media sexta cifra.
    vec_txt = pares.get('vecxz', '()').strip('()').split(',')
    for i in range(3):
        t = vec_txt[i] if i < len(vec_txt) else None
        v = float(t) if t else None
        cota_g = 0.5 * 10.0 ** (math.floor(math.log10(abs(v))) - 5) if v else 0.0
        filas.append(('tag: vecxz[%d]' % i, o['vecxz'][i], v, cota_g))
    for campo, py in (('L', L), ('E_kPa', o['E']), ('G_kPa', o['G']),
                      ('A', float(sec_c['A'])), ('Iy', float(sec_c['Iy'])),
                      ('Iz', float(sec_c['Iz'])), ('J', float(sec_c['J']))):
        filas.append((campo, py, el[campo], cota_campo(anexo['elementos'], campo)))
    for i in range(3):
        filas.append(('vecxz[%d]' % i, o['vecxz'][i], el['vecxz'][i],
                      cota_campo(anexo['elementos'], 'vecxz')))
    for extremo, nid in (('restr_n1', o['n1']), ('restr_n2', o['n2'])):
        filas.append((extremo, _v(cap['restringidos'].get(nid, [0] * 6)), _v(el[extremo]), 0))
    filas.append(('diafragma_n1', maestros.get(o['n1'], -1), el['diafragma_n1'], 0))
    filas.append(('diafragma_n2', maestros.get(o['n2'], -1), el['diafragma_n2'], 0))

    caso = next((c for c in anexo['casos'] if c['nombre'] == caso_pedido), None)
    if caso is None:
        print('    el caso %s no esta en los resultados' % caso_pedido)
    else:
        s = next(x for x in caso['esfuerzos'] if int(x['id']) == eid)
        cf = cota_campo(caso['esfuerzos'], 'f')
        for i, c in enumerate(COMP):
            filas.append(('f %s_i' % c, f[i], s['f'][i], cf))
        for i, c in enumerate(COMP):
            filas.append(('f %s_j' % c, f[6 + i], s['f'][6 + i], cf))
        filas.append(('estaciones', len(xs), len(s['x']), 0))
        for c in COMP:
            ce = cota_campo(caso['esfuerzos'], c)
            filas.append(('%s(0)' % c, esf[c][0], s[c][0], ce))
            filas.append(('%s(L)' % c, esf[c][-1], s[c][-1], ce))
        dem = next((x for x in caso['demandas'] if int(x['id']) == eid), None)
        if demanda and dem:
            cd = {kk: cota_campo(caso['demandas'], kk)
                  for kk in ('P', 'M', 'M_fuera_plano', 'Mn', 'u')}
            filas += [('demanda P', demanda['P_kN'], dem['P'], cd['P']),
                      ('demanda M', demanda['M_kNm'], dem['M'], cd['M']),
                      ('demanda M fuera de plano', demanda['M_fuera_de_plano_kNm'] or 0.0,
                       dem['M_fuera_plano'], cd['M_fuera_plano']),
                      ('demanda extremo', demanda['extremo'], dem['extremo'], 0),
                      ('Mn', demanda['Mn'], dem['Mn'], cd['Mn']),
                      ('u' if demanda['Mn'] > 1e-9 else 'u (9999 = Mn 0, sin cociente)',
                       demanda['u'], dem['u'], cd['u']),
                      ('pasa', demanda['u'] <= 1.0, dem['pasa'], 0)]
        elif demanda or dem:
            filas.append(('tiene demanda', bool(demanda), bool(dem), 0))
    if curva is not None and el['familia'] >= 0:
        fam = anexo['familias'][el['familia']]
        filas.append(('familia %d: elementos' % el['familia'], 'contiene',
                      'contiene' if eid in fam['elementos'] else 'no', 0))
        filas.append(('puntos de la curva', len(curva), len(fam['P']), 0))
        for i, pt in enumerate(curva[:len(fam['P'])]):
            filas.append(('curva P[%d]' % i, pt['P_kN'], fam['P'][i], medio_decimal(fam['P'])))
            filas.append(('curva Mn[%d]' % i, pt['M_kNm'], fam['Mn'][i], medio_decimal(fam['Mn'])))
    elif curva is not None or el['familia'] >= 0:
        filas.append(('familia', 'con fierro' if curva else -1,
                      el['familia'] if el['familia'] < 0 else 'con fierro', 0))

    malas = _tabla_de_comparacion(filas)
    print()
    print('    cota de cada numero: el redondeo con que los resultados escriben esa familia de')
    print('    valores (medido) mas medio intervalo float32 (lo que pierde JsonUtility)')
    print('=' * 78)
    if cociente > 1.0:
        print('  EL ELEMENTO NO CIERRA en x = L (error/cota %.3f en %s)' % (cociente, peor))
    if malas:
        print('  %d NUMERO(S) NO CALZAN con lo que lee Unity' % malas)
    if malas or cociente > 1.0:
        return malas + (1 if cociente > 1.0 else 0)
    print('  LA CADENA CALZA: OpenSees -> modelo -> Unity -> resultados -> capacidad')
    return 0


def trazabilidad(inf, args):
    eid = args.elemento if args.elemento is not None else ELEMENTO_TRAZABILIDAD
    fallas = cadena(eid, args.caso, args.flags)
    inf.check(fallas == 0, 'la cadena de %d calza: OpenSees -> modelo -> Unity -> resultados '
              '-> capacidad' % eid)


# ============================================================
# R4: SUPERPOSICION E1..E3 POR CUATRO VIAS
# ============================================================
VIAS = {
    '1': 'superposicion.resolver_explicito (OpenSees con la carga combinada, la referencia)',
    '2': 'superposicion.caso_combinado (suma lineal de los casos base)',
    '3': 'POST /combinar de exportar/servidor.py por app.test_client()',
    '4': 'salidas/resultados.json, bloque superposicion (precalculado, exe sin servidor)',
}

FAMILIAS = ('desplazamientos', 'max_desplazamiento_mm', 'fuerzas f', 'estaciones x',
            'estaciones N..Mz', 'D/C P', 'D/C M', 'D/C M fuera de plano', 'D/C Mn',
            'D/C u', 'D/C = demanda.revisar')

# Por que dos familias quedan en 1.000 o casi, y no es un aviso: en las
# dos la unica diferencia posible es el redondeo con que la via ESCRIBE,
# y un valor que cae justo en el medio de dos decimales la alcanza entera.
NOTAS_COCIENTES = [
    'estaciones x = 1.000: una estacion k L / 8 puede tener un decimal mas de los que los '
    'resultados escriben; si ese decimal es un 5, el error es exactamente el medio ultimo '
    'decimal. Es el redondeo mismo, no un desvio (el caso concreto se imprime abajo).',
    'D/C = demanda.revisar ~ 0.99: demanda.revisar arma el mismo punto con las mismas fuerzas '
    'base, asi que solo difiere el redondeo de salida (u a 6 decimales, P, M y Mn a 4); entre '
    'todos los elementos con fierro por 5 campos siempre hay uno pegado al medio decimal.',
]


def detalle_de_x(b, donde):
    """'elemento 355 x[4]' -> el largo, la x exacta y la escrita, para la nota."""
    partes = (donde or '').split()
    if len(partes) != 3 or partes[0] != 'elemento' or not partes[2].startswith('x['):
        return None
    eid, i = int(partes[1]), int(partes[2][2:-1])
    L = b['largos'][eid]
    xs = es.estaciones(L, True)
    if i >= len(xs):
        xs = es.estaciones(L, False)
    x = xs[i]
    return ('elemento %d: L = %.10g m, x[%d] = %.10g exacta, escrita %r; error %.3e'
            % (eid, L, i, x, round(x, es.DECIMALES_ESTACION),
               abs(round(x, es.DECIMALES_ESTACION) - x)))


class Peor(object):
    """El peor error/cota de una familia de valores, y donde fue."""

    def __init__(self):
        self.n = 0
        self.fuera = 0
        self.cociente = 0.0
        self.err = 0.0
        self.cota = 0.0
        self.donde = None

    def ver(self, err, cota, donde):
        self.n += 1
        err = abs(err)
        c = err / cota if cota > 0 else (0.0 if err == 0 else math.inf)
        if c > 1.0:
            self.fuera += 1
        if self.n == 1 or c > self.cociente:
            self.cociente, self.err, self.cota, self.donde = c, err, cota, donde

    @property
    def calza(self):
        # Una familia sin valores no se aprueba por vacio.
        return self.n > 0 and self.fuera == 0


def texto_donde(donde):
    if donde is None:
        return ''
    return ' '.join(str(x) for x in donde)


def r_de(resultado, clave, campos):
    """Medio ultimo decimal de una familia de un resultado del servidor."""
    d = sp.decimales_de(resultado, clave, campos)
    return 0.5 * 10.0 ** -d if d else 0.0


def diferencias(a, b, ruta='$'):
    r"""
    (hojas comparadas, primera diferencia o None), exacto. Sirve para
    las vias que tienen que ser el MISMO calculo que (2): un float que
    viaja por json.dumps/loads vuelve bit a bit (repr de Python).
    """
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return 0, '%s: claves %s' % (ruta, sorted(set(a) ^ set(b)))
        n = 0
        for k in a:
            m, d = diferencias(a[k], b[k], '%s.%s' % (ruta, k))
            n += m
            if d:
                return n, d
        return n, None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return 0, '%s: largo %d contra %d' % (ruta, len(a), len(b))
        n = 0
        for i, (x, y) in enumerate(zip(a, b)):
            m, d = diferencias(x, y, '%s[%d]' % (ruta, i))
            n += m
            if d:
                return n, d
        return n, None
    if type(a) is not type(b) or a != b:
        return 1, '%s: %r contra %r' % (ruta, a, b)
    return 1, None


def momentos_de_extremos(f, tipo, plano):
    r"""
    El M de cada extremo con la regla de demanda.demanda (columna
    hypot(My, Mz), muro |M del plano|). Solo para decidir si el extremo
    que manda esta dentro del redondeo; la demanda misma la calcula
    demanda.demanda.
    """
    if tipo == 'muro':
        k = 4 if plano == 'My' else 5
        return abs(f[k]), abs(f[6 + k])
    return math.hypot(f[4], f[5]), math.hypot(f[10], f[11])


def pendiente_cerca(curva, P, e):
    """Mayor |dMn/dP| de los tramos de la curva que tocan [P - e, P + e]."""
    pts = sorted(((float(p['P_kN']), float(p['M_kNm'])) for p in curva), key=lambda t: t[0])
    s = 0.0
    for (p1, m1), (p2, m2) in zip(pts, pts[1:]):
        if p2 < P - e or p1 > P + e:
            continue
        if abs(p2 - p1) < 1e-9:
            continue
        s = max(s, abs((m2 - m1) / (p2 - p1)))
    return s, pts[0][0], pts[-1][0]


def u_de(M, Mn):
    return M / Mn if Mn > 1e-9 else U_FUERA


def referencia(b, lam, nombre):
    r"""
    Todo lo que sale de la corrida explicita y lo que se necesita para
    las cotas. Nada de esto usa superposicion.caso_combinado.
    """
    ctx = b['ctx']
    datos, resultados = ctx['datos'], ctx['resultados']
    activos = {c: l for c, l in lam.items() if l != 0.0}
    suma = sum(abs(l) for l in activos.values())

    t = time.time()
    exp = sp.resolver_explicito(datos, lam, nombre)
    t_exp = time.time() - t

    carga = sp.combinar_cargas(datos, lam, nombre)
    r = {
        'exp': exp, 't': t_exp, 'activos': activos, 'suma': suma, 'carga': carga,
        'f': {int(x['id']): [float(v) for v in x['f']] for x in exp['fuerzas_elementos']},
        'u': {int(x['id']): [float(x[k]) for k in CAMPOS_U] for x in exp['desplazamientos']},
        'f_base': {c: {int(x['id']): [float(v) for v in x['f']]
                       for x in resultados[c]['fuerzas_elementos']} for c in activos},
        'u_base': {c: {int(x['id']): [float(x[k]) for k in CAMPOS_U]
                       for x in resultados[c]['desplazamientos']} for c in activos},
        # La carga repartida combinada por OTRO camino que bloque_caso.
        'w': es.cargas_por_elemento(carga),
    }

    def e_lin(clave, campos):
        r_base = max((r_de(resultados[c], clave, campos) for c in activos), default=0.0)
        return r_base * suma + r_de(exp, clave, campos), r_base

    r['e_u'], r['r_base_u'] = e_lin('desplazamientos', CAMPOS_U)
    r['e_f'], r['r_base_f'] = e_lin('fuerzas_elementos', None)
    r['e_r'], r['r_base_r'] = e_lin('reacciones', CAMPOS_R)
    r['r_exp_r'] = r_de(exp, 'reacciones', CAMPOS_R)

    u_max = 0.0
    for nid, v in r['u'].items():
        u_max = max(u_max, math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2))
    r['max_mm'] = 1000.0 * u_max

    # Demanda-capacidad con la f explicita.
    curvas = ctx['curvas']
    r['dc'] = {}
    for e in b['anexo']['elementos']:
        fam = int(e['familia'])
        if fam < 0:
            continue
        eid = int(e['id'])
        f = r['f'][eid]
        plano = e['momento_en_el_plano'] or None
        d = dc.demanda(f, e['tipo'], plano)
        Mn = dc.capacidad_en(d['P_kN'], curvas[fam])
        Mi, Mj = momentos_de_extremos(f, e['tipo'], plano)
        r['dc'][eid] = {'d': d, 'Mn': Mn, 'u': u_de(d['M_kNm'], Mn), 'fam': fam,
                        'tipo': e['tipo'], 'plano': plano, 'Mi': Mi, 'Mj': Mj}
    return r


def comparar_via(b, lam, ref, caso):
    """{familia: Peor} y lo indecidible por redondeo."""
    peores = {k: Peor() for k in FAMILIAS if k != 'D/C = demanda.revisar'}
    indecidibles = []
    activos, suma = ref['activos'], ref['suma']

    # --- desplazamientos ---
    r_u = medio_decimal(v for d in caso['desplazamientos'] for v in (d[k] for k in CAMPOS_U))
    desp = por_id(caso['desplazamientos'])
    ids_ok = set(desp) == set(ref['u'])
    for nid, v_exp in (ref['u'].items() if ids_ok else ()):
        for k, campo in enumerate(CAMPOS_U):
            mag = abs(v_exp[k]) + sum(abs(l) * abs(ref['u_base'][c][nid][k])
                                      for c, l in activos.items())
            peores['desplazamientos'].ver(float(desp[nid][campo]) - v_exp[k],
                                          ref['e_u'] + r_u + FP * mag, ('nodo', nid, campo))
    if not ids_ok:
        peores['desplazamientos'].ver(math.inf, 0.0, ('ids de nodos distintos',))

    r_mm = medio_decimal([caso['max_desplazamiento_mm']])
    peores['max_desplazamiento_mm'].ver(
        caso['max_desplazamiento_mm'] - ref['max_mm'],
        1000.0 * math.sqrt(3.0) * (ref['e_u'] + r_u) + r_mm + FP * ref['max_mm'],
        ('mm',))

    # --- fuerzas y estaciones ---
    esf = por_id(caso['esfuerzos'])
    r_f = medio_decimal(v for s in caso['esfuerzos'] for v in s['f'])
    r_est = medio_decimal(v for s in caso['esfuerzos'] for k in COMP for v in s[k])
    r_x = medio_decimal(v for s in caso['esfuerzos'] for v in s['x'])
    ids_ok = set(esf) == set(ref['f'])
    if not ids_ok:
        peores['fuerzas f'].ver(math.inf, 0.0, ('ids de barras distintos',))
    for eid, f_exp in (ref['f'].items() if ids_ok else ()):
        s = esf[eid]
        for k in range(12):
            mag = abs(f_exp[k]) + sum(abs(l) * abs(ref['f_base'][c][eid][k])
                                      for c, l in activos.items())
            peores['fuerzas f'].ver(float(s['f'][k]) - f_exp[k],
                                    ref['e_f'] + r_f + FP * mag, ('elemento', eid, 'f[%d]' % k))

        L = b['largos'][eid]
        w = ref['w'].get(eid, (0.0, 0.0, 0.0))
        xs = es.estaciones(L, any(v != 0.0 for v in w))
        if len(xs) != len(s['x']) or any(len(s[k]) != len(xs) for k in COMP):
            peores['estaciones x'].ver(math.inf, 0.0, ('elemento', eid, 'cantidad de estaciones'))
            continue
        internos = es.esfuerzos_internos(f_exp, w, xs)
        mags = es.magnitudes_de_cierre(f_exp, w, L)
        for c, l in activos.items():
            m_c = es.magnitudes_de_cierre(ref['f_base'][c][eid],
                                          b['cargas_base'][c].get(eid, (0.0, 0.0, 0.0)), L)
            mags = [a + abs(l) * m for a, m in zip(mags, m_c)]
        for i, x in enumerate(xs):
            peores['estaciones x'].ver(float(s['x'][i]) - x, r_x + FP * L,
                                       ('elemento', eid, 'x[%d]' % i))
            for k, nombre in enumerate(COMP):
                e = ref['e_f'] * (1.0 + x) if nombre in ('My', 'Mz') else ref['e_f']
                peores['estaciones N..Mz'].ver(
                    float(s[nombre][i]) - internos[nombre][i], e + r_est + FP * mags[k],
                    ('elemento', eid, '%s(x=%.4f)' % (nombre, x)))

    # --- demanda-capacidad ---
    dem = por_id(caso['demandas'])
    r_dc = medio_decimal(v for d in caso['demandas'] for v in (d['P'], d['M'], d['M_fuera_plano'], d['Mn']))
    r_uu = medio_decimal(d['u'] for d in caso['demandas'] if d['u'] < U_FUERA)
    if set(dem) != set(ref['dc']):
        peores['D/C P'].ver(math.inf, 0.0, ('ids con fierro distintos',))
    curvas = b['ctx']['curvas']
    for eid, rd in ref['dc'].items():
        v = dem.get(eid)
        if v is None:
            continue
        d, e = rd['d'], ref['e_f']
        dM = math.sqrt(2.0) * e if rd['tipo'] != 'muro' else e
        mag = FP * (1.0 + suma) * (abs(d['P_kN']) + d['M_kNm'] + rd['Mn'] + 1.0)
        if int(v['familia']) != rd['fam']:
            peores['D/C P'].ver(math.inf, 0.0, ('elemento', eid, 'familia'))
            continue
        if v['extremo'] != d['extremo']:
            if abs(rd['Mi'] - rd['Mj']) <= 2.0 * dM:
                indecidibles.append('elemento %d: extremo (M_i %.4f, M_j %.4f)'
                                    % (eid, rd['Mi'], rd['Mj']))
                continue
            peores['D/C M'].ver(math.inf, 0.0, ('elemento', eid, 'extremo'))
            continue
        peores['D/C P'].ver(v['P'] - d['P_kN'], e + r_dc + mag, ('elemento', eid, 'P'))
        peores['D/C M'].ver(v['M'] - d['M_kNm'], dM + r_dc + mag, ('elemento', eid, 'M'))
        peores['D/C M fuera de plano'].ver(
            v['M_fuera_plano'] - (d['M_fuera_de_plano_kNm'] or 0.0),
            (e if rd['tipo'] == 'muro' else 0.0) + r_dc + mag, ('elemento', eid, 'M fuera'))
        s, P_min, P_max = pendiente_cerca(curvas[rd['fam']], d['P_kN'], e)
        dMn = s * e
        peores['D/C Mn'].ver(v['Mn'] - rd['Mn'], dMn + r_dc + mag, ('elemento', eid, 'Mn'))

        cerca_del_borde = min(abs(d['P_kN'] - P_min), abs(d['P_kN'] - P_max)) <= e
        if v['u'] >= U_FUERA and rd['u'] >= U_FUERA:
            peores['D/C u'].ver(0.0, 1.0, ('elemento', eid, 'u fuera de curva'))
        elif (v['u'] >= U_FUERA) != (rd['u'] >= U_FUERA):
            if cerca_del_borde or rd['Mn'] <= dMn + 1e-9:
                indecidibles.append('elemento %d: fuera de curva (P %.4f, curva %.4f..%.4f)'
                                    % (eid, d['P_kN'], P_min, P_max))
            else:
                peores['D/C u'].ver(math.inf, 0.0, ('elemento', eid, 'u 9999 en una sola'))
        else:
            den = rd['Mn'] - dMn
            if den <= 0.0:
                indecidibles.append('elemento %d: Mn %.4f dentro de su cota' % (eid, rd['Mn']))
            else:
                cota_u = (dM + rd['u'] * dMn) / den + r_uu + FP * 4.0 * rd['u']
                peores['D/C u'].ver(v['u'] - rd['u'], cota_u, ('elemento', eid, 'u'))
                if v['pasa'] != (rd['u'] <= 1.0):
                    if abs(rd['u'] - 1.0) <= cota_u:
                        indecidibles.append('elemento %d: pasa con u = %.6f' % (eid, rd['u']))
                    else:
                        peores['D/C u'].ver(math.inf, 0.0, ('elemento', eid, 'pasa'))
    return peores, indecidibles


def comparar_con_revisar(b, lam, caso):
    r"""
    La demanda de la via contra demanda.revisar(..., lambdas): otra forma
    de armar el mismo punto (fuerzas_por_caso + combinar + demanda +
    capacidad_en, con las fuerzas base SIN redondear la suma). Solo puede
    diferir en el redondeo de salida de la via.
    """
    ctx = b['ctx']
    p = Peor()
    r_dc = medio_decimal(v for d in caso['demandas'] for v in (d['P'], d['M'], d['M_fuera_plano'], d['Mn']))
    r_uu = medio_decimal(d['u'] for d in caso['demandas'] if d['u'] < U_FUERA)
    elementos = por_id(b['anexo']['elementos'])
    with opensees.AvisosDeOpenSees():
        for v in caso['demandas']:
            eid = int(v['id'])
            res = dc.revisar(eid, lambdas=lam,
                             curva=ctx['curvas'][elementos[eid]['familia']],
                             modelo=ctx['modelo'], resultados=ctx['resultados'])
            d = res['puntos']['COMB']
            u = d['utilizacion'] if math.isfinite(d['utilizacion']) else U_FUERA
            mag = FP * (abs(d['P_kN']) + d['M_kNm'] + d['M_capacidad_kNm'] + u + 1.0)
            for campo, a, ref, r in (('P', v['P'], d['P_kN'], r_dc), ('M', v['M'], d['M_kNm'], r_dc),
                                     ('M_fuera_plano', v['M_fuera_plano'],
                                      d['M_fuera_de_plano_kNm'] or 0.0, r_dc),
                                     ('Mn', v['Mn'], d['M_capacidad_kNm'], r_dc),
                                     ('u', v['u'], u, r_uu if u < U_FUERA else 0.0)):
                p.ver(float(a) - float(ref), r + mag, ('elemento', eid, campo))
            if v['extremo'] != d['extremo'] or v['pasa'] != d['pasa']:
                p.ver(math.inf, 0.0, ('elemento', eid, 'extremo/pasa'))
    return p


def bloque_reacciones(b, lam, ref, inf, via_eq):
    """Reacciones superpuestas contra la explicita y el equilibrio de las dos."""
    ctx = b['ctx']
    datos = ctx['datos']
    exp = ref['exp']
    sup = sp.combinar_resultados(ctx['resultados'], lam)
    base_r = {c: por_id(ctx['resultados'][c]['reacciones']) for c in ref['activos']}

    p = Peor()
    a, e = por_id(sup['reacciones']), por_id(exp['reacciones'])
    if set(a) != set(e):
        p.ver(math.inf, 0.0, ('ids de apoyos distintos',))
    else:
        for nid, fila in e.items():
            for campo in CAMPOS_R:
                mag = abs(float(fila[campo])) + sum(abs(l) * abs(float(base_r[c][nid][campo]))
                                                    for c, l in ref['activos'].items())
                p.ver(float(a[nid][campo]) - float(fila[campo]), ref['e_r'] + FP * mag,
                      ('nodo', nid, campo))

    n = opensees.filas_que_cuentan(datos, exp['reacciones'])
    eq_exp = opensees.equilibrio(datos, ref['carga'], exp)
    eq_sup = sp.equilibrio_combinado(b, lam)
    r_eq = 0.5e-8        # error_kN sale con 8 decimales (opensees.equilibrio)
    r_salida = 0.5e-4    # aplicada_kN y reaccion_kN salen con 4
    malos = []
    filas = []
    for i, eje in enumerate(('Fx', 'Fy', 'Fz')):
        tam = FP * (abs(eq_exp['aplicada_kN'][i]) + sum(abs(float(r[CAMPOS_R[i]]))
                                                         for r in exp['reacciones'])) * (1 + ref['suma'])
        cota_exp = n[i] * ref['r_exp_r'] + r_eq + tam
        cota_sup = n[i] * ref['r_base_r'] * ref['suma'] + r_eq + tam
        cota_reac = n[i] * ref['e_r'] + 2.0 * r_salida + tam
        err_reac = eq_sup['reaccion_kN'][i] - eq_exp['reaccion_kN'][i]
        filas.append({'eje': eje, 'aplicada_kN': eq_exp['aplicada_kN'][i],
                      'reaccion_explicita_kN': eq_exp['reaccion_kN'][i],
                      'error_explicita_kN': eq_exp['error_kN'][i], 'cota_explicita_kN': cota_exp,
                      'error_superpuesta_kN': eq_sup['error_kN'][i], 'cota_superpuesta_kN': cota_sup})
        for que, err, cota in (('explicita', eq_exp['error_kN'][i], cota_exp),
                               ('superpuesta', eq_sup['error_kN'][i], cota_sup),
                               ('reaccion superpuesta - explicita', err_reac, cota_reac)):
            if abs(err) > cota:
                malos.append('%s %s: %.3e > cota %.3e' % (que, eje, err, cota))
    malos += ['aplicada distinta: %s contra %s' % (eq_sup['aplicada_kN'], eq_exp['aplicada_kN'])
              ] if eq_sup['aplicada_kN'] != eq_exp['aplicada_kN'] else []
    if not (eq_exp['confiable'] and eq_sup['confiable']):
        malos.append('opensees.equilibrio no es confiable: %d cargas sin convertir'
                     % eq_exp['cargas_sin_convertir'])

    # La trampa, a la vista: la suma de TODAS las filas.
    directa = [sum(float(r[c]) for r in exp['reacciones']) for c in ('fx', 'fy', 'fz')]

    print('  %-34s %6d valores   peor %.3e   cota %.3e   cociente %.3f   %s'
          % ('reacciones (superposicion vs 1)', p.n, p.err, p.cota, p.cociente,
             texto_donde(p.donde)))
    print('  equilibrio (opensees.equilibrio; filas que cuentan Fx %d, Fy %d, Fz %d):'
          % tuple(n))
    for f in filas:
        print('    %s aplicada %13.4f   explicita: reaccion %13.4f error %+.2e (cota %.2e)   '
              'superpuesta: error %+.2e (cota %.2e)'
              % (f['eje'], f['aplicada_kN'], f['reaccion_explicita_kN'], f['error_explicita_kN'],
                 f['cota_explicita_kN'], f['error_superpuesta_kN'], f['cota_superpuesta_kN']))
    print('    (sumar TODAS las filas daria Fx %.4f, Fy %.4f, Fz %.4f: los nodos de diafragma'
          % tuple(directa))
    print('     traen la fuerza interna de la restriccion; por eso solo opensees.equilibrio)')

    iguales = []
    for via, eq in via_eq.items():
        if eq is None:
            continue
        _n, dif = diferencias(eq, eq_sup)
        iguales.append((via, dif))
    inf.check(p.calza and not malos and all(d is None for _v, d in iguales),
              'reacciones de los %d apoyos (x6) = explicita; equilibrio de la explicita y de la '
              'superpuesta dentro de su cota; "equilibrio" de %s = opensees.equilibrio superpuesto'
              % (len(e), ', '.join('(%s)' % v for v, _d in iguales) or '-'),
              malos + ['(%s): %s' % (v, d) for v, d in iguales if d])
    return p


def elegir_control(b, caso_e1):
    """Los ids de control por la regla de laboratorio.json (superposicion.control.reglas)."""
    info = b['anexo']['info']
    tipos = {int(e['id']): e['tipo'] for e in b['anexo']['elementos']}
    vigas = [s for s in caso_e1['esfuerzos'] if tipos[int(s['id'])].startswith('viga')]
    viga = max(vigas, key=lambda s: (max(abs(v) for v in s['My']), -int(s['id'])))
    nodo = max(caso_e1['desplazamientos'],
               key=lambda d: (math.sqrt(d['ux'] ** 2 + d['uy'] ** 2 + d['uz'] ** 2), -int(d['id'])))
    return {'columna': int(info['columna_demo']), 'muro': int(info['muro_demo']),
            'viga': int(viga['id']), 'nodo': int(nodo['id'])}


def control_de_estado(b, lam, ref, caso, ids, curvas_propias):
    """Los numeros de control de un estado: lo que Unity muestra y la explicita al lado."""
    dem = por_id(caso['demandas'])
    esf = por_id(caso['esfuerzos'])
    desp = por_id(caso['desplazamientos'])
    base_ = {c['nombre']: por_id(c['demandas']) for c in b['anexo']['casos'] if c['tipo'] == 'caso'}
    elementos = por_id(b['anexo']['elementos'])
    salida = {'max_desplazamiento_mm': caso['max_desplazamiento_mm'],
              'max_desplazamiento_mm_explicita': round(ref['max_mm'], 4),
              'no_pasan': sum(1 for d in caso['demandas'] if not d['pasa']),
              'no_pasan_explicita': sum(1 for rd in ref['dc'].values() if not rd['u'] <= 1.0),
              'fuera_de_curva': sum(1 for d in caso['demandas'] if d['u'] >= U_FUERA),
              'con_fierro': len(caso['demandas']),
              # Lo que el mapa D/C de Unity tiene que pintar de rojo, con la
              # u de la corrida explicita al lado.
              'lista_no_pasan': [{'id': d['id'], 'objeto_unity': nombre_objeto(elementos[int(d['id'])]),
                                  'P': d['P'], 'M': d['M'], 'Mn': d['Mn'], 'u': d['u'],
                                  'u_explicita': round(ref['dc'][int(d['id'])]['u'], 6)}
                                 for d in caso['demandas'] if not d['pasa']]}
    problemas = []
    for etiqueta in ('columna', 'muro'):
        eid = ids[etiqueta]
        v, rd = dem.get(eid), ref['dc'].get(eid)
        if v is None or rd is None:
            problemas.append('%s %d sin demanda' % (etiqueta, eid))
            continue
        Mn_propia = dc.capacidad_en(rd['d']['P_kN'], curvas_propias[eid])
        s, _a, _b = pendiente_cerca(curvas_propias[eid], rd['d']['P_kN'], ref['e_f'])
        cota_Mn = s * ref['e_f'] + 0.5e-4 + FP * (1 + Mn_propia)
        if abs(Mn_propia - v['Mn']) > cota_Mn:
            problemas.append('%s %d: Mn de su propia curva %.4f contra %.4f de la familia'
                             % (etiqueta, eid, Mn_propia, v['Mn']))
        suma_u = sum(l * base_[c][eid]['u'] for c, l in lam.items() if l != 0.0)
        salida[etiqueta] = {
            'id': eid, 'objeto_unity': nombre_objeto(elementos[eid]),
            'familia': v['familia'], 'plano': rd['plano'] or '',
            'P': v['P'], 'M': v['M'], 'M_fuera_plano': v['M_fuera_plano'],
            'extremo': v['extremo'], 'Mn': v['Mn'], 'u': v['u'], 'pasa': v['pasa'],
            'explicita': {'P': round(rd['d']['P_kN'], 4), 'M': round(rd['d']['M_kNm'], 4),
                          'Mn': round(rd['Mn'], 4), 'u': round(rd['u'], 6),
                          'extremo': rd['d']['extremo']},
            'Mn_de_su_propia_curva': round(Mn_propia, 4),
            'suma_lambda_u_de_los_casos_base': round(suma_u, 6),
        }
    eid = ids['viga']
    s = esf[eid]
    i_max = max(range(len(s['My'])), key=lambda k: abs(s['My'][k]))
    f = ref['f'][eid]
    salida['viga'] = {'id': eid, 'objeto_unity': nombre_objeto(elementos[eid]),
                      'w': s['w'], 'x': s['x'], 'My': s['My'],
                      'My_0': s['My'][0], 'My_L': s['My'][-1],
                      'max_abs_My': s['My'][i_max], 'x_de_max_abs_My': s['x'][i_max],
                      'explicita': {'My_0': round(-f[4], 4), 'My_L': round(f[10], 4)}}
    nid = ids['nodo']
    d = desp[nid]
    e = ref['u'][nid]
    salida['nodo'] = {'id': nid, 'ux': d['ux'], 'uy': d['uy'], 'uz': d['uz'],
                      'explicita': {'ux': e[0], 'uy': e[1], 'uz': e[2]}}
    return salida, problemas


def superposicion_4_vias(inf, args):
    fallas_antes = len(inf.fallas)
    flags = list(args.flags)
    print('=' * 78)
    print('  LA SUPERPOSICION E1..E3 POR CUATRO VIAS   %s' % _ed.NOMBRE.upper())
    print('=' * 78)
    t0 = time.time()
    b = contexto(flags)
    ctx = b['ctx']
    print('  base: exportar.resultados.construir (esfuerzos.base) en %.1f s '
          '(%d nodos, %d barras, %d con fierro)'
          % (b['segundos'], len(b['ids_nodos']), len(b['largos']), len(ctx['secciones'])))
    for linea in b['parametros']:
        print('  %s' % linea)
    print()
    print('  vias:')
    for k, v in VIAS.items():
        print('    (%s) %s' % (k, v))
    print()
    print('  cotas (MEDIDAS: r = medio ultimo decimal de cada fuente, superposicion.decimales_de):')
    print('    e_lin = r_base * sum|lambda| + r_explicita;  cota = e_lin + r_via + 4 eps * tamano')
    print('    estaciones My, Mz: e_lin (1 + x);  D/C: P, M muro e_lin; M columna sqrt(2) e_lin;')
    print('    Mn pendiente * e_lin; u (dM + u dMn)/(Mn - dMn);  vias (3) y (4) = (2) exacto')

    estados = sp.cargar_estados()
    inf.check([e['nombre'] for e in estados['estados']] == ['E1', 'E2', 'E3'],
              'laboratorio.json (superposicion) trae E1, E2, E3 en ese orden')
    inf.check(ctx['datos']['casos_de_carga'] == list(ctx['arm']['casos'].values()),
              'lo que se combina son los casos del laboratorio (laboratorio.armar_casos: %s), '
              'no los del modelo' % ', '.join(c['nombre'] for c in ctx['datos']['casos_de_carga']))

    # --- via (3): el servidor, sin red ---
    from exportar import servidor as srv
    from exportar.resultados import GENERADO_POR
    srv.ARGV_PARAMETROS[:] = flags
    cliente = srv.app.test_client()

    # --- via (4): el precalculado, el bloque 'superposicion' de los resultados ---
    disco, ruta_pre = leer_resultados()
    pre = None
    if disco is None:
        inf.check(False, 'existe %s (python sap.py preparar)' % rel(ruta_pre))
    else:
        pre = disco.get('superposicion')
        print()
        print('  precalculado: %s, bloque superposicion (el archivo pesa %.2f MB)'
              % (rel(ruta_pre), os.path.getsize(ruta_pre) / 1048576.0))
        info = (pre or {}).get('info') or {}
        inf.check(info.get('edificio') == _ed.NOMBRE and info.get('generado_por') == GENERADO_POR,
                  'info.edificio = %r e info.generado_por = %r'
                  % (info.get('edificio'), info.get('generado_por')))
        if not inf.check(info.get('parametros') == b['parametros'],
                         'info.parametros = los de esta corrida (y los de los resultados)',
                         [] if info.get('parametros') == b['parametros'] else
                         ['precalculado: %s' % info.get('parametros'),
                          'esta corrida: %s' % b['parametros'],
                          'regenerar: python sap.py preparar %s' % ' '.join(flags)]):
            pre = None
        else:
            hay = [(e.get('nombre'), e.get('lambdas')) for e in (pre.get('estados') or [])]
            quiero = [(e['nombre'], sp.lambdas_de(e['lambdas'])) for e in estados['estados']]
            inf.check(hay == quiero, 'estados del precalculado = laboratorio.json (nombre y lambdas)')
        copia = os.path.join(rutas.STREAMING, rutas.NOMBRES_EN_UNITY['resultados'])
        inf.check(os.path.isfile(copia) and filecmp.cmp(ruta_pre, copia, shallow=False),
                  'StreamingAssets/%s es identico byte a byte a %s'
                  % (rutas.NOMBRES_EN_UNITY['resultados'], rel(ruta_pre)),
                  [] if os.path.isfile(copia) and filecmp.cmp(ruta_pre, copia, shallow=False)
                  else ['corre: python sap.py sincronizar'])

    ids_control = None
    curvas_propias = {}
    tabla = {}

    for est in estados['estados']:
        nombre = est['nombre']
        lam = sp.lambdas_de(est['lambdas'])
        print()
        print('[%s] %s   lambdas G %.2f  Q %.2f  EX %.2f  EY %.2f'
              % (nombre, est['descripcion'], lam['G'], lam['Q'], lam['EX'], lam['EY']))
        print('-' * 78)
        ref = referencia(b, lam, nombre)
        inf.check(ref['exp'].get('ok', False), '(1) OpenSees resolvio la corrida explicita '
                  '(%d cargas nodales y %d repartidas combinadas, %.3f s)'
                  % (len(ref['carga']['cargas_nodales']), len(ref['carga']['cargas_distribuidas']),
                     ref['t']))

        t = time.time()
        caso2, cierre = sp.caso_combinado(b, lam, nombre=nombre)
        t2 = time.time() - t
        eq2 = sp.equilibrio_combinado(b, lam)
        print('  (2) caso_combinado en %.3f s; autoverificacion de bloque_caso: peor cierre %.3f '
              '(elemento %d, %s)' % (t2, cierre[0], cierre[1], cierre[2]))

        t = time.time()
        http = cliente.post('/combinar', json=dict(lam, edificio=_ed.NOMBRE))
        t3 = time.time() - t
        resp3 = http.get_json(silent=True) or {}
        caso3 = resp3.get('caso')
        ok3 = inf.check(http.status_code == 200 and resp3.get('ok') is True and caso3 is not None,
                        '(3) POST /combinar respondio HTTP %d, ok = %r en %.3f s%s'
                        % (http.status_code, resp3.get('ok'), t3,
                           ' (incluye armar la base del servidor)' if nombre == 'E1' else ''),
                        resp3.get('error') or '')
        if ok3:
            inf.check(resp3.get('edificio') == _ed.NOMBRE and resp3.get('parametros') == b['parametros']
                      and resp3.get('error') == '',
                      '(3) edificio, parametros y error de la respuesta son los esperados')
            inf.check(caso3.get('nombre') == sp.NOMBRE_LIBRE and caso3.get('tipo') == sp.TIPO,
                      '(3) caso.nombre = %r, caso.tipo = %r' % (caso3.get('nombre'), caso3.get('tipo')))

        caso4, eq4 = None, None
        if pre is not None:
            e4 = next((e for e in pre['estados'] if e.get('nombre') == nombre), None)
            caso4 = e4.get('caso') if e4 else None
            eq4 = e4.get('equilibrio') if e4 else None
            inf.check(caso4 is not None, '(4) el precalculado trae el caso de %s' % nombre)

        # --- identidades ---
        sin_nombre = lambda c: {k: v for k, v in c.items() if k != 'nombre'}   # noqa: E731
        inf.check(caso2['factores'] == [lam[c] for c in CASOS] and caso2['tipo'] == sp.TIPO
                  and caso2['descripcion'] == sp.texto_combinacion(lam),
                  '(2) factores = %s, tipo = %r, descripcion = %r'
                  % (caso2['factores'], caso2['tipo'], caso2['descripcion']))
        for via, caso in (('3', caso3), ('4', caso4)):
            if caso is None:
                continue
            n, dif = diferencias(sin_nombre(caso), sin_nombre(caso2))
            inf.check(dif is None, '(%s) identica a (2), bit a bit: %d valores (salvo el nombre)'
                      % (via, n), dif or '')
        if caso4 is not None:
            inf.check(caso4.get('nombre') == nombre, '(4) caso.nombre = %r' % caso4.get('nombre'))
        del_anexo = next((c for c in b['anexo']['casos']
                          if [float(x) for x in c['factores']] == caso2['factores']), None)
        if del_anexo is not None:
            quitar = ('nombre', 'tipo', 'descripcion')
            n, dif = diferencias({k: v for k, v in del_anexo.items() if k not in quitar},
                                 {k: v for k, v in caso2.items() if k not in quitar})
            inf.check(dif is None, "(2) identica al caso '%s' de los resultados: %d valores"
                      % (del_anexo['nombre'], n), dif or '')
        else:
            # Que se vea que este control cruzado NO corrio: si laboratorio.json
            # deja de declarar 1.2G+1.6Q, E2 pierde su comparacion con los
            # resultados y eso no puede pasar en silencio.
            print('  [--  ] ningun caso de los resultados tiene factores %s: sin control '
                  'cruzado con los resultados' % caso2['factores'])

        # --- contra la explicita ---
        inf.check(set(por_id(caso2['desplazamientos'])) == set(b['ids_nodos'])
                  and set(por_id(caso2['esfuerzos'])) == set(b['largos'])
                  and set(por_id(caso2['demandas'])) == set(ref['dc']),
                  '(2) trae los %d nodos, las %d barras y las %d con fierro'
                  % (len(b['ids_nodos']), len(b['largos']), len(ref['dc'])))
        vias = [('2', caso2)] + [(v, c) for v, c in (('3', caso3), ('4', caso4)) if c is not None]
        resultados_via = {}
        for via, caso in vias:
            resultados_via[via] = comparar_via(b, lam, ref, caso)
        rev = comparar_con_revisar(b, lam, caso2)

        print()
        print('  %-24s %7s %11s %11s   %s   %s'
              % ('familia (contra (1))', 'valores', 'peor (2)', 'cota', '  '.join(
                  'cociente (%s)' % v for v, _c in vias), 'donde, en (2)'))
        for fam in FAMILIAS:
            if fam == 'D/C = demanda.revisar':
                p2, cocientes = rev, [rev]
            else:
                p2 = resultados_via['2'][0][fam]
                cocientes = [resultados_via[v][0][fam] for v, _c in vias]
            print('  %-24s %7d %11.3e %11.3e   %s   %s'
                  % (fam, p2.n, p2.err, p2.cota,
                     '  '.join('%12.3f' % p.cociente for p in cocientes)
                     + ('  (solo (2))' if fam == 'D/C = demanda.revisar' else ''),
                     texto_donde(p2.donde)))
            # Para la tabla final: el peor cociente de las vias y, en las
            # estaciones x, donde quedo pegado al medio decimal (la nota).
            tabla.setdefault(fam, {})[nombre] = (
                max(p.cociente for p in cocientes),
                [texto_donde(p.donde) for p in cocientes if p.cociente > 0.999]
                if fam == 'estaciones x' else [])
            if not all(p.calza for p in cocientes):
                inf.fallas.append('%s: %s fuera de cota (%s)' % (
                    nombre, fam, ', '.join('(%s) %d de %d' % (v, p.fuera, p.n)
                                           for (v, _c), p in zip(vias, cocientes) if not p.calza)))
        indecidibles = sorted(set(i for v, _c in vias for i in resultados_via[v][1]))
        todas = all(p.calza for v, _c in vias for p in resultados_via[v][0].values()) and rev.calza
        inf.check(todas, '%s: las %d familias calzan en las vias %s (cociente <= 1)'
                  % (nombre, len(FAMILIAS), ', '.join('(%s)' % v for v, _c in vias)))
        print('  indecidibles por redondeo (extremo o pasa dentro de la cota): %d%s'
              % (len(indecidibles), (': ' + '; '.join(indecidibles)) if indecidibles else ''))

        print()
        rea = bloque_reacciones(b, lam, ref, inf, {'2': eq2, '3': resp3.get('equilibrio') if ok3
                                                   else None, '4': eq4})
        tabla.setdefault('reacciones', {})[nombre] = (rea.cociente, [])

        # --- control ---
        if ids_control is None:
            ids_control = elegir_control(b, caso2)
            esperados = (estados.get('control') or {}).get('esperados')
            print()
            print('  elementos de control (reglas de laboratorio.json, sobre E1): %s'
                  % ', '.join('%s %d' % kv for kv in ids_control.items()))
            # Si faltan los declarados, es una FALLA: un id de control que
            # nadie fija deja de compararse sin que nadie se entere.
            inf.check(esperados == ids_control,
                      'la regla da los ids declarados en laboratorio.json '
                      '(superposicion.control.esperados)',
                      [] if esperados == ids_control else
                      ['declarados %s, la regla da %s' % (esperados, ids_control)])
            with opensees.AvisosDeOpenSees():
                for etiqueta in ('columna', 'muro'):
                    eid = ids_control[etiqueta]
                    curvas_propias[eid] = capacidad.interaccion(
                        capacidad.desde_elemento(ctx['modelo'], eid))
        control_e, problemas = control_de_estado(b, lam, ref, caso2, ids_control, curvas_propias)
        inf.check(not problemas, '%s: control con la curva P-M propia de la columna y del muro'
                  % nombre, problemas)
        print('  control %s:' % nombre)
        for etiqueta in ('columna', 'muro'):
            c = control_e.get(etiqueta)
            if c:
                print('    %-7s %4d  P %11.4f  M %11.4f  (%s)  Mn %11.4f  u %s  %s   '
                      'sum lambda u_caso = %.6f'
                      % (etiqueta, c['id'], c['P'], c['M'], c['extremo'], c['Mn'],
                         'fuera de curva' if c['u'] >= U_FUERA else '%.6f' % c['u'],
                         'pasa' if c['pasa'] else 'NO PASA', c['suma_lambda_u_de_los_casos_base']))
        v = control_e['viga']
        print('    viga    %4d  wz %.4f  My(0) %.4f  My(L) %.4f  max|My| %.4f en x = %.4f'
              % (v['id'], v['w'][2], v['My_0'], v['My_L'], v['max_abs_My'], v['x_de_max_abs_My']))
        n_ = control_e['nodo']
        print('    nodo    %4d  ux %.8f  uy %.8f  uz %.8f' % (n_['id'], n_['ux'], n_['uy'], n_['uz']))
        print('    max %.4f mm;  NO PASA %d/%d (%d fuera de curva)'
              % (control_e['max_desplazamiento_mm'], control_e['no_pasan'], control_e['con_fierro'],
                 control_e['fuera_de_curva']))
        for d in control_e['lista_no_pasan']:
            print('      NO PASA %-18s P %11.4f  M %11.4f  Mn %11.4f  u %s (explicita %s)'
                  % (d['objeto_unity'], d['P'], d['M'], d['Mn'],
                     'fuera de curva' if d['u'] >= U_FUERA else '%.6f' % d['u'],
                     'fuera de curva' if d['u_explicita'] >= U_FUERA else '%.6f' % d['u_explicita']))
        # Los numeros de control de la superposicion (numeros_de_control.json).
        inf.check(calza(control_e['max_desplazamiento_mm'], 'superposicion', nombre, 'max_mm')
                  and control_e['no_pasan'] == control('superposicion', nombre, 'no_pasa')[0]
                  and control_e['con_fierro'] == control('superposicion', 'de')[0]
                  and ('fuera_de_curva' not in control('superposicion', nombre)[0]
                       or control_e['fuera_de_curva']
                       == control('superposicion', nombre, 'fuera_de_curva')[0]),
                  '%s: maximo, NO PASA y fuera de curva = los numeros de control' % nombre)

    # ------------------------------------------------------------
    print()
    print('=' * 78)
    print('  TABLA DE COCIENTES (peor error / cota, la mayor de las vias comparadas)')
    nombres = [e['nombre'] for e in estados['estados']]
    print('  %-24s %s' % ('familia', '  '.join('%8s' % n for n in nombres)))
    for fam in list(FAMILIAS) + ['reacciones']:
        valores = [tabla.get(fam, {}).get(n, (float('nan'), []))[0] for n in nombres]
        print('  %-24s %s' % (fam, '  '.join('%8.3f' % v for v in valores)))
    notas = list(NOTAS_COCIENTES)
    peores_x = sorted({d for n in nombres for d in tabla.get('estaciones x', {}).get(n, (0, []))[1]})
    notas += [d for d in (detalle_de_x(b, x) for x in peores_x) if d]
    print()
    for nota in notas:
        print('  nota: %s' % nota)
    print('  (%.1f s)' % (time.time() - t0))
    print('=' * 78)
    if len(inf.fallas) == fallas_antes:
        print('  TODO CALZA: E1..E3 por las vias %s = corrida explicita de OpenSees'
              % ('(2), (3) y (4)' if pre is not None else '(2) y (3)'))
    else:
        print('  NO CALZA (%d)' % (len(inf.fallas) - fallas_antes))
    print('=' * 78)


# ============================================================
# R5: LOS SLIDERS INSTANTANEOS (LA REPLICA)
# ============================================================
# Lo que hace el C# (VisorResultados.Instantanea) al mover un slider:
# combina en Unity los cuatro casos base que ya trae resultados.json, sin
# pedirle nada al servidor. Aca se repite paso a paso con la MISMA
# aritmetica de 32 bits y se compara contra superposicion.caso_combinado.
#
# DE DONDE SALEN LAS COTAS (cada termino tiene una causa medible):
#  1. El REDONDEO DE LOS RESULTADOS. El C# suma valores que resultados.json
#     YA escribio redondeados, y Python redondea al final:
#     sum(lambda * redondeo(v)) contra redondeo(sum(lambda * v)). El error
#     es medio ultimo decimal por su lambda, mas el final: R (sum|l| + 1).
#  2. LA ARITMETICA DE 32 BITS. Unity guarda y opera en float: cada
#     operacion redondea a 2^-24 relativo. Por termino lambda*v hay hasta
#     7 redondeos (cargar, tres al interpolar a la malla comun, el lambda,
#     el producto y la suma), uno por suma parcial, y M = hypot agrega
#     cuatro: menos de 14. Se toma K_F32 = 16 por la ESCALA de la suma,
#     sum|lambda_c| * |v_c|. En P = 5400 kN son 5e-3 kN, cien veces el
#     redondeo: sin este termino el registro de Unity se sale de la cota
#     entre 1.4 y 6 veces sin que nadie se haya equivocado.
#  3. Mn sale de interpolar en la curva P-M: su error es el de P por la
#     pendiente de la curva. Se acota con la pendiente maxima medida.
#  4. "Instantaneo" tambien se mide: un cuadro a 60 Hz (16.7 ms). Eso lo
#     cruza verificacion/capturas.py con el registro de la app.
MAGNITUDES = ('N', 'Vy', 'Vz', 'T', 'My', 'Mz')
GDL = ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')
# El medio ultimo decimal con que los resultados escriben fuerzas y
# desplazamientos (esfuerzos.DECIMALES_*).
R_FUERZA = 0.5e-4
R_DESPL = 0.5e-8
EPS = 4.0 * sys.float_info.epsilon
EPS32 = 2.0 ** -24
K_F32 = 16
U_FUERA_DE_CURVA = 9999.0       # PanelUI.U_FUERA_DE_CURVA
MS_INSTANTANEO = 1000.0 / 60.0  # un cuadro a 60 Hz

# Los juegos de lambdas de la prueba. Los tres primeros son E1..E3, que
# es lo que ponen los botones de la app.
LAMBDAS = [
    (1.0, 1.0, 0.0, 0.0),        # E1
    (1.2, 1.6, 0.0, 0.0),        # E2
    (1.2, 1.0, -1.4, 0.0),       # E3
    (1.0, 0.0, 0.0, 0.0),        # solo G
    (0.0, 0.0, 1.0, 0.0),        # solo EX
    (0.0, 0.0, 0.0, -1.0),       # solo EY, negativo
    (0.9, 0.0, -1.4, 0.0),
    (1.2, 1.0, 0.0, 1.4),
    (-0.5, 0.35, 1.05, -0.7),    # feo a proposito
    (0.0, 0.0, 0.0, 0.0),        # todo en cero
]


class PeorMargen(object):
    """El valor con MENOS holgura respecto de su cota (err - cota mayor).
    Se imprime siempre, pase o no: asi se ve cuanto margen queda."""

    def __init__(self):
        self.margen, self.err, self.cota, self.donde = None, 0.0, 0.0, ''

    def ver(self, err, cota, donde):
        m = err - cota
        if self.margen is None or m > self.margen:
            self.margen, self.err, self.cota, self.donde = m, err, cota, donde

    @property
    def ok(self):
        return self.margen is None or self.margen <= 0.0

    def __str__(self):
        return 'peor %.2e en %s, cota %.2e' % (self.err, self.donde or '-', self.cota)


def a_la_malla(valor, n_origen, n_destino):
    """
    La MISMA retabulacion que hace el C# (Ins_ALaMalla): interpolacion
    lineal a la malla comun, POR FRACCION DE INDICE y no por x, y en
    float de 32 bits.

    Es exacta cuando la barra no lleva carga repartida en ese caso,
    porque ahi el axial y los cortes son constantes y los momentos son
    rectas. Y se interpola por indice porque las dos mallas van de 0 a L
    equiespaciadas (lo comprueba el bloque [1]): usar la x de los
    resultados meteria su redondeo a 4 decimales -- hasta 5e-5 m --
    multiplicado por la pendiente del momento, que es el corte: en una
    viga del LT2 bajo G llega a 272 kN, o sea hasta 1.4e-2 kN m.
    """
    if not valor or len(valor) != n_origen:
        return [0.0] * n_destino
    if n_origen == n_destino:
        return list(valor)
    if n_origen == 1:
        return [valor[0]] * n_destino
    salida = []
    for i in range(n_destino):
        p = 0.0 if n_destino == 1 else f32(f32(i / (n_destino - 1)) * (n_origen - 1))
        j = min(max(int(math.floor(p)), 0), n_origen - 2)
        frac = f32(p - j)
        salida.append(f32(valor[j] + f32(f32(valor[j + 1] - valor[j]) * frac)))
    return salida


def capacidad_en(P, familia):
    """La misma interpolacion que Ins_CapacidadEn en el C#, en float."""
    Ps, Mns = familia['P'], familia['Mn']
    if len(Ps) < 2 or P <= Ps[0] or P >= Ps[-1]:
        return 0.0
    for i in range(len(Ps) - 1):
        p1, p2 = Ps[i], Ps[i + 1]
        if p1 <= P <= p2:
            d = f32(p2 - p1)
            if abs(d) < 1e-9:
                return max(Mns[i], Mns[i + 1])
            return f32(Mns[i] + f32(f32(Mns[i + 1] - Mns[i]) * f32(f32(P - p1) / d)))
    return 0.0


def demanda_de(f, elemento, familia):
    """La misma regla que Ins_Demanda en el C#, y que demanda.demanda():
    los dos extremos, gana el de mayor M."""
    muro = elemento.get('tipo') == 'muro'
    plano_es_my = elemento.get('momento_en_el_plano') != 'Mz'
    Pi, Myi, Mzi = f[0], f[4], f[5]
    Pj, Myj, Mzj = f32(-f[6]), f[10], f[11]

    def hyp(a, b):
        return f32(math.sqrt(f32(f32(a * a) + f32(b * b))))

    if muro:
        Mi = abs(Myi if plano_es_my else Mzi)
        Mfi = abs(Mzi if plano_es_my else Myi)
        Mj = abs(Myj if plano_es_my else Mzj)
        Mfj = abs(Mzj if plano_es_my else Myj)
    else:
        Mi, Mfi = hyp(Myi, Mzi), 0.0
        Mj, Mfj = hyp(Myj, Mzj), 0.0
    gana_j = Mj > Mi
    P = Pj if gana_j else Pi
    M = Mj if gana_j else Mi
    Mn = capacidad_en(P, familia)
    u = f32(M / Mn) if Mn > 1e-9 else U_FUERA_DE_CURVA
    return {'id': elemento['id'], 'familia': elemento['familia'], 'P': P, 'M': M,
            'M_fuera_plano': Mfj if gana_j else Mfi,
            'extremo': 'j (superior)' if gana_j else 'i (inferior)',
            'Mn': Mn, 'u': u, 'pasa': u <= 1.0}


def preparar(anexo):
    """Lo que el C# hace una vez al cargar: los cuatro casos base
    llevados a una malla comun por barra. Todo en float de 32 bits, que
    es como JsonUtility lo deja en memoria."""
    por_caso = {c['nombre']: c for c in anexo['casos']}
    faltan = [c for c in CASOS if c not in por_caso]
    if faltan:
        raise SystemExit('los resultados no traen los casos base: %s' % faltan)

    elementos = {int(e['id']): e for e in anexo['elementos']}
    esf = {c: {int(s['id']): s for s in por_caso[c]['esfuerzos']} for c in CASOS}

    barras = []
    for s_g in por_caso['G']['esfuerzos']:
        eid = int(s_g['id'])
        malla = s_g['x']
        for c in CASOS[1:]:
            s = esf[c].get(eid)
            if s and len(s['x']) > len(malla):
                malla = s['x']
        barra = {'id': eid, 'x': malla, 'f': {}, 'mag': {}, 'elemento': elementos.get(eid)}
        for c in CASOS:
            s = esf[c].get(eid)
            if s is None:
                barra['f'][c] = [0.0] * 12
                barra['mag'][c] = {m: [0.0] * len(malla) for m in MAGNITUDES}
                continue
            barra['f'][c] = [f32(v) for v in s['f']]
            barra['mag'][c] = {m: a_la_malla([f32(v) for v in s[m]], len(s['x']), len(malla))
                               for m in MAGNITUDES}
        barras.append(barra)

    nodos = [int(d['id']) for d in por_caso['G']['desplazamientos']]
    u_base = {}
    for c in CASOS:
        d_por_id = {int(d['id']): d for d in por_caso[c]['desplazamientos']}
        u_base[c] = [[f32(d_por_id[n][k]) if n in d_por_id else 0.0 for k in GDL] for n in nodos]

    familias = []
    for fam in anexo['familias']:
        f2 = dict(fam)
        f2['P'] = [f32(v) for v in fam['P']]
        f2['Mn'] = [f32(v) for v in fam['Mn']]
        familias.append(f2)
    return {'barras': barras, 'nodos': nodos, 'u': u_base, 'familias': familias}


def combinar_como_unity(prep, lam):
    """Lo que el C# hace al mover un slider, con su aritmetica. Devuelve
    tambien la ESCALA de cada suma, sum|lambda_c|*|v_c|, que es lo que
    multiplica el error de 32 bits."""
    l = {c: f32(v) for c, v in zip(CASOS, lam)}

    desplazamientos, esc_u, mayor = [], {}, 0.0
    for i, nid in enumerate(prep['nodos']):
        u, e = [0.0] * 6, [0.0] * 6
        for c in CASOS:
            if l[c] == 0.0:
                continue
            fila = prep['u'][c][i]
            for k in range(6):
                u[k] = f32(u[k] + f32(l[c] * fila[k]))
                e[k] += abs(l[c] * fila[k])
        desplazamientos.append(dict(zip(GDL, u), id=nid))
        esc_u[nid] = dict(zip(GDL, e))
        norma = f32(math.sqrt(f32(f32(f32(u[0] * u[0]) + f32(u[1] * u[1])) + f32(u[2] * u[2]))))
        mayor = max(mayor, norma)

    esfuerzos, demandas, esc_f, esc_m = [], [], {}, {}
    for b in prep['barras']:
        f, ef = [0.0] * 12, [0.0] * 12
        for c in CASOS:
            if l[c] == 0.0:
                continue
            for i in range(12):
                f[i] = f32(f[i] + f32(l[c] * b['f'][c][i]))
                ef[i] += abs(l[c] * b['f'][c][i])
        fila = {'id': b['id'], 'f': f, 'x': b['x']}
        em = {}
        for m in MAGNITUDES:
            v, e = [0.0] * len(b['x']), [0.0] * len(b['x'])
            for c in CASOS:
                if l[c] == 0.0:
                    continue
                base_ = b['mag'][c][m]
                for i in range(len(v)):
                    v[i] = f32(v[i] + f32(l[c] * base_[i]))
                    e[i] += abs(l[c] * base_[i])
            fila[m] = v
            em[m] = e
        esfuerzos.append(fila)
        esc_f[b['id']] = ef
        esc_m[b['id']] = em

        e4 = b['elemento']
        if e4 is not None and int(e4.get('familia', -1)) >= 0:
            demandas.append(demanda_de(f, e4, prep['familias'][int(e4['familia'])]))

    return {'max_desplazamiento_mm': f32(mayor * 1000.0), 'desplazamientos': desplazamientos,
            'esfuerzos': esfuerzos, 'demandas': demandas,
            'escala': {'u': esc_u, 'f': esc_f, 'm': esc_m}}


def cota_f32(escala):
    return K_F32 * EPS32 * escala


def escala_demanda(esc_f, d):
    """La escala de P y de M de una demanda, segun el extremo que gano."""
    j = d['extremo'].startswith('j')
    eP = esc_f[6] if j else esc_f[0]
    eM = (esc_f[10] + esc_f[11]) if j else (esc_f[4] + esc_f[5])
    return eP, eM


def conteos(demandas):
    no_pasan = sum(1 for d in demandas if not d['pasa'])
    fuera = sum(1 for d in demandas if float(d['u']) >= U_FUERA_DE_CURVA)
    return no_pasan, fuera, len(demandas)


def norma_maxima_mm(desplazamientos):
    return max(math.sqrt(float(d['ux']) ** 2 + float(d['uy']) ** 2 + float(d['uz']) ** 2)
               for d in desplazamientos) * 1000.0


def comparar_replica(unity, python, lam, inf, etiqueta):
    suma = sum(abs(v) for v in lam)
    cota_u = R_DESPL * (suma + 1.0)
    cota_f = R_FUERZA * (suma + 1.0)
    esc = unity['escala']

    # --- desplazamientos ---
    py_u = {int(d['id']): d for d in python['desplazamientos']}
    peor_u = PeorMargen()
    for d in unity['desplazamientos']:
        p = py_u.get(int(d['id']))
        if p is None:
            inf.check(False, '%s: el nodo %d no esta en el caso de Python' % (etiqueta, d['id']))
            return
        for k in GDL:
            peor_u.ver(abs(float(d[k]) - float(p[k])),
                       cota_u + cota_f32(esc['u'][int(d['id'])][k]) + EPS,
                       'nodo %d %s' % (d['id'], k))
    inf.check(peor_u.ok, '%s: desplazamientos de %d nodos (%s)'
              % (etiqueta, len(unity['desplazamientos']), peor_u))

    # --- esfuerzos: f y los extremos de las estaciones ---
    py_e = {int(s['id']): s for s in python['esfuerzos']}
    peor_f, peor_x = PeorMargen(), PeorMargen()
    for s in unity['esfuerzos']:
        p = py_e.get(int(s['id']))
        if p is None:
            continue
        for i in range(12):
            peor_f.ver(abs(s['f'][i] - float(p['f'][i])),
                       cota_f + cota_f32(esc['f'][s['id']][i]) + EPS,
                       'elem %d f[%d]' % (s['id'], i))
        # Las estaciones se comparan en los extremos, que existen en las
        # dos mallas; el interior solo cuando la malla es la misma (si
        # no, Python tabula 2 puntos y Unity 9, y comparar indice a
        # indice no tendria sentido).
        mismo = len(s['x']) == len(p['x'])
        for m in MAGNITUDES:
            idx = range(len(s['x'])) if mismo else (0, len(s['x']) - 1)
            jdx = range(len(p['x'])) if mismo else (0, len(p['x']) - 1)
            for i, j in zip(idx, jdx):
                peor_x.ver(abs(s[m][i] - float(p[m][j])),
                           cota_f + cota_f32(esc['m'][s['id']][m][i]) + EPS,
                           'elem %d %s[%d]' % (s['id'], m, i))
    inf.check(peor_f.ok, '%s: las 12 fuerzas de %d barras (%s)'
              % (etiqueta, len(unity['esfuerzos']), peor_f))
    inf.check(peor_x.ok, '%s: esfuerzos en las estaciones (%s)' % (etiqueta, peor_x))

    # --- demandas: lo que NO es lineal ---
    comparar_demandas(unity['demandas'], python['demandas'], esc['f'], cota_f, inf, etiqueta)


def comparar_demandas(dem_unity, dem_python, esc_f, cota_f, inf, etiqueta):
    py_d = {int(d['id']): d for d in dem_python}
    peor = {'P': PeorMargen(), 'M': PeorMargen(), 'Mn': PeorMargen()}
    distinto_extremo, distinto_pasa = [], []
    for d in dem_unity:
        p = py_d.get(int(d['id']))
        if p is None:
            inf.check(False, '%s: la barra %d tiene demanda en Unity y no en Python'
                      % (etiqueta, d['id']))
            return
        eP, eM = escala_demanda(esc_f[int(d['id'])], d)
        topes = {'P': cota_f + cota_f32(eP) + EPS,
                 'M': cota_f + cota_f32(eM) + EPS,
                 # Mn: el error de P por la pendiente maxima de la curva.
                 'Mn': max((cota_f + cota_f32(eP)) * 100.0, 1e-3)}
        for k in ('P', 'M', 'Mn'):
            peor[k].ver(abs(float(d[k]) - float(p[k])), topes[k], 'elem %d' % d['id'])
        if d['extremo'] != p['extremo']:
            distinto_extremo.append('elem %d: Unity %s, Python %s'
                                    % (d['id'], d['extremo'], p['extremo']))
        if bool(d['pasa']) != bool(p['pasa']):
            distinto_pasa.append('elem %d: Unity %s, Python %s'
                                 % (d['id'], d['pasa'], p['pasa']))

    n = len(dem_unity)
    inf.check(peor['P'].ok and peor['M'].ok,
              '%s: P y M de %d demandas (P: %s; M: %s)' % (etiqueta, n, peor['P'], peor['M']))
    inf.check(peor['Mn'].ok, '%s: Mn interpolado en la curva (%s)' % (etiqueta, peor['Mn']))
    inf.check(not distinto_extremo,
              '%s: el extremo que manda es el mismo en las %d demandas' % (etiqueta, n),
              distinto_extremo[:4])
    inf.check(not distinto_pasa,
              '%s: pasa / no pasa coincide en las %d demandas' % (etiqueta, n),
              distinto_pasa[:4])


def instantanea(inf, args):
    fallas_antes = len(inf.fallas)
    cuantos = args.casos if args.casos is not None else len(LAMBDAS)
    print('=' * 78)
    print('  LOS SLIDERS INSTANTANEOS CONTRA PYTHON   %s' % _ed.NOMBRE.upper())
    print('=' * 78)
    print('  Unity combina los cuatro casos base de los resultados al mover un slider.')
    print('  Aca se repite esa combinacion paso a paso, con la aritmetica de 32 bits de')
    print('  Unity, y se compara contra superposicion.caso_combinado().')

    anexo, ruta = leer_resultados()
    if anexo is None:
        inf.check(False, 'existe %s (python sap.py preparar)' % rel(ruta))
        return
    if anexo['info']['edificio'] != _ed.NOMBRE:
        inf.check(False, '%s es de %s, no de %s: python sap.py preparar'
                  % (rel(ruta), anexo['info']['edificio'], _ed.NOMBRE))
        return
    print('  resultados   %s  (%s, %d elementos, %d familias)'
          % (rel(ruta), anexo['info']['edificio'], len(anexo['elementos']), len(anexo['familias'])))

    titulo('[1] LA BASE DE PYTHON  (resuelve G, Q, EX y EY en OpenSees)')
    b = base_del_laboratorio(args.flags)
    print('  %d elementos, %d nodos, %.1f s' % (len(b['elementos']), len(b['ids_nodos']),
                                                b['segundos']))
    inf.check(b['parametros'] == anexo['info']['parametros'],
              'la base usa los mismos parametros que los resultados que lee Unity')

    titulo('[2] LA PREPARACION QUE HACE UNITY UNA SOLA VEZ')
    prep = preparar(anexo)
    finas = sum(1 for x in prep['barras'] if len(x['x']) > 2)
    inf.check(len(prep['barras']) == len(anexo['elementos']),
              'las %d barras de los resultados quedaron en la malla comun (%d con estaciones finas)'
              % (len(prep['barras']), finas))

    titulo('[3] LA REPLICA DEL ALGORITMO, JUEGO POR JUEGO, CONTRA PYTHON')
    for lam in LAMBDAS[:cuantos]:
        etiqueta = 'l = (%s)' % ', '.join('%g' % v for v in lam)
        caso, _peor = sp.caso_combinado(b, dict(zip(CASOS, lam)))
        unity = combinar_como_unity(prep, lam)
        comparar_replica(unity, caso, lam, inf, etiqueta)

    print()
    print('=' * 78)
    if len(inf.fallas) == fallas_antes:
        print('  EL ALGORITMO DE LOS SLIDERS DA LO DE PYTHON (lo que la app calculo al mover')
        print('  los sliders lo cruza con Python: python -m verificacion.capturas visor)')
    else:
        print('  NO CALZA (%d)' % (len(inf.fallas) - fallas_antes))
    print('=' * 78)


# ============================================================
class _Argumentos(object):
    """
    Lo que entiende main: los bloques; el elemento de la trazabilidad
    (el numero que sigue a 'trazabilidad'); --caso NOMBRE; --casos N
    (instantanea); y todo lo demas son los flags de los parametros, que
    valida calculo.laboratorio.cargar.
    """

    def __init__(self, argv):
        self.bloques, self.flags = [], []
        self.elemento, self.caso, self.casos = None, None, None
        i = 0
        while i < len(argv):
            a = argv[i]
            if a in BLOQUES:
                self.bloques.append(a)
                if a == 'trazabilidad' and i + 1 < len(argv) and re.fullmatch(r'\d+', argv[i + 1]):
                    self.elemento = int(argv[i + 1])
                    i += 1
            elif a in ('--caso', '--casos'):
                if i + 1 >= len(argv):
                    raise SystemExit('%s necesita un valor' % a)
                i += 1
                if a == '--caso':
                    self.caso = argv[i]
                else:
                    self.casos = int(argv[i])
            else:
                self.flags.append(a)
            i += 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv):
        print(__doc__)
        return 0
    a = _Argumentos(argv)
    try:
        lab.cargar(list(a.flags))
    except ValueError as e:
        raise SystemExit('flags de los parametros: %s' % e)
    hacer = {'al_dia': al_dia, 'bloques_1_8': bloques_1_8, 'trazabilidad': trazabilidad,
             'superposicion_4_vias': superposicion_4_vias, 'instantanea': instantanea}
    consola_tolerante()
    t0 = time.time()
    inf = Informe()
    for b in (a.bloques or BLOQUES):
        hacer[b](inf, a)
    print('  (%.0f s)' % (time.time() - t0))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
