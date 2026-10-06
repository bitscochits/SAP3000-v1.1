# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/capacidad.py  -  QUE AGUANTA UNA SECCION
================================================================
 Momento-curvatura y curva de interaccion P-M de una seccion de
 hormigon armado, con Fiber Section de OpenSees.

 Correr:
   python sap.py revisar capacidad 200037          una columna del LT2
   python sap.py revisar capacidad 200009          un muro
   python sap.py revisar capacidad 200037 --pm     ademas su curva P-M, interpretada
   python sap.py revisar capacidad 200037 --mphi   el grafico M-phi a varios axiales
   python sap.py revisar capacidad 200037 --dibujo la discretizacion, dibujada
   python sap.py revisar capacidad 200037 --sensibilidad

 Sirve para los dos: una columna es una seccion cuadrada con
 armadura perimetral y un muro una seccion muy alargada con malla
 repartida mas barras en las puntas. Lo que cambia es como se arman
 las fibras, no el analisis. Ver _seccion_de_muro().

 ----------------------------------------------------------------
 UNA SOLA DEFINICION DE LA SECCION
 ----------------------------------------------------------------
 El M-phi y la P-M salen del MISMO objeto de fibras. Es la razon de
 que la P-M se calcule corriendo un M-phi por cada nivel de carga
 axial y quedarse con el momento maximo, en vez de integrar aparte
 con una ley escrita a mano en Python.

 Integrar aparte es mas rapido, pero deja dos definiciones de la
 misma seccion que hay que mantener sincronizadas: distinta
 discretizacion, distinta ley del hormigon, distinto numero de
 barras. Cuando se separan, el M-phi y la P-M dejan de ser de la
 misma columna y nadie lo nota, porque los dos graficos siguen
 saliendo con forma razonable.

 Ademas asi el punto de la P-M tiene una definicion que se puede
 explicar en una frase: es el momento maximo que alcanza la seccion
 con esa compresion.

 ----------------------------------------------------------------
 DE DONDE SALE CADA NUMERO
 ----------------------------------------------------------------
 La seccion se lee del modelo, no se escribe aca:

     b, h            de la seccion del elemento    (edificio.json)
     f'c             de la seccion (fpc_MPa: cada cuerpo trae el suyo,
                     G35 el LT2 y G28 el antiguo); si no, del material
     estribo, trabas de la elevacion del plano     (enfierradura del
                                                    elemento, con su origen)
     n de barras     deducido del estribo          (una traba amarra
                                                    una barra)
     diametro        SUPUESTO, declarado en supuestos del edificio

 El confinamiento NO es un numero puesto a mano: sale del estribo
 que trae el elemento, con Mander. Por eso las dos familias de
 columnas del LT2 -- las de 3 trabas y las de 4 -- dan curvas
 distintas, que es justamente lo que hay que poder mostrar.

 ----------------------------------------------------------------
 UNIDADES
 ----------------------------------------------------------------
 Todo en m, kN, kPa, como el resto del proyecto. f'c = 35 MPa son
 35000 kPa. Los momentos salen en kN*m y las curvaturas en 1/m.
================================================================
"""
from __future__ import annotations

import copy
import math
import os
import sys

from calculo import edificio as _ed
from calculo import rutas

# --- discretizacion por defecto -------------------------------
# Fibras a lo alto del nucleo. 20 basta: la sensibilidad esta
# verificada en sensibilidad_discretizacion() y entre 20 y 40 el
# momento maximo cambia menos de 0.5%.
FIBRAS_NUCLEO = 20
FIBRAS_RECUBRIMIENTO = 4

# --- deformaciones caracteristicas ----------------------------
EPS_C0 = 0.002          # hormigon no confinado, peak
EPS_CU_RECUBRIMIENTO = 0.004
EPS_SU = 0.10           # rotura del acero (A630-420H, alargamiento)

# Deformacion ultima del hormigon que usa ACI 318 para definir la
# resistencia NOMINAL de la seccion. No es la deformacion a la que la
# seccion se rompe -- con el nucleo confinado llega mucho mas lejos --
# sino la convencion con la que se calcula a mano y con la que estan
# hechas las tablas del curso de hormigon armado.
EPS_C_ACI = 0.003

# ke de Mander para seccion rectangular con estribos y trabas.
# 0.75 es el valor tipico; con muchas trabas sube, con pocas baja.
KE_CONFINAMIENTO = 0.75

# --- analisis -------------------------------------------------
# Paso de curvatura para una seccion de 0.70 m de canto. Para otra
# altura se escala: la curvatura de rotura va como 1/h, asi que un
# muro de 7.95 m fluye a curvaturas once veces menores y con el paso
# de la columna la curva sale de diez puntos.
PASO_CURVATURA = 1.0e-4     # 1/m, referido a CANTO_REFERENCIA
CANTO_REFERENCIA = 0.70     # m
PASOS_MAXIMOS = 2500


def paso_para(sec):
    """Paso de curvatura proporcionado al canto de la seccion."""
    return PASO_CURVATURA * CANTO_REFERENCIA / max(sec.h, 0.10)


class Seccion(object):
    """Una seccion de hormigon armado, con todo lo que hace falta."""

    def __init__(self, nombre, b, h, fpc_kPa, barras, recubrimiento,
                 fy_kPa, Es_kPa, endurecimiento, estribo=None,
                 trabas_x=0, trabas_y=0, origen=None):
        self.nombre = nombre
        self.b = float(b)                  # ancho, direccion z local
        self.h = float(h)                  # canto, direccion y local
        self.fpc = float(fpc_kPa)
        self.barras = barras               # [(y, z, area_m2), ...]
        self.rec = float(recubrimiento)
        self.fy = float(fy_kPa)
        self.Es = float(Es_kPa)
        self.endurecimiento = float(endurecimiento)
        self.estribo = estribo or {}
        self.trabas_x = int(trabas_x)
        self.trabas_y = int(trabas_y)
        self.origen = origen or {}

    # --- geometria ---------------------------------------------
    @property
    def Ag(self):
        return self.b * self.h

    @property
    def As(self):
        return sum(a for _y, _z, a in self.barras)

    @property
    def cuantia(self):
        return self.As / self.Ag if self.Ag else 0.0

    @property
    def P_traccion(self):
        """Traccion pura: todo el acero fluye, el hormigon no toma nada."""
        return -self.As * self.fy

    @property
    def P_compresion(self):
        """Compresion pura, el tope teorico:  f'c (Ag - As) + fy As."""
        return self.fpc * (self.Ag - self.As) + self.fy * self.As

    def nucleo(self):
        """(alto, ancho) del nucleo, medido al EJE del estribo."""
        d = self._diametro_estribo()
        return (self.h - 2 * self.rec - d, self.b - 2 * self.rec - d)

    def _diametro_estribo(self):
        return float(self.estribo.get('diametro_mm', 0.0)) / 1000.0

    # --- confinamiento (Mander) --------------------------------
    def confinamiento(self):
        r"""
        Presion de confinamiento y hormigon confinado, por Mander.

        No es un factor puesto a mano: sale del estribo que el plano
        le pone a ESTE elemento. Un pilar con 4 trabas tiene mas
        ramas que uno con 3, mas presion lateral, y por lo tanto mas
        f'cc y mucha mas deformacion ultima. Es la diferencia que se
        tiene que ver entre las dos familias de columnas del LT2.

        Devuelve un dict con todo lo intermedio, para poder mostrarlo
        y para que se pueda revisar a mano.
        """
        d = self._diametro_estribo()
        s = float(self.estribo.get('separacion_cm', 0.0)) / 100.0
        hc, bc = self.nucleo()
        if min(d, s, hc, bc) <= 0:
            return None

        a_barra = math.pi * d ** 2 / 4.0
        # Ramas que cruzan cada direccion: las dos del estribo mas una
        # por cada traba.
        ramas_x = 2 + self.trabas_x
        ramas_y = 2 + self.trabas_y
        Ash_x = ramas_x * a_barra
        Ash_y = ramas_y * a_barra

        rho_x = Ash_x / (s * bc)
        rho_y = Ash_y / (s * hc)
        fl_x = KE_CONFINAMIENTO * rho_x * self.fy
        fl_y = KE_CONFINAMIENTO * rho_y * self.fy
        fl = (fl_x + fl_y) / 2.0

        # Mander para confinamiento igual en las dos direcciones.
        r = fl / self.fpc
        K = -1.254 + 2.254 * math.sqrt(1.0 + 7.94 * r) - 2.0 * r
        fcc = K * self.fpc
        eps_cc = EPS_C0 * (1.0 + 5.0 * (K - 1.0))

        # Deformacion ultima del nucleo (Priestley): el nucleo se
        # rompe cuando se corta el estribo.
        rho_s = rho_x + rho_y
        eps_cu = 0.004 + 1.4 * rho_s * self.fy * EPS_SU / fcc

        return {
            'ramas_x': ramas_x, 'ramas_y': ramas_y,
            'rho_x': rho_x, 'rho_y': rho_y, 'rho_s': rho_s,
            'fl_kPa': fl, 'K': K,
            'fcc_kPa': fcc, 'eps_cc': eps_cc, 'eps_cu': eps_cu,
            'nucleo_m': (hc, bc), 'separacion_m': s,
        }

    def resumen(self):
        c = self.confinamiento()
        L = ['%s   %.2f x %.2f m' % (self.nombre, self.b, self.h),
             '  hormigon   f\'c = %.1f MPa' % (self.fpc / 1000.0),
             '  acero      fy  = %.0f MPa, Es = %.0f GPa'
             % (self.fy / 1000.0, self.Es / 1e6),
             '  refuerzo   %d barras, As = %.2f cm2, cuantia = %.2f %%'
             % (len(self.barras), self.As * 1e4, 100 * self.cuantia),
             '  estribo    %s' % (self.estribo.get('texto', '(sin dato)')),
             '  trabas     %d en x, %d en y' % (self.trabas_x, self.trabas_y)]
        if c:
            L.append('  confinado  f\'cc = %.1f MPa (K = %.3f), '
                     'eps_cc = %.5f, eps_cu = %.5f'
                     % (c['fcc_kPa'] / 1000.0, c['K'], c['eps_cc'],
                        c['eps_cu']))
        return '\n'.join(L)


# ============================================================
# LEER LA SECCION DESDE EL MODELO
# ============================================================
def desde_elemento(modelo, elemento_id):
    """
    La seccion del elemento tal como la describe el modelo, con la
    enfierradura que se le pego en la etapa de armado.

    Falla con un mensaje explicito si el elemento no trae fierro: una
    seccion de hormigon armado sin armadura no es una seccion con
    armadura cero, es un dato que falta.
    """
    elementos = {int(e['id']): e for e in modelo['elementos']}
    if int(elemento_id) not in elementos:
        raise SystemExit('el elemento %s no existe en el modelo'
                         % elemento_id)
    e = elementos[int(elemento_id)]

    fe = e.get('enfierradura')
    if not fe:
        raise SystemExit(
            'el elemento %s (%s) no trae enfierradura.\n'
            'El fierro viaja en el elemento (enfierradura) de entrada/edificio.json, '
            'leido de la elevacion del plano; no todos los muros la tienen.'
            % (elemento_id, e.get('tipo')))

    if fe.get('tipo') == 'muro':
        return _seccion_de_muro(modelo, e, fe, elemento_id)

    secciones = {s['nombre']: s for s in modelo['secciones']}
    s = secciones.get(e.get('seccion'))
    if not s:
        raise SystemExit('el elemento %s usa la seccion %r, que no esta '
                         'declarada' % (elemento_id, e.get('seccion')))

    b, h = float(s['b']), float(s['h'])
    fpc = _fpc_kPa(modelo, s)
    acero = fe.get('acero') or {}
    fy = float(acero.get('fy_MPa', 420.0)) * 1000.0
    Es = float(acero.get('Es_MPa', 200000.0)) * 1000.0
    endur = float(acero.get('endurecimiento', 0.01))

    lon = fe['longitudinal']
    rec = float(fe.get('recubrimiento_m', 0.04))
    d_estribo = float((fe.get('estribo') or {}).get('diametro_mm', 0)) / 1000.0
    d_barra = float(lon['diametro_mm']) / 1000.0
    barras = _perimetral(b, h, rec + d_estribo + d_barra / 2.0,
                         int(lon['por_cara']), d_barra)

    trabas = sum(t['cantidad'] for t in (fe.get('trabas') or []))
    trabas_l = sum(t['cantidad'] for t in (fe.get('trabas_longitudinales') or []))

    return Seccion(
        nombre='%s (elem %s)' % (e['seccion'], elemento_id),
        b=b, h=h, fpc_kPa=fpc, barras=barras, recubrimiento=rec,
        fy_kPa=fy, Es_kPa=Es, endurecimiento=endur,
        estribo=fe.get('estribo'), trabas_x=trabas, trabas_y=trabas_l,
        origen=fe.get('fuente') or {})


def _fpc_kPa(modelo, seccion):
    """
    El f'c de la seccion, en kPa. Lo trae la seccion cuando el modelo
    junta cuerpos de hormigones distintos -- el conjunto: LT2 G35 e
    Ingenieria G28 --; si no, es el del material del modelo.
    """
    propio = (seccion or {}).get('fpc_MPa')
    return float(propio or modelo['material']['fpc_MPa']) * 1000.0


def _seccion_de_muro(modelo, e, fe, elemento_id, recubrimiento=0.03):
    r"""
    La seccion de un muro, para flexion EN SU PLANO.

    h es el LARGO del muro (ahi flecta bajo sismo) y b el espesor: un
    M 0.25x7.95 es una seccion de 25 cm de ancho y 7.95 m de canto. Solo
    la direccion principal, que es la que se compara.

    Dos familias de fierro: la MALLA en dos cortinas ('D.M.'), repartida
    y con poco brazo; y las BARRAS DE BORDE en las puntas, en la posicion
    que el plano les da, que son las que mandan. El hormigon va SIN
    confinar -- el alma no tiene estribos y el confinamiento de las
    puntas no esta asociado muro por muro -- asi que la capacidad queda
    del lado seguro.
    """
    secciones = {s['nombre']: s for s in modelo['secciones']}
    s = secciones.get(e.get('seccion'))
    t = float(fe.get('espesor_m') or (s and s['b']) or 0.0)
    L = float(fe.get('largo_m') or (s and s['h']) or 0.0)
    fpc = _fpc_kPa(modelo, s)

    mv = fe.get('malla_vertical') or {}
    capas = int(fe.get('capas', 2))
    barras = []

    # --- la malla, repartida a lo largo del muro ---
    d_malla = float(mv.get('diametro_mm', 0.0)) / 1000.0
    sep = float(mv.get('separacion_cm', 0.0)) / 100.0
    z_capa = max(t / 2.0 - recubrimiento - d_malla / 2.0, 0.0)
    if d_malla > 0 and sep > 0:
        a = math.pi * d_malla ** 2 / 4.0
        n = int(L / sep)
        for i in range(n + 1):
            y = -L / 2.0 + i * sep
            if abs(y) > L / 2.0:
                continue
            for z in ((-z_capa, z_capa) if capas >= 2 else (0.0,)):
                barras.append((y, z, a))

    # --- las barras de borde, en su sitio ---
    for b in fe.get('barras_de_borde') or []:
        d = float(b['diametro_mm']) / 1000.0
        a = math.pi * d ** 2 / 4.0
        y = max(-L / 2.0, min(L / 2.0, float(b['s'])))
        n = int(b.get('cantidad', 1))
        # Repartidas entre las dos cortinas, como van en la punta.
        for k in range(n):
            z = z_capa if k % 2 == 0 else -z_capa
            barras.append((y, z, a))

    acero = {'fy_MPa': 420.0, 'Es_MPa': 200000.0, 'endurecimiento': 0.01}
    return Seccion(
        nombre='%s (muro, elem %s)' % (e['seccion'], elemento_id),
        b=t, h=L, fpc_kPa=fpc, barras=barras, recubrimiento=recubrimiento,
        fy_kPa=acero['fy_MPa'] * 1000.0, Es_kPa=acero['Es_MPa'] * 1000.0,
        endurecimiento=acero['endurecimiento'],
        estribo=None, trabas_x=0, trabas_y=0,
        origen=dict(fe.get('fuente') or {},
                    malla=mv.get('texto'),
                    barras_de_borde=len(fe.get('barras_de_borde') or [])))


def _perimetral(b, h, d, por_cara, diam):
    """
    Barras repartidas en el perimetro, `por_cara` en cada lado,
    contando las esquinas una sola vez. `d` es la distancia del borde
    al CENTRO de la barra.

    (y, z) con y hacia el canto h y z hacia el ancho b, que es la
    convencion de fibras de OpenSees.
    """
    a = math.pi * diam ** 2 / 4.0
    y0, z0 = h / 2.0 - d, b / 2.0 - d
    n = max(int(por_cara), 2)
    ys = [-y0 + 2 * y0 * i / (n - 1) for i in range(n)]
    zs = [-z0 + 2 * z0 * i / (n - 1) for i in range(n)]
    puntos = set()
    for y in (ys[0], ys[-1]):
        for z in zs:
            puntos.add((round(y, 6), round(z, 6)))
    for z in (zs[0], zs[-1]):
        for y in ys:
            puntos.add((round(y, 6), round(z, 6)))
    return [(y, z, a) for y, z in sorted(puntos)]


# ============================================================
# LA SECCION EN OPENSEES
# ============================================================
def parches(sec, nf=FIBRAS_NUCLEO):
    r"""
    Como se corta la seccion en fibras. Devuelve los rectangulos con
    su material y su subdivision.

    ----------------------------------------------------------------
    UNA SOLA DEFINICION, OTRA VEZ
    ----------------------------------------------------------------
    Esto existe para que el DIBUJO de la discretizacion y lo que se le
    manda a OpenSees salgan de la misma funcion. Dibujar la seccion
    por separado seria volver a tener dos descripciones del mismo
    objeto -- el error que este modulo evita a proposito entre el
    M-phi y la P-M -- solo que esta vez la que mienta seria la figura
    del informe, que es peor: se ve bien y nadie la comprueba.

    material 1 = nucleo confinado, 2 = recubrimiento sin confinar.
    """
    hc, bc = sec.nucleo()
    yc, zc = hc / 2.0, bc / 2.0
    nr = FIBRAS_RECUBRIMIENTO
    H, B = sec.h / 2.0, sec.b / 2.0
    return [
        {'material': 1, 'ny': nf, 'nz': nf,
         'y0': -yc, 'z0': -zc, 'y1': yc, 'z1': zc, 'que': 'nucleo confinado'},
        {'material': 2, 'ny': nr, 'nz': nf,
         'y0': -H, 'z0': -zc, 'y1': -yc, 'z1': zc, 'que': 'recubrimiento'},
        {'material': 2, 'ny': nr, 'nz': nf,
         'y0': yc, 'z0': -zc, 'y1': H, 'z1': zc, 'que': 'recubrimiento'},
        {'material': 2, 'ny': nf + 2 * nr, 'nz': nr,
         'y0': -H, 'z0': -B, 'y1': H, 'z1': -zc, 'que': 'recubrimiento'},
        {'material': 2, 'ny': nf + 2 * nr, 'nz': nr,
         'y0': -H, 'z0': zc, 'y1': H, 'z1': B, 'que': 'recubrimiento'},
    ]


def dibujar(sec, destino, nf=FIBRAS_NUCLEO):
    """
    La seccion como la ve OpenSees: cada fibra, su material y cada
    barra en su sitio. Es lo que pide el enunciado -- discretizacion,
    materiales, refuerzo -- y sale de parches(), o sea de lo mismo que
    se resuelve.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Circle

    conf = sec.confinamiento()
    colores = {1: '#b8c7d9', 2: '#e6d3b3'}
    fig, ax = plt.subplots(figsize=(7.2, 7.2 * min(3.0, max(sec.h / sec.b,
                                                            0.4))))
    n_fibras = 0
    for p in parches(sec, nf):
        dy = (p['y1'] - p['y0']) / p['ny']
        dz = (p['z1'] - p['z0']) / p['nz']
        n_fibras += p['ny'] * p['nz']
        for i in range(p['ny']):
            for j in range(p['nz']):
                ax.add_patch(Rectangle(
                    (p['z0'] + j * dz, p['y0'] + i * dy), dz, dy,
                    facecolor=colores[p['material']],
                    edgecolor='white', linewidth=0.25))

    for y, z, a in sec.barras:
        r = math.sqrt(a / math.pi)
        ax.add_patch(Circle((z, y), r, facecolor='#8b1a1a',
                            edgecolor='black', linewidth=0.5, zorder=4))

    ax.add_patch(Rectangle((-sec.b / 2, -sec.h / 2), sec.b, sec.h,
                           fill=False, edgecolor='black', linewidth=1.4))
    ax.set_xlim(-sec.b / 2 * 1.12, sec.b / 2 * 1.12)
    ax.set_ylim(-sec.h / 2 * 1.06, sec.h / 2 * 1.06)
    ax.set_aspect('equal')
    ax.set_xlabel('z [m]   (ancho b = %.2f m)' % sec.b)
    ax.set_ylabel('y [m]   (canto h = %.2f m)  -- comprimido arriba' % sec.h)

    d_bar = 2 * math.sqrt(sec.barras[0][2] / math.pi) * 1000 if sec.barras else 0
    lineas = [
        '%s' % sec.nombre,
        '%d fibras de hormigon en %d parches' % (n_fibras, len(parches(sec, nf))),
        '%d barras, D%.0f, As = %.1f cm2, cuantia %.2f %%'
        % (len(sec.barras), d_bar, sec.As * 1e4, 100 * sec.cuantia),
    ]
    if conf:
        lineas.append("nucleo confinado  f'cc = %.1f MPa  (Mander, K = %.3f)"
                      % (conf['fcc_kPa'] / 1000.0, conf['K']))
        lineas.append("recubrimiento     f'c  = %.1f MPa, sin confinar"
                      % (sec.fpc / 1000.0))
    else:
        lineas.append("hormigon  f'c = %.1f MPa, SIN confinar"
                      % (sec.fpc / 1000.0))
    lineas.append('acero  fy = %.0f MPa, Es = %.0f GPa, endurecimiento %.0f %%'
                  % (sec.fy / 1000.0, sec.Es / 1e6,
                     100 * sec.endurecimiento))
    ax.set_title(chr(10).join(lineas), fontsize=9, loc='left')
    fig.tight_layout()
    fig.savefig(destino, dpi=150)
    plt.close(fig)
    return destino


def dibujar_momento_curvatura(sec, destino, niveles_kN, nf=FIBRAS_NUCLEO):
    r"""
    Las curvas M-phi de la seccion para varios niveles de compresion,
    en un solo grafico. Es el grafico que pide el enunciado, y la forma
    mas directa de MOSTRAR por que P cambia la capacidad a momento: con
    P = 0 la seccion es ductil y llega a poco momento; con mas
    compresion el momento sube pero la curva se acaba antes, porque el
    hormigon llega a su deformacion ultima con menos curvatura.

    `niveles_kN` son las compresiones a graficar. Quien llama decide:
    el CLI usa fracciones de la compresion pura; demanda_capacidad.py
    puede pasar los axiales que la demanda le pone a esa columna.

    El punto marcado sobre cada curva es el hormigon a 0.003: la
    capacidad NOMINAL, la que se compara con un calculo a mano.

    Devuelve las curvas, para que quien llama pueda imprimir numeros.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    Pc = sec.P_compresion
    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    curvas = []
    for P in niveles_kN:
        r = momento_curvatura(sec, P=P, nf=nf)
        if not r['M']:
            continue
        curvas.append(r)
        etiqueta = 'P = %.0f kN  (%.0f %% de la compresion pura)' % (
            P, 100.0 * P / Pc if Pc else 0.0)
        linea, = ax.plot(r['phi'], r['M'], lw=1.8, label=etiqueta)
        if r['M_aci'] is not None:
            ax.plot([r['phi_aci']], [r['M_aci']], 'o', ms=6,
                    color=linea.get_color(), markeredgecolor='black',
                    zorder=5)

    ax.set_xlabel('curvatura phi [1/m]')
    ax.set_ylabel('momento M [kN m]')
    ax.set_title('%s\nmomento-curvatura segun la compresion axial. '
                 'El punto es el hormigon a 0.003 (capacidad nominal).'
                 % sec.nombre, fontsize=9, loc='left')
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(destino, dpi=150)
    plt.close(fig)
    return curvas


def _armar(sec, nf=FIBRAS_NUCLEO):
    """
    Deja construida en OpenSees la Fiber Section (tag 1) y devuelve
    los tags de material. Modelo 2D: ndm=2, ndf=3.

    Tres materiales, no uno:
      1  hormigon CONFINADO      el nucleo, dentro del estribo
      2  hormigon NO confinado   el recubrimiento, que se pierde antes
      3  acero
    """
    import openseespy.opensees as ops
    conf = sec.confinamiento()
    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)

    if conf:
        ops.uniaxialMaterial('Concrete01', 1, -conf['fcc_kPa'],
                             -conf['eps_cc'], -0.25 * conf['fcc_kPa'],
                             -conf['eps_cu'])
    else:
        ops.uniaxialMaterial('Concrete01', 1, -sec.fpc, -EPS_C0,
                             -0.2 * sec.fpc, -EPS_CU_RECUBRIMIENTO)
    ops.uniaxialMaterial('Concrete01', 2, -sec.fpc, -EPS_C0,
                         0.0, -EPS_CU_RECUBRIMIENTO)
    ops.uniaxialMaterial('Steel01', 3, sec.fy, sec.Es, sec.endurecimiento)

    ops.section('Fiber', 1, '-GJ', 1.0e8)
    for p in parches(sec, nf):
        ops.patch('rect', p['material'], p['ny'], p['nz'],
                  p['y0'], p['z0'], p['y1'], p['z1'])
    for y, z, a in sec.barras:
        ops.fiber(y, z, a, 3)
    return conf


def momento_curvatura(sec, P=0.0, nf=FIBRAS_NUCLEO,
                      paso=None, pasos=PASOS_MAXIMOS):
    r"""
    Curva momento-curvatura para una compresion axial P (kN, positiva en
    COMPRESION).

    Un zeroLengthSection entre dos nodos en el mismo punto: el GDL 3 es
    la curvatura y su fuerza el momento. La axial se aplica primero y se
    deja constante (loadConst) mientras se impone la curvatura.

    TERMINO. Manda el material, no el numero de pasos: se corta cuando
    la fibra mas comprimida del nucleo llega a eps_cu (Mander, desde el
    estribo real) o la barra mas traccionada a eps_su, leyendo 'section
    deformation' -> eps(y) = eps_axial - curvatura*y. Tambien si deja de
    converger o el momento cae bajo el 80% del maximo, y el motivo queda
    en el resultado. Se devuelve ademas M_aci, el momento cuando el
    hormigon llega a 0.003: la capacidad NOMINAL con la que se compara el
    calculo a mano, siempre menor que el maximo.
    """
    import openseespy.opensees as ops
    if paso is None:
        paso = paso_para(sec)
    conf = _armar(sec, nf)

    ops.node(1, 0.0, 0.0)
    ops.node(2, 0.0, 0.0)
    ops.fix(1, 1, 1, 1)
    ops.fix(2, 0, 1, 0)
    ops.element('zeroLengthSection', 1, 1, 2, 1)

    # --- 1. la axial, y se deja constante ---
    if abs(P) > 1e-9:
        ops.timeSeries('Constant', 1)
        ops.pattern('Plain', 1, 1)
        ops.load(2, -float(P), 0.0, 0.0)     # negativo = compresion
        ops.system('BandGeneral')
        ops.numberer('Plain')
        ops.constraints('Plain')
        ops.test('NormDispIncr', 1.0e-8, 20, 0)
        ops.algorithm('Newton')
        ops.integrator('LoadControl', 0.1)
        ops.analysis('Static')
        if ops.analyze(10) != 0:
            return {'P_kN': P, 'phi': [], 'M': [], 'motivo': 'no converge la axial'}
        ops.loadConst('-time', 0.0)

    # --- 2. la curvatura, en control de desplazamiento ---
    # wipeAnalysis borra el analisis de la axial. Sin esto OpenSees
    # avisa "can't set handler after analysis is created" y se queda
    # con el integrador anterior: la curvatura no se impondria.
    ops.wipeAnalysis()
    ops.timeSeries('Linear', 2)
    ops.pattern('Plain', 2, 2)
    ops.load(2, 0.0, 0.0, 1.0)
    ops.system('BandGeneral')
    ops.numberer('Plain')
    ops.constraints('Plain')
    ops.test('NormDispIncr', 1.0e-8, 20, 0)
    ops.algorithm('Newton')
    ops.integrator('DisplacementControl', 2, 3, paso)
    ops.analysis('Static')

    # Fibras extremas: la del nucleo mas comprimida y la barra mas
    # traccionada. Sus deformaciones son las que deciden el final.
    hc, _bc = sec.nucleo()
    y_nucleo = hc / 2.0
    y_barra = max(abs(y) for y, _z, _a in sec.barras) if sec.barras else 0.0
    eps_cu = conf['eps_cu'] if conf else EPS_CU_RECUBRIMIENTO

    phi, M, motivo = [0.0], [0.0], 'se llego al maximo de pasos'
    eps_c = eps_s = 0.0
    M_aci = phi_aci = None
    for _ in range(pasos):
        if ops.analyze(1) != 0:
            # Newton se atasca justo en el peak del hormigon, donde la
            # rigidez tangente pasa por cero. Antes de darse por
            # vencido se prueba con la matriz inicial y pasos chicos,
            # que es lento pero atraviesa el punto.
            ops.algorithm('ModifiedNewton', '-initial')
            ops.integrator('DisplacementControl', 2, 3, paso / 10.0)
            rescatado = ops.analyze(10) == 0
            ops.algorithm('Newton')
            ops.integrator('DisplacementControl', 2, 3, paso)
            if not rescatado:
                motivo = 'el analisis dejo de converger'
                break
        c = ops.nodeDisp(2, 3)
        m = abs(ops.eleResponse(1, 'section', 'force')[1])
        phi.append(c)
        M.append(m)

        d = ops.eleResponse(1, 'section', 'deformation')
        eps_axial, kappa = float(d[0]), float(d[1])
        eps_c = eps_axial - kappa * y_nucleo      # la mas comprimida
        eps_s = eps_axial + kappa * y_barra       # la mas traccionada
        # El momento cuando el hormigon llega a 0.003: la capacidad
        # NOMINAL, la que se puede contrastar con un calculo a mano.
        if M_aci is None and -eps_c >= EPS_C_ACI:
            M_aci, phi_aci = m, c

        if -eps_c >= eps_cu:
            motivo = ('el nucleo llego a eps_cu = %.5f (se corta el estribo)'
                      % eps_cu)
            break
        if eps_s >= EPS_SU:
            motivo = 'la barra traccionada llego a eps_su = %.3f' % EPS_SU
            break
        if m < 0.8 * max(M):
            motivo = 'el momento cayo bajo el 80% del maximo'
            break

    # Rigidez inicial: la pendiente del primer tramo, antes de que
    # fisure. Se mide sobre los primeros pasos y no sobre el primero
    # solo, que es ruido numerico.
    k = 0.0
    if len(phi) > 4 and phi[4] > 0:
        k = M[4] / phi[4]

    return {
        'P_kN': float(P),
        'phi': phi, 'M': M,
        'M_max': max(M) if M else 0.0,
        'phi_en_M_max': phi[M.index(max(M))] if M else 0.0,
        # Capacidad NOMINAL, con la convencion de ACI: el momento
        # cuando la fibra de hormigon mas comprimida llega a 0.003.
        # Es SIEMPRE menor que M_max, porque despues de ese punto el
        # nucleo confinado sigue tomando carga y el acero endurece.
        'M_aci': M_aci, 'phi_aci': phi_aci,
        'rigidez_inicial_kNm2': k,
        'motivo_termino': motivo,
        'eps_hormigon_final': eps_c,
        'eps_acero_final': eps_s,
        'n_puntos': len(phi),
        'fibras': nf,
        'confinamiento': conf,
    }


def interaccion(sec, niveles=None, nf=FIBRAS_NUCLEO, paso=None):
    r"""
    Curva de interaccion P-M. Cada punto es el momento MAXIMO que la
    seccion alcanza con esa compresion, sacado de su propio M-phi.

    ----------------------------------------------------------------
    LOS DOS EXTREMOS
    ----------------------------------------------------------------
    Traccion pura   P = -As*fy,   M = 0
                    todo el acero fluye en traccion, el hormigon no
                    aporta (Concrete01 no tiene resistencia a
                    traccion)

    Compresion pura P = f'c*(Ag-As) + fy*As,   M = 0
                    sin excentricidad no hay momento; es el tope
                    teorico, mayor que el que admitiria una norma,
                    que lo recorta por excentricidad minima

    Entre medio, cada punto sale de una corrida. Subiendo P el
    momento primero CRECE -- la compresion cierra las fisuras y
    retrasa la fluencia del acero traccionado -- hasta el punto
    BALANCEADO, y despues cae, porque el hormigon se aplasta antes de
    que el acero llegue a fluir. Esa nariz es la respuesta a "por que
    P cambia la capacidad a momento".
    """
    P_traccion = sec.P_traccion
    P_compresion = sec.P_compresion

    if niveles is None:
        # Mas densos abajo, que es donde esta la nariz.
        niveles = [P_compresion * f for f in
                   (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40,
                    0.50, 0.65, 0.80)]

    # LOS DOS SENTIDOS DEL MOMENTO
    # Una seccion con el fierro descentrado -- los muros del LT2 lo
    # estan -- tiene DOS capacidades, una por sentido, y el sismo va en
    # los dos. La demanda se compara con |M| (demanda_capacidad.demanda),
    # asi que la capacidad honesta es el MINIMO de las dos. Informar
    # solo la directa es optimista en un tercio de las filas de muro.
    # Si el fierro es simetrico las dos corridas dan lo mismo y la
    # segunda no se hace (es la mitad del tiempo de las 54 familias).
    otra = None if fierro_simetrico(sec) else espejo(sec)

    puntos = [{'P_kN': P_traccion, 'M_kNm': 0.0, 'de': 'traccion pura',
               'sentido': 'los dos'}]
    for P in niveles:
        r = momento_curvatura(sec, P=P, nf=nf, paso=paso)
        if not r['M']:
            continue
        M = r['M_aci'] if r['M_aci'] else r['M_max']
        sentido = 'los dos' if otra is None else 'directo'
        if otra is not None:
            r2 = momento_curvatura(otra, P=P, nf=nf, paso=paso)
            M2 = (r2['M_aci'] if r2['M_aci'] else r2['M_max']) if r2['M'] else None
            if M2 is not None and M2 < M:
                r, M, sentido = r2, M2, 'espejado'
        puntos.append({
            'P_kN': float(P),
            'M_kNm': M,
            'M_max_kNm': r['M_max'],
            'phi_kNm': r['phi_aci'] or r['phi_en_M_max'],
            'de': ('hormigon a 0.003 (nominal)' if r['M_aci']
                   else 'maximo del M-phi'),
            'motivo': r['motivo_termino'],
            'sentido': sentido,
        })
    puntos.append({'P_kN': P_compresion, 'M_kNm': 0.0,
                   'de': 'compresion pura', 'sentido': 'los dos'})
    return puntos


def interpretar(puntos, sec):
    """
    La curva P-M explicada con los numeros de ESTA seccion. Es lo que
    el enunciado pide despues de los primeros puntos: 'Interprete'.
    Devuelve lineas de texto listas para imprimir.
    """
    nariz = max(puntos, key=lambda p: p['M_kNm'])
    flexion = min((p for p in puntos if abs(p['P_kN']) < 1e-6),
                  key=lambda p: abs(p['P_kN']), default=None)
    L = [
        'Traccion pura: P = %.0f kN, M = 0. Es As*fy = %.2f cm2 x %.0f MPa:'
        % (sec.P_traccion, sec.As * 1e4, sec.fy / 1000.0),
        '  solo el acero; el hormigon no toma traccion.',
        'Compresion pura: P = %.0f kN, M = 0. Sin excentricidad no hay'
        % sec.P_compresion,
        '  momento; es el tope teorico, f\'c (Ag - As) + fy As.',
        'Entre medio el momento primero SUBE con P -- la compresion cierra',
        '  las fisuras y retrasa la fluencia del acero traccionado -- hasta',
        '  la nariz, en P = %.0f kN con M = %.0f kN m, y despues BAJA: con'
        % (nariz['P_kN'], nariz['M_kNm']),
        '  mas compresion el hormigon se aplasta antes de que el acero',
        '  llegue a fluir.',
        'Por eso la seccion no tiene "un" momento resistente: tiene uno',
        '  por cada nivel de carga axial, y la demanda hay que compararla',
        '  contra el que corresponde a SU compresion.',
    ]
    if flexion and flexion['M_kNm'] > 0:
        L.append('Con P = 0 (flexion pura) admite %.0f kN m; en la nariz, %.0f:'
                 % (flexion['M_kNm'], nariz['M_kNm']))
        L.append('  %.1f veces mas, solo por la compresion que la acompana.'
                 % (nariz['M_kNm'] / flexion['M_kNm']))
    return L


def sensibilidad_discretizacion(sec, P=0.0, cuantas=(8, 12, 20, 30, 40)):
    """
    Cuanto cambia el momento maximo al refinar las fibras. Es la
    verificacion de que 20 fibras alcanzan: si el resultado todavia se
    mueve, la discretizacion manda sobre la respuesta y el numero no
    es de la seccion, es del mallado.
    """
    salida = []
    for nf in cuantas:
        r = momento_curvatura(sec, P=P, nf=nf)
        salida.append({'fibras': nf, 'M_max': r['M_max'],
                       'rigidez_inicial': r['rigidez_inicial_kNm2']})
    if salida:
        ref = salida[-1]['M_max']
        for s in salida:
            s['error_vs_mas_fino'] = (abs(s['M_max'] - ref) / ref
                                      if ref else 0.0)
    return salida


# ============================================================
def main(argv):
    if not argv:
        print(__doc__)
        return 1
    elem = argv[0] if argv and not argv[0].startswith('--') else None
    if elem is None:
        modelo = _ed.estructura()
        cols = [e['id'] for e in modelo['elementos'] if 'enfierradura' in e]
        print('Elementos con enfierradura: %s' % cols)
        return 0

    modelo = _ed.estructura()
    sec = desde_elemento(modelo, elem)

    print('=' * 68)
    print('  CAPACIDAD DE LA SECCION')
    print('=' * 68)
    print(sec.resumen())
    if sec.origen:
        print('  del plano   %s, %s, eje %s'
              % (sec.origen.get('lamina'), sec.origen.get('elevacion'),
                 sec.origen.get('eje')))

    r = momento_curvatura(sec)
    print()
    print('  M-phi a P = 0')
    print('    %d puntos, M maximo = %.1f kN m en phi = %.5f 1/m'
          % (r['n_puntos'], r['M_max'], r['phi_en_M_max']))
    if r['M_aci']:
        print('    nominal (hormigon a 0.003) = %.1f kN m en phi = %.5f 1/m'
              % (r['M_aci'], r['phi_aci']))
    print('    rigidez inicial = %.0f kN m2' % r['rigidez_inicial_kNm2'])
    print('    termino porque %s' % r['motivo_termino'])
    print('    al final: eps hormigon = %.5f, eps acero = %.5f'
          % (r['eps_hormigon_final'], r['eps_acero_final']))

    if '--pm' in argv:
        pts = interaccion(sec)
        print()
        print('  Curva P-M')
        print('    %10s %12s %12s   %s'
              % ('P [kN]', 'Mn [kN m]', 'M max', 'de'))
        for p in pts:
            print('    %10.1f %12.1f %12.1f   %s'
                  % (p['P_kN'], p['M_kNm'], p.get('M_max_kNm', 0.0), p['de']))
        print()
        for linea in interpretar(pts, sec):
            print('  ' + linea)

    if '--mphi' in argv:
        # Cuatro compresiones, como fraccion del tope: la de P = 0 y tres
        # que suben hasta la mitad. Con eso la nariz de la P-M se ve como
        # cambio de forma en las curvas, no solo como un punto.
        niveles = [sec.P_compresion * f for f in (0.0, 0.15, 0.30, 0.50)]
        destino = os.path.join(rutas.FIGURAS, 'mphi_%s.png' % elem)
        rutas.asegurar(destino)
        curvas = dibujar_momento_curvatura(sec, destino, niveles)
        print()
        print('  M-phi a varios axiales -> %s'
              % os.path.relpath(destino, rutas.RAIZ))
        for r in curvas:
            print('    P = %8.0f kN   M max = %7.1f kN m   nominal = %7s   %s'
                  % (r['P_kN'], r['M_max'],
                     ('%.1f' % r['M_aci']) if r['M_aci'] else '-',
                     r['motivo_termino']))

    if '--dibujo' in argv:
        destino = os.path.join(rutas.FIGURAS, 'fibras_%s.png' % elem)
        rutas.asegurar(destino)
        dibujar(sec, destino)
        print()
        print('  discretizacion -> %s'
              % os.path.relpath(destino, rutas.RAIZ))

    if '--sensibilidad' in argv:
        print()
        print('  Sensibilidad a la discretizacion (P = 0)')
        for s in sensibilidad_discretizacion(sec):
            print('    %3d fibras  M_max = %8.1f kN m   %.3f %% vs la mas fina'
                  % (s['fibras'], s['M_max'], 100 * s['error_vs_mas_fino']))
    return 0


# ============================================================
# LOS DOS SENTIDOS DEL MOMENTO
# ============================================================
def espejo(sec):
    """
    La MISMA seccion con el fierro reflejado (y -> -y).

    Sirve para la capacidad del otro sentido del momento. Se refleja
    solo la posicion de las barras: el hormigon es un rectangulo b x h
    simetrico, y el estribo, el confinamiento y los materiales no
    dependen del sentido. Es una copia: no toca la seccion original.
    """
    otra = copy.copy(sec)
    otra.barras = [(-y, z, a) for (y, z, a) in sec.barras]
    otra.nombre = sec.nombre + ' (espejada)'
    return otra


def fierro_simetrico(sec, tol=1e-6):
    """
    True si el fierro es simetrico respecto de y = 0, o sea si las dos
    corridas darian lo mismo y la espejada se puede saltar.

    Se compara el conjunto de barras con el conjunto reflejado, barra
    por barra y con su area: dos barras en +y y -y con areas distintas
    NO son simetricas, aunque las posiciones si lo sean.
    """
    def clave(barras):
        return sorted((round(y, 9), round(z, 9), round(a, 12))
                      for y, z, a in barras)
    return clave(sec.barras) == clave((-y, z, a) for y, z, a in sec.barras)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
