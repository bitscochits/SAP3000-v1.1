# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/esfuerzos.py  -  DE LAS FUERZAS DE EXTREMO A LOS DIAGRAMAS
================================================================
 OpenSees entrega doce numeros por barra (localForce): las fuerzas
 que los nudos le hacen AL elemento en sus extremos. Con la carga
 uniforme local w = (wx, wy, wz) del caso, el equilibrio de un trozo
 [0, x] da los esfuerzos internos en cualquier punto:

     N(x)  = -(N_i + wx x)            traccion positiva
     Vy(x) = -(Vy_i + wy x)           Vz(x) = -(Vz_i + wz x)
     T(x)  = -T_i
     My(x) = -(My_i + x Vz_i + wz x^2/2)
     Mz(x) = -(Mz_i - x Vy_i - wy x^2/2)

 En x = L eso tiene que devolver f_j, que OpenSees calculo por su
 lado. Es la AUTOVERIFICACION: si algun elemento de algun caso no
 cierra dentro de lo que explica el redondeo del servidor, los
 resultados no se escriben. Ver cociente_de_cierre().

 Una barra sin carga repartida tiene diagramas lineales y basta con
 sus dos extremos; con carga, el momento es una parabola y se
 muestrea en nueve puntos.

 Aca vive tambien caso_resuelto(): un caso o una combinacion de los
 casos del laboratorio con sus desplazamientos, sus esfuerzos por
 estacion y su demanda contra la curva P-M. Lo usan los resultados
 (los 15 casos), la superposicion E1..E3 y el servidor (/combinar).
================================================================
"""
from __future__ import annotations

import math
import sys

from calculo import capacidad
from calculo import demanda as dc
from calculo import edificio as _ed
from calculo import laboratorio as lab

CASOS_BASE = lab.CASOS_BASE
N_ESTACIONES_CARGADA = 9

# El servidor redondea las fuerzas a 4 decimales (extraer_resultados):
# cada valor de f puede estar corrido hasta 5e-5 de lo que calculo
# OpenSees. Es la unica fuente de desacuerdo entre esfuerzo(L) y f_j.
COTA_REDONDEO = 5e-5

# Los mismos decimales que el servidor: escribir mas seria inventar
# precision que no existe.
DECIMALES_FUERZA = 4
DECIMALES_ESTACION = 4
DECIMALES_DESPLAZAMIENTO = 8

CONVENCION = [
    'f = eleResponse(tag, localForce): [N,Vy,Vz,T,My,Mz] en i y en j, fuerzas '
    'SOBRE el elemento en ejes locales',
    'w = (wx, wy, wz) carga uniforme en ejes locales (eleLoad -beamUniform)',
    'N(x) = -(N_i + wx x), traccion positiva',
    'Vy(x) = -(Vy_i + wy x);  Vz(x) = -(Vz_i + wz x);  T(x) = -T_i',
    'My(x) = -(My_i + x Vz_i + wz x^2/2);  Mz(x) = -(Mz_i - x Vy_i - wy x^2/2)',
    'en x = L cada esfuerzo devuelve f_j, a la cota de redondeo del servidor',
    'viga simplemente apoyada con wz < 0: My < 0 en el tramo',
    'dibujo del lado traccionado: My en +My*z_local, Mz en -Mz*y_local',
    'Vz en +Vz*z_local, Vy en +Vy*y_local, N y T en +valor*z_local',
    'demanda: P positivo en compresion; columna M = hypot(My, Mz); '
    'muro M = |My| o |Mz|, el de su plano (elemento.momento_en_el_plano)',
]


# ============================================================
# ESFUERZOS INTERNOS
# ============================================================
def estaciones(L, cargada):
    """Donde se evalua la barra: 9 puntos si hay carga repartida (el
    momento es una parabola), los dos extremos si no (es lineal)."""
    L = float(L)
    if not cargada:
        return [0.0, L]
    n = N_ESTACIONES_CARGADA - 1
    return [L * i / n for i in range(n + 1)]


def esfuerzos_internos(f, w, xs):
    """
    Los esfuerzos internos en cada x, por equilibrio del trozo [0, x]
    con las fuerzas del extremo i y la carga uniforme w = (wx, wy, wz).
    Ver el encabezado para las formulas y su convencion de signos.
    """
    Ni, Vyi, Vzi, Ti, Myi, Mzi = [float(v) for v in f[:6]]
    wx, wy, wz = [float(v) for v in w]
    salida = {'N': [], 'Vy': [], 'Vz': [], 'T': [], 'My': [], 'Mz': []}
    for x in xs:
        x = float(x)
        salida['N'].append(-(Ni + wx * x))
        salida['Vy'].append(-(Vyi + wy * x))
        salida['Vz'].append(-(Vzi + wz * x))
        salida['T'].append(-Ti)
        salida['My'].append(-(Myi + x * Vzi + wz * x * x / 2.0))
        salida['Mz'].append(-(Mzi - x * Vyi - wy * x * x / 2.0))
    return salida


def cargas_por_elemento(caso):
    """{id: (wx, wy, wz)} con las distribuidas del caso. Si un elemento
    trae mas de una entrada se suman: OpenSees las aplica todas."""
    salida = {}
    for c in caso.get('cargas_distribuidas', []):
        t = int(c['elemento'])
        wx, wy, wz = salida.get(t, (0.0, 0.0, 0.0))
        salida[t] = (wx + float(c.get('wx', 0.0)),
                     wy + float(c.get('wy', 0.0)),
                     wz + float(c.get('wz', 0.0)))
    return salida


def magnitudes_de_cierre(f, w, L):
    """
    El tamano de los terminos que entran a esfuerzo(L) - f_j, por
    componente: |f_i| + |f_j| + lo que aporta la carga y, en los
    momentos, x*V_i. Sirve para acotar el error de coma flotante.
    """
    f = [abs(float(v)) for v in f]
    wx, wy, wz = [abs(float(v)) for v in w]
    return [f[0] + f[6] + wx * L,
            f[1] + f[7] + wy * L,
            f[2] + f[8] + wz * L,
            f[3] + f[9],
            f[4] + f[10] + L * f[2] + wz * L * L / 2.0,
            f[5] + f[11] + L * f[1] + wy * L * L / 2.0]


# Cada numero decimal redondeado que no es representable en binario, y
# cada suma o producto de la formula y de la combinacion, se corre a lo
# mas eps/2 de su tamano. Hay menos de ocho de esos por componente, asi
# que 4 eps por la magnitud acota esa parte. Se midio en el conjunto: el
# elemento 100103 bajo G cierra Vz con error 1e-4 + 3.3e-15, justo el
# redondeo mas la representacion binaria de 35.4688, que no es exacta.
FACTOR_COMA_FLOTANTE = 4.0 * sys.float_info.epsilon


def cota_de_cierre(L, suma_lambdas, magnitudes=None):
    """
    Cuanto puede discrepar esfuerzo(L) de f_j sin que nadie se haya
    equivocado, por componente [N, Vy, Vz, T, My, Mz].

    Lo que manda es el redondeo del servidor: N, V y T mezclan dos
    valores redondeados (el de i y el de j); My y Mz ademas llevan
    x*V_i, que multiplica su redondeo por L. En una combinacion cada
    caso aporta el suyo escalado por su lambda.

    Encima, si se da la magnitud de los terminos (sumada por caso con
    |lambda|), la coma flotante: del orden de 1e-14 contra 1e-4, no
    esconde nada, pero sin ella un error de EXACTAMENTE dos redondeos
    marca 1.000000000003 y detiene la exportacion.
    """
    corto = COTA_REDONDEO * 2.0 * suma_lambdas
    largo = COTA_REDONDEO * (2.0 + L) * suma_lambdas
    cotas = [corto, corto, corto, corto, largo, largo]
    if magnitudes is not None:
        cotas = [c + FACTOR_COMA_FLOTANTE * m for c, m in zip(cotas, magnitudes)]
    return cotas


def cociente_de_cierre(f, w, L, suma_lambdas, magnitudes=None):
    """(peor error/cota, componente) de un elemento en x = L."""
    en_L = esfuerzos_internos(f, w, [L])
    cotas = cota_de_cierre(L, suma_lambdas, magnitudes)
    peor = (0.0, 'N')
    for k, nombre in enumerate(('N', 'Vy', 'Vz', 'T', 'My', 'Mz')):
        error = abs(en_L[nombre][0] - float(f[6 + k]))
        c = error / cotas[k] if cotas[k] > 0 else (0.0 if error == 0 else math.inf)
        if c > peor[0]:
            peor = (c, nombre)
    return peor


# ============================================================
# LO QUE EL SERVIDOR LE PASA A OPENSEES
# ============================================================
def restricciones_como_el_servidor(modelo):
    """
    {nodo: [ux,uy,uz,rx,ry,rz]} de los nodos que el servidor fija. Es la
    regla de opensees.construir_modelo (lista a medida, o 'fijo' sin lista
    = empotrado; y los GDL fuera del plano del maestro de un diafragma, si
    nadie los fijo). Replicada y no importada porque alli vive en linea,
    junto a ops.fix; la verificacion de los resultados las compara.
    """
    restr = {}
    for nd in modelo['nodos']:
        r = nd.get('restricciones') or None
        if r is None:
            r = [1, 1, 1, 1, 1, 1] if nd.get('fijo', False) else None
        if r is not None and any(int(v) for v in r):
            restr[int(nd['id'])] = [int(v) for v in r]
    for d in modelo.get('diafragmas', []):
        m = int(d['nodo_maestro'])
        if m not in restr:
            restr[m] = {3: [0, 0, 1, 1, 1, 0], 2: [0, 1, 0, 1, 0, 1],
                        1: [1, 0, 0, 0, 1, 1]}[int(d.get('perpendicular', 3))]
    return restr


def rigidez_como_el_servidor(e, seccion, pi, pj, material):
    """
    E, G, vecxz e inercias de UN elemento tal como los recibe
    ops.element en opensees.construir_modelo:

      material del modelo: Ec = 4700 sqrt(f'c) 1000 kPa, Gc = Ec / (2 (1 + nu))
      vertical por geometria (proyeccion horizontal / L < 1e-6);
          vecxz propio o (1,0,0) vertical, (0,0,1) no
      inercias cruzadas SOLO si no es vertical
      E y G de la seccion si los trae; sin G, nu = 0.3

    El motor lo calcula en linea dentro del bucle, sin una funcion que
    se pueda llamar, asi que se replica aca. Es lo que muestra el panel
    del elemento ("tag_opensees"); la verificacion de los resultados
    captura la llamada real a ops.element y la compara con esto.
    """
    fpc = float(material.get('fpc_MPa', 25.0))
    nu = float(material.get('poisson', 0.2))
    Ec = 4700.0 * math.sqrt(fpc) * 1000.0
    Gc = Ec / (2.0 * (1.0 + nu))

    dx, dy, dz = (pj[0] - pi[0], pj[1] - pi[1], pj[2] - pi[2])
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    vertical = (math.sqrt(dx * dx + dy * dy) / L) < 1e-6
    vecxz = e.get('vecxz') or None
    if vecxz is not None:
        vecxz = (float(vecxz[0]), float(vecxz[1]), float(vecxz[2]))
    else:
        vecxz = (1.0, 0.0, 0.0) if vertical else (0.0, 0.0, 1.0)

    Iy, Iz = float(seccion['Iy']), float(seccion['Iz'])
    Iy_pasa, Iz_pasa = (Iy, Iz) if vertical else (Iz, Iy)

    propio = bool(seccion.get('E'))
    E = float(seccion['E']) if propio else Ec
    if seccion.get('G'):
        G = float(seccion['G'])
    else:
        G = Gc if not propio else E / (2.0 * (1.0 + 0.3))
    return {'E': E, 'G': G, 'poisson': E / (2.0 * G) - 1.0,
            'fpc_MPa': 0.0 if propio else fpc, 'propio': propio,
            'vertical': vertical, 'vecxz': vecxz, 'L': L,
            'Iy_pasa': Iy_pasa, 'Iz_pasa': Iz_pasa}


def _texto_vecxz(v):
    return '(%s)' % ','.join('%g' % c for c in v)


def _texto_restr(r):
    return '[%s]' % ' '.join(str(v) for v in r)


ORIGEN_RESULTADOS = ('laboratorio.resolver() en memoria, con los parametros de '
                     'entrada/laboratorio.json')


# ============================================================
# FAMILIAS P-M
# ============================================================
def _fuente(fe):
    fu = fe.get('fuente') or {}
    partes = []
    if fu.get('lamina'):
        partes.append('lamina %s' % fu['lamina'])
    if fu.get('elevacion'):
        partes.append(str(fu['elevacion']))
    if fu.get('eje'):
        partes.append('eje %s' % fu['eje'])
    return ', '.join(partes) or '(sin fuente declarada)'


def _refuerzo(e, sec):
    fe = e.get('enfierradura') or {}
    if fe.get('tipo') == 'muro':
        mv = (fe.get('malla_vertical') or {}).get('texto') or '-'
        return ('malla vertical %s en %d capas + %d barras de borde (%d barras)'
                % (mv, int(fe.get('capas', 2)), len(fe.get('barras_de_borde') or []),
                   len(sec.barras)))
    lon = fe.get('longitudinal') or {}
    return ('%d D%g (%s por cara), estribo %s'
            % (len(sec.barras), float(lon.get('diametro_mm', 0.0)),
               lon.get('por_cara', '?'), (sec.estribo or {}).get('texto', '-')))


def _clave_legible(firma):
    seccion, b, h, n, As, estribo, malla = firma
    return ('%s | %.2f x %.2f m | %d barras | As = %.2f cm2 | estribo %s | malla %s'
            % (seccion, b, h, n, As * 1e4, estribo or '-', malla or '-'))


def bloque_familias(modelo):
    """
    Una curva por familia de enfierradura, en orden de aparicion por id.
    Agrupa con demanda.firma_de_seccion, la misma clave que usa la
    revision (--todas): dos elementos con la misma firma comparten curva.
    """
    con_fierro = sorted((e for e in modelo['elementos'] if e.get('enfierradura')),
                        key=lambda e: int(e['id']))
    familias, indice_de, familia_de, secciones, curvas = [], {}, {}, {}, {}
    for e in con_fierro:
        eid = int(e['id'])
        sec = capacidad.desde_elemento(modelo, eid)
        secciones[eid] = sec
        firma = dc.firma_de_seccion(e, sec)
        if firma not in indice_de:
            i = len(familias)
            indice_de[firma] = i
            puntos = capacidad.interaccion(sec)
            curvas[i] = puntos
            familias.append({
                'indice': i,
                'clave': _clave_legible(firma),
                'tipo': e.get('tipo', ''),
                'seccion': e.get('seccion', ''),
                'b': round(sec.b, 4),
                'h': round(sec.h, 4),
                'As_cm2': round(sec.As * 1e4, 4),
                'cuantia_pct': round(100.0 * sec.cuantia, 4),
                'refuerzo': _refuerzo(e, sec),
                'fuente': _fuente(e['enfierradura']),
                'P': [round(float(p['P_kN']), DECIMALES_FUERZA) for p in puntos],
                'Mn': [round(float(p['M_kNm']), DECIMALES_FUERZA) for p in puntos],
                'Mmax': [round(float(p.get('M_max_kNm', 0.0)), DECIMALES_FUERZA)
                         for p in puntos],
                'de': [str(p.get('de', '')) for p in puntos],
                'elementos': [],
            })
        familia_de[eid] = indice_de[firma]
        familias[indice_de[firma]]['elementos'].append(eid)
    return familias, familia_de, secciones, curvas


# ============================================================
# ELEMENTOS
# ============================================================
def bloque_elementos(modelo, cargas, familia_de):
    """Lo fijo de cada elemento: ids, seccion, material, ejes, apoyos."""
    nodos = {int(n['id']): (float(n['x']), float(n['y']), float(n['z']))
             for n in modelo['nodos']}
    secciones = {s['nombre']: s for s in modelo['secciones']}
    material = modelo.get('material', {})
    restr = restricciones_como_el_servidor(modelo)
    de_nodo = _ed.indice_de_diafragma(modelo)
    maestros = [int(d['nodo_maestro']) for d in modelo.get('diafragmas', [])]

    def maestro_de(n):
        i = de_nodo.get(n)
        return maestros[i] if i is not None else -1

    salida = []
    for e in sorted(modelo['elementos'], key=lambda e: int(e['id'])):
        eid, n1, n2 = int(e['id']), int(e['n1']), int(e['n2'])
        tipo = e.get('tipo', '')
        s = secciones[e['seccion']]
        k = rigidez_como_el_servidor(e, s, nodos[n1], nodos[n2], material)

        if k['propio']:
            texto_mat = 'E y G propios de la seccion'
            if s.get('E_del_cuerpo'):
                texto_mat += ' (cuerpo %s)' % s['E_del_cuerpo']
        else:
            texto_mat = "hormigon f'c %g MPa, Ec = 4700 sqrt(f'c)" % k['fpc_MPa']

        es_brazo = tipo in ('brazo', 'brazo_rigido')
        r1, r2 = restr.get(n1, [0] * 6), restr.get(n2, [0] * 6)
        d1, d2 = maestro_de(n1), maestro_de(n2)
        condiciones = []
        for nombre, n, r, d in (('n1', n1, r1, d1), ('n2', n2, r2, d2)):
            if any(r):
                condiciones.append('%s %d: %s %s' % (
                    nombre, n, 'empotrado' if all(r) else 'apoyo', _texto_restr(r)))
            if d >= 0:
                condiciones.append('%s %d: diafragma rigido, maestro %d' % (nombre, n, d))
        if es_brazo:
            condiciones.append('brazo rigido: barra de rigidez x100 hasta la cara del muro')
        if not condiciones:
            condiciones.append('nodos libres: sin apoyo ni diafragma')

        cargada = any(any(v != 0.0 for v in cargas[c].get(eid, (0.0, 0.0, 0.0)))
                      for c in ('G', 'Q'))

        salida.append({
            'id': eid, 'n1': n1, 'n2': n2,
            'tipo': tipo, 'seccion': e['seccion'],
            # El momento que se compara con la curva: el de inercia mayor.
            'momento_en_el_plano': (dc.momento_en_el_plano(s['Iy'], s['Iz'])
                                    if tipo == 'muro' else ''),
            'L': round(k['L'], DECIMALES_ESTACION),
            'objeto_unity': 'Elem_%d_%s' % (eid, tipo),
            'tag_opensees': ('element elasticBeamColumn %d %d %d A=%.4f E=%.4e '
                             'G=%.4e J=%.3e Iy=%.3e Iz=%.3e vecxz=%s'
                             % (eid, n1, n2, float(s['A']), k['E'], k['G'],
                                float(s['J']), k['Iy_pasa'], k['Iz_pasa'],
                                _texto_vecxz(k['vecxz']))),
            'material': texto_mat,
            'fpc_MPa': k['fpc_MPa'],
            'E_kPa': round(k['E'], 4), 'G_kPa': round(k['G'], 4),
            'poisson': round(k['poisson'], 6),
            'gamma': float(s.get('gamma', material.get('gamma', 25.0))),
            'A': float(s['A']), 'Iy': float(s['Iy']), 'Iz': float(s['Iz']),
            'J': float(s['J']),
            # Los muros del cuerpo antiguo declaran largo/espesor en vez de h/b.
            'b': float(s.get('b') or s.get('espesor') or 0.0),
            'h': float(s.get('h') or s.get('largo') or 0.0),
            'vecxz': list(k['vecxz']),
            'restr_n1': r1, 'restr_n2': r2,
            'diafragma_n1': d1, 'diafragma_n2': d2,
            'es_brazo_rigido': es_brazo,
            'condiciones': '; '.join(condiciones),
            'cargada': cargada,
            'familia': familia_de.get(eid, -1),
            'resultados': ORIGEN_RESULTADOS,
        })
    return salida


# ============================================================
# CASOS Y COMBINACIONES
# ============================================================
def lista_de_combinaciones(p):
    """
    Los casos base y despues las combinaciones de entrada/laboratorio.json,
    en su orden. Si la combinacion activa no esta entre ellas (--comb a mano)
    se agrega al final: el caso por defecto tiene que existir en el anexo.
    """
    salida = [(c, 'caso', None, {k: (1.0 if k == c else 0.0) for k in CASOS_BASE})
              for c in CASOS_BASE]
    nombres = set(CASOS_BASE)
    for combo in list(p['combinaciones']) + [p['combinacion']]:
        if combo['nombre'] in nombres:
            continue
        nombres.add(combo['nombre'])
        salida.append((combo['nombre'], 'combinacion', lab.como_texto(combo),
                       lab.factores(combo)))
    return salida


def bloque_caso(nombre, tipo, descripcion, factores, resultados, elementos,
                cargas_base, familias_de, curvas, largos, nucleo_de=None):
    """
    Un caso o una combinacion: desplazamientos, esfuerzos y demandas.
    La combinacion se arma con demanda.combinar -- la suma lineal de la
    revision de demanda -- sobre f, desplazamientos y w.
    Devuelve (bloque, cargas combinadas, peor cierre (cociente, id, comp)).
    """
    activos = {c: l for c, l in factores.items() if l != 0.0}
    suma_lambdas = sum(abs(l) for l in activos.values())

    # --- desplazamientos ---
    por_nodo = {}
    for c in activos:
        for d in resultados[c]['desplazamientos']:
            por_nodo.setdefault(int(d['id']), {})[c] = [
                float(d[k]) for k in ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')]
    desplazamientos, maximo = [], 0.0
    for nid in sorted(por_nodo):
        u = dc.combinar(por_nodo[nid], activos)
        maximo = max(maximo, math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2))
        desplazamientos.append(dict(
            [('id', nid)] + [(k, round(v, DECIMALES_DESPLAZAMIENTO))
                             for k, v in zip(('ux', 'uy', 'uz', 'rx', 'ry', 'rz'), u)]))

    # --- cargas repartidas combinadas ---
    cargas = {}
    for c, l in activos.items():
        for eid, w in cargas_base[c].items():
            cargas.setdefault(eid, {})[c] = list(w)
    cargas = {eid: tuple(dc.combinar(por_caso, activos)) for eid, por_caso in cargas.items()}

    # --- esfuerzos y demandas ---
    fuerzas = {c: {int(x['id']): x['f'] for x in resultados[c]['fuerzas_elementos']}
               for c in activos}
    esfuerzos, demandas = [], []
    peor = (0.0, -1, 'N')
    for e in elementos:
        eid = e['id']
        f = dc.combinar({c: [float(v) for v in fuerzas[c][eid]] for c in activos}, activos)
        w = cargas.get(eid, (0.0, 0.0, 0.0))
        L = largos[eid]
        xs = estaciones(L, any(v != 0.0 for v in w))
        internos = esfuerzos_internos(f, w, xs)

        magnitudes = [0.0] * 6
        for c, l in activos.items():
            m_c = magnitudes_de_cierre(fuerzas[c][eid],
                                       cargas_base[c].get(eid, (0.0, 0.0, 0.0)), L)
            magnitudes = [a + abs(l) * b for a, b in zip(magnitudes, m_c)]
        cociente, comp = cociente_de_cierre(f, w, L, suma_lambdas, magnitudes)
        if cociente > peor[0]:
            peor = (cociente, eid, comp)

        fila = {'id': eid,
                'f': [round(v, DECIMALES_FUERZA) for v in f],
                # La carga que recibe beamUniform, ya combinada: es la que
                # cierra el diagrama, y el visor la dibuja como una magnitud
                # mas para ver la causa al lado del efecto.
                'w': [round(v, DECIMALES_FUERZA) for v in w],
                'x': [round(x, DECIMALES_ESTACION) for x in xs]}
        for k in ('N', 'Vy', 'Vz', 'T', 'My', 'Mz'):
            fila[k] = [round(v, DECIMALES_FUERZA) for v in internos[k]]
        esfuerzos.append(fila)

        fam = familias_de.get(eid, -1)
        if fam >= 0:
            d = dc.demanda(f, e['tipo'], e['momento_en_el_plano'] or None)
            Mn = dc.capacidad_en(d['P_kN'], curvas[fam])
            # El mismo umbral que demanda.revisar.
            u = d['M_kNm'] / Mn if Mn > 1e-9 else 9999.0
            demandas.append({
                'id': eid, 'familia': fam,
                'P': round(d['P_kN'], DECIMALES_FUERZA),
                'M': round(d['M_kNm'], DECIMALES_FUERZA),
                'M_fuera_plano': round(d['M_fuera_de_plano_kNm'] or 0.0, DECIMALES_FUERZA),
                'extremo': d['extremo'],
                'Mn': round(Mn, DECIMALES_FUERZA),
                'u': round(u, 6),
                'pasa': u <= 1.0,
            })

    # --- de que NUCLEO es cada pata (demanda.grupos_de_nucleo) ---
    # NO cambia ningun veredicto: dice de DONDE viene el axial. La
    # traccion que saca a una pata de su curva casi siempre es el par
    # interno de su grupo, y el mapa la mostraba como una falla de
    # capacidad. Va despues del bucle porque necesita el P de TODAS
    # las patas del grupo en ESTE caso.
    # Las cuatro claves van en TODAS las filas, no solo en las patas: el
    # contrato exige que cada campo del C# tenga clave en todos los
    # objetos (verificacion del contrato con Unity). nucleo_patas = 0 es
    # "este elemento no es pata de ningun nucleo".
    P_de = {x['id']: x['P'] for x in demandas}
    for x in demandas:
        g = (nucleo_de or {}).get(x['id'])
        P = sum(P_de.get(i, 0.0) for i in g['patas']) if g else 0.0
        x['nucleo_patas'] = len(g['patas']) if g else 0
        x['nucleo_P'] = round(P, DECIMALES_FUERZA)
        x['nucleo_Asfy'] = round(g['Asfy_kN'], DECIMALES_FUERZA) if g else 0.0
        x['nucleo_estado'] = dc.estado(P, g['Asfy_kN']) if g else ''

    bloque = {
        'nombre': nombre,
        'tipo': tipo,
        'descripcion': descripcion,
        'factores': [factores[c] for c in CASOS_BASE],
        'max_desplazamiento_mm': round(maximo * 1000.0, 4),
        'desplazamientos': desplazamientos,
        'esfuerzos': esfuerzos,
        'demandas': demandas,
    }
    return bloque, cargas, peor


# ============================================================
# LA ESCALA GRAFICA DE LA DEFORMADA
# ============================================================
# El mayor desplazamiento del modelo se dibuja como esta fraccion de la
# diagonal de su caja envolvente. No es un largo en metros: un largo
# fijo se ve enorme en un cuerpo chico y no se ve en uno grande.
FRACCION_DIAGONAL = 0.05


def escala_deformada(modelo, casos):
    r"""
    Cuanto hay que exagerar la deformada para que se VEA. Se calcula
    aca y viaja en info.escala_deformada: Python calcula, Unity
    muestra. El visor la usa como valor por defecto y el usuario la
    puede cambiar; es solo grafica y no toca ningun resultado.

    UNA sola por modelo -- la del caso mas deformado de todos -- para
    que la deformada no cambie de tamano al cambiar de caso en el
    visor. Y relativa al TAMANO del modelo: el mayor desplazamiento se
    dibuja como FRACCION_DIAGONAL de la diagonal de la caja envolvente
    de los nodos, asi que dos modelos de tamanos distintos salen igual
    de exagerados. Un factor fijo no puede: el x300 de la escena deja
    al LT2 legible y al conjunto -- caja el doble de larga y el doble
    de desplazamiento -- como una carpa colapsada.

    Devuelve los numeros que los resultados declaran en
    _escala_deformada_por_que y que comprueba la verificacion del
    contrato con Unity:

      escala      el factor, redondeado a 2 cifras significativas
      paso        el ultimo digito de ese redondeo (la tolerancia)
      exacta      el factor antes de redondear
      mayor_mm    el desplazamiento que se lleva al objetivo
      caso        en que caso esta ese desplazamiento
      objetivo_m  FRACCION_DIAGONAL * diagonal_m
      diagonal_m  la diagonal de la caja envolvente de los nodos
      por_que     el texto para el anexo

    Sin desplazamiento (un modelo sin resolver) devuelve escala 0: el
    visor lo lee como "no hay dato" y se queda con lo que tenia.
    """
    xs = [float(n['x']) for n in modelo['nodos']]
    ys = [float(n['y']) for n in modelo['nodos']]
    zs = [float(n['z']) for n in modelo['nodos']]
    caja = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    diagonal = math.sqrt(sum(l * l for l in caja))
    objetivo = FRACCION_DIAGONAL * diagonal
    peor = max(casos, key=lambda c: c['max_desplazamiento_mm'], default=None)
    mayor = peor['max_desplazamiento_mm'] if peor else 0.0
    if mayor <= 0.0 or objetivo <= 0.0:
        return {'escala': 0.0, 'paso': 0.0, 'exacta': 0.0, 'mayor_mm': mayor,
                'caso': peor['nombre'] if peor else '', 'objetivo_m': objetivo,
                'diagonal_m': diagonal,
                'por_que': 'sin desplazamiento que dibujar: no hay escala'}

    exacta = objetivo / (mayor / 1000.0)
    # Dos cifras significativas, para que sea un numero que se pueda
    # decir en voz alta (x89, x82) y no un x89.1307. Es el mismo
    # redondeo que la escala de la carga movil ('%.2g').
    paso = 10.0 ** (math.floor(math.log10(exacta)) - 1)
    escala = round(round(exacta / paso) * paso, 10)
    por_que = ('solo grafica, no cambia ningun calculo: el mayor desplazamiento del '
               'modelo (%.4f mm, en %s, de %d casos) se dibuja como %.2f m, el %g %% de '
               'la diagonal de su caja envolvente (%.2f m, de %.2f x %.2f x %.2f m). '
               'Factor exacto x%.4f, redondeado a x%g (2 cifras, paso %g). UNA para todo '
               'el modelo: con una por caso, la deformada cambiaria de tamano al cambiar '
               'de caso. El visor la usa de valor por defecto y el deslizador manda.'
               % (mayor, peor['nombre'], len(casos), objetivo, 100.0 * FRACCION_DIAGONAL,
                  diagonal, caja[0], caja[1], caja[2], exacta, escala, paso))
    return {'escala': escala, 'paso': paso, 'exacta': exacta, 'mayor_mm': mayor,
            'caso': peor['nombre'], 'objetivo_m': objetivo, 'diagonal_m': diagonal,
            'por_que': por_que}


# ============================================================
# LA BASE: LOS CASOS DEL LABORATORIO RESUELTOS UNA VEZ
# ============================================================
def base(argv=()):
    """
    Todo lo que hace falta para armar CUALQUIER caso o combinacion del
    laboratorio, calculado una vez: los parametros, los casos resueltos en
    OpenSees, las cargas repartidas por caso, las familias P-M con sus
    curvas, los datos de cada elemento, los largos y los nucleos. La usan
    los resultados (15 casos), la superposicion E1..E3, el servidor
    (/combinar) y el Excel.
    """
    p = lab.cargar(list(argv))
    modelo = _ed.estructura()
    arm = lab.armar_casos(modelo, p)
    datos, resultados = lab.resolver(modelo, arm['casos'])

    cargas_base = {c: cargas_por_elemento(arm['casos'][c]) for c in CASOS_BASE}
    familias, familia_de, secciones, curvas = bloque_familias(modelo)
    elementos = bloque_elementos(modelo, cargas_base, familia_de)

    nodos = {int(n['id']): n for n in modelo['nodos']}
    por_id = {int(e['id']): e for e in modelo['elementos']}
    largos = {eid: _ed.largo(e, nodos) for eid, e in por_id.items()}

    # Los grupos de nucleo y el As*fy de cada uno se calculan UNA vez
    # (cada As*fy arma una seccion de fibras); despues cada caso solo
    # suma los P de las patas. Ver demanda.grupos_de_nucleo.
    _cache = {}
    nucleo_de = {}
    for eid, patas in dc.grupos_de_nucleo(modelo).items():
        asfy, sin_fierro = dc.asfy_de(modelo, patas, _cache)
        nucleo_de[eid] = {'patas': patas, 'Asfy_kN': asfy,
                          'sin_fierro': len(sin_fierro)}

    return {'p': p, 'modelo': modelo, 'arm': arm, 'datos': datos,
            'resultados': resultados, 'cargas_base': cargas_base,
            'familias': familias, 'familia_de': familia_de,
            'secciones': secciones, 'curvas': curvas, 'elementos': elementos,
            'por_id': por_id, 'largos': largos, 'nucleo_de': nucleo_de}
