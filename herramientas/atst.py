# -*- coding: utf-8 -*-
r"""
================================================================
 herramientas/atst.py  -  EL AT-ST QUE CAMINA POR LA LOSA
================================================================
 La pestana Persona dibuja a quien camina. Esto prepara un AT-ST para
 que lo dibuje Unity sin importar nada a mano: lee el OBJ, separa el
 cuerpo de las dos piernas (para que caminen), lo pasa a los ejes de
 Unity, lo escala y deja unity/Assets/Resources/Personaje/atst.json,
 que VisorPersona (VisorPersona.Personaje.cs) arma como mallas.

 EL MODELO (unity/FuentesPersonaje/LICENCIA.md)
   "AT-ST" de Tom Meyer, CC BY 3.0, via Poly Pizza
   (https://poly.pizza/m/6jqEk8QiL0m). Se cambio: separado en piezas,
   reorientado y escalado. La licencia pide nombrar al autor: va en el
   JSON (info.atribucion) y el panel la muestra. El OBJ vive fuera de
   Assets (unity/FuentesPersonaje/) para que no entre a la build: la app
   solo necesita el JSON.

 QUE HACE CON LA GEOMETRIA
   - Piezas: el OBJ son 73 primitivas sueltas (Google Blocks). Una
     primitiva es de una PIERNA si su centro esta bajo CORTE_PIERNAS
     (el fondo de la cabina); el lado lo da su x contra el punto medio
     de las dos piernas. Lo demas es el cuerpo.
   - Ejes: el OBJ es de mano derecha con Y arriba y mira hacia -z (los
     pies y los canones). A Unity (mano izquierda, mira hacia +z) se
     pasa con (x, y, -z): es un espejo, asi que se invierte el orden de
     los vertices de cada triangulo para que la cara de afuera siga
     siendo la de afuera (bloque [3]).
   - Tamano: ALTO_M, para que quepa bajo la viga del piso de arriba
     (LT2: 3.91 m entre pisos menos 0.80 m de viga). Es de juguete: no
     pretende el tamano de la pelicula.
   - Cada pierna gira en su cadera: el pivote es el centro de su pieza
     mas alta.

 Que el JSON calce con las clases C# que lo leen (PersonajeJson,
 InfoPersonaje, PiezaPersonaje: CLASES_CS) lo revisa la verificacion de
 contratos de Unity, junto con los demas JSON del visor.

 Correr:
   python sap.py atst              arma y escribe
   python sap.py atst --verificar  el JSON escrito es el que se arma hoy
================================================================
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np

from calculo import rutas

FUENTES = os.path.join(rutas.UNITY_PROYECTO, 'FuentesPersonaje')
OBJ = os.path.join(FUENTES, 'at-st_tom_meyer.obj')
MTL = os.path.join(FUENTES, 'materials.mtl')
SALIDA = os.path.join(rutas.RESOURCES, 'Personaje', 'atst.json')

ALTO_M = 2.8
CORTE_PIERNAS = 0.03         # y del OBJ: el fondo de la cabina esta en 0.043
ATRIBUCION = ('"AT-ST" de Tom Meyer, CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/), '
              'via Poly Pizza (https://poly.pizza/m/6jqEk8QiL0m). Separado en piezas, '
              'reorientado y escalado para este visor.')
# El texto que ya lleva atst.json en info.generado_por. Se conserva tal
# cual para que regenerar el asset de los MISMOS bytes (su md5 es un
# numero de control): cambiarlo es cambiar el asset, no solo su origen.
GENERADO_POR = 'semana05_lab/personaje_atst.py'

# Las clases C# que leen atst.json y la clave del JSON que lee cada una
# (None = la raiz). Las usa la verificacion de contratos de Unity.
CLASES_CS = {'PersonajeJson': None, 'InfoPersonaje': 'info', 'PiezaPersonaje': 'piezas'}


def leer_obj(ruta):
    V, F, mat = [], [], None
    for linea in io.open(ruta, encoding='utf-8'):
        p = linea.split()
        if not p:
            continue
        if p[0] == 'v':
            V.append([float(c) for c in p[1:4]])
        elif p[0] == 'f':
            F.append([int(t.split('/')[0]) - 1 for t in p[1:]])
        elif p[0] == 'usemtl':
            mat = p[1]
    return np.array(V), F, mat


def color_de(mtl, nombre):
    actual = None
    for linea in io.open(mtl, encoding='utf-8'):
        p = linea.split()
        if p and p[0] == 'newmtl':
            actual = p[1]
        elif p and p[0] == 'Kd' and actual == nombre:
            return [float(c) for c in p[1:4]]
    return [0.6, 0.6, 0.6]


def componentes(F, n):
    padre = list(range(n))

    def raiz(a):
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    for f in F:
        for v in f[1:]:
            a, b = raiz(f[0]), raiz(v)
            if a != b:
                padre[max(a, b)] = min(a, b)
    grupos = {}
    for i, f in enumerate(F):
        grupos.setdefault(raiz(f[0]), []).append(i)
    return list(grupos.values())


def volumen(P, tris):
    """Volumen con signo (positivo si las normales cross(b-a, c-a) miran afuera)."""
    return sum(float(np.dot(P[a], np.cross(P[b], P[c]))) for a, b, c in tris) / 6.0


def armar(fallas):
    V, F, mat = leer_obj(OBJ)
    comps = componentes(F, len(V))
    # --- piezas
    centros = []
    for fs in comps:
        vs = sorted({v for i in fs for v in F[i]})
        centros.append(V[vs].mean(axis=0))
    piernas = [k for k, c in enumerate(centros) if c[1] < CORTE_PIERNAS]
    medio = 0.5 * (min(centros[k][0] for k in piernas) + max(centros[k][0] for k in piernas))
    parte = {}
    for k in range(len(comps)):
        if k not in piernas:
            parte[k] = 'cuerpo'
        else:
            # quien mira hacia -z con Y arriba (mano derecha) tiene la
            # derecha en +x, como la camara de OpenGL
            parte[k] = 'pierna_der' if centros[k][0] > medio else 'pierna_izq'
    # --- a Unity: (x, y, -z), escalado, los pies en y = 0 y centrado en la cabina
    U = V * np.array([1.0, 1.0, -1.0])
    alto = U[:, 1].max() - U[:, 1].min()
    esc = ALTO_M / alto
    cuerpo_vs = sorted({v for k in range(len(comps)) if parte[k] == 'cuerpo' for i in comps[k] for v in F[i]})
    c0 = U[cuerpo_vs].mean(axis=0)
    U = (U - np.array([c0[0], U[:, 1].min(), c0[2]])) * esc

    piezas, total_tris, vol = [], 0, 0.0
    for nombre in ('cuerpo', 'pierna_izq', 'pierna_der'):
        ks = [k for k in range(len(comps)) if parte[k] == nombre]
        tris = []
        for k in ks:
            for i in comps[k]:
                f = F[i]
                for j in range(1, len(f) - 1):
                    # abanico; (a, c, b) en vez de (a, b, c): el espejo de z
                    tris.append((f[0], f[j + 1], f[j]))
        vol += volumen(U, tris)
        total_tris += len(tris)
        if nombre == 'cuerpo':
            pivote = np.zeros(3)
        else:
            alta = max(ks, key=lambda k: max(U[v, 1] for i in comps[k] for v in F[i]))
            vs = sorted({v for i in comps[alta] for v in F[i]})
            pivote = U[vs].mean(axis=0)
        # vertices sin compartir: cada triangulo con su normal (aristas duras)
        verts = []
        for a, b, c in tris:
            for v in (a, b, c):
                verts.extend(round(float(t), 4) for t in (U[v] - pivote))
        piezas.append({'nombre': nombre, 'pivote': [round(float(t), 4) for t in pivote],
                       'vertices': verts, 'n_piezas_obj': len(ks)})
    n_caras = sum(len(f) - 2 for f in F)
    fallas.append(('cada cara del OBJ quedo en una pieza (%d triangulos, %d primitivas: '
                   'cuerpo %d, piernas %d y %d)' % (total_tris, len(comps), piezas[0]['n_piezas_obj'],
                                                   piezas[1]['n_piezas_obj'], piezas[2]['n_piezas_obj']),
                   total_tris == n_caras and all(p['n_piezas_obj'] > 0 for p in piezas)))
    fallas.append(('[3] las caras miran hacia afuera en Unity (volumen con signo %.3f m3 > 0)' % vol,
                   vol > 0))
    alto_final = max(max(p['vertices'][1::3]) + p['pivote'][1] for p in piezas) \
        - min(min(p['vertices'][1::3]) + p['pivote'][1] for p in piezas)
    fallas.append(('mide %.2f m y apoya en y = 0' % alto_final, abs(alto_final - ALTO_M) < 2e-3))
    caderas = [p['pivote'][1] for p in piezas[1:]]
    fallas.append(('las caderas quedan bajo la cabina (y = %.2f y %.2f m de %.2f)'
                   % (caderas[0], caderas[1], ALTO_M), all(0.3 * ALTO_M < c < 0.75 * ALTO_M for c in caderas)))
    return {
        'info': {
            'nombre': 'AT-ST',
            'atribucion': ATRIBUCION,
            'generado_por': GENERADO_POR,
            'alto_m': ALTO_M,
            'color': color_de(MTL, mat),
            '_por_que': ('Mallas listas para Unity (ejes de Unity, m): el cuerpo y dos piernas que '
                         'giran en su cadera (pivote). vertices = x, y, z de cada vertice de cada '
                         'triangulo, sin compartir, relativos al pivote; adelante es +z.'),
        },
        'piezas': piezas,
    }


def main(argv):
    fallas = []
    for ruta in (OBJ, MTL):
        if not os.path.isfile(ruta):
            print('  [FALLA] existe %s' % rutas.relativa(ruta))
            print()
            print('  1 FALLA(S)')
            return 1
    js = armar(fallas)
    if '--verificar' in argv:
        try:
            with io.open(SALIDA, encoding='utf-8') as f:
                escrito = json.load(f)
            fallas.append(('el JSON de Resources es el que se arma hoy', escrito == js))
        except FileNotFoundError:
            fallas.append(('existe %s' % os.path.relpath(SALIDA, rutas.RAIZ), False))
    for msg, ok in fallas:
        print('  [%s] %s' % ('OK  ' if ok else 'FALLA', msg))
    malas = sum(1 for _, ok in fallas if not ok)
    if malas:
        print()
        print('  %d FALLA(S)' % malas)
        return 1
    if '--verificar' not in argv:
        os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
        with io.open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(js, f, ensure_ascii=False, separators=(',', ':'))
        print('  escrito %s (%.0f KB)' % (os.path.relpath(SALIDA, rutas.RAIZ), os.path.getsize(SALIDA) / 1e3))
    print()
    print('  TODO OK')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
