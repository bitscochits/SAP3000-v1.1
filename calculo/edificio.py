# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/edificio.py  -  LEER Y ENTENDER EL EDIFICIO
================================================================
 entrada/edificio.json es el UNICO modelo del programa: los dos cuerpos
 del Edificio de Ingenieria UAndes (el antiguo, planos 2017_67, tags
 1xxxxx; el LT2, planos 2024_22, tags 2xxxxx) como un solo edificio,
 separados por una junta de dilatacion libre de 5 cm.

     estructura   info .. casos_de_carga (en la raiz del JSON): lo que
                  resuelve OpenSees. Es el archivo mismo, sin los
                  bloques de abajo: un modelo valido del contrato.
     vista        poligonos de losa y terreno: lo que solo dibuja el
                  visor (ya en las coordenadas del edificio)
     supuestos    lo que el plano no dice, con su porque. NINGUN calculo
                  lo lee

 Este archivo es la unica definicion de lo que es un modelo: que trae,
 como se valida, cuales son los ejes locales de una barra, a que cuerpo
 pertenece un tag y como se le pegan los desplazamientos para el visor.
 No sabe de OpenSees (eso es calculo/opensees.py).

 ----------------------------------------------------------------
 QUE ES ESTRUCTURA Y QUE ES DIBUJO
 ----------------------------------------------------------------
 La regla: si sacarlo cambia el resultado del analisis, es estructura.
 Si solo cambia como se ve, es vista. El poligono tributario es vista
 aunque de el SALGA la carga: lo que entra al analisis es la carga
 distribuida ya calculada. Su AREA, en cambio, viaja dentro de cada
 elemento ('area_tributaria'), porque es el dato del que salio la carga
 y lo que permite verificar sum(w L) = q A.
================================================================
"""
from __future__ import annotations

import copy
import io
import json
import math

from calculo import rutas

NOMBRE = 'conjunto'

# Las claves que definen la estructura. Lo que no este aca es vista,
# supuestos o documentacion.
CLAVES_ESTRUCTURA = (
    'info',
    'material',
    'secciones',
    'nodos',
    'elementos',
    'diafragmas',
    'brazos_rigidos',
    'casos_de_carga',
)

# Campos de un nodo que son resultado, no dato.
CAMPOS_RESULTADO_NODO = ('ux', 'uy', 'uz')

# Lo minimo que tiene que traer un modelo para poder resolverse.
OBLIGATORIAS = ('secciones', 'nodos', 'elementos')

# El area de losa que le llega a un elemento (m2). El POLIGONO es vista.
CAMPO_AREA = 'area_tributaria'

# Bandera OPCIONAL de un caso de carga: si sus distribuidas ya traen el
# peso propio de la barra (G suele traerlo: w = A*gamma + q*A_trib/L; Q
# nunca). Sin ella hay que inferirlo, y quien infiera tiene que decirlo.
CAMPO_PESO_PROPIO = 'incluye_peso_propio'

# Los dos cuerpos viven en el mismo modelo y se distinguen por el tag:
# tag del edificio = PASO_DE_TAG * k + tag del cuerpo. NO se renumera:
# 200037 esta impreso en el marcador de la AR y las demos se citan por tag.
PASO_DE_TAG = 100000
CUERPOS = {1: 'ingenieria', 2: 'lt2'}


# ============================================================
# LEER
# ============================================================
_TEXTO = {}


def _texto(ruta):
    if ruta not in _TEXTO:
        with io.open(ruta, encoding='utf-8') as f:
            _TEXTO[ruta] = f.read()
    return _TEXTO[ruta]


def cargar(ruta: str = None) -> dict:
    """
    El JSON del edificio entero. Cada llamada devuelve un objeto NUEVO (se
    parsea el texto otra vez): quien lo modifica -una demo que borra una
    columna, una prueba que subdivide una viga- no ensucia a los demas.
    """
    return json.loads(_texto(ruta or rutas.EDIFICIO))


def estructura(edificio: dict = None) -> dict:
    """
    Lo que recibe el solver: las claves de CLAVES_ESTRUCTURA, tal cual
    estan en el archivo. Es exactamente el data/modelo/conjunto.json de v1.0.
    """
    e = edificio if edificio is not None else cargar()
    return {k: e[k] for k in CLAVES_ESTRUCTURA if k in e}


def vista(edificio: dict = None) -> dict:
    """Lo que solo se dibuja: areas_tributarias, cota_terreno, terrenos."""
    e = edificio if edificio is not None else cargar()
    return e.get('vista', {})


def supuestos(edificio: dict = None) -> dict:
    """La documentacion de lo que el plano no dice. Ningun calculo la lee."""
    e = edificio if edificio is not None else cargar()
    return e.get('supuestos', {})


# ============================================================
# LOS DOS CUERPOS
# ============================================================
def cuerpo_de(tag) -> str:
    """'ingenieria' o 'lt2' segun el rango del tag (1xxxxx o 2xxxxx)."""
    k = int(tag) // PASO_DE_TAG
    if k not in CUERPOS:
        raise ValueError('el tag %s no es de ningun cuerpo (1xxxxx o 2xxxxx)' % tag)
    return CUERPOS[k]


def por_cuerpo(modelo: dict) -> dict:
    """
    {cuerpo: submodelo} partiendo el modelo por rango de tag: nodos,
    elementos, diafragmas, brazos y cargas de cada cuerpo. Sirve para
    comprobar que la junta es LIBRE (cada cuerpo resuelto solo tiene que
    dar lo mismo que dentro del edificio) sin volver a tener un modelo por
    cuerpo en disco. Las secciones y el material van enteros a los dos.
    """
    partes = {}
    for nombre in CUERPOS.values():
        es = lambda t, n=nombre: cuerpo_de(t) == n          # noqa: E731
        sub = {k: copy.deepcopy(v) for k, v in modelo.items()
               if k not in ('nodos', 'elementos', 'diafragmas', 'brazos_rigidos',
                            'casos_de_carga')}
        sub['nodos'] = [copy.deepcopy(n) for n in modelo['nodos'] if es(n['id'])]
        sub['elementos'] = [copy.deepcopy(e) for e in modelo['elementos'] if es(e['id'])]
        sub['diafragmas'] = [copy.deepcopy(d) for d in modelo.get('diafragmas', [])
                             if es(d['nodo_maestro'])]
        sub['brazos_rigidos'] = [copy.deepcopy(b) for b in modelo.get('brazos_rigidos', [])
                                 if es(b['maestro'])]
        sub['casos_de_carga'] = []
        for c in modelo.get('casos_de_carga', []):
            c2 = {k: copy.deepcopy(v) for k, v in c.items()
                  if k not in ('cargas_nodales', 'cargas_distribuidas')}
            c2['cargas_nodales'] = [copy.deepcopy(x) for x in c.get('cargas_nodales', [])
                                    if es(x['nodo'])]
            c2['cargas_distribuidas'] = [copy.deepcopy(x) for x in c.get('cargas_distribuidas', [])
                                         if es(x['elemento'])]
            sub['casos_de_carga'].append(c2)
        partes[nombre] = sub
    return partes


# ============================================================
# GEOMETRIA DE BARRAS Y DIAFRAGMAS
# ============================================================
def largo(e, nodos) -> float:
    """Largo de la barra `e`; `nodos` es {id: nodo}."""
    a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
    return math.sqrt(sum((float(b[k]) - float(a[k])) ** 2
                         for k in ('x', 'y', 'z')))


def niveles(modelo) -> list:
    """(cota, nodo maestro) de cada diafragma, de abajo hacia arriba."""
    nodos = {int(n['id']): n for n in modelo['nodos']}
    return sorted(((float(nodos[int(d['nodo_maestro'])]['z']),
                    int(d['nodo_maestro']))
                   for d in modelo.get('diafragmas', [])),
                  key=lambda t: t[0])


def indice_de_diafragma(modelo) -> dict:
    """{nodo: i} con el diafragma al que pertenece cada nodo (el primero que lo nombra)."""
    de_nodo = {}
    for i, d in enumerate(modelo.get('diafragmas', [])):
        de_nodo[int(d['nodo_maestro'])] = i
        for n in d.get('nodos', []):
            de_nodo.setdefault(int(n), i)
    return de_nodo


def restricciones_de(nd):
    """
    Los apoyos de un nodo como los lee el solver: la lista 'restricciones'
    de 6 valores, o 'fijo': true sin lista = empotrado. None si el nodo no
    tiene ninguna. Una lista VACIA cuenta como ausente: JsonUtility de Unity
    serializa siempre todos los campos y un nodo libre llega con [].
    """
    r = nd.get('restricciones') or None
    if r is None and nd.get('fijo', False):
        r = [1, 1, 1, 1, 1, 1]
    if r is None or not any(int(v) for v in r):
        return None
    return [int(v) for v in r]


def es_vertical(pi, pj) -> bool:
    """
    La UNICA definicion de "barra vertical": proyeccion horizontal / largo
    menor que 1e-6. Es la regla con que el solver elige la transformacion
    (calculo/opensees.construir_modelo); el equilibrio y los ejes que se le
    muestran a Unity la usan tambien, para que nadie elija otro vecxz.
    """
    dx, dy, dz = pj[0] - pi[0], pj[1] - pi[1], pj[2] - pi[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    if L < 1e-12:
        return False
    return math.sqrt(dx * dx + dy * dy) / L < 1e-6


def vecxz_por_defecto(pi, pj):
    """La regla del solver: vertical -> (1,0,0), si no (0,0,1)."""
    return (1.0, 0.0, 0.0) if es_vertical(pi, pj) else (0.0, 0.0, 1.0)


def ejes_locales(pi, pj, vecxz):
    """
    Los tres versores locales de una barra, con la MISMA convencion que
    usa OpenSees en geomTransf:

        local_x = (j - i) normalizado
        local_z = componente de vecxz perpendicular a local_x
        local_y = local_z x local_x

    Devuelve ({'wx','wy','wz'}, L), o (None, L) si la barra es degenerada
    o vecxz es paralelo a ella.
    """
    dx = [pj[k] - pi[k] for k in range(3)]
    L = math.sqrt(sum(c * c for c in dx))
    if L < 1e-12:
        return None, 0.0
    ex = [c / L for c in dx]
    proy = sum(vecxz[k] * ex[k] for k in range(3))
    ez = [vecxz[k] - proy * ex[k] for k in range(3)]
    n = math.sqrt(sum(c * c for c in ez))
    if n < 1e-9:
        return None, L
    ez = [c / n for c in ez]
    ey = [ez[1] * ex[2] - ez[2] * ex[1],
          ez[2] * ex[0] - ez[0] * ex[2],
          ez[0] * ex[1] - ez[1] * ex[0]]
    return {'wx': ex, 'wy': ey, 'wz': ez}, L


def sellar_ejes_locales(modelo) -> int:
    """
    Le pone localX/localY/localZ a cada elemento que no los traiga (6
    decimales). Unity NO deduce la orientacion de una seccion: la lee de
    aca, y sin esto dibuja el canto de las vigas con un vector por defecto
    sin que nadie se entere. Devuelve cuantos se sellaron.

    Se sella al EXPORTAR el visor, nunca en el edificio: el equilibrio usa
    localX si viene, y congelarlo redondeado moveria su ultimo decimal.
    """
    nodos = {int(n['id']): (float(n['x']), float(n['y']), float(n['z']))
             for n in modelo.get('nodos', [])}
    sellados = 0
    for e in modelo.get('elementos', []):
        if e.get('localX') and e.get('localY') and e.get('localZ'):
            continue
        pi, pj = nodos.get(int(e['n1'])), nodos.get(int(e['n2']))
        if pi is None or pj is None:
            continue
        vecxz = e.get('vecxz') or vecxz_por_defecto(pi, pj)
        base, _L = ejes_locales(pi, pj, [float(v) for v in vecxz])
        if base is None:
            continue
        e['localX'] = [round(v, 6) for v in base['wx']]
        e['localY'] = [round(v, 6) for v in base['wy']]
        e['localZ'] = [round(v, 6) for v in base['wz']]
        if not e.get('vecxz'):
            e['vecxz'] = [float(v) for v in vecxz]
        sellados += 1
    return sellados


def areas_por_elemento(vista_: dict) -> dict:
    """
    {tag: m2} de losa que le llega a cada elemento, sumando sus poligonos.
    Conviven dos formas de escribirlos (el LT2: una entrada por elemento con
    sus poligonos concatenados y 'tamanos'; el cuerpo antiguo: una entrada
    por poligono), y en las dos el area del elemento es la SUMA.
    """
    por_elemento = {}
    for a in (vista_ or {}).get('areas_tributarias', []) or []:
        try:
            tag = int(a['elemento'])
        except (KeyError, TypeError, ValueError):
            continue
        por_elemento[tag] = por_elemento.get(tag, 0.0) + float(a.get('area', 0.0))
    return por_elemento


# ============================================================
# UNIR (para el visor) Y SUBDIVIDIR (para las pruebas)
# ============================================================
def unir(estructura_: dict, vista_: dict = None, resultados: dict = None) -> dict:
    """
    El diccionario que espera el visor: la estructura, la vista y, si vienen
    resultados, los desplazamientos pegados en cada nodo -las traslaciones Y
    LOS GIROS, porque el visor curva cada barra con las funciones de forma
    de sus dos nodos (VisorEstructura.CurvaDe) y sin rx/ry/rz la dibuja recta.
    """
    completo = dict(estructura_)
    if vista_:
        completo.update(vista_)
    if resultados:
        desp = {int(d['id']): d for d in resultados.get('desplazamientos', [])}
        nodos = []
        for n in completo.get('nodos', []):
            n = dict(n)
            d = desp.get(int(n['id']))
            if d:
                n['ux'], n['uy'], n['uz'] = d['ux'], d['uy'], d['uz']
                for g in ('rx', 'ry', 'rz'):
                    n[g] = d.get(g, 0.0)
            nodos.append(n)
        completo['nodos'] = nodos
    return completo


def subdividir(modelo, ids, veces):
    """
    Una copia del modelo con cada elemento de `ids` partido en `veces`
    tramos iguales. Los nodos nuevos toman los tags siguientes al mayor y
    heredan el diafragma del nodo inicial; la carga distribuida se copia
    (es por unidad de largo) y el area tributaria se reparte. Lo usan la
    prueba "viga partida no es rotula" y la carga movil.
    """
    m = copy.deepcopy(modelo)
    nodos = {int(n['id']): n for n in m['nodos']}
    elems = {int(e['id']): e for e in m['elementos']}
    sig_n = max(nodos) + 1
    sig_e = max(elems) + 1
    de_nodo = indice_de_diafragma(m)

    for eid in ids:
        e = elems[eid]
        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        dia = de_nodo.get(int(e['n1']))
        nuevos = []
        for k in range(1, veces):
            t = k / float(veces)
            n = {'id': sig_n, 'fijo': False, 'auxiliar': False,
                 'restricciones': [0, 0, 0, 0, 0, 0]}
            for c in 'xyz':
                n[c] = float(a[c]) + t * (float(b[c]) - float(a[c]))
            m['nodos'].append(n)
            nuevos.append(sig_n)
            # El nodo nuevo esta en la losa: lo ata el mismo diafragma.
            if dia is not None:
                m['diafragmas'][dia]['nodos'].append(sig_n)
            sig_n += 1

        cadena = [int(e['n1'])] + nuevos + [int(e['n2'])]
        e['n2'] = cadena[1]
        if 'area_tributaria' in e:
            e['area_tributaria'] = float(e['area_tributaria']) / veces
        hijos = [e]
        for k in range(1, veces):
            h = copy.deepcopy(e)
            h['id'] = sig_e
            sig_e += 1
            h['n1'], h['n2'] = cadena[k], cadena[k + 1]
            m['elementos'].append(h)
            hijos.append(h)
        for caso in m['casos_de_carga']:
            extra = []
            for c in caso.get('cargas_distribuidas', []):
                if int(c['elemento']) == eid:
                    for h in hijos[1:]:
                        d = dict(c)
                        d['elemento'] = h['id']
                        extra.append(d)
            caso['cargas_distribuidas'].extend(extra)
    return m


# ============================================================
# VALIDAR
# ============================================================
def validar(modelo: dict) -> list:
    """
    Revisa que el modelo se pueda resolver. Devuelve la lista de problemas;
    vacia si esta sano. Lo que se revisa es lo que rompe EN SILENCIO:

      - una CARGA sobre un nodo o elemento que ya no existe: OpenSees avisa
        por consola y la DESCARTA; el analisis "funciona" con menos peso y el
        equilibrio cierra igual, porque esa carga nunca entro;
      - un elemento que apunta a un nodo o a una seccion que no existe;
      - un diafragma cuyos nodos no estan todos a la misma cota.
    """
    problemas = []
    for k in OBLIGATORIAS:
        if k not in modelo:
            problemas.append('falta la clave obligatoria %r' % k)
    if problemas:
        return problemas

    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}
    secciones = {s['nombre'] for s in modelo['secciones']}

    for e in modelo['elementos']:
        for extremo in ('n1', 'n2'):
            if int(e[extremo]) not in nodos:
                problemas.append('el elemento %s apunta al nodo %s, que no existe'
                                 % (e['id'], e[extremo]))
        if e.get('seccion') and e['seccion'] not in secciones:
            problemas.append('el elemento %s usa la seccion %r, que no esta declarada'
                             % (e['id'], e['seccion']))

    for caso in modelo.get('casos_de_carga', []):
        n = caso.get('nombre', '?')
        for c in caso.get('cargas_nodales', []):
            if int(c['nodo']) not in nodos:
                problemas.append('caso %s: carga sobre el nodo %s, que no existe '
                                 '(OpenSees la descartaria en silencio)' % (n, c['nodo']))
        for c in caso.get('cargas_distribuidas', []):
            if int(c['elemento']) not in elementos:
                problemas.append('caso %s: carga distribuida sobre el elemento %s, '
                                 'que no existe (OpenSees la descartaria en silencio)'
                                 % (n, c['elemento']))

    for d in modelo.get('diafragmas', []):
        maestro = int(d['nodo_maestro'])
        if maestro not in nodos:
            problemas.append('diafragma con maestro %s, que no existe' % maestro)
            continue
        z = nodos[maestro].get('z')
        for s in d.get('nodos', []):
            if int(s) not in nodos:
                problemas.append('diafragma %s: el esclavo %s no existe' % (maestro, s))
            elif abs(nodos[int(s)].get('z', z) - z) > 1e-6:
                problemas.append('diafragma %s: el esclavo %s esta a otra cota '
                                 '(%.4f vs %.4f)' % (maestro, s, nodos[int(s)]['z'], z))

    for b in modelo.get('brazos_rigidos', []):
        for extremo in ('maestro', 'esclavo'):
            if int(b[extremo]) not in nodos:
                problemas.append('brazo rigido: el nodo %s no existe' % b[extremo])
    return problemas


def resumen(modelo: dict) -> str:
    """Una linea con el tamano del modelo, para los mensajes."""
    tipos = {}
    for e in modelo.get('elementos', []):
        tipos[e.get('tipo', '?')] = tipos.get(e.get('tipo', '?'), 0) + 1
    detalle = ', '.join('%d %s' % (v, k) for k, v in sorted(tipos.items()))
    return ('%d nodos, %d elementos (%s), %d secciones, %d diafragmas, %d caso(s)'
            % (len(modelo.get('nodos', [])), len(modelo.get('elementos', [])),
               detalle, len(modelo.get('secciones', [])),
               len(modelo.get('diafragmas', [])),
               len(modelo.get('casos_de_carga', []))))
