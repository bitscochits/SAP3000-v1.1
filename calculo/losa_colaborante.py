# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/losa_colaborante.py  -  LA VIGA TRABAJARIA CON SU ALA DE LOSA
================================================================
 REGLA ESCRITA Y NO CONECTADA: ningun modelo la usa. Cada viga entra a
 OpenSees como un rectangulo bw x h que CARGA la losa pero no se deja
 AYUDAR por ella. Eso es fisicamente inconsistente --el hormigon de la
 losa y el de la viga se vacian juntos-- y es la razon de fondo de que
 las flechas de gravedad salgan grandes. Aca esta la regla para cuando
 se decida conectarla, y un informe de cuanto cambiaria cada viga.

 Conectarla NO es gratis: sube la Iz de 520 vigas (mediana x1.39) y
 cambian todos los desplazamientos y todos los D/C, pero G no cambia
 (el area queda rectangular), asi que el equilibrio no lo delata. Es
 una decision, no un arreglo.

 Correr:
   python sap.py revisar losa-colaborante

 ----------------------------------------------------------------
 LA REGLA  (ACI 318-08 8.12.2, viga con losa a los dos lados)
 ----------------------------------------------------------------
     b_eff <= L / 4                     un cuarto de la luz
     ala por lado <= 8 hf               ocho espesores de losa
     ala por lado <= media distancia libre al alma vecina

 Los dos primeros se aplican tal cual. El tercero se aplica con el
 ANCHO TRIBUTARIO de la viga, que es justamente la media distancia a
 sus vecinas: asi el ala nunca se pasa de la losa que esa viga
 realmente tiene, y dos vigas vecinas no se reparten dos veces el
 mismo hormigon. En una viga de BORDE el tributario ya es de un solo
 lado, o sea que la regla se acota sola sin tener que distinguirla.

 No inventa ninguna dimension: usa el espesor de losa y la regla de
 ancho efectivo. Medido en el edificio: manda casi siempre L/4, porque
 8 hf = 2.00 m y los tributarios son de 2 a 3 m.

 ----------------------------------------------------------------
 QUE SE CAMBIARIA Y QUE NO
 ----------------------------------------------------------------
 SOLO la inercia de gravedad, Iz. No el area.

 El area se deja RECTANGULAR a proposito: el peso propio de cada viga
 sale de A * gamma, y el peso de la losa ya entra por separado como
 carga tributaria. Si el area incluyera el ala, la losa pesaria DOS
 VECES y el equilibrio cerraria igual, sin avisar. Iy y J tampoco: el
 ala casi no ayuda a la flexion en planta (que ademas toma el
 diafragma) ni a la torsion, y dejarlos es el lado seguro.
================================================================
"""
from __future__ import annotations

import collections
import math

# ACI 318-08 8.12.2
FRACCION_LUZ = 4.0          # b_eff <= L / 4
ESPESORES_POR_LADO = 8.0    # ala por lado <= 8 hf

# El espesor de losa con que se arma el INFORME: 0.25 m en todas las
# vigas, la losa supuesta del cuerpo antiguo (supuestos.ingenieria del
# edificio). La del LT2 es de 0.15 m. Como la regla no esta conectada, no
# cambia ningun numero del programa; se deja asi para que el informe siga
# dando lo que daba (mediana x1.39 en 520 vigas) y se pueda comparar.
HF_DEL_INFORME = 0.25


def ancho_efectivo(bw, h, hf, L, b_trib=None):
    """
    El ancho de ala que ACI deja usar para ESTA viga, en m.

    b_trib es el ancho tributario TOTAL de la viga (su area tributaria
    dividida por su luz). Si no se sabe, no se aplica ese tope: los
    otros dos siguen acotando, y el resultado es mayor o igual, o sea
    hay que pasarlo cuando se tenga.
    """
    bw, hf, L = float(bw), float(hf), float(L)
    if bw <= 0 or hf <= 0 or L <= 0:
        return bw
    topes = [L / FRACCION_LUZ, bw + 2.0 * ESPESORES_POR_LADO * hf]
    if b_trib:
        topes.append(float(b_trib))
    # Nunca menos que el alma: una viga muy corta se queda sin ala.
    return max(bw, min(topes))


def inercia_T(bw, h, hf, b_eff):
    """
    Inercia de gravedad de la seccion T respecto de su centro de
    gravedad, en m4. Con b_eff = bw devuelve la del rectangulo.
    """
    bw, h, hf, b_eff = float(bw), float(h), float(hf), float(b_eff)
    rect = bw * h ** 3 / 12.0
    ala = b_eff - bw
    if ala <= 1e-9 or hf <= 1e-9 or hf >= h:
        return rect
    # y se mide desde la fibra INFERIOR; el ala esta arriba.
    Aw, Af = bw * h, ala * hf
    yw, yf = h / 2.0, h - hf / 2.0
    yg = (Aw * yw + Af * yf) / (Aw + Af)
    return (rect + Aw * (yw - yg) ** 2
            + ala * hf ** 3 / 12.0 + Af * (yf - yg) ** 2)


def propiedades(bw, h, hf, L, b_trib=None):
    """
    Todo junto, para quien arma una viga:
      b_eff, Iz (con ala), Iz_rectangular, y cual de los topes mando.
    El AREA no se devuelve a proposito: se queda rectangular (ver la
    cabecera de este modulo).
    """
    b_eff = ancho_efectivo(bw, h, hf, L, b_trib)
    topes = {'L/4': L / FRACCION_LUZ,
             'bw+16hf': bw + 2.0 * ESPESORES_POR_LADO * hf}
    if b_trib:
        topes['tributario'] = float(b_trib)
    manda = min(topes, key=lambda k: topes[k])
    rect = bw * h ** 3 / 12.0
    Iz = inercia_T(bw, h, hf, b_eff)
    return {'b_eff': b_eff, 'Iz': Iz, 'Iz_rectangular': rect,
            'razon': Iz / rect if rect else 1.0, 'manda': manda}


def informe(modelo, hf=HF_DEL_INFORME):
    """
    Que daria el ala en cada viga del modelo, SIN aplicarlo: (razones Iz
    con ala / Iz rectangular, ordenadas; {tope que manda: cuantas vigas}).
    Las vigas metalicas y las barras sin b o h quedan fuera; el ancho
    tributario es area_tributaria / L.
    """
    N = {n['id']: n for n in modelo['nodos']}
    S = {s['nombre']: s for s in modelo['secciones']}
    manda = collections.Counter()
    razones = []
    for e in modelo['elementos']:
        if not e['tipo'].startswith('viga') or e['tipo'] == 'viga_metal':
            continue
        s = S.get(e['seccion'])
        if not s or not s.get('b') or not s.get('h'):
            continue
        a, b = N.get(e['n1']), N.get(e['n2'])
        if not a or not b:
            continue
        L = math.dist((a['x'], a['y'], a['z']), (b['x'], b['y'], b['z']))
        At = e.get('area_tributaria') or 0.0
        r = propiedades(s['b'], s['h'], hf, L, (At / L) if At and L else None)
        manda[r['manda']] += 1
        razones.append(r['razon'])
    razones.sort()
    return razones, manda
