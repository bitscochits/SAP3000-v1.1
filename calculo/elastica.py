# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/elastica.py  -  LAS FORMULAS DE LA VIGA (LAS COPIA EL C#)
================================================================
 Cada barra del modelo es un elemento Euler-Bernoulli elastico. Entre
 sus dos nodos la deformada sale EXACTA de los 6 GDL de cada extremo
 (funciones de forma de Hermite) y, si la barra lleva una carga
 puntual, de la solucion de la viga biempotrada. Este archivo es la
 UNICA definicion en Python de esas formulas. El visor las transcribe
 (es la licencia de sumar en C#: combina casos ya resueltos, no
 resuelve nada) y la verificacion de las transcripciones LEE el C# y
 lo evalua contra estas:

     VisorEstructura.CurvaDe      desplazamiento_en, sin carga
     VisorPersona (la persona)    hermite, pesos, forma_local, uz_en,
                                  empotramiento_local, my_en, mz_en

 Son dos familias, a proposito, porque el C# copia cada una:

   LA CARGA MOVIL, en metros y kN, con los ejes locales de la barra:
     desplazamiento_en, flecha_biempotrada, esfuerzos_con_puntual,
     empotramiento, elastica (y ejes_de, carga_local, rigidez).

   LA PERSONA, en el plano vertical de una viga horizontal, con la
   forma ADIMENSIONAL de la carga (el C# no ve ni E ni I: Python le
   pasa la flexibilidad L^3/EI de cada viga):
     hermite, pesos, forma_local, uz_en, empotramiento_local, my_en,
     mz_en, flecha_bajo_carga.

 La segunda es la primera reescrita para lo que suma el C#; la
 verificacion de la persona comprueba que dan lo mismo ([2], [8c]).
 Una formula que se toca aca se toca tambien en el C#, o la guardia
 de las transcripciones falla.
================================================================
"""
from __future__ import annotations

from calculo import edificio as _ed
from calculo import esfuerzos


# ============================================================
# LA BARRA: GEOMETRIA, CARGA Y RIGIDEZ
# ============================================================
def xyz(n):
    """Las coordenadas de un nodo del modelo, (x, y, z) en m."""
    return (float(n['x']), float(n['y']), float(n['z']))


def ejes_de(e, nodos):
    """Versores locales y largo de la barra `e` con la regla del solver
    (edificio.vecxz_por_defecto y edificio.ejes_locales); `nodos` es {id: nodo}."""
    pi, pj = xyz(nodos[int(e['n1'])]), xyz(nodos[int(e['n2'])])
    vecxz = e.get('vecxz') or _ed.vecxz_por_defecto(pi, pj)
    base, L = _ed.ejes_locales(pi, pj, [float(v) for v in vecxz])
    return base, L


def carga_local(base, P):
    """
    (Px, Py, Pz) locales de una carga P hacia abajo, y su vector global.
    Global = (0, 0, -P); cada componente local es su producto punto con
    el versor.
    """
    g = (0.0, 0.0, -float(P))
    loc = [sum(g[c] * base[k][c] for c in range(3)) for k in ('wx', 'wy', 'wz')]
    return tuple(loc), g


def rigidez(modelo, e, nodos):
    """E, Iy, Iz de la barra `e` tal como los recibe ops.element (las reglas
    del motor, en esfuerzos.rigidez_como_el_servidor)."""
    secciones = {s['nombre']: s for s in modelo['secciones']}
    return esfuerzos.rigidez_como_el_servidor(e, secciones[e['seccion']],
                                              xyz(nodos[int(e['n1'])]),
                                              xyz(nodos[int(e['n2'])]),
                                              modelo.get('material', {}))


# ============================================================
# LA CARGA MOVIL: ESFUERZOS Y DESPLAZAMIENTOS DE LA VIGA CARGADA
# ============================================================
def esfuerzos_con_puntual(f, Px, Py, Pz, a, xs):
    """
    esfuerzos.esfuerzos_internos (sin carga repartida) mas el salto de
    la carga puntual en x = a, con H(x-a) = 1 si x > a:

        N(x)  = -(N_i  + Px H)
        Vy(x) = -(Vy_i + Py H)            Vz(x) = -(Vz_i + Pz H)
        My(x) = -(My_i + x Vz_i + Pz (x-a) H)
        Mz(x) = -(Mz_i - x Vy_i - Py (x-a) H)

    Es la misma forma que la uniforme con w x -> P H y w x^2/2 ->
    P (x-a) H: la resultante de la carga a la izquierda del corte y su
    brazo. En x = a (H = 0) el momento no salta, asi que M bajo la carga
    es el mismo por los dos lados.
    """
    Ni, Vyi, Vzi, Ti, Myi, Mzi = [float(v) for v in f[:6]]
    out = {'N': [], 'Vy': [], 'Vz': [], 'T': [], 'My': [], 'Mz': []}
    for x in xs:
        H = 1.0 if x > a else 0.0
        out['N'].append(-(Ni + Px * H))
        out['Vy'].append(-(Vyi + Py * H))
        out['Vz'].append(-(Vzi + Pz * H))
        out['T'].append(-Ti)
        out['My'].append(-(Myi + x * Vzi + Pz * (x - a) * H))
        out['Mz'].append(-(Mzi - x * Vyi - Py * (x - a) * H))
    return out


def flecha_biempotrada(P, a, L, x, EI):
    """
    Flecha en x de una viga biempotrada con una carga P (con signo) en a:

        x <= a:  P b^2 x^2 (3 a L - (3 a + b) x) / (6 E I L^3)
        x >= a:  la misma con x -> L - x y a <-> b

    En x = a da P a^3 b^3 / (3 E I L^3). Es la solucion particular que se
    suma a la interpolacion de Hermite de los nodos.
    """
    b = L - a
    if x <= a:
        return P * b * b * x * x * (3 * a * L - (3 * a + b) * x) / (6.0 * EI * L ** 3)
    xp = L - x
    return P * a * a * xp * xp * (3 * b * L - (3 * b + a) * xp) / (6.0 * EI * L ** 3)


def desplazamiento_en(base, L, k, ui, uj, x, carga=None):
    """
    Traslacion global (m) del punto x (m desde n1) de una barra, desde los
    6 GDL de sus nodos. Exacto para el elemento Euler-Bernoulli elastico:

      axial      u(xi) lineal                (sin carga axial en el tramo)
      local y    v(xi) Hermite con dv/dx = +rz_local
      local z    w(xi) Hermite con dw/dx = -ry_local
                 (girar +ry lleva el eje x hacia -z)

    y si la barra tiene la carga puntual, carga = (Py, Pz) en x mismo o
    (Py, Pz, a) en otro punto, la flecha de la viga biempotrada
    (flecha_biempotrada), en y con E Iz y en z con E Iy. Sin carga, `k`
    no se usa. La carga movil lo comprueba contra los nodos de la viga
    partida ([e]) y con Betti ([g]); el visor lo transcribe en
    VisorEstructura.CurvaDe para curvar cada barra.
    """
    ex, ey, ez = base['wx'], base['wy'], base['wz']

    def dot(v, w):
        return sum(v[c] * w[c] for c in range(3))

    ti, tj = ui[:3], uj[:3]
    ri, rj = ui[3:], uj[3:]
    xi = x / L
    N1 = 1 - 3 * xi ** 2 + 2 * xi ** 3
    N2 = xi - 2 * xi ** 2 + xi ** 3
    N3 = 3 * xi ** 2 - 2 * xi ** 3
    N4 = -xi ** 2 + xi ** 3
    u = (1 - xi) * dot(ex, ti) + xi * dot(ex, tj)
    v = (N1 * dot(ey, ti) + N2 * L * dot(ez, ri)
         + N3 * dot(ey, tj) + N4 * L * dot(ez, rj))
    w = (N1 * dot(ez, ti) - N2 * L * dot(ey, ri)
         + N3 * dot(ez, tj) - N4 * L * dot(ey, rj))
    if carga is not None:
        Py, Pz = carga[0], carga[1]
        a_carga = carga[2] if len(carga) > 2 else x
        v += flecha_biempotrada(Py, a_carga, L, x, k['E'] * k['Iz_pasa'])
        w += flecha_biempotrada(Pz, a_carga, L, x, k['E'] * k['Iy_pasa'])
    return [u * ex[c] + v * ey[c] + w * ez[c] for c in range(3)]


# Estaciones de la elastica de la viga cargada: los decimos de L (los
# nodos de la viga partida de [e], que la verifican) mas el punto de la
# carga. Solo para DIBUJAR la curva: el visor las escala, no interpola.
DECIMOS_ELASTICA = 10


def elastica(pi, pj, base, L, k, ui, uj, Py, Pz, a):
    """[{xL, x, y, z, ux, uy, uz}] de la viga cargada, en m."""
    # Redondeado antes de juntar: 1 - 0.7 no es 0.3 en coma flotante, y el
    # punto de la carga saldria repetido con largo cero.
    xs = sorted({round(i / DECIMOS_ELASTICA, 9) for i in range(DECIMOS_ELASTICA + 1)}
                | {round(a / L, 9)})
    salida = []
    for t in xs:
        u = desplazamiento_en(base, L, k, ui, uj, t * L, carga=(Py, Pz, a))
        salida.append({
            'xL': round(t, 6),
            'x': round(pi[0] + t * (pj[0] - pi[0]), 4),
            'y': round(pi[1] + t * (pj[1] - pi[1]), 4),
            'z': round(pi[2] + t * (pj[2] - pi[2]), 4),
            'ux': round(u[0], 8), 'uy': round(u[1], 8), 'uz': round(u[2], 8),
        })
    return salida


def empotramiento(Pz, a, L):
    """
    Fuerzas de empotramiento perfecto de una carga Pz (local, negativa
    hacia abajo) en a, con la convencion de localForce (fuerzas de los
    nodos sobre la barra): son las "fuerzas nodales equivalentes" que
    OpenSees ensambla con el signo cambiado. La carga movil las compara
    con OpenSees en una viga biempotrada aislada ([i]).
    """
    P = -Pz
    b = L - a
    return {'V_i': P * b * b * (3 * a + b) / L ** 3,
            'V_j': P * a * a * (a + 3 * b) / L ** 3,
            'My_i': -P * a * b * b / L ** 2,
            'My_j': P * a * a * b / L ** 2}


# ============================================================
# LA PERSONA: LO QUE SUMA EL C# (forma adimensional)
# ============================================================
# Una carga puntual P en alfa = a/L de una viga le entrega a sus dos
# nodos las FUERZAS NODALES EQUIVALENTES, P por las funciones de forma
# de Hermite en alfa:
#
#     en n1:  Fz = -P N1(alfa)      M = P L N2(alfa) (z x d)
#     en n2:  Fz = -P N3(alfa)      M = P L N4(alfa) (z x d)
#
# (d = versor de la viga en planta; z x d = (-dy, dx, 0) es el eje de
# giro de la flexion). Con esas cargas OpenSees da los desplazamientos
# nodales EXACTOS de eleLoad -beamPoint, asi que la deformada de la
# persona es la suma de a lo mas seis casos unitarios con estos pesos.
def hermite(a):
    """N1..N4 de Hermite en alfa, con N2 y N4 SIN el factor L."""
    return (1 - 3 * a * a + 2 * a ** 3,
            a - 2 * a * a + a ** 3,
            3 * a * a - 2 * a ** 3,
            -a * a + a ** 3)


def pesos(rec, alfa, P):
    """
    [(nodo, gdl, peso)] de la carga P (kN, hacia abajo) en alfa del
    receptor. Los casos unitarios son Fz = 1 kN HACIA ABAJO y momentos
    de 1 kN m, asi que el peso de Fz es +P N.
    """
    if rec['tipo'] == 'nodo':
        return [(rec['nodo'], 'Fz', P)]
    N1, N2, N3, N4 = hermite(alfa)
    L, nx, ny = rec['L'], -rec['dy'], rec['dx']          # z x d
    return [(rec['n1'], 'Fz', P * N1), (rec['n1'], 'Mx', P * L * N2 * nx),
            (rec['n1'], 'My', P * L * N2 * ny),
            (rec['n2'], 'Fz', P * N3), (rec['n2'], 'Mx', P * L * N4 * nx),
            (rec['n2'], 'My', P * L * N4 * ny)]


def forma_local(xi, alfa):
    """
    phi(xi, alfa): la flecha de la viga biempotrada con la carga en alfa,
    dividida por P L^3 / (E I). Es flecha_biempotrada sin unidades; la
    guardia de las transcripciones comprueba que son la misma.
    """
    if xi > alfa:
        xi, alfa = 1.0 - xi, 1.0 - alfa
    return (1 - alfa) ** 2 * xi * xi * (3 * alfa - (1 + 2 * alfa) * xi) / 6.0


def uz_en(rec, ui, uj, xi, alfa, P):
    """
    uz (m) en xi de la viga cargada en alfa: Hermite de los nodos en el
    plano vertical de la viga (la pendiente dz/dx = -(z x d) . giro) mas
    la flecha local. Es la componente vertical de desplazamiento_en,
    que la verificacion de la persona ([2]) usa de referencia.
    """
    N1, N2, N3, N4 = hermite(xi)
    nx, ny, L = -rec['dy'], rec['dx'], rec['L']
    gi = nx * ui[3] + ny * ui[4]
    gj = nx * uj[3] + ny * uj[4]
    return (N1 * ui[2] - N2 * L * gi + N3 * uj[2] - N4 * L * gj
            - P * rec['flex'] * forma_local(xi, alfa))


def empotramiento_local(rec, alfa, P):
    """
    Lo que la carga P en alfa le agrega al localForce de SU viga: las
    fuerzas de empotramiento perfecto, P por N1..N4 (indices Vz_i, My_i,
    Vz_j, My_j). Es empotramiento() con Pz = -P (lo comprueba la guardia
    de las transcripciones).
    """
    N1, N2, N3, N4 = hermite(alfa)
    L = rec['L']
    return {2: P * N1, 4: -P * L * N2, 8: P * N3, 10: -P * L * N4}


def my_en(f, x, a, P):
    """My(x) de la barra con extremos f; P (kN, hacia abajo) en a si es la
    cargada, 0 si no. Es esfuerzos_con_puntual con Pz = -P."""
    return -(f[4] + x * f[2] - P * max(0.0, x - a))


def mz_en(f, x):
    """Mz(x): sin carga en y local, lineal entre extremos."""
    return -(f[5] - x * f[1])


def flecha_bajo_carga(rec, ui, uj, alfa, P):
    """uz (m) del punto cargado (el nodo, si es un muro)."""
    if rec['tipo'] == 'nodo':
        return ui[2]
    return uz_en(rec, ui, uj, alfa, alfa, P)
