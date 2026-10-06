# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/suite.py  -  TODA LA SUITE, DE UNA
================================================================
 Corre cada verificacion del proyecto y dice cual paso.

 Correr:
   python sap.py verificar                       las 42
   python sap.py verificar --rapido              sin las seis lentas (36)
   python sap.py verificar --solo edificio sismo  las que nombran esas palabras
   python sap.py verificar --solo E2 L4          o esas entradas, por su codigo
   python sap.py verificar --lista               la lista, sin correr nada
   python sap.py revisar qa                      la tabla de 10 filas (tabla_qa)

 Es el comando para antes de un commit y para el dia de la
 demostracion. Si aca sale todo en OK, el proyecto esta como se entrega.

 Cada entrada es un bloque que ya se puede correr solo, desde la raiz:

     python -m verificacion.<modulo> <bloque>

 este archivo no verifica nada por su cuenta: los llama en orden, cada
 uno en su propio proceso (OpenSees tiene estado global: una corrida no
 puede heredar el modelo de la anterior), y resume. Asi la lista de
 abajo es tambien el indice de QUE se comprueba y DONDE.

 NINGUNA ENTRADA ESCRIBE EN salidas/: comparan. Que las salidas esten al
 dia es una entrada mas (R1, U3), no un efecto lateral de la suite que
 pisaria lo que se esta mirando en Unity.

 Los numeros que no pueden cambiar sin una decision estan en
 verificacion/numeros_de_control.json; los leen las entradas que los
 miden y la tabla QA (control()).
================================================================
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import os
import re
import subprocess
import sys
import time

from calculo import edificio as _ed
from calculo import rutas
from verificacion.comun import medio_digito, titulo

NUMEROS = os.path.join(rutas.RAIZ, 'verificacion', 'numeros_de_control.json')

# (codigo, etiqueta, argumentos de python -m, es lenta)
SUITE = [
    # --- el edificio: el dato, la junta libre, la losa y el modelo
    ('E1', 'edificio: dato', ['verificacion.edificio', 'dato'], False),
    ('E2', 'edificio: junta libre', ['verificacion.edificio', 'junta'], False),
    ('E3', 'edificio: losa aplicada = dibujada', ['verificacion.edificio', 'tributarias'], False),
    ('E4', 'edificio: modelo', ['verificacion.edificio', 'modelo'], True),
    # --- el motor: el benchmark, el servidor y los casos del modelo
    ('M1', 'motor: benchmark y servidor', ['verificacion.motor', 'servidor'], False),
    ('M2', 'motor: casos del modelo', ['verificacion.motor', 'casos_del_modelo'], False),
    ('M3', 'motor: reanalisis = modelo', ['verificacion.motor', 'reanalisis'], False),
    ('M4', 'motor: M1 borrar columna 200069', ['verificacion.motor', 'm1'], False),
    ('M5', 'motor: M3 seccion de una viga', ['verificacion.motor', 'm3'], False),
    ('M6', 'motor: M4 soltar un apoyo', ['verificacion.motor', 'm4'], False),
    ('M7', 'motor: viga partida no es rotula', ['verificacion.motor', 'viga_partida'], False),
    # --- el laboratorio: parametros, partes A/B/C, sismo, superposicion, M2
    ('L1', 'laboratorio: parametros', ['verificacion.laboratorio', 'parametros'], False),
    ('L2', 'laboratorio: Partes A, B y C', ['verificacion.laboratorio', 'partes_abc'], False),
    ('L3', 'laboratorio: sismo del modelo', ['verificacion.laboratorio', 'sismo'], False),
    ('L4', 'laboratorio: superposicion contra corrida explicita',
     ['verificacion.laboratorio', 'superposicion_explicita'], True),
    ('L5', 'laboratorio: M2 cs 0.20', ['verificacion.laboratorio', 'm2'], False),
    # --- la capacidad: fibras, a mano, demanda, nucleos, losa colaborante
    ('C1', 'capacidad: M-phi y P-M', ['verificacion.capacidad', 'mphi_pm'], False),
    ('C2', 'capacidad: fibras contra calculo a mano', ['verificacion.capacidad', 'rc_a_mano'], True),
    ('C3', 'capacidad: demanda --todas', ['verificacion.capacidad', 'demanda_todas'], False),
    ('C4', 'capacidad: nucleos = grupos de resultados.json', ['verificacion.capacidad', 'nucleos'], False),
    ('C5', 'capacidad: losa colaborante (regla)', ['verificacion.capacidad', 'losa_colaborante'], False),
    # --- los resultados del laboratorio que lee el visor
    ('R1', 'resultados: al dia y cierre f_j', ['verificacion.resultados', 'al_dia'], False),
    ('R2', 'resultados: esfuerzos y signos [1]-[8]', ['verificacion.resultados', 'bloques_1_8'], False),
    ('R3', 'resultados: trazabilidad 100018', ['verificacion.resultados', 'trazabilidad'], False),
    ('R4', 'resultados: superposicion E1..E3 por 4 vias',
     ['verificacion.resultados', 'superposicion_4_vias'], False),
    ('R5', 'resultados: sliders instantaneos (replica)', ['verificacion.resultados', 'instantanea'], False),
    # --- la carga movil, la persona y el relieve
    ('P1', 'carga movil [a]-[i]', ['exportar.carga_movil', '--no-escribir'], False),
    ('P2', 'persona: suma = OpenSees', ['verificacion.persona', 'suma_igual_opensees'], False),
    ('P3', 'relieve del sitio', ['exportar.relieve', '--no-escribir', '--verificar'], False),
    # --- el contrato con Unity. U4 abre el editor en batch: es lento y
    # sale con 2 si Unity ya esta abierto.
    ('U1', 'unity: contrato JSON <-> C#', ['verificacion.unity', 'contratos'], False),
    ('U2', 'unity: transcripciones C# = elastica.py', ['verificacion.unity', 'transcripciones'], False),
    ('U3', 'unity: nombres y copias al dia', ['verificacion.unity', 'nombres_y_copias'], False),
    ('U4', 'unity: JsonUtility real', ['verificacion.unity', 'jsonutility'], True),
    # --- el Excel
    ('X1', 'excel: libro y reanalisis', ['verificacion.excel', 'libro'], True),
    # --- lo que la app registro al capturar (verificacion/registros/capturas)
    ('K1', 'capturas: visor', ['verificacion.capturas', 'visor'], False),
    ('K2', 'capturas: persona', ['verificacion.capturas', 'persona'], False),
    ('K3', 'capturas: relieve', ['verificacion.capturas', 'relieve'], False),
    # --- la app de realidad aumentada. A2 abre Chrome o Edge sin ventana.
    ('A1', 'AR: tags, resultados y pose', ['verificacion.ar', 'ids_resultados_pose'], False),
    ('A2', 'AR: registro y tracking', ['verificacion.ar', 'registro_y_tracking'], True),
    ('A3', 'AR: precision del registro', ['verificacion.ar', 'precision'], False),
    # --- los recursos de la vista realista y el AT-ST
    ('H1', 'vista realista: recursos', ['herramientas.recursos_realistas', '--verificar'], False),
    ('H2', 'persona: el AT-ST', ['herramientas.atst', '--verificar'], False),
]


# ============================================================
# EL CORREDOR
# ============================================================
def correr(args):
    """(paso, segundos, salida) de `python -m <args>` con cwd = la raiz."""
    t0 = time.time()
    # El hijo escribe a un pipe, y en Windows un pipe sale con la pagina de
    # codigos del sistema (cp1252), no con UTF-8: una 'φ' en un print tumbaba
    # una verificacion con UnicodeEncodeError y la entrada salia FALLA fuera
    # de una terminal que ya tuviera PYTHONIOENCODING. Se lee como UTF-8
    # abajo, asi que el hijo tiene que escribir UTF-8.
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, '-m'] + list(args), cwd=rutas.RAIZ,
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env)
    return r.returncode == 0, time.time() - t0, (r.stdout + r.stderr)


def comando(args):
    return 'python -m ' + ' '.join(args)


def consola_tolerante():
    """
    Que un caracter que la consola no sabe escribir ('φ', '·') no tumbe la
    corrida: en Windows, sin PYTHONIOENCODING, la consola es cp1252 y un
    print con esos caracteres muere con UnicodeEncodeError. Se reemplaza el
    caracter y se sigue.
    """
    try:
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass


def elegidas(rapido=False, solo=None):
    """Las entradas que tocan: sin las lentas con --rapido; con --solo, las
    que nombran alguna palabra (en el codigo exacto, la etiqueta o el comando)."""
    codigos = {e[0] for e in SUITE}
    salida = []
    for codigo, etiqueta, args, lenta in SUITE:
        if rapido and lenta:
            continue
        if solo:
            texto = ('%s %s' % (etiqueta, ' '.join(args))).lower()
            # Un codigo (E1, L4...) nombra SU entrada y ninguna otra: 'e1'
            # tambien aparece en "superposicion E1..E3".
            if not any((s.upper() == codigo) if s.upper() in codigos else (s.lower() in texto)
                       for s in solo):
                continue
        salida.append((codigo, etiqueta, args, lenta))
    return salida


def main(argv=None):
    consola_tolerante()
    argv = list(sys.argv[1:] if argv is None else argv)
    rapido = '--rapido' in argv
    lista = '--lista' in argv
    solo = None
    if '--solo' in argv:
        solo = [a for a in argv[argv.index('--solo') + 1:] if not a.startswith('--')]
        if not solo:
            raise SystemExit('--solo necesita al menos una palabra o un codigo (E1, L4...)')
    desconocidos = [a for a in argv if a.startswith('--')
                    and a not in ('--rapido', '--lista', '--solo')]
    if desconocidos:
        raise SystemExit('no conozco %s (son: --rapido, --solo PALABRA..., --lista)'
                         % ', '.join(desconocidos))
    entradas = elegidas(rapido, solo)

    if lista:
        print('%d entradas%s%s' % (len(entradas), ' (sin las lentas)' if rapido else '',
                                   (' que nombran %s' % ', '.join(solo)) if solo else ''))
        for codigo, etiqueta, args, lenta in entradas:
            print('  %-3s %-52s %s  %s' % (codigo, etiqueta, 'L' if lenta else ' ', comando(args)))
        print()
        print('  L = lenta (--rapido la deja fuera)')
        return 0
    if not entradas:
        raise SystemExit('ninguna entrada nombra %s: python sap.py verificar --lista' % ', '.join(solo))

    ancho = max(len(e[1]) for e in entradas)
    print('=' * 78)
    print('  SUITE COMPLETA   (%s)' % rutas.RAIZ)
    print('=' * 78)
    fallaron, n = [], 0
    for codigo, etiqueta, args, _lenta in entradas:
        n += 1
        ok, dt, salida = correr(args)
        print('  %-3s %-*s %-5s %6.1fs   %s'
              % (codigo, ancho, etiqueta, 'OK' if ok else 'FALLA', dt, comando(args)))
        if not ok:
            fallaron.append((codigo, etiqueta, args, salida))

    print('=' * 78)
    print('  %d de %d EN OK' % (n - len(fallaron), n))
    if fallaron:
        print('  FALLARON %d: %s' % (len(fallaron), ', '.join(f[0] for f in fallaron)))
        for codigo, etiqueta, args, salida in fallaron:
            print()
            print('--- %s %s   (%s)' % (codigo, etiqueta, comando(args)))
            print('\n'.join('    ' + l for l in salida.strip().splitlines()[-12:]))
        return 1
    return 0


# ============================================================
# LOS NUMEROS DE CONTROL
# ============================================================
_NUMEROS = {}


def numeros_de_control():
    """verificacion/numeros_de_control.json entero (se lee una vez)."""
    if not _NUMEROS:
        with io.open(NUMEROS, encoding='utf-8') as fh:
            _NUMEROS.update(json.load(fh))
    return _NUMEROS


def control(*claves):
    r"""
    (valor, cota) de un numero de control: control('edificio', 'G_kN').

    Los decimales van escritos como TEXTO con los digitos con que se
    comparan ('16.8000'): la cota es medio ultimo digito escrito. Como
    numero, 16.8 y 16.8000 serian lo mismo y no se sabria a cuantos
    decimales exigirlo. Los enteros (conteos, tags) se exigen exactos.
    """
    v = numeros_de_control()
    for k in claves:
        v = v[k]
    if isinstance(v, str):
        return float(v), medio_digito(v)
    return v, 0


def calza(medido, *claves):
    """Si `medido` es el numero de control, dentro de medio ultimo digito escrito."""
    valor, cota = control(*claves)
    return abs(float(medido) - valor) <= cota * (1 + 1e-9)


# ============================================================
# LA TABLA QA: diez filas, sin volver a correr guardias
# ============================================================
# Cada fila corre su prueba con las funciones del proyecto -- ninguna
# regla se copia -- y decide su estado con un criterio escrito al lado de
# su causa:
#
#   OK       la prueba corrio y cumple su criterio.
#   PARCIAL  cumple lo que se puede comprobar, pero hay algo abierto que
#            la misma prueba MIDE y dice cuanto vale. El dia que se
#            arregle, la fila pasa sola a OK.
#   FALLA    no cumple. La tabla termina con codigo 1.
#
# Las filas viven donde vive su tema (verificacion/laboratorio.py y
# verificacion/capacidad.py) y las corre tambien la entrada de la suite
# que las cubre; aca solo se juntan. Las dos que en otra epoca corrian una
# guardia entera en un proceso aparte (los IDs y la AR) leen lo que ya
# esta escrito: salidas/modelo.json, salidas/resultados.json y la copia de
# ar.json que lee el telefono.
class Fila(object):
    """Una fila de la tabla: sus chequeos, lo abierto y el numero clave."""

    def __init__(self, prueba, comando):
        self.prueba = prueba
        self.comando = comando
        self.fallas = []
        self.abiertos = []
        self.numero = ''
        self.criterio = ''
        self.segundos = 0.0
        self.datos = {}

    def check(self, ok, que, *detalle):
        print('  [%s] %s' % ('OK  ' if ok else 'FALLA', que))
        for d in detalle:
            print('         %s' % d)
        if not ok:
            self.fallas.append(que)
        return ok

    def abierto(self, que, *detalle):
        print('  [PARC] %s' % que)
        for d in detalle:
            print('         %s' % d)
        self.abiertos.append(que)

    @staticmethod
    def info(que):
        print('         %s' % que)

    @property
    def estado(self):
        if self.fallas:
            return 'FALLA'
        return 'PARCIAL' if self.abiertos else 'OK'


def contexto_qa(argv=()):
    r"""
    El edificio y los cuatro casos del LABORATORIO (G, Q, EX, EY de
    laboratorio.armar_casos) resueltos ahora, una vez, y los resultados del
    laboratorio que lee el visor: los de salidas/resultados.json si son de
    estos mismos parametros; si no, armados en memoria con el mismo codigo
    que los escribe (exportar/ar.py, resultados_del_laboratorio).
    """
    from calculo import laboratorio as lab
    from calculo import opensees
    from exportar import ar as exar
    modelo = _ed.estructura()
    p = lab.cargar(list(argv))
    arm = lab.armar_casos(modelo, p)
    with contextlib.redirect_stdout(io.StringIO()), opensees.AvisosDeOpenSees():
        _datos, res = lab.resolver(modelo, arm['casos'])
    anexo, origen = exar.resultados_del_laboratorio(list(argv))
    return {'modelo': modelo, 'p': p, 'arm': arm,
            'casos': {n: arm['casos'][n] for n in lab.CASOS_BASE},
            'res': res, 'anexo': anexo, 'origen_anexo': origen.replace(os.sep, '/')}


# --- IDs Unity ---------------------------------------------------------
# El texto con que VisorEstructura nombra cada barra. Se busca en el .cs y
# no se copia: si el C# cambia la regla, objeto_unity de los resultados
# dejaria de encontrar su GameObject sin que nada fallara.
# MOVER A verificacion/comun.py (lo usan tambien la trazabilidad y la AR)
LITERAL_NOMBRE = '"Elem_" + e.id + "_" + e.tipo'


def regla_de_nombre_en_visor():
    r"""
    (numero de linea, linea) donde VisorEstructura.cs nombra la barra con
    LITERAL_NOMBRE, o (None, None). Los comentarios se vacian conservando
    los saltos de linea, para que un ejemplo en una nota no cuente como
    codigo.
    """
    with io.open(rutas.cs('VisorEstructura.cs'), encoding='utf-8') as f:
        src = f.read()
    src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'),
                 src, flags=re.S)
    for i, linea in enumerate(src.splitlines(), 1):
        codigo = linea.split('//', 1)[0]
        if LITERAL_NOMBRE in codigo and '.name' in codigo:
            return i, codigo.strip()
    return None, None


def fila_ids(ctx):
    from verificacion.capacidad import COLUMNA
    f = Fila('IDs Unity', 'python -m verificacion.unity contratos')
    modelo = ctx['modelo']
    ruta = rutas.salida('modelo')
    if not f.check(os.path.isfile(ruta), 'existe %s, el modelo que dibuja el visor'
                   % rutas.relativa(ruta).replace(os.sep, '/')):
        f.numero = 'sin %s' % rutas.relativa(ruta)
        return f
    with io.open(ruta, encoding='utf-8') as fh:
        visor = json.load(fh)
    f.info('el contrato JSON <-> C# (claves, tipos, anidados) lo prueba la entrada U1 de la '
           'suite; aca se cruzan los tags de lo que ya esta escrito')
    nm = {int(n['id']): (n['x'], n['y'], n['z']) for n in modelo['nodos']}
    nv = {int(n['id']): (n['x'], n['y'], n['z']) for n in visor['nodos']}
    dxyz = max((max(abs(a - b) for a, b in zip(nm[i], nv[i])) for i in nm if i in nv), default=0.0)
    f.check(set(nm) == set(nv) and dxyz == 0.0,
            'nodos: %d en el modelo y %d en el visor, mismos tags, max |dxyz| = %.1e m'
            % (len(nm), len(nv), dxyz))
    clave = lambda e: (int(e['n1']), int(e['n2']), e['tipo'], e['seccion'])   # noqa: E731
    em = {int(e['id']): clave(e) for e in modelo['elementos']}
    ev = {int(e['id']): clave(e) for e in visor['elementos']}
    distintos = [i for i in em if ev.get(i) != em[i]]
    f.check(set(em) == set(ev) and not distintos,
            'elementos: %d en el modelo y %d en el visor, mismos tags, nodos, tipo y seccion'
            % (len(em), len(ev)))

    linea, _codigo = regla_de_nombre_en_visor()
    f.check(linea is not None,
            'el visor nombra cada barra con %s (VisorEstructura.Redibujar)' % LITERAL_NOMBRE)
    anexo = ctx['anexo']['elementos']
    mal_obj = [e['id'] for e in anexo if e['objeto_unity'] != 'Elem_%d_%s' % (e['id'], e['tipo'])]
    mal_tag = [e['id'] for e in anexo if not e['tag_opensees'].startswith(
        'element elasticBeamColumn %d %d %d ' % (e['id'], e['n1'], e['n2']))]
    f.check({e['id'] for e in anexo} == set(em) and not mal_obj and not mal_tag,
            'resultados: %d elementos; objeto_unity = Elem_<tag>_<tipo> y tag_opensees = "element '
            'elasticBeamColumn <tag> <n1> <n2>" en todos' % len(anexo),
            'ej.: %s | %s' % next((e['objeto_unity'], e['tag_opensees'][:52])
                                  for e in anexo if e['id'] == COLUMNA))
    f.numero = '%d nodos y %d elementos: mismo tag en modelo, visor, resultados y GameObject' % (len(nm), len(em))
    f.criterio = '0 diferencias de tag, nodos, tipo, seccion y coordenadas; nombre del GameObject leido del C#'
    return f


# --- AR -----------------------------------------------------------------
IPHONE = os.path.join(rutas.REGISTROS, 'iphone')


def evidencia_del_iphone():
    if not os.path.isdir(IPHONE):
        return []
    return sorted(n for n in os.listdir(IPHONE)
                  if n.lower().endswith(('.jpg', '.jpeg', '.png', '.heic', '.mp4', '.mov')))


def fila_ar(ctx):
    from verificacion import ar as var
    from verificacion.comun import Informe
    f = Fila('AR', 'python -m verificacion.ar ids_resultados_pose')
    if not os.path.isfile(var.AR_JSON):
        f.check(False, 'existe %s, lo que lee el telefono (python sap.py exportar ar y sincronizar)'
                % var.rel(var.AR_JSON))
        f.numero = 'sin ar.json'
        return f
    app = var.leer(var.AR_JSON)
    inf = Informe()
    with contextlib.redirect_stdout(io.StringIO()) as salida:
        var.bloque_ids(app, ctx['modelo'], ctx['anexo'], inf)
        var.bloque_resultados(app, ctx['anexo'], inf)
        var.bloque_pose(app, ctx['modelo'], inf)
    f.check(not inf.fallas,
            '%s: [1] mismos elementTag/nodeTag que OpenSees; [2] cada numero de la app = '
            'resultados, bit a bit; [3a] pose del marcador' % var.rel(var.AR_JSON),
            *inf.fallas[:3])
    for linea in salida.getvalue().splitlines():
        if 'numeros' in linea and 'identicos' in linea:
            f.info(linea.strip().replace('[OK  ] ', ''))
    if os.path.isfile(var.TRACKING):
        trk = var.leer(var.TRACKING)
        f.info('[3b] y [4] (ar.js y el tracking en Chrome) medidos el %s en %s: %s'
               % (trk.get('medido'), var.rel(var.TRACKING), 'ok' if trk.get('ok') else 'NO CALZA'))
    else:
        f.info('[3b] y [4] (ar.js y el tracking en Chrome): sin medir; python -m verificacion.ar '
               'registro_y_tracking')
    fotos = evidencia_del_iphone()
    if fotos:
        f.check(True, 'evidencia del iPhone en %s: %s'
                % (rutas.relativa(IPHONE).replace(os.sep, '/'), ', '.join(fotos)))
    else:
        f.abierto('sin prueba en un iPhone: %s no tiene capturas. Todo lo anterior corre en '
                  'Chrome de escritorio' % rutas.relativa(IPHONE).replace(os.sep, '/'))
    f.numero = 'app = OpenSees bit a bit; pose del marcador' + ('' if fotos else '; sin iPhone')
    f.criterio = 'la app = los resultados, sin FALLA; una captura del telefono en verificacion/registros/iphone/'
    return f


# --- la tabla -------------------------------------------------------------
def tabla(filas):
    ancho = max(len(x.prueba) for x in filas)
    print()
    print('=' * 78)
    print('  QA FINAL ESTRUCTURAL: %s (%s)' % (_ed.NOMBRE.upper(), datetime.date.today().isoformat()))
    print('=' * 78)
    for x in filas:
        print('  %-*s  %-7s  %s' % (ancho, x.prueba, x.estado, x.numero))
    print('=' * 78)


def celda(texto):
    """Texto para una celda de tabla markdown: un | suelto la parte."""
    return texto.replace('|', r'\|')


def git(*args):
    try:
        return subprocess.run(['git'] + list(args), cwd=rutas.RAIZ, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def escribir(ruta, filas, ctx, segundos):
    """La tabla en markdown, para el informe. Solo si se pide con --salida."""
    sucio = git('status', '--porcelain', '--', '.', ':!unity/Library', ':!unity/Temp',
                ':!unity/Logs', ':!unity/obj')
    lineas = [
        '# QA final estructural del edificio',
        '',
        'Generado por `python sap.py revisar qa --salida` el %s, sobre el commit `%s`%s, en '
        '%.0f s. No se edita a mano.'
        % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), git('rev-parse', '--short', 'HEAD'),
           ' con cambios sin commitear' if sucio else '', segundos),
        '',
        'Modelo: `entrada/edificio.json` (%d nodos, %d elementos). Resultados: %s.'
        % (len(ctx['modelo']['nodos']), len(ctx['modelo']['elementos']), ctx['origen_anexo']),
        '',
        '| Prueba | Estado | Número | Criterio | Comando |',
        '|---|---|---|---|---|',
    ]
    for x in filas:
        lineas.append('| %s | **%s** | %s | %s | `%s` |'
                      % (x.prueba, x.estado, celda(x.numero), celda(x.criterio), x.comando))
    abiertos = [(x.prueba, a) for x in filas for a in x.abiertos]
    if abiertos:
        lineas += ['', '**Lo abierto** (lo que deja una fila en PARCIAL, medido por la misma prueba):', '']
        lineas += ['- %s: %s' % pa for pa in abiertos]
    fallas = [(x.prueba, a) for x in filas for a in x.fallas]
    if fallas:
        lineas += ['', '**FALLAS:**', '']
        lineas += ['- %s: %s' % pa for pa in fallas]
    rutas.escribir_atomico(ruta, ('\n'.join(lineas) + '\n').encode('utf-8'))
    print('  escrito %s' % ruta)


def tabla_qa(argv=None):
    r"""
    La tabla de QA de diez filas para la defensa: equilibrio G y Q, corte
    basal EX y EY, superposicion, M-phi, P-M de columna y de muro, IDs y
    AR. Corre las pruebas de cada fila en el momento (con las funciones del
    proyecto) y lee los resultados ya escritos; NO vuelve a correr las
    guardias de la suite, que siguen siendo sus entradas propias.
    """
    from verificacion import capacidad as vcap
    from verificacion import laboratorio as vlab
    consola_tolerante()
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='python sap.py revisar qa', description=tabla_qa.__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--salida', metavar='ARCHIVO',
                    help='ademas escribe la tabla en markdown en ese archivo')
    a = ap.parse_args(argv)
    t0 = time.time()

    print('=' * 78)
    print('  QA FINAL ESTRUCTURAL, EN VIVO')
    print('=' * 78)
    ctx = contexto_qa()
    print('  modelo      %s (%d nodos, %d elementos)'
          % (rutas.relativa(rutas.EDIFICIO).replace(os.sep, '/'),
             len(ctx['modelo']['nodos']), len(ctx['modelo']['elementos'])))
    print('  resultados  %s (%d casos)' % (ctx['origen_anexo'], len(ctx['anexo']['casos'])))
    print('  casos       G, Q, EX y EY del laboratorio (laboratorio.armar_casos), resueltos ahora')

    pasos = [('Equilibrio G', lambda: vlab.fila_equilibrio(ctx, 'G')),
             ('Equilibrio Q', lambda: vlab.fila_equilibrio(ctx, 'Q')),
             ('Corte basal EX', lambda: vlab.fila_corte(ctx, 'EX')),
             ('Corte basal EY', lambda: vlab.fila_corte(ctx, 'EY')),
             ('Superposicion', lambda: vlab.fila_superposicion(ctx)),
             ('M-phi', lambda: vcap.fila_mphi(ctx)),
             ('P-M columna', lambda: vcap.fila_pm_columna(ctx)),
             ('P-M muro', lambda: vcap.fila_pm_muro(ctx)),
             ('IDs Unity', lambda: fila_ids(ctx)),
             ('AR', lambda: fila_ar(ctx))]
    filas = []
    for nombre, hacer in pasos:
        titulo(nombre.upper())
        t = time.time()
        x = hacer()
        x.segundos = time.time() - t
        filas.append(x)

    tabla(filas)
    if a.salida:
        escribir(os.path.abspath(a.salida), filas, ctx, time.time() - t0)
    fallas = [x.prueba for x in filas if x.estado == 'FALLA']
    if fallas:
        print('  FALLA: %s' % ', '.join(fallas))
        return 1
    parciales = [x.prueba for x in filas if x.estado == 'PARCIAL']
    print('  %d OK y %d PARCIAL%s, 0 FALLA (%.0f s)'
          % (len(filas) - len(parciales), len(parciales),
             (' (%s)' % ', '.join(parciales)) if parciales else '', time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
