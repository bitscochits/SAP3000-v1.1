# -*- coding: utf-8 -*-
r"""
================================================================
 sap.py  -  LA UNICA PUERTA DE ENTRADA
================================================================
 SAP3000: el laboratorio estructural digital del Edificio de
 Ingenieria de la UAndes (los dos cuerpos, el antiguo y el LT2, en un
 solo edificio), modelado en OpenSees, verificado y mostrado en Unity,
 en el telefono (AR) y en Excel. Grupo 7.

     entrada/edificio.json + entrada/laboratorio.json
        -> calculo/   (Python + OpenSees: lo UNICO que calcula)
        -> exportar/  -> salidas/   (un archivo por cada consumidor)
        -> sincronizar -> Unity (StreamingAssets) . AR (ar/web/datos) . Excel

     python sap.py                 el flujo, el estado y los comandos
     python sap.py preparar        calcular + exportar todo + sincronizar
     python sap.py unity app       abre el visor
     python sap.py verificar       la suite entera

 ESTE ARCHIVO NO CALCULA NADA. Lee la linea de comandos y llama a la
 funcion de cada modulo; cada main(argv) recibe los argumentos SIN el
 nombre del comando y devuelve el codigo de salida. Lo unico que hace
 por su cuenta es ORQUESTAR 'preparar' y 'exportar todo' en un solo
 proceso: la base del laboratorio (los cuatro casos resueltos y las
 curvas P-M, lo caro) se arma UNA vez y la reciben los resultados, el
 Excel y la AR.

 Los modulos se importan recien dentro de cada comando: abrir la ayuda
 no carga OpenSees, y si un modulo todavia no existe, el comando lo
 dice claro (codigo 2) en vez de caerse al arrancar.

 Codigos de salida: 0 bien, 1 algo fallo, 2 no se pudo correr (falta un
 modulo, un comando mal escrito).
================================================================
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
import time
import traceback

# sap.py es el UNICO que toca sys.path: deja su carpeta (la raiz) primera,
# para que 'from calculo import rutas' encuentre ESTE proyecto aunque se
# corra desde otra carpeta. Los demas se importan como paquetes desde aca.
_AQUI = os.path.dirname(os.path.abspath(__file__))
if not sys.path or os.path.abspath(sys.path[0] or os.curdir) != _AQUI:
    sys.path.insert(0, _AQUI)

# La consola de Windows es cp1252 y algunos textos traen 'phi' griega: con
# la salida redirigida a un archivo, imprimirla cortaria el comando. Los
# subprocesos (el servidor de las capturas, la suite) heredan lo mismo.
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
for _flujo in (sys.stdout, sys.stderr):
    if (getattr(_flujo, 'encoding', '') or '').lower().replace('-', '') != 'utf8':
        try:
            _flujo.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


# ============================================================
# LO QUE OFRECE (la tabla de comandos)
# ============================================================
COMANDOS = (
    ('calcular', '[--caso G]',
     'los casos del MODELO (G, Q, EX, EY de edificio.json) en OpenSees -> salidas/casos_del_modelo.json'),
    ('exportar', '<modelo|resultados|carga_movil|persona|relieve|excel|ar|todo> [flags] [--no-escribir]',
     'arma lo que leen Unity, la AR y Excel -> salidas/'),
    ('sincronizar', '[--seco] [--destino CARPETA]',
     'salidas/ -> StreamingAssets de Unity (proyecto y builds) y ar/web/datos'),
    ('preparar', '[--seco] [--sin-persona] [flags]',
     'calcular + exportar todo + sincronizar (carga movil y persona solo avisan si fallan)'),
    ('servidor', '[--lan] [--puerto 5000] [--sin-precalentar] [flags]',
     'el servidor para Unity: /ping /analizar /combinar /estados'),
    ('unity', '<app|editor|build|web|android|compilar> [--forzar] [--seco] [--pantalla-completa] [--preparar]',
     'abrir el visor, compilarlo, o compilar solo los C# sin abrir Unity'),
    ('capturar', '<visor|diagramas|persona|relieve> [--carpeta C] [--sin-servidor] [--seco]',
     'la app compilada saca sus fotos y su registro.txt (verificacion/registros/capturas/)'),
    ('ar', '<servir|marcador|precision> [...]',
     'la app de realidad aumentada: servirla al telefono, el marcador, la precision'),
    ('revisar', '<tema> [...]',
     'herramientas de explicacion y defensa ("python sap.py revisar" lista los temas)'),
    ('verificar', '[--rapido] [--solo palabra ...] [--lista]',
     'la suite: cada trampa de CLAUDE.md con su guardia'),
    ('recursos', '[--verificar]',
     'vista realista: el giro del cielo, los mapas de detalle, las licencias'),
    ('atst', '[--verificar]',
     'el AT-ST de la pestana Persona: unity/FuentesPersonaje -> Resources/Personaje/atst.json'),
)

# Los flags de los parametros del laboratorio (laboratorio.cargar). Valen
# en todo comando que arma los casos del laboratorio y nunca escriben
# entrada/laboratorio.json.
FLAGS_LABORATORIO = ('--q', '--uso', '--cs', '--fq', '--patron', '--k', '--fracciones',
                     '--comb', '--combinacion')

EXPORTABLES = ('modelo', 'resultados', 'carga_movil', 'persona', 'relieve', 'excel', 'ar')


class NoDisponible(Exception):
    """Un modulo (o una funcion) que el comando necesita todavia no existe."""


# ============================================================
# AYUDANTES
# ============================================================
def _modulo(nombre):
    """
    Importa un modulo del proyecto ('exportar.excel'). Si el ARCHIVO no
    existe, NoDisponible con su ruta; si existe pero falla al importarse
    (le falta una dependencia, tiene un error), el error sale tal cual.
    """
    try:
        return importlib.import_module(nombre)
    except ModuleNotFoundError as e:
        if e.name and (nombre == e.name or nombre.startswith(e.name + '.')):
            raise NoDisponible('falta %s.py' % nombre.replace('.', '/'))
        raise


def _existe(nombre):
    """True si el modulo existe (sin importarlo)."""
    try:
        return importlib.util.find_spec(nombre) is not None
    except ModuleNotFoundError:
        return False


def _funcion(nombre_modulo, funcion='main'):
    mod = _modulo(nombre_modulo)
    fn = getattr(mod, funcion, None)
    if fn is None:
        raise NoDisponible('%s.py no tiene %s()' % (nombre_modulo.replace('.', '/'), funcion))
    return fn


def _acepta(fn, parametro):
    """True si `fn` recibe un argumento con ese nombre."""
    try:
        return fn is not None and parametro in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _main(nombre_modulo, argv, **compartido):
    """
    modulo.main(argv), pasandole de `compartido` solo lo que su main
    declara recibir: un modulo que no lo acepta sigue funcionando, y arma
    lo suyo.
    """
    fn = _funcion(nombre_modulo)
    extra = {k: v for k, v in compartido.items() if v is not None and _acepta(fn, k)}
    return fn(list(argv), **extra)


def _codigo(rc):
    """El codigo de salida de lo que devuelve un main (None = bien)."""
    if rc is None or rc is True:
        return 0
    if rc is False:
        return 1
    return int(rc) if isinstance(rc, int) else 0


def _sacar(argv, *flags):
    """argv sin esos flags (los que no llevan valor)."""
    return [a for a in argv if a not in flags]


def _flags_ajenos(argv, propios=()):
    """Los '--algo' que no son de este comando ni de los parametros del
    laboratorio. laboratorio.cargar ignora lo que no reconoce: un flag
    mal escrito pasaria sin decir nada."""
    validos = set(FLAGS_LABORATORIO) | set(propios)
    return [a for a in argv if a.startswith('--') and a not in validos]


def _validar_flags(flags):
    """Los parametros del laboratorio se validan antes de correr nada: un
    --cs mal escrito tiene que cortar aca, no a mitad del camino."""
    from calculo import laboratorio as lab
    try:
        lab.cargar(list(flags))
    except (ValueError, SystemExit) as e:
        print('  ERROR en los parametros: %s' % (e.code if isinstance(e, SystemExit) else e))
        return False
    if flags:
        print('  parametros del laboratorio: %s (no se escriben en entrada/laboratorio.json)'
              % ' '.join(flags))
    return True


def _uso(comando):
    for nombre, args, que in COMANDOS:
        if nombre == comando:
            print('  python sap.py %s %s' % (nombre, args))
            print('      %s' % que)
            return
    print('  python sap.py %s' % comando)


# ============================================================
# calcular
# ============================================================
def calcular(args):
    """calcular [--caso G]: los casos del modelo -> salidas/casos_del_modelo.json"""
    args = list(args)
    caso = None
    if '--caso' in args:
        i = args.index('--caso')
        if i + 1 >= len(args):
            print('  --caso necesita el nombre de un caso (G, Q, EX, EY)')
            return 2
        caso = args[i + 1]
        del args[i:i + 2]
    if args:
        print('  no se que es: %s' % ' '.join(args))
        _uso('calcular')
        return 2

    modelo = _modulo('exportar.modelo')
    from calculo import edificio as _ed
    from calculo import rutas

    print('=' * 68)
    print(' CASOS DEL MODELO   %s' % _ed.NOMBRE.upper())
    print('=' * 68)
    print('  %s' % _ed.resumen(_ed.estructura()))
    try:
        nuevos = modelo.casos_del_modelo(solo_caso=caso)
    except ValueError as e:
        print('  ERROR: %s' % e)
        return 1
    datos = _junto_a_los_demas(nuevos, rutas.salida('casos_del_modelo')) if caso else nuevos
    ruta = modelo.escribir_casos_del_modelo(datos)
    modelo.imprimir_casos(nuevos)
    print('  -> %s%s' % (rutas.relativa(ruta),
                         '  (se rehizo solo %s; los demas quedan como estaban)' % caso if caso else ''))
    return 0


def _junto_a_los_demas(nuevos, ruta):
    """
    Con --caso se resuelve uno solo, pero el archivo lleva todos: se
    reemplaza ese caso y los demas quedan como estaban, en el orden de
    edificio.json (como si cada caso fuera su propio archivo).
    """
    import json
    from calculo import edificio as _ed
    previos = {}
    if os.path.isfile(ruta):
        with open(ruta, encoding='utf-8') as f:
            previos = {c['caso']: c for c in json.load(f).get('casos', [])}
    for c in nuevos['casos']:
        previos[c['caso']] = c
    orden = [c.get('nombre') for c in _ed.estructura().get('casos_de_carga', [])]
    casos = [previos[n] for n in orden if n in previos]
    casos += [c for n, c in previos.items() if n not in orden]
    return dict(nuevos, casos=casos)


# ============================================================
# exportar, preparar
# ============================================================
class Paso(object):
    def __init__(self, nombre, que, llama, obligatorio, correr):
        self.nombre, self.que, self.llama = nombre, que, llama
        self.obligatorio, self.correr = obligatorio, correr


def _pasos(flags, no_escribir=False, sin_persona=False, con_calcular=False,
           con_sincronizar=False, seco=False):
    """
    Los pasos de 'exportar todo' (y de 'preparar', que agrega calcular y
    sincronizar), en orden. `compartido` es lo que se arma una vez y pasa
    de un paso a otro: la base del laboratorio y los resultados ya
    construidos con ella.
    """
    ne = ['--no-escribir'] if no_escribir else []
    compartido = {}
    pasos = []
    if con_calcular:
        pasos.append(Paso('calcular', 'los casos del modelo en OpenSees -> salidas/casos_del_modelo.json',
                          'exportar.modelo.casos_del_modelo', True, lambda: calcular([])))
    pasos += [
        Paso('modelo', 'lo que dibuja el visor -> salidas/modelo.json',
             'exportar.modelo.main', True, lambda: _main('exportar.modelo', ne)),
        Paso('base', 'los casos del laboratorio resueltos UNA vez (para resultados, Excel y AR)',
             'calculo.esfuerzos.base', True, lambda: _paso_base(flags, compartido)),
        Paso('resultados', 'lo que el visor muestra de cada caso -> salidas/resultados.json',
             'exportar.resultados.main', True,
             lambda: _paso_resultados(flags, flags + ne, compartido)),
        Paso('excel', 'el libro del edificio -> salidas/resultados.xlsx',
             'exportar.excel.main', True,
             lambda: _main('exportar.excel', flags + ne, construido=compartido.get('construido'),
                           base=compartido.get('base'))),
        Paso('ar', 'el sector de la columna del marcador -> salidas/ar.json',
             'exportar.ar.main', True,
             lambda: _main('exportar.ar', flags + ne, construido=compartido.get('construido'),
                           base=compartido.get('base'))),
        Paso('relieve', 'el relieve del sitio -> salidas/relieve.json',
             'exportar.relieve.main', True, lambda: _main('exportar.relieve', ne)),
        Paso('carga_movil', 'la carga movil precalculada -> salidas/carga_movil.json',
             'exportar.carga_movil.main', False, lambda: _main('exportar.carga_movil', ne)),
    ]
    if not sin_persona:
        pasos.append(Paso('persona', 'la deformada de la persona, caso a caso -> salidas/persona.json '
                                     '(lenta: unos 2 min)',
                          'exportar.persona.main', False, lambda: _main('exportar.persona', ne)))
    if con_sincronizar:
        pasos.append(Paso('sincronizar', 'salidas/ -> StreamingAssets (proyecto y builds) y ar/web/datos',
                          'exportar.sincronizar.main', True,
                          lambda: _main('exportar.sincronizar', ['--seco'] if seco else [])))
    return pasos


def _paso_base(flags, compartido):
    """La base del laboratorio (calculo.esfuerzos.base), con los avisos de
    OpenSees de las curvas P-M juntados y contados en vez de inundar la
    consola."""
    from calculo import esfuerzos
    from calculo import opensees
    t0 = time.time()
    avisos = opensees.AvisosDeOpenSees()
    try:
        with avisos:
            b = esfuerzos.base(list(flags))
    except BaseException:
        texto = (getattr(avisos, 'texto', '') or '').strip()
        if texto:
            print('  lo ultimo que escribio OpenSees:')
            for linea in texto.splitlines()[-10:]:
                print('    %s' % linea)
        raise
    compartido['base'] = b
    print('  %d nodos, %d elementos, %d curvas P-M para %d elementos con fierro, en %.1f s'
          % (len(b['modelo']['nodos']), len(b['modelo']['elementos']), len(b['familias']),
             len(b['secciones']), time.time() - t0))
    if avisos.resumen():
        print('  %s' % avisos.resumen())
    return 0


def _paso_resultados(flags, argv, compartido):
    """
    exportar.resultados con la base ya armada: construir(flags, b=base) una
    vez, y ese (resultados, contexto) lo reciben su main, el Excel y la AR.
    """
    mod = _modulo('exportar.resultados')
    b = compartido.get('base')
    if b is not None and _acepta(getattr(mod, 'construir', None), 'b'):
        compartido['construido'] = mod.construir(list(flags), b=b)
    if compartido.get('construido') is not None and _acepta(mod.main, 'construido'):
        return mod.main(list(argv), construido=compartido['construido'])
    if b is not None:
        print('  (exportar.resultados.main no recibe lo ya construido: vuelve a armar la base)')
        sys.stdout.flush()
    return mod.main(list(argv))


def _ejecutar(correr):
    """('ok' | 'falla' | 'falta', motivo)"""
    try:
        rc = correr()
    except NoDisponible as e:
        return 'falta', str(e)
    except SystemExit as e:
        if e.code in (None, 0):
            return 'ok', ''
        if isinstance(e.code, int):
            return 'falla', 'codigo %d' % e.code
        print('  %s' % e.code)
        return 'falla', str(e.code)
    except Exception as e:
        traceback.print_exc()
        return 'falla', '%s: %s' % (type(e).__name__, e)
    rc = _codigo(rc)
    return ('ok', '') if rc == 0 else ('falla', 'codigo %d' % rc)


def _correr_pasos(titulo, pasos, seco=False):
    """Corre los pasos en orden y deja una tabla. Devuelve el codigo de salida."""
    print()
    print('=' * 72)
    print('  %s%s' % (titulo, '   EN SECO: no se escribe nada' if seco else ''))
    print('=' * 72)
    if seco:
        for i, p in enumerate(pasos, 1):
            modulo = p.llama.rsplit('.', 1)[0]
            falta = '' if _existe(modulo) else '   FALTA %s.py' % modulo.replace('.', '/')
            print('  %2d %-12s %s%s' % (i, p.nombre, p.que, '' if p.obligatorio else '   (opcional)'))
            print('     %-12s llama a %s%s' % ('', p.llama, falta))
        final = [p for p in pasos if p.nombre == 'sincronizar']
        if final:
            print()
            estado, motivo = _ejecutar(final[0].correr)
            if estado != 'ok':
                print('  >> sincronizar: %s' % motivo)
        return 0

    filas = []
    for i, p in enumerate(pasos, 1):
        if p.nombre == 'sincronizar' and any(e != 'ok' and q.obligatorio for q, e, _, _ in filas):
            filas.append((p, 'no', 'no se sincroniza: fallo un paso obligatorio', 0.0))
            continue
        print()
        print('-' * 72)
        print('  [%d/%d] %s: %s' % (i, len(pasos), p.nombre, p.que))
        print('-' * 72)
        # OpenSees escribe directo al descriptor 2, sin pasar por el buffer
        # de Python: sin esto, con la salida a un archivo, sus avisos
        # aparecen antes que el titulo del paso que los produjo.
        sys.stdout.flush()
        t0 = time.time()
        estado, motivo = _ejecutar(p.correr)
        sys.stdout.flush()
        filas.append((p, estado, motivo, time.time() - t0))
        if estado != 'ok':
            print('  >> %s: %s' % (p.nombre, motivo))

    print()
    print('=' * 72)
    print('  RESUMEN')
    for p, estado, motivo, segundos in filas:
        print('    %-12s %-6s %7.1f s   %s%s'
              % (p.nombre, estado if estado == 'ok' else estado.upper(), segundos, motivo,
                 '' if p.obligatorio else '   (opcional)'))
    duros = [p.nombre for p, e, _, _ in filas if e not in ('ok', 'no') and p.obligatorio]
    blandos = [p.nombre for p, e, _, _ in filas if e != 'ok' and not p.obligatorio]
    if blandos:
        print()
        print('  Opcionales que no se pudieron hacer: %s. El visor lo avisa en su panel'
              % ', '.join(blandos))
        print('  y el resto funciona igual.')
    print('=' * 72)
    if duros:
        print('  NO SE PUDO: %s' % ', '.join(duros))
        return 1
    return 0


def exportar(args):
    """exportar <x|todo> [flags] [--no-escribir]"""
    if not args or args[0] not in EXPORTABLES + ('todo',):
        print('  exportar que? %s o todo' % ', '.join(EXPORTABLES))
        _uso('exportar')
        return 2
    que, resto = args[0], list(args[1:])
    if que != 'todo':
        return _codigo(_main('exportar.' + que, resto))
    ajenos = _flags_ajenos(resto, ('--no-escribir', '--sin-persona'))
    if ajenos:
        print('  no se que es: %s' % ' '.join(ajenos))
        _uso('exportar')
        return 2
    flags = _sacar(resto, '--no-escribir', '--sin-persona')
    if not _validar_flags(flags):
        return 1
    pasos = _pasos(flags, no_escribir='--no-escribir' in resto, sin_persona='--sin-persona' in resto)
    return _correr_pasos('EXPORTAR TODO', pasos)


def preparar(args):
    """preparar [--seco] [--sin-persona] [flags]"""
    args = list(args)
    ajenos = _flags_ajenos(args, ('--seco', '--sin-persona'))
    if ajenos:
        print('  no se que es: %s' % ' '.join(ajenos))
        _uso('preparar')
        return 2
    seco = '--seco' in args
    flags = _sacar(args, '--seco', '--sin-persona')
    if not _validar_flags(flags):
        return 1
    pasos = _pasos(flags, sin_persona='--sin-persona' in args, con_calcular=True,
                   con_sincronizar=True, seco=seco)
    return _correr_pasos('PREPARAR   (calcular + exportar todo + sincronizar)', pasos, seco=seco)


# ============================================================
# sincronizar, servidor, unity, capturar, ar, verificar, recursos, atst
# ============================================================
def sincronizar(args):
    return _codigo(_main('exportar.sincronizar', args))


def servidor(args):
    return _codigo(_main('exportar.servidor', args))


def unity(args):
    """unity <modo> [...]; con --preparar (app, editor) corre antes 'preparar'."""
    args = list(args)
    if '--preparar' in args:
        args = _sacar(args, '--preparar')
        modo = args[0] if args and not args[0].startswith('-') else 'app'
        if modo not in ('app', 'editor'):
            print("  --preparar solo sirve con 'unity app' o 'unity editor'")
            return 2
        rc = preparar([])
        if rc:
            return rc
    return _codigo(_main('herramientas.lanzador', args))


# La comparacion de cada captura con Python (verificacion/capturas.py).
COMPARACION_DE_CAPTURA = ('visor', 'persona', 'relieve')


def capturar(args):
    """capturar <modo> [...]: la app saca fotos y registro; despues se compara con Python."""
    args = list(args)
    rc = _codigo(_funcion('herramientas.lanzador', 'capturar')(args))
    modo = args[0] if args else None
    if rc != 0 or modo not in COMPARACION_DE_CAPTURA or '--seco' in args or '--carpeta' in args:
        return rc
    print()
    print('  Lo que la app registro, contra Python (verificacion.capturas %s):' % modo)
    try:
        return _codigo(_main('verificacion.capturas', [modo]))
    except NoDisponible as e:
        print('  %s: no se comparo' % e)
        return rc


def ar(args):
    """ar <servir|marcador|precision> [...]"""
    sub, resto = (args[0], list(args[1:])) if args else (None, [])
    if sub == 'servir':
        return _codigo(_main('ar.servir', resto))
    if sub == 'marcador':
        return _codigo(_main('ar.marcador', resto))
    if sub == 'precision':
        return _codigo(_main('verificacion.ar', ['precision'] + resto))
    print('  ar que? servir, marcador o precision')
    print('    python sap.py ar servir [--http] [--puerto N]                   la app al telefono (https) o local')
    print('    python sap.py ar marcador [--elemento --cara --altura --ancho]  marcador.png, PDF y targets.mind')
    print('    python sap.py ar precision [--fov]                              presupuesto de error del registro')
    return 2


def verificar(args):
    return _codigo(_main('verificacion.suite', args))


def recursos(args):
    return _codigo(_main('herramientas.recursos_realistas', args))


def atst(args):
    return _codigo(_main('herramientas.atst', args))


# ============================================================
# revisar
# ============================================================
# tema: (argumentos, que hace, modulo, bloque que se le antepone a argv)
REVISAR = (
    ('parametros', '[flags]', 'describir() y las combinaciones; valida los flags',
     None, None),
    ('laboratorio', '[flags]', 'Partes A, B y C del laboratorio (q*A, corte basal, superposicion)',
     'verificacion.laboratorio', 'partes_abc'),
    ('sismo', '[EX|EY] [--detalle]', 'el sismo de los casos del modelo: corte, sentido, torsion',
     'calculo.sismo', None),
    ('superposicion', '[--lambdas G Q EX EY | --explicita] [flags]',
     'un caso combinado, o las combinaciones contra la corrida explicita',
     'calculo.superposicion', None),
    ('capacidad', '<elem> [--pm --mphi --dibujo --sensibilidad]', 'seccion de fibras: M-phi y P-M',
     'calculo.capacidad', None),
    ('demanda', '<elem>|--todas|--lista [--comb G Q EX EY] [--grafico --mphi]',
     'demanda contra capacidad', 'calculo.demanda', None),
    ('rc', '[elem]', 'fibras contra el calculo a mano (Whitney)',
     'verificacion.capacidad', 'rc_a_mano'),
    ('nucleos', '', 'grupos de patas de nucleo y su axial', 'verificacion.capacidad', 'nucleos'),
    ('losa-colaborante', '', 'la regla escrita y NO conectada (solo informa)',
     'verificacion.capacidad', 'losa_colaborante'),
    ('viga-partida', '[nodo]', 'refinar una viga no cambia la flecha (no es rotula)',
     'verificacion.motor', 'viga_partida'),
    ('m1', '[--float32] [--url] [--desde]', 'M1: borrar una columna, sin Unity', 'verificacion.motor', 'm1'),
    ('m2', '[--cs 0.20]', 'M2: cambiar Cs sin escribir', 'verificacion.laboratorio', 'm2'),
    ('m3', '[--float32] [--url] [--desde]', 'M3: cambiar la seccion de una viga', 'verificacion.motor', 'm3'),
    ('m4', '[--float32] [--url] [--desde]', 'M4: soltar un apoyo', 'verificacion.motor', 'm4'),
    ('trazabilidad', '<elem> [--caso]', 'la cadena OpenSees -> modelo -> GameObject -> resultados -> capacidad',
     'verificacion.resultados', 'trazabilidad'),
    ('qa', '[--salida]', 'la tabla de 10 filas para la defensa (no vuelve a correr guardias)',
     'verificacion.suite', None),
)


def revisar(args):
    temas = {t[0]: t for t in REVISAR}
    if not args or args[0] not in temas:
        if args:
            print('  no hay un tema %r' % args[0])
        print('  python sap.py revisar <tema>   (los ids por defecto salen de entrada/laboratorio.json)')
        for tema, argumentos, que, _, _ in REVISAR:
            print('    %-17s %-44s %s' % (tema, argumentos, que))
        return 0 if not args else 2
    tema, resto = args[0], list(args[1:])
    _, _, _, modulo, bloque = temas[tema]
    if tema == 'parametros':
        return _revisar_parametros(resto)
    if tema == 'superposicion':
        # Sin --lambdas, calculo.superposicion.main compara las combinaciones
        # contra la corrida explicita; --explicita solo lo dice en voz alta.
        return _codigo(_main(modulo, _sacar(resto, '--explicita')))
    if tema == 'qa':
        fn = _funcion('verificacion.suite', 'tabla_qa')
        obligatorios = [p for p in inspect.signature(fn).parameters.values()
                        if p.default is inspect.Parameter.empty
                        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        return _codigo(fn(resto) if obligatorios or resto else fn())
    return _codigo(_main(modulo, ([bloque] if bloque else []) + resto))


def _revisar_parametros(args):
    """Los parametros con que se arman los casos del laboratorio: las lineas
    de describir() (la huella que viaja en cada salida) y las combinaciones."""
    from calculo import laboratorio as lab
    try:
        p = lab.cargar(list(args))
    except ValueError as e:
        print('  ERROR: %s' % e)
        return 1
    print('PARAMETROS DEL LABORATORIO')
    print(lab.describir(p))
    if p['combinaciones']:
        print()
        print('  combinaciones declaradas:')
        for c in p['combinaciones']:
            print('    %-18s %s' % (c['nombre'], lab.como_texto(c)))
    return 0


# ============================================================
# sin argumentos: el flujo, el estado y los comandos
# ============================================================
def inicio():
    from calculo import rutas
    print()
    print('  SAP3000  -  laboratorio estructural del Edificio de Ingenieria UAndes (Grupo 7)')
    print('  raiz: %s' % rutas.RAIZ)
    print()
    print('  EL FLUJO')
    print('    entrada/edificio.json + entrada/laboratorio.json')
    print('       -> calculo/   Python + OpenSees: lo unico que calcula')
    print('       -> exportar/  -> salidas/   un archivo por cada consumidor')
    print('       -> sincronizar -> Unity (StreamingAssets) . AR (ar/web/datos) . Excel')
    print()
    print('    python sap.py calcular        OpenSees resuelve los 4 casos del edificio -> salidas/casos_del_modelo.json')
    print('    python sap.py exportar todo   arma lo que leen Unity, la AR y Excel      -> salidas/')
    print('    python sap.py sincronizar     lo copia a Unity (proyecto y builds) y a la AR')
    print('    python sap.py unity app       abre el visor')
    print('    python sap.py preparar        = calcular + exportar todo + sincronizar')
    print()
    try:
        _estado()
    except Exception as e:                 # el estado informa; nunca impide ver la ayuda
        print('  ESTADO: no se pudo revisar (%s: %s)' % (type(e).__name__, e))
    print()
    print('  COMANDOS   (python sap.py <comando> ...)')
    for nombre, argumentos, que in COMANDOS:
        print('    %-12s %s' % (nombre, argumentos))
        print('    %-12s   %s' % ('', que))
    print()
    print('  [flags] son los parametros del laboratorio: %s' % ' '.join(FLAGS_LABORATORIO))
    print('  (cambian lo que se calcula en esa corrida; nunca escriben entrada/laboratorio.json)')
    print()


def _fecha(ruta):
    return time.strftime('%d-%m %H:%M', time.localtime(os.path.getmtime(ruta)))


def _estado():
    """Que hay en entrada/, que falta o quedo atras en salidas/, y si las
    copias de Unity y de la AR estan al dia (por md5, sin escribir)."""
    from calculo import rutas
    print('  ESTADO')
    t_entrada = 0.0
    for ruta in (rutas.EDIFICIO, rutas.LABORATORIO):
        if os.path.isfile(ruta):
            t_entrada = max(t_entrada, os.path.getmtime(ruta))
            print('    entrada   %-24s %7.2f MB   %s'
                  % (os.path.basename(ruta), os.path.getsize(ruta) / 1048576.0, _fecha(ruta)))
        else:
            print('    entrada   %-24s FALTA' % os.path.basename(ruta))

    atras = []
    for clave in ('casos_del_modelo',) + EXPORTABLES:
        ruta = rutas.salida(clave)
        nombre = os.path.basename(ruta)
        if not os.path.isfile(ruta):
            como = 'calcular' if clave == 'casos_del_modelo' else 'exportar %s' % clave
            print('    salidas   %-24s falta        (python sap.py %s)' % (nombre, como))
            continue
        vieja = os.path.getmtime(ruta) < t_entrada
        if vieja:
            atras.append(nombre)
        print('    salidas   %-24s %7.2f MB   %s%s'
              % (nombre, os.path.getsize(ruta) / 1048576.0, _fecha(ruta),
                 '   anterior a un cambio de entrada/' if vieja else ''))
    if atras:
        print('              (las anteriores a un cambio de entrada/ pueden estar viejas: '
              'python sap.py preparar)')

    if not _existe('exportar.sincronizar'):
        return
    from exportar import sincronizar as sinc
    registros = sinc.sincronizar(seco=True, verbose=False)
    por_carpeta = {}
    for r in registros:
        if r['accion'] == 'copiar':
            c = por_carpeta.setdefault(r['carpeta'], {})
            c[r['estado']] = c.get(r['estado'], 0) + 1
    for carpeta, c in por_carpeta.items():
        print('    copias    %-38s %d al dia, %d por copiar, %d sin origen'
              % (rutas.relativa(carpeta), c.get('igual', 0), c.get('se copiaria', 0),
                 c.get('no copiado', 0)))
    viejos = [r for r in registros if r['accion'] == 'borrar']
    if viejos:
        print('    copias    %d nombres viejos en StreamingAssets (los borra la sincronizacion)'
              % len(viejos))
    if any(r['estado'] == 'se copiaria' for r in registros) or viejos:
        print('              -> python sap.py sincronizar')
    exe = os.path.join(rutas.BUILD, 'LaboratorioEstructural.exe')
    print('    build     %s' % ('LaboratorioEstructural.exe del %s' % _fecha(exe) if os.path.isfile(exe)
                                else 'sin compilar (python sap.py unity build)'))


# ============================================================
ACCIONES = {
    'calcular': calcular, 'exportar': exportar, 'sincronizar': sincronizar,
    'preparar': preparar, 'servidor': servidor, 'unity': unity, 'capturar': capturar,
    'ar': ar, 'revisar': revisar, 'verificar': verificar, 'recursos': recursos,
    'atst': atst,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'ayuda', 'help'):
        inicio()
        return 0
    comando, resto = argv[0], argv[1:]
    accion = ACCIONES.get(comando)
    if accion is None:
        print('  no hay un comando %r. Hay: %s' % (comando, ', '.join(n for n, _, _ in COMANDOS)))
        print('  (python sap.py sin nada muestra el flujo y que hace cada uno)')
        return 2
    try:
        return _codigo(accion(resto))
    except NoDisponible as e:
        print()
        print('  NO DISPONIBLE: %s' % e)
        print('  (python sap.py %s necesita ese modulo, y todavia no esta)' % comando)
        return 2


if __name__ == '__main__':
    sys.exit(main())
