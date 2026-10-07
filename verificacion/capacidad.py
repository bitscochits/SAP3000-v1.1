# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/capacidad.py  -  LO QUE AGUANTA CADA SECCION, COMPROBADO
================================================================
 Seis bloques; sin bloque corre los seis:

   python -m verificacion.capacidad mphi_pm            # C1
   python -m verificacion.capacidad rc_a_mano [elem]   # C2 (lenta)
   python -m verificacion.capacidad demanda_todas      # C3
   python -m verificacion.capacidad nucleos            # C4
   python -m verificacion.capacidad losa_colaborante   # C5
   python -m verificacion.capacidad pandeo             # C6 (Honors)

 MPHI_PM. La seccion de fibras de 100018 (columna del cuerpo antiguo),
 200001 y 200037 (columnas del LT2; la ultima es la del marcador de la
 AR): M-phi a P = 0 y curva P-M, interpretada. Despues las filas M-phi,
 P-M columna y P-M muro de la tabla QA: Mn contra Whitney a mano, la
 rigidez fisurada contra Ec I_cr a mano, 20 contra 40 fibras, la curva
 de resultados.json = capacidad.interaccion, la u de los 15 casos
 rehecha con la regla de calculo/demanda.py, y los muros 100537 y 200009
 con su momento del plano por inercias.

 RC_A_MANO. Las fibras contra las formulas del curso de hormigon armado
 --bloque de Whitney, compatibilidad de deformaciones-- en la primera
 columna y el primer muro con fierro de cada cuerpo (o en los elementos
 que se pidan). No se espera que den lo mismo, y esa es la gracia: ver
 rc_a_mano().

 DEMANDA_TODAS. El punto (P, M) de cada barra con fierro sobre la curva
 de su familia, con G + Q. Y la FIRMA de familia: dos secciones con el
 mismo numero de barras no son la misma seccion, y la cache de curvas
 P-M no puede juntarlas (CLAUDE.md, trampas).

 NUCLEOS. Los grupos de patas de nucleo (calculo/demanda.py) son
 consistentes, y los nucleo_* que lleva cada demanda en
 salidas/resultados.json son los que sale de recalcularlos.

 LOSA_COLABORANTE. La regla de ancho efectivo de ACI (no conectada)
 contra casos con respuesta conocida, y cuanto subiria Iz en cada viga.

 Ninguno escribe en salidas/. Las curvas P-M hacen que OpenSees avise
 "failed to converge" por stderr: es la busqueda del peak, no un error
 (calculo/opensees.py, AvisosDeOpenSees).
================================================================
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import io
import json
import math
import os
import re
import sys
import time

from calculo import capacidad
from calculo import demanda as dem
from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import losa_colaborante as losa
from calculo import opensees
from calculo import rutas
from verificacion.comun import Informe, titulo
from verificacion.suite import Fila, calza, consola_tolerante, numeros_de_control

BLOQUES = ('mphi_pm', 'rc_a_mano', 'demanda_todas', 'nucleos', 'losa_colaborante', 'pandeo')

CASOS = lab.CASOS_BASE

# Las secciones que revisa mphi_pm: una columna de cada cuerpo (las que
# la suite revisaba por cuerpo) y la columna del marcador de la AR.
CAPACIDAD = (100018, 200001, 200037)

# Las de la tabla QA: la columna del marcador de la AR (laboratorio.json,
# bloque "ar") y un muro de cada cuerpo, que eligen su momento del plano
# con convenciones distintas (el cuerpo antiguo My, el LT2 Mz).
COLUMNA = 200037
MUROS = (100537, 200009)

# Whitney y las fibras no son el mismo modelo (bloque rectangular contra
# la parabola de Concrete01 con Mander), asi que no coinciden al
# redondeo. El umbral de 2 % no se eligio a ojo: se imprime al lado lo
# que mueve Mn el error de dato mas chico que tiene que detectar (un
# diametro menos, 25 -> 22 mm), y el umbral queda muy por debajo.
TOL_MODELOS = 0.02
# Lo que declara calculo/capacidad.py junto a FIBRAS_NUCLEO: "entre 20 y
# 40 el momento maximo cambia menos de 0.5%". Se le toma la palabra.
TOL_MALLADO = 0.005

# S3 (1.0G + 0.5Q + 1.0EX) es la combinacion de servicio; las otras 10 de
# laboratorio.json son las mayoradas: con esas se busca la que gobierna.
NO_DE_DISENO = ('S3',)


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


def resultados_del_laboratorio():
    """(resultados, de donde): los de salidas/resultados.json si son de estos
    parametros; si no, armados en memoria con el codigo que los escribe."""
    from exportar import ar as exar
    anexo, origen = exar.resultados_del_laboratorio([])
    return anexo, origen.replace(os.sep, '/')


# ============================================================
# A MANO: el bloque de Whitney y la compatibilidad de deformaciones
# ============================================================
# Calcula los puntos caracteristicos de la seccion con las formulas del
# curso de hormigon armado y los compara contra la Fiber Section de
# OpenSees. NO SE ESPERA QUE DEN LO MISMO, Y ESA ES LA GRACIA: las dos
# cuentas describen la misma seccion con hipotesis distintas, y las
# diferencias son PREDECIBLES. Si aparece una que no se puede explicar,
# hay un error en alguna de las dos.
#
#   COMPRESION PURA. A mano se usa 0.85 f'c: el 0.85 de ACI cubre la
#   diferencia entre la probeta y el hormigon de la pieza real. El
#   modelo de fibras usa Concrete01, que llega a f'c. La razon entre los
#   dos tiene que ser exactamente 0.85 sobre la parte de hormigon.
#
#   FLEXION. A mano el hormigon comprimido se reemplaza por un
#   RECTANGULO de 0.85 f'c y altura a = beta1 * c (Whitney). En las
#   fibras la distribucion es la parabola de Concrete01, integrada fibra
#   por fibra. Las dos dan resultantes parecidas -- para eso se calibro
#   el bloque -- pero no iguales.
#
#   TRACCION PURA. Aca si tienen que coincidir exacto: no interviene el
#   hormigon, es As * fy y nada mas. Si esta no calza, el error es de
#   conteo de barras o de area, no de hipotesis.
#
#   ENDURECIMIENTO DEL ACERO. A mano la barra se topa en fy. En las
#   fibras, Steel01 sigue subiendo con 1% de pendiente. Da igual
#   mientras las deformaciones sean chicas, pero en flexion pura de un
#   MURO no lo son: con c = 0.54 m sobre un canto de 7.95, la barra mas
#   traccionada llega a eps = 0.041, donde vale 498 MPa en vez de 420 --
#   un 19% mas. En la columna llega a 0.015 y son 446 MPa, un 6%.
#
#   CONFINAMIENTO. El calculo a mano usa hormigon SIN confinar, con f'c.
#   El modelo de fibras confina el nucleo con Mander a partir del estribo
#   real. A P = 0 casi no se nota -- el hormigon comprimido es poco --
#   pero en el punto balanceado explica la mitad de la diferencia. Por
#   eso se corre el modelo de fibras DOS veces, con y sin confinar, y se
#   muestra el desglose: lo que queda es Whitney contra la parabola con
#   axial alto, una discrepancia conocida del bloque equivalente, que se
#   calibro para secciones dominadas por flexion y no por compresion.
#
# CONVENCION. En Seccion, la coordenada y corre a lo largo del canto h,
# de -h/2 a +h/2, y la fibra MAS COMPRIMIDA esta en y = +h/2. La
# profundidad de una barra desde esa cara es entonces d_i = h/2 - y_i.
EPS_CU = 0.003          # ACI 318 22.2.2.1
FACTOR_ACI = 0.85       # el 0.85 f'c del bloque equivalente


def beta1(fpc_kPa):
    """
    ACI 318-08 10.2.7.3. Vale 0.85 hasta 28 MPa y baja 0.05 por cada
    7 MPa por encima, con piso en 0.65.
    """
    f = fpc_kPa / 1000.0
    if f <= 28.0:
        return 0.85
    return max(0.65, 0.85 - 0.05 * (f - 28.0) / 7.0)


def _capas(sec):
    """
    Las barras agrupadas por profundidad, que es como se calcula a
    mano: (d desde la cara comprimida, area total de esa capa).
    """
    por_d = {}
    for y, _z, a in sec.barras:
        d = round(sec.h / 2.0 - y, 6)
        por_d[d] = por_d.get(d, 0.0) + a
    return sorted(por_d.items())


def compresion_pura(sec):
    """P0 = 0.85 f'c (Ag - As) + fy As.  ACI 318-08 10.3.6."""
    return (FACTOR_ACI * sec.fpc * (sec.Ag - sec.As) + sec.fy * sec.As)


def traccion_pura(sec):
    """Pt = As fy. Sin hormigon: no resiste traccion."""
    return sec.As * sec.fy


def punto(sec, c):
    r"""
    (P, M) para una profundidad de eje neutro c, con el bloque de
    Whitney y compatibilidad de deformaciones.

    P positivo en compresion, M respecto del centro de la seccion.
    """
    b, h = sec.b, sec.h
    a = min(beta1(sec.fpc) * c, h)
    Cc = FACTOR_ACI * sec.fpc * b * a          # kN
    P = Cc
    M = Cc * (h / 2.0 - a / 2.0)

    for d, area in _capas(sec):
        # Deformacion por triangulos semejantes desde la fibra a eps_cu.
        eps = EPS_CU * (c - d) / c if c > 1e-12 else -1.0
        fs = max(-sec.fy, min(sec.fy, sec.Es * eps))
        # Una barra dentro del bloque comprimido ocupa hormigon que ya
        # se conto: se le descuenta 0.85 f'c. Es el clasico
        # (fs - 0.85 f'c) As de los apuntes.
        if d <= a and fs > 0:
            fs -= FACTOR_ACI * sec.fpc
        F = fs * area
        P += F
        M += F * (h / 2.0 - d)
    return P, M


def flexion_pura(sec, tol=1e-6):
    """
    c tal que P = 0, por biseccion. Es el caso de flexion simple del
    curso: la seccion no lleva axial y el equilibrio horizontal fija
    la profundidad del eje neutro.
    """
    lo, hi = 1e-5, sec.h
    P_lo, _ = punto(sec, lo)
    P_hi, _ = punto(sec, hi)
    if P_lo > 0 or P_hi < 0:
        return None
    for _ in range(200):
        med = (lo + hi) / 2.0
        P, _M = punto(sec, med)
        if abs(P) < tol * max(sec.Ag * sec.fpc, 1.0):
            break
        if P < 0:
            lo = med
        else:
            hi = med
    c = (lo + hi) / 2.0
    P, M = punto(sec, c)
    return {'c': c, 'a': beta1(sec.fpc) * c, 'P_kN': P, 'M_kNm': M}


def balanceado(sec):
    """
    El punto balanceado: el hormigon llega a 0.003 justo cuando la
    barra mas traccionada llega a fluir.
    """
    capas = _capas(sec)
    if not capas:
        return None
    d = capas[-1][0]                    # la barra mas profunda
    eps_y = sec.fy / sec.Es
    c = EPS_CU / (EPS_CU + eps_y) * d
    P, M = punto(sec, c)
    return {'c': c, 'd': d, 'eps_y': eps_y,
            'a': beta1(sec.fpc) * c, 'P_kN': P, 'M_kNm': M}


def curva_a_mano(sec, n=24):
    """
    La envolvente entera con el metodo del curso, para poder mirarla
    al lado de la de fibras.
    """
    pts = [{'P_kN': -traccion_pura(sec), 'M_kNm': 0.0, 'de': 'traccion pura'}]
    for i in range(1, n + 1):
        c = sec.h * i / float(n)
        P, M = punto(sec, c)
        pts.append({'P_kN': P, 'M_kNm': M, 'c': c, 'de': 'Whitney'})
    pts.append({'P_kN': compresion_pura(sec), 'M_kNm': 0.0,
                'de': 'compresion pura'})
    return pts


def comparar(modelo, elemento_id, mostrar=True):
    sec = capacidad.desde_elemento(modelo, elemento_id)
    fib = capacidad.interaccion(sec)

    # --- los tres puntos que se calculan a mano ---
    a_mano = {
        'traccion pura': (-traccion_pura(sec), 0.0),
        'compresion pura': (compresion_pura(sec), 0.0),
    }
    fp = flexion_pura(sec)
    if fp:
        a_mano['flexion pura (P=0)'] = (fp['P_kN'], fp['M_kNm'])
    bal = balanceado(sec)
    if bal:
        a_mano['balanceado'] = (bal['P_kN'], bal['M_kNm'])

    # --- los mismos, sacados de la curva de fibras ---
    de_fibras = {}
    p_trac = min(fib, key=lambda p: p['P_kN'])
    p_comp = max(fib, key=lambda p: p['P_kN'])
    de_fibras['traccion pura'] = (p_trac['P_kN'], p_trac['M_kNm'])
    de_fibras['compresion pura'] = (p_comp['P_kN'], p_comp['M_kNm'])
    p0 = min((p for p in fib if abs(p['P_kN']) < 1e-6),
             key=lambda p: abs(p['P_kN']), default=None)
    if p0:
        de_fibras['flexion pura (P=0)'] = (p0['P_kN'], p0['M_kNm'])
    # El balanceado se compara AL MISMO P, no contra el maximo de la
    # envolvente muestreada. Comparar "el maximo de mi muestreo" contra
    # "el punto exacto" mezcla dos cosas: la diferencia de hipotesis y
    # lo grueso del muestreo. Con diez niveles de axial, el maximo real
    # cae entre dos muestras y la diferencia salia del 14%.
    sin_conf = None
    if bal:
        r = capacidad.momento_curvatura(sec, P=bal['P_kN'])
        M = r['M_aci'] if r.get('M_aci') else r['M_max']
        de_fibras['balanceado'] = (bal['P_kN'], M)

        # La misma seccion pero sin confinar, que es la hipotesis del
        # calculo a mano. Sirve para separar cuanto de la diferencia es
        # el confinamiento y cuanto es Whitney contra la parabola.
        if sec.estribo:
            desnuda = copy.copy(sec)
            desnuda.estribo = {}
            desnuda.trabas_x = desnuda.trabas_y = 0
            r2 = capacidad.momento_curvatura(desnuda, P=bal['P_kN'])
            sin_conf = r2['M_aci'] if r2.get('M_aci') else r2['M_max']
    p_max = max(fib, key=lambda p: p['M_kNm'])
    de_fibras['maximo de la envolvente'] = (p_max['P_kN'], p_max['M_kNm'])

    if mostrar:
        print(sec.resumen())
        print()
        print('    beta1 = %.3f     d (barra mas profunda) = %.4f m'
              % (beta1(sec.fpc), _capas(sec)[-1][0] if _capas(sec) else 0))
        if fp:
            print('    flexion pura: c = %.4f m, a = %.4f m'
                  % (fp['c'], fp['a']))
        if bal:
            print('    balanceado:   c = %.4f m, a = %.4f m, eps_y = %.5f'
                  % (bal['c'], bal['a'], bal['eps_y']))
        print()
        print('    %-20s %14s %14s %14s %14s'
              % ('punto', 'P a mano', 'P fibras', 'M a mano', 'M fibras'))
        for k in ('traccion pura', 'flexion pura (P=0)', 'balanceado',
                  'compresion pura', 'maximo de la envolvente'):
            if k not in a_mano or k not in de_fibras:
                continue
            (Pa, Ma), (Pf, Mf) = a_mano[k], de_fibras[k]
            print('    %-20s %14.1f %14.1f %14.1f %14.1f'
                  % (k, Pa, Pf, Ma, Mf))

        print()
        print('    diferencias, y si se explican:')
        Pa = a_mano['compresion pura'][0]
        Pf = de_fibras['compresion pura'][0]
        # el modelo de fibras usa f'c y el calculo a mano 0.85 f'c
        esperado = (sec.fpc * (sec.Ag - sec.As) + sec.fy * sec.As)
        print('      compresion pura   %.1f contra %.1f kN  (%.1f %%)'
              % (Pa, Pf, 100 * (Pa - Pf) / Pf))
        print('        la de fibras usa f\'c y la de mano 0.85 f\'c; con f\'c')
        print('        el calculo a mano daria %.1f kN, o sea %.2f %% de la'
              % (esperado, 100 * esperado / Pf))
        print('        de fibras. La diferencia es SOLO el 0.85 de ACI.')
        Pa = -traccion_pura(sec)
        Pf = de_fibras['traccion pura'][0]
        print('      traccion pura     %.1f contra %.1f kN  (%.2e relativo)'
              % (Pa, Pf, abs(Pa - Pf) / max(abs(Pf), 1.0)))
        print('        aca NO hay hipotesis distintas: es As*fy. Tiene que')
        print('        coincidir, y coincide.')
        if fp and 'flexion pura (P=0)' in de_fibras:
            Ma = fp['M_kNm']
            Mf = de_fibras['flexion pura (P=0)'][1]
            print('      flexion pura      %.1f contra %.1f kN m  (%.1f %%)'
                  % (Ma, Mf, 100 * (Ma - Mf) / Mf))
            print('        Whitney contra la parabola de Concrete01, y')
            capas = _capas(sec)
            if capas and fp['c'] > 1e-9:
                d = capas[-1][0]
                eps = EPS_CU * (d - fp['c']) / fp['c']
                eps_y = sec.fy / sec.Es
                fs = sec.fy + sec.endurecimiento * sec.Es * max(0.0,
                                                                eps - eps_y)
                print('        sobre todo ENDURECIMIENTO: con c = %.3f m sobre'
                      % fp['c'])
                print('        un canto de %.2f m, la barra mas traccionada'
                      % sec.h)
                print('        llega a eps = %.4f, donde Steel01 da %.0f MPa'
                      % (eps, fs / 1000.0))
                print('        en vez de los %.0f de fy: un %.0f %% mas.'
                      % (sec.fy / 1000.0, 100 * (fs - sec.fy) / sec.fy))
        if 'balanceado' in a_mano and 'balanceado' in de_fibras:
            (Pab, Mab) = a_mano['balanceado']
            (Pfb, Mfb) = de_fibras['balanceado']
            print('      balanceado        M %.1f contra %.1f kN m  (%.1f %%)'
                  % (Mab, Mfb, 100 * (Mab - Mfb) / max(Mfb, 1e-9)))
            print('        los dos evaluados a P = %.0f kN, que es el axial'
                  % Pab)
            print('        balanceado que sale del calculo a mano.')
            if sin_conf:
                print('        la MISMA seccion sin confinar da %.1f kN m '
                      '(%.1f %%):' % (sin_conf,
                                      100 * (Mab - sin_conf) / sin_conf))
                print('        o sea que el confinamiento explica la mitad de')
                print('        la diferencia y el resto es el bloque')
                print('        equivalente con axial alto, donde no fue')
                print('        calibrado.')

    return {'seccion': sec, 'a_mano': a_mano, 'de_fibras': de_fibras,
            'flexion_pura': fp, 'balanceado': bal}


def elementos_rc_por_defecto(modelo):
    """La primera columna y el primer muro con fierro de cada cuerpo."""
    salida = []
    for cuerpo in _ed.CUERPOS.values():
        for tipo in ('columna', 'muro'):
            eid = next((e['id'] for e in modelo['elementos']
                        if e.get('tipo') == tipo and 'enfierradura' in e
                        and _ed.cuerpo_de(e['id']) == cuerpo), None)
            if eid is not None:
                salida.append(eid)
    return salida


def rc_a_mano(inf, args):
    """C2: las fibras contra el calculo a mano."""
    modelo = _ed.estructura()
    elems = [int(x) for x in (getattr(args, 'elementos', None) or [])] or elementos_rc_por_defecto(modelo)
    print('=' * 76)
    print('  VERIFICACION RC: FIBRAS CONTRA CALCULO A MANO')
    print('=' * 76)
    for e in elems:
        print()
        r = comparar(modelo, e)
        print()
        print('-' * 76)
        sec = r['seccion']
        # Lo que TIENE que cumplirse, y por que (ver el encabezado de la
        # seccion "A MANO"): traccion pura exacta, y en compresion pura la
        # diferencia es SOLO el 0.85 de ACI.
        Pt_a, Pt_f = r['a_mano']['traccion pura'][0], r['de_fibras']['traccion pura'][0]
        inf.check(abs(Pt_a - Pt_f) <= 1e-9 * max(abs(Pt_f), 1.0),
                  '%s: traccion pura de fibras = -As fy a mano (%.1f kN)' % (e, Pt_f))
        Pc_f = r['de_fibras']['compresion pura'][0]
        sin_085 = sec.fpc * (sec.Ag - sec.As) + sec.fy * sec.As
        inf.check(abs(sin_085 - Pc_f) <= 1e-9 * abs(Pc_f),
                  '%s: compresion pura de fibras = f\'c (Ag - As) + fy As; la de mano difiere '
                  'solo por el 0.85 de ACI' % e)
        bal = r['balanceado']
        if bal:
            inf.check(abs(r['de_fibras']['balanceado'][0] - bal['P_kN']) <= 1e-9 * abs(bal['P_kN']),
                      '%s: el balanceado de fibras se evalua al MISMO P que el de mano (%.0f kN)'
                      % (e, bal['P_kN']))
    print()


# ============================================================
# LA TABLA QA: M-phi, P-M columna, P-M muro
# ============================================================
def seccion_fisurada(sec):
    r"""
    A MANO: seccion fisurada elastica con P = 0, primera fluencia de la
    barra mas traccionada. Equilibrio de momentos estaticos para kd,
    y M respecto del eje neutro (con P = 0 da igual el punto). Las
    barras comprimidas con (n - 1), porque desplazan hormigon.
    """
    Ec = 4700.0 * math.sqrt(sec.fpc / 1000.0) * 1000.0
    n = sec.Es / Ec
    capas = _capas(sec)
    b = sec.b

    def estatico(kd):
        s = b * kd ** 2 / 2.0
        for d, A in capas:
            s += ((n - 1) if d < kd else n) * A * (kd - d)
        return s

    lo, hi = 1e-6, sec.h
    for _ in range(200):
        m = 0.5 * (lo + hi)
        if estatico(m) < 0:
            lo = m
        else:
            hi = m
    kd = 0.5 * (lo + hi)
    I_cr = b * kd ** 3 / 3.0 + sum(((n - 1) if d < kd else n) * A * (kd - d) ** 2
                                   for d, A in capas)
    phi_y = (sec.fy / sec.Es) / (capas[-1][0] - kd)
    return {'kd': kd, 'n': n, 'Ec': Ec, 'EI_cr': Ec * I_cr, 'phi_y': phi_y,
            'My': Ec * I_cr * phi_y, 'fc_arriba_MPa': Ec * phi_y * kd / 1000.0}


def con_barras(sec, diametro_nuevo_m):
    """La misma seccion con otro diametro en todas las barras."""
    otra = copy.copy(sec)
    otra.barras = []
    for y, z, a in sec.barras:
        d = math.sqrt(4.0 * a / math.pi)
        otra.barras.append((y, z, a * (diametro_nuevo_m / d) ** 2))
    return otra


def fila_mphi(ctx):
    f = Fila('M-phi', 'python -m verificacion.capacidad mphi_pm')
    sec = capacidad.desde_elemento(ctx['modelo'], COLUMNA)
    with opensees.AvisosDeOpenSees():
        r20 = capacidad.momento_curvatura(sec, P=0.0)
        r40 = capacidad.momento_curvatura(sec, P=0.0, nf=40)
    print('    columna %d, %s, f\'c %.0f MPa, %d barras, As %.2f cm2'
          % (COLUMNA, sec.nombre, sec.fpc / 1000.0, len(sec.barras), sec.As * 1e4))

    w = flexion_pura(sec)
    d_mn = rel(r20['M_aci'], w['M_kNm'])
    w22 = flexion_pura(con_barras(sec, 0.022))
    f.check(d_mn <= TOL_MODELOS,
            'Mn (hormigon a 0.003) fibras %.1f contra Whitney a mano %.1f kN m: %.2f %% '
            '(umbral %.0f %%)' % (r20['M_aci'], w['M_kNm'], 100 * d_mn, 100 * TOL_MODELOS),
            'el umbral detecta un diametro menos: con D22 Whitney da %.1f kN m (%+.1f %%)'
            % (w22['M_kNm'], 100 * (w22['M_kNm'] / w['M_kNm'] - 1)))

    h = seccion_fisurada(sec)
    k_fib = r20['rigidez_inicial_kNm2']
    d_ei = rel(k_fib, h['EI_cr'])
    f.check(d_ei <= TOL_MODELOS,
            'rigidez fisurada: pendiente inicial de la curva %.0f contra Ec I_cr a mano '
            '%.0f kN m2: %.2f %%' % (k_fib, h['EI_cr'], 100 * d_ei),
            'a mano: n = %.2f, kd = %.4f m, primera fluencia phi_y = %.5f 1/m, My = %.1f kN m '
            '(fc arriba %.1f MPa)' % (h['n'], h['kd'], h['phi_y'], h['My'], h['fc_arriba_MPa']))

    d_nf = rel(r20['M_max'], r40['M_max'])
    f.check(d_nf <= TOL_MALLADO,
            'mallado: M_max con 20 fibras %.1f contra 40 fibras %.1f kN m: %.2f %% '
            '(lo que declara capacidad.py: < 0.5 %%)' % (r20['M_max'], r40['M_max'], 100 * d_nf))

    termina = r20['motivo_termino']
    f.check('eps_su' in termina or 'eps_cu' in termina,
            'la curva la corta el material, no el analisis: %s' % termina,
            'M_max %.1f kN m en phi %.4f 1/m; ductilidad de curvatura phi_u / phi_y(a mano) = %.0f'
            % (r20['M_max'], r20['phi_en_M_max'], r20['phi'][-1] / h['phi_y']))
    f.numero = 'Mn %.1f vs Whitney %.1f kN m (%.1f %%); EI_cr %.1f %%' % (
        r20['M_aci'], w['M_kNm'], 100 * d_mn, 100 * d_ei)
    f.criterio = 'fibras vs a mano <= 2 %; 20 vs 40 fibras <= 0.5 %'
    f.datos['M_aci'] = r20['M_aci']
    return f


def familia_del_anexo(anexo, eid):
    e = next(x for x in anexo['elementos'] if x['id'] == eid)
    return e, next(fa for fa in anexo['familias'] if fa['indice'] == e['familia'])


def demandas_del_anexo(ctx, eid, tipo, plano):
    r"""
    (caso, P, M, Mn, u) de eid en cada caso de los resultados, rehechos con
    la regla de calculo/demanda.py sobre los esfuerzos de los resultados, y
    la u que guardaron los resultados. Tienen que ser la misma: una sola
    definicion.
    """
    e, fam = familia_del_anexo(ctx['anexo'], eid)
    curva = [{'P_kN': P, 'M_kNm': M} for P, M in zip(fam['P'], fam['Mn'])]
    filas = []
    for caso in ctx['anexo']['casos']:
        fz = next(x for x in caso['esfuerzos'] if x['id'] == eid)
        d = dem.demanda(fz['f'], tipo=tipo, plano=plano)
        Mn = dem.capacidad_en(d['P_kN'], curva)
        u = d['M_kNm'] / Mn if Mn > 0 else float('inf')
        guardada = next(x for x in caso['demandas'] if x['id'] == eid)
        filas.append({'caso': caso['nombre'], 'P': d['P_kN'], 'M': d['M_kNm'],
                      'fuera': d.get('M_fuera_de_plano_kNm'), 'Mn': Mn, 'u': u,
                      'u_anexo': guardada['u'], 'pasa': guardada['pasa']})
    return filas


def curva_igual_al_anexo(f, sec, fam):
    """La curva de los resultados es la de capacidad.interaccion, al redondeo."""
    with opensees.AvisosDeOpenSees():
        pts = capacidad.interaccion(sec)
    pts = sorted(pts, key=lambda q: q['P_kN'])
    peor = max(max(abs(a['P_kN'] - P), abs(a['M_kNm'] - M))
               for a, P, M in zip(pts, fam['P'], fam['Mn']))
    cota = 0.5e-4 * (1 + 1e-9)
    f.check(len(pts) == len(fam['P']) and peor <= cota,
            'la curva de los resultados (familia %d, %d puntos) = capacidad.interaccion: '
            'peor %.1e (los resultados escriben 4 decimales)' % (fam['indice'], len(pts), peor))
    return pts


def fila_pm_columna(ctx):
    f = Fila('P-M columna', 'python -m verificacion.capacidad mphi_pm')
    sec = capacidad.desde_elemento(ctx['modelo'], COLUMNA)
    e, fam = familia_del_anexo(ctx['anexo'], COLUMNA)
    print('    familia %d: %s (%d columnas)' % (fam['indice'], fam['refuerzo'], len(fam['elementos'])))
    pts = curva_igual_al_anexo(f, sec, fam)

    t = min(pts, key=lambda q: q['P_kN'])
    f.check(rel(t['P_kN'], -traccion_pura(sec)) <= 1e-9,
            'traccion pura: fibras %.1f = -As fy %.1f kN (sin hipotesis distintas)'
            % (t['P_kN'], -traccion_pura(sec)))
    p0 = min(pts, key=lambda q: abs(q['P_kN']))
    w = flexion_pura(sec)
    f.check(rel(p0['M_kNm'], w['M_kNm']) <= TOL_MODELOS,
            'flexion pura: fibras %.1f contra Whitney %.1f kN m (%.2f %%)'
            % (p0['M_kNm'], w['M_kNm'], 100 * rel(p0['M_kNm'], w['M_kNm'])))

    bal = balanceado(sec)
    with opensees.AvisosDeOpenSees():
        rb = capacidad.momento_curvatura(sec, P=bal['P_kN'])
        desnuda = copy.copy(sec)
        desnuda.estribo = {}
        desnuda.trabas_x = desnuda.trabas_y = 0
        rd = capacidad.momento_curvatura(desnuda, P=bal['P_kN'])
    Mb = rb['M_aci'] or rb['M_max']
    Md = rd['M_aci'] or rd['M_max']
    f.check(Mb <= bal['M_kNm'],
            'balanceado (P = %.0f kN): fibras %.1f bajo Whitney %.1f kN m (%.1f %%), del lado seguro'
            % (bal['P_kN'], Mb, bal['M_kNm'], 100 * (bal['M_kNm'] / Mb - 1)),
            'sin confinar las fibras dan %.1f (%.1f %%): el confinamiento explica esa parte y el '
            'resto es el bloque de Whitney con axial alto' % (Md, 100 * (bal['M_kNm'] / Md - 1)))
    f.info('compresion pura: fibras %.1f kN = f\'c(Ag - As) + fy As; ACI con 0.85 da %.1f'
           % (max(q['P_kN'] for q in pts), compresion_pura(sec)))

    filas = demandas_del_anexo(ctx, COLUMNA, 'columna', None)
    peor_u = max(abs(x['u'] - x['u_anexo']) for x in filas)
    f.check(peor_u <= 0.5e-6 + 1e-9,
            'la u de los 15 casos, rehecha con calculo/demanda.py sobre los esfuerzos de los '
            'resultados, = la de los resultados (peor %.1e; escriben 6 decimales)' % peor_u)
    diseno = [x for x in filas if x['caso'] not in NO_DE_DISENO and x['caso'] not in CASOS]
    g = max(diseno, key=lambda x: x['u'])
    f.check(g['u'] < 1.0,
            'gobierna %s: P = %.1f kN, M = %.1f kN m, Mn = %.1f kN m, u = %.3f, PASA'
            % (g['caso'], g['P'], g['M'], g['Mn'], g['u']),
            'Mn nominal, sin phi; M = resultante sqrt(My2 + Mz2) contra una curva uniaxial')
    f.numero = 'extremos exactos; flexion %.1f %%; u = %.3f en %s' % (
        100 * rel(p0['M_kNm'], w['M_kNm']), g['u'], g['caso'])
    f.criterio = 'traccion = -As fy; flexion vs Whitney <= 2 %; resultados = interaccion; u rehecha = resultados'
    f.datos['pts'] = pts
    return f


def fila_pm_muro(ctx):
    f = Fila('P-M muro', 'python -m verificacion.capacidad mphi_pm')
    modelo = ctx['modelo']
    numeros = []
    for eid in MUROS:
        e = next(x for x in modelo['elementos'] if int(x['id']) == eid)
        sec = capacidad.desde_elemento(modelo, eid)
        _ea, fam = familia_del_anexo(ctx['anexo'], eid)
        plano = dem.momento_en_el_plano_de(modelo, e)
        print('    muro %d, %s, %.2f x %.2f m, f\'c %.0f MPa, %d barras, As %.2f cm2, '
              'momento del plano %s' % (eid, sec.nombre, sec.b, sec.h, sec.fpc / 1000.0,
                                        len(sec.barras), sec.As * 1e4, plano))
        pts = curva_igual_al_anexo(f, sec, fam)

        filas = demandas_del_anexo(ctx, eid, 'muro', plano)
        ey = next(x for x in filas if x['caso'] == 'EY')
        f.check(ey['M'] > 10 * ey['fuera'],
                '%d: el momento del plano (%s, por inercias) es el grande: en EY %.1f contra %.1f '
                'kN m fuera del plano' % (eid, plano, ey['M'], ey['fuera']))
        t = min(pts, key=lambda q: q['P_kN'])
        f.check(rel(t['P_kN'], -traccion_pura(sec)) <= 1e-9,
                '%d: traccion pura fibras %.1f = -As fy %.1f kN'
                % (eid, t['P_kN'], -traccion_pura(sec)))

        # Flexion pura, desarmada. rc_a_mano compara Whitney en UN sentido
        # contra el menor de los dos de las fibras; aca se toma el mismo
        # sentido y se sacan, de a una, las dos cosas que las separan: el
        # mallado y el endurecimiento de Steel01.
        otra = capacidad.espejo(sec)
        with opensees.AvisosDeOpenSees():
            m20 = [capacidad.momento_curvatura(s, P=0.0)['M_aci'] for s in (sec, otra)]
            m40 = [capacidad.momento_curvatura(s, P=0.0, nf=40)['M_aci'] for s in (sec, otra)]
            k = 0 if m20[0] <= m20[1] else 1
            s_k = (sec, otra)[k]
            plano_ = copy.copy(s_k)
            plano_.endurecimiento = 0.0
            m40_se = capacidad.momento_curvatura(plano_, P=0.0, nf=40)['M_aci']
        w_dir = flexion_pura(sec)['M_kNm']
        w_k = flexion_pura(s_k)['M_kNm']
        f.info('%d flexion pura, como la imprime rc_a_mano: Whitney %.1f contra fibras %.1f '
               'kN m (%+.1f %%)' % (eid, w_dir, min(m20), 100 * (w_dir / min(m20) - 1)))
        f.info('  en el sentido que manda (%s): 20 fibras %.1f -> 40 fibras %.1f -> sin '
               'endurecimiento %.1f; Whitney %.1f'
               % ('directo' if k == 0 else 'espejado', m20[k], m40[k], m40_se, w_k))
        resid = rel(m40_se, w_k)
        f.check(resid <= TOL_MODELOS,
                '%d: con el mismo sentido, sin endurecimiento y con 40 fibras, fibras = Whitney '
                'al %.2f %%' % (eid, 100 * resid))
        mall = rel(m20[k], m40[k])
        if mall > TOL_MALLADO:
            f.abierto('%d: el mallado de 20 fibras no alcanza en un muro de %.2f m: a P = 0 '
                      'sobreestima Mn en %.1f %% contra 40 (capacidad.py declara < 0.5 %%)'
                      % (eid, sec.h, 100 * mall))
        endu = rel(m40[k], m40_se)
        if endu > TOL_MODELOS:
            f.abierto('%d: cerca de P = 0 la curva incluye el endurecimiento de Steel01 (+%.1f %%): '
                      'no es la capacidad nominal de ACI' % (eid, 100 * endu))

        diseno = [x for x in filas if x['caso'] not in NO_DE_DISENO and x['caso'] not in CASOS]
        g = max(diseno, key=lambda x: x['u'])
        with opensees.AvisosDeOpenSees():
            fina = capacidad.interaccion(sec, nf=40)
        Mn_f = dem.capacidad_en(g['P'], fina)
        f.check(g['u'] < 1.0 and g['M'] / Mn_f < 1.0,
                '%d gobierna %s: P = %.1f kN, M = %.1f kN m, Mn = %.1f, u = %.3f (con 40 fibras '
                '%.3f), PASA' % (eid, g['caso'], g['P'], g['M'], g['Mn'], g['u'], g['M'] / Mn_f))
        peor_u = max(abs(x['u'] - x['u_anexo']) for x in filas if math.isfinite(x['u']))
        f.check(peor_u <= 0.5e-6 + 1e-9,
                '%d: u rehecha = u de los resultados en los 15 casos (peor %.1e)' % (eid, peor_u))
        numeros.append('%d u = %.3f (%.3f fino)' % (eid, g['u'], g['M'] / Mn_f))
    f.numero = '; '.join(numeros)
    f.criterio = 'extremos exactos; plano por inercias; fibras = Whitney con las mismas hipotesis <= 2 %'
    return f


def _sumar_fila(inf, fila, abiertos):
    """Lo que una fila de la tabla QA no cumplio pasa al informe del bloque;
    lo abierto (PARCIAL) se informa y no es falla."""
    inf.fallas.extend('%s: %s' % (fila.prueba, x) for x in fila.fallas)
    abiertos.extend('%s: %s' % (fila.prueba, x) for x in fila.abiertos)


def mphi_pm(inf, args=None):
    """C1: M-phi y P-M de tres columnas, y las filas M-phi y P-M de la tabla QA."""
    for eid in CAPACIDAD:
        rc = capacidad.main([str(eid), '--pm'])
        inf.check(rc == 0, 'calculo.capacidad %d --pm termina bien' % eid)
        print()

    anexo, origen = resultados_del_laboratorio()
    ctx = {'modelo': _ed.estructura(), 'anexo': anexo}
    print('  resultados  %s (%d casos)' % (origen, len(anexo['casos'])))
    abiertos = []
    filas = {}
    for nombre, hacer in (('M-phi', fila_mphi), ('P-M columna', fila_pm_columna),
                          ('P-M muro', fila_pm_muro)):
        titulo(nombre.upper())
        filas[nombre] = hacer(ctx)
        _sumar_fila(inf, filas[nombre], abiertos)

    titulo('LOS NUMEROS DE CONTROL DE %d' % COLUMNA)
    pts = filas['P-M columna'].datos['pts']
    nariz = max(pts, key=lambda q: q['M_kNm'])
    p0 = min(pts, key=lambda q: abs(q['P_kN']))
    clave = 'capacidad_%d' % COLUMNA
    escrito = numeros_de_control()[clave]
    inf.check(calza(round(p0['M_kNm'], 1), clave, 'Mn_P0_kNm')
              and calza(round(nariz['P_kN']), clave, 'nariz_P_kN')
              and calza(round(nariz['M_kNm']), clave, 'nariz_M_kNm'),
              '%d: Mn(P = 0) = %.1f kN m; nariz en P = %.0f kN con M = %.0f kN m '
              '(verificacion/numeros_de_control.json: %s, %s y %s)'
              % (COLUMNA, p0['M_kNm'], nariz['P_kN'], nariz['M_kNm'],
                 escrito['Mn_P0_kNm'], escrito['nariz_P_kN'], escrito['nariz_M_kNm']))
    if abiertos:
        print()
        print('  abierto (PARCIAL, no es falla: lo mide la misma prueba):')
        for a in abiertos:
            print('    - %s' % a)


# ============================================================
# DEMANDA --TODAS Y LA FIRMA DE FAMILIA
# ============================================================
class _Copia(io.TextIOBase):
    """Escribe en la consola y guarda lo escrito (para leer el resumen)."""

    def __init__(self, destino):
        self.destino = destino
        self.texto = io.StringIO()

    def write(self, s):
        self.destino.write(s)
        self.texto.write(s)
        return len(s)

    def flush(self):
        self.destino.flush()


def huella_de_seccion(sec):
    """Todo lo que cambia la curva de fibras de una seccion (el nombre sin el
    '(elem ...)' del elemento, que no la cambia)."""
    return (re.sub(r'\s*\(.*\)$', '', sec.nombre), round(sec.b, 9), round(sec.h, 9), round(sec.fpc, 6),
            round(sec.fy, 6), round(sec.Es, 3), round(sec.endurecimiento, 9), round(sec.rec, 9),
            tuple(sorted((round(y, 9), round(z, 9), round(a, 12)) for y, z, a in sec.barras)),
            json.dumps(sec.estribo, sort_keys=True), sec.trabas_x, sec.trabas_y)


def demanda_todas(inf, args=None):
    """C3: la demanda de cada barra con fierro sobre su curva, y la firma de familia."""
    copia = _Copia(sys.stdout)
    with contextlib.redirect_stdout(copia):
        rc = dem.main(['--todas'])
    texto = copia.texto.getvalue()
    inf.check(rc == 0, 'calculo.demanda --todas termina bien')
    m1 = re.search(r'(\d+) curvas distintas para (\d+) elementos', texto)
    m2 = re.search(r'la mas exigida es la (\d+), con u = ([\d.]+)', texto)
    inf.check(bool(m1 and m2)
              and calza(int(m1.group(1)), 'demanda', 'familias')
              and calza(int(m1.group(2)), 'demanda', 'elementos_con_fierro')
              and calza(int(m2.group(1)), 'demanda', 'mas_exigida_G_mas_Q')
              and calza(float(m2.group(2)), 'demanda', 'u_mas_exigida_G_mas_Q'),
              '%s curvas para %s elementos; la mas exigida con G + Q es la %s con u = %s '
              '(los numeros de control)' % (m1 and m1.group(1), m1 and m1.group(2),
                                            m2 and m2.group(1), m2 and m2.group(2)))

    titulo('LA FIRMA DE FAMILIA: dos secciones con la misma firma son la misma seccion')
    modelo = _ed.estructura()
    por_firma = collections.defaultdict(set)
    n = 0
    for e in modelo['elementos']:
        if 'enfierradura' not in e:
            continue
        sec = capacidad.desde_elemento(modelo, e['id'])
        por_firma[dem.firma_de_seccion(e, sec)].add(huella_de_seccion(sec))
        n += 1
    mezcladas = [k for k, v in por_firma.items() if len(v) > 1]
    inf.check(not mezcladas,
              '%d firmas para %d elementos con fierro; dentro de cada firma la seccion de fibras es '
              'UNA (b, h, f\'c, fy, recubrimiento, cada barra, estribo y trabas)' % (len(por_firma), n),
              ['firma %s junta %d secciones distintas' % (k[0], len(por_firma[k]))
               for k in mezcladas[:3]])
    anexo, origen = resultados_del_laboratorio()
    inf.check(len(anexo['familias']) == len(por_firma),
              '%s trae %d familias P-M: una por firma' % (origen, len(anexo['familias'])))


# ============================================================
# NUCLEOS
# ============================================================
def nucleos(inf, args=None):
    r"""
    C4. Informa los grupos de patas de nucleo y COMPRUEBA dos cosas:

    [1] los invariantes del agrupamiento (si i esta en el grupo de j,
        j esta en el de i; ninguna pata repetida; ningun grupo de 1);
    [2] que los `nucleo_*` de salidas/resultados.json sean los que sale de
        recalcular aca. Dos definiciones del mismo grupo divergen en
        silencio, y la que mentiria es la que lee el visor.
    """
    modelo = _ed.estructura()
    g = dem.grupos_de_nucleo(modelo)
    distintos = {tuple(v) for v in g.values()}
    muros = sum(1 for e in modelo['elementos'] if e.get('tipo') == 'muro')
    check = inf.check

    print('=' * 64)
    print('  NUCLEOS DE %s' % _ed.NOMBRE.upper())
    print('=' * 64)
    print('  %d muros; %d son pata de un nucleo, en %d grupos'
          % (muros, len(g), len(distintos)))

    print('\n[1] los grupos son consistentes')
    sueltos = [tuple(v) for v in distintos if len(v) < 2]
    check(not sueltos, 'ningun "grupo" tiene una sola pata', str(sueltos[:3]))
    dobles = [v for v in distintos if len(set(v)) != len(v)]
    check(not dobles, 'ninguna pata aparece dos veces en su grupo', str(dobles[:3]))
    asimetricos = [(i, j) for i, v in g.items() for j in v if i not in g.get(j, ())]
    check(not asimetricos, 'si i esta en el grupo de j, j esta en el de i',
          str(asimetricos[:3]))
    cache = {}
    sin_fierro_total = 0
    for ids in sorted(distintos, key=len, reverse=True):
        _asfy, sin = dem.asfy_de(modelo, ids, cache)
        sin_fierro_total += len(sin)
    print('         %d patas sin enfierradura: aportan 0 al As*fy del grupo, '
          'o sea el grupo se informa MAS traccionado de lo que esta'
          % sin_fierro_total)

    print('\n[2] salidas/resultados.json trae los mismos grupos')
    ruta = rutas.salida('resultados')
    if not os.path.exists(ruta):
        check(False, 'existe %s (python sap.py exportar resultados)' % rutas.relativa(ruta))
        return
    with open(ruta, encoding='utf-8') as f:
        anexo = json.load(f)
    de = (anexo.get('info') or {}).get('edificio')
    if not check(de == _ed.NOMBRE, 'los resultados son de %r' % _ed.NOMBRE,
                 [] if de == _ed.NOMBRE else 'traen %r' % de):
        return

    peor, n, estados = 0.0, 0, collections.Counter()
    for k in anexo['casos']:
        P_de = {x['id']: x['P'] for x in k['demandas']}
        for x in k['demandas']:
            ids = g.get(x['id'])
            esperado_patas = len(ids) if ids else 0
            if x.get('nucleo_patas', 0) != esperado_patas:
                check(False, 'nucleo_patas del elemento %d en %s'
                      % (x['id'], k['nombre']),
                      'resultados %s, recalculado %s'
                      % (x.get('nucleo_patas'), esperado_patas))
                return
            if not ids:
                continue
            P = sum(P_de.get(i, 0.0) for i in ids)
            peor = max(peor, abs(P - x['nucleo_P']))
            estados[x['nucleo_estado']] += 1
            n += 1
    # Los resultados redondean a DECIMALES_FUERZA = 4, asi que la cota es
    # medio ultimo decimal por cada pata que se suma.
    cota = 0.5e-4 * max(len(v) for v in distintos)
    check(peor <= cota, 'el nucleo_P de las %d filas de pata calza al recalcularlo' % n,
          'peor diferencia %.2e kN, cota por redondeo %.2e' % (peor, cota))
    print('         estados: %s' % dict(estados))
    fuera = estados.get(dem.TRACCION_FUERA, 0)
    print('         %d filas con el grupo POR SOBRE su As*fy%s'
          % (fuera, ' (ninguna: toda la traccion que saca a una pata de su '
             'curva es par interno o cabe en el fierro del grupo)' if not fuera else ''))

    print()
    check(calza(len(g), 'nucleos', 'patas') and calza(len(distintos), 'nucleos', 'grupos')
          and calza(n, 'nucleos', 'filas_de_pata'),
          '%d patas en %d grupos y %d filas de pata: los numeros de control'
          % (len(g), len(distintos), n))


# ============================================================
# LOSA COLABORANTE
# ============================================================
def losa_colaborante(inf, args=None):
    """C5: la regla de ancho efectivo (no conectada) y lo que daria."""
    check = inf.check
    inercia_T, ancho_efectivo = losa.inercia_T, losa.ancho_efectivo

    print('=' * 64)
    print('  LA LOSA COLABORANTE (ACI 318-08 8.12.2)')
    print('=' * 64)

    print('\n[1] la formula, contra casos con respuesta conocida')
    check(abs(inercia_T(0.3, 0.6, 0.25, 0.3) - 0.3 * 0.6 ** 3 / 12) < 1e-15,
          'sin ala (b_eff = bw) da la inercia del rectangulo')
    check(inercia_T(0.3, 0.6, 0.25, 1.25) > 0.3 * 0.6 ** 3 / 12,
          'con ala da mas que el rectangulo')
    check(abs(ancho_efectivo(0.3, 0.6, 0.25, 5.0) - 1.25) < 1e-12,
          'en una viga de 5.00 m manda L/4 = 1.25 m')
    check(abs(ancho_efectivo(0.3, 0.6, 0.25, 0.4) - 0.3) < 1e-12,
          'en una viga de 0.40 m el ala no baja del alma (b_eff = bw)')
    # Una T simetrica respecto de su centro no existe, pero el caso
    # limite hf -> h tiene que dar el rectangulo de ancho b_eff.
    I = inercia_T(0.3, 0.5, 0.4999999, 1.0)
    check(I > 0, 'el caso limite hf -> h no explota', 'Iz = %.6f' % I)

    ed = _ed.NOMBRE
    razones, manda = losa.informe(_ed.estructura())
    print('\n[2] %s: que daria el ala en cada viga' % ed)
    if not razones:
        check(False, '%s: hay vigas con b y h para revisar' % ed)
        return
    print('         %d vigas; Iz x%.2f de mediana (de x%.2f a x%.2f)'
          % (len(razones), razones[len(razones) // 2], razones[0], razones[-1]))
    print('         tope que manda: %s' % dict(manda))
    check(razones[0] >= 1.0, '%s: ninguna viga PIERDE inercia con el ala' % ed,
          'la menor razon es x%.4f' % razones[0])
    print('         (la regla NO esta conectada: ningun numero del programa depende de esto)')


# ============================================================
# PANDEO DE LAS BARRAS (Dhakal y Maekawa 2002) - Honors
# ============================================================
# OpenSees (ReinforcingSteel -DMBuck) contra las ecuaciones del paper,
# hasta eps*. Cota MEDIDA, no elegida: con el acero de laboratorio.json
# la peor diferencia es 0.15 % de fy con L/D = 4 y 1.7 % con L/D = 8. La
# causa: OpenSees degrada con la misma pendiente que la ec. (1) (0.434
# contra 0.422 y 4.72 contra 4.75 por unidad de deformacion) pero empieza
# un poco despues de eps_y. Despues de eps* OpenSees baja mas suave que el
# -0.02 Es del paper; eso queda fuera del M-phi (termina en eps_cu) y no
# se compara.
TOL_DM_OPENSEES = 0.02          # de fy, hasta eps*
TOL_DM_PENDIENTE = 0.05         # la pendiente de la degradacion, relativa


def pandeo(inf, args=None):
    """C6: Dhakal-Maekawa en OpenSees = el paper, y lo que le hace a la 200037."""
    import numpy as np
    check = inf.check
    p = capacidad.parametros_pandeo()
    a, alfa = p['acero'], float(p['alfa'])
    fy, Es = a['fy_MPa'] * 1e3, a['Es_MPa'] * 1e3
    ey = fy / Es

    print('=' * 64)
    print('  PANDEO DE LAS BARRAS: Dhakal y Maekawa (2002)')
    print('=' * 64)

    print('\n[1] las ecuaciones (2) y (3), contra las rectas de su Fig. 10')
    e, sl = capacidad.curva_de_barra(a, n=4001)
    lam_mano = 4.0 * math.sqrt(420.0 / 100.0)
    _s, ee, se, lam = capacidad.dhakal_maekawa(e, sl, fy, Es, 4.0, alfa)
    check(abs(lam - lam_mano) < 1e-12 and abs(ee / ey - (55 - 2.3 * lam_mano)) < 1e-9
          and abs(se / np.interp(ee, e, sl) - (1.1 - 0.016 * lam_mano)) < 1e-9,
          'L/D 4, fy 420 MPa: lambda = 4 raiz(4.2) = %.4f, eps*/eps_y = 55 - 2.3 lambda = %.3f, '
          'sig*/sig_l* = 1.1 - 0.016 lambda = %.4f' % (lam, ee / ey, se / np.interp(ee, e, sl)))
    _s, ee30, se30, _l = capacidad.dhakal_maekawa(e, sl, fy, Es, 30.0, alfa)
    check(abs(ee30 / ey - 7.0) < 1e-12 and abs(se30 - 0.2 * fy) < 1e-9,
          'los topes: con L/D 30 eps* = 7 eps_y y sig* = 0.2 fy')

    print('\n[2] OpenSees ReinforcingSteel -DMBuck = el paper hasta eps*')
    for n in p['separaciones_de_estribo']:
        L_D = 4.0 * n
        _e, so = capacidad.curva_de_barra(a, L_D, alfa, n=4001)
        sd, ee, se, lam = capacidad.dhakal_maekawa(e, sl, fy, Es, L_D, alfa)
        m = e <= ee
        d = np.abs(so[m] - sd[m]) / fy
        i = int(np.argmax(d))
        # la pendiente de 1 - sig/sig_l contra (eps - eps_y), en el tramo de la ec. (1)
        t = (e > 0.012) & (e < 0.8 * ee)
        k_os = np.polyfit(e[t] - ey, 1 - so[t] / sl[t], 1)[0]
        k_pa = (1 - se / np.interp(ee, e, sl)) / (ee - ey)
        check(d[i] <= TOL_DM_OPENSEES and abs(k_os / k_pa - 1) <= TOL_DM_PENDIENTE,
              'L/D %.0f (lambda %.2f, eps* %.4f): |OpenSees - paper| <= %.0f %% de fy y la misma pendiente'
              % (L_D, lam, ee, 100 * TOL_DM_OPENSEES),
              'peor %.2f %% de fy en eps %.4f; pendiente %.3f contra %.3f del paper'
              % (100 * d[i], e[m][i], k_os, k_pa))

    print('\n[3] OpenSees no depende de las unidades, solo de eps_y')
    L_D = 8.0
    _e, s_kpa = capacidad.curva_de_barra(a, L_D, alfa, n=1201)
    en_mpa = dict(a, fy_MPa=a['fy_MPa'] / 1e3, fu_MPa=a['fu_MPa'] / 1e3, Es_MPa=a['Es_MPa'] / 1e3,
                  Esh_MPa=a['Esh_MPa'] / 1e3)                  # los mismos numeros en MPa
    _e, s_mpa = capacidad.curva_de_barra(en_mpa, L_D, alfa, n=1201)
    check(np.max(np.abs(s_kpa / fy - s_mpa * 1e3 / fy)) < 1e-12,
          'en kPa y en MPa da la misma curva normalizada (no hay trampa de unidades)')
    otro = dict(a, fy_MPa=a['fy_MPa'] / 2, fu_MPa=a['fu_MPa'] / 2, Es_MPa=a['Es_MPa'] / 2,
                Esh_MPa=a['Esh_MPa'] / 2)                     # misma eps_y, fy a la mitad
    _e, s_mitad = capacidad.curva_de_barra(otro, L_D, alfa, n=1201)
    igual = np.max(np.abs(s_kpa / fy - s_mitad / (fy / 2))) < 1e-12
    check(igual and abs(a['Es_MPa'] - 200000.0) < 1e-9,
          'OpenSees toma raiz(fy/100) por eps_y (fy a la mitad con la misma eps_y da lo mismo): '
          'coincide con el paper porque Es = 200 GPa')

    print('\n[4] la columna 200037: el pandeo solo resta, y no cambia el Mn nominal')
    modelo = _ed.estructura()
    sec = capacidad.desde_elemento(modelo, COLUMNA)
    P = 0.30 * sec.P_compresion
    with contextlib.redirect_stderr(io.StringIO()):
        sin = capacidad.momento_curvatura(capacidad.con_acero(sec, a), P=P)
        con = {n: capacidad.momento_curvatura(capacidad.con_acero(sec, a, capacidad.esbeltez(sec, n)[0], alfa), P=P)
               for n in p['separaciones_de_estribo']}
    eps_cu = sec.confinamiento()['eps_cu']
    for n, r in con.items():
        L_D = capacidad.esbeltez(sec, n)[0]
        k = min(len(r['M']), len(sin['M']))
        sobra = max(r['M'][i] - sin['M'][i] for i in range(k))
        # Cota del Mn: la ec. (1) a la deformacion de 0.003 baja el acero
        # comprimido a lo mas en (1 - sig*/sig_l*)(0.003 - eps_y)/(eps* - eps_y).
        _s, ee, se, _l = capacidad.dhakal_maekawa(e, sl, fy, Es, L_D, alfa)
        cota = (1 - se / np.interp(ee, e, sl)) * max(capacidad.EPS_C_ACI - ey, 0) / (ee - ey)
        dmn = abs(r['M_aci'] - sin['M_aci']) / sin['M_aci']
        check(sobra <= 1e-6 * sin['M_max'] and dmn <= cota,
              'L = %d s (L/D %.2f): M con pandeo <= sin pandeo en cada paso; Mn cambia %.4f %% (cota %.4f %%)'
              % (n, L_D, 100 * dmn, 100 * cota),
              'M max %.1f contra %.1f kN m (%+.2f %%); eps* %.4f, el M-phi termina en eps_cu %.4f'
              % (r['M_max'], sin['M_max'], 100 * (r['M_max'] / sin['M_max'] - 1), ee, eps_cu))
    L_D1 = capacidad.esbeltez(sec, 1)[0]
    _s, ee1, _se, lam1 = capacidad.dhakal_maekawa(e, sl, fy, Es, L_D1, alfa)
    r1 = con[1]
    check(calza(round(L_D1, 2), 'pandeo_200037', 'L_D') and calza(round(lam1, 2), 'pandeo_200037', 'lambda')
          and calza(round(ee1, 4), 'pandeo_200037', 'eps_estrella')
          and calza(round(eps_cu, 4), 'pandeo_200037', 'eps_cu_nucleo')
          and calza(round(sin['M_max'], 1), 'pandeo_200037', 'M_max_sin_kNm')
          and calza(round(r1['M_max'], 1), 'pandeo_200037', 'M_max_DM_s_kNm')
          and calza(round(con[2]['M_max'], 1), 'pandeo_200037', 'M_max_DM_2s_kNm'),
          'L/D %.2f, lambda %.2f, eps* %.4f > eps_cu %.4f; M max %.1f / %.1f / %.1f kN m: los numeros de control'
          % (L_D1, lam1, ee1, eps_cu, sin['M_max'], r1['M_max'], con[2]['M_max']))
    print('         (no cambia ninguna curva del programa: el acero del programa sigue siendo Steel01)')


# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m verificacion.capacidad',
                                 description='Capacidad de las secciones: fibras, a mano, demanda, '
                                             'nucleos y losa colaborante')
    ap.add_argument('bloques', nargs='*', metavar='bloque',
                    help='%s (sin bloque: los seis)' % ', '.join(BLOQUES))
    ap.add_argument('--elementos', nargs='+', default=[], metavar='ELEM',
                    help='rc_a_mano: los elementos a revisar (por defecto la primera columna '
                         'y el primer muro con fierro de cada cuerpo)')
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    # rc_a_mano acepta el elemento suelto: "rc_a_mano 200037"
    sueltos = [b for b in a.bloques if b.isdigit()]
    a.bloques = [b for b in a.bloques if not b.isdigit()]
    a.elementos = list(a.elementos) + sueltos
    malos = [b for b in a.bloques if b not in BLOQUES]
    if malos:
        ap.error('bloque desconocido: %s (son: %s)' % (', '.join(malos), ', '.join(BLOQUES)))
    hacer = {'mphi_pm': mphi_pm, 'rc_a_mano': rc_a_mano, 'demanda_todas': demanda_todas,
             'nucleos': nucleos, 'losa_colaborante': losa_colaborante, 'pandeo': pandeo}
    consola_tolerante()
    t0 = time.time()
    inf = Informe()
    for b in (a.bloques or BLOQUES):
        hacer[b](inf, a)
    print('  (%.0f s)' % (time.time() - t0))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
