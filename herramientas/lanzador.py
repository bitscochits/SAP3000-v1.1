# -*- coding: utf-8 -*-
r"""
================================================================
 herramientas/lanzador.py  -  ABRIR, COMPILAR Y CAPTURAR EL VISOR
================================================================
 Todo lo que hace falta para pasar de salidas/ a ver el edificio en
 Unity, sin tocar el editor a mano:

   python sap.py unity app          compila (una vez) la app de Windows y
                                    la ejecuta. No necesita el editor
                                    abierto y arranca en segundos. Es el
                                    modo para la DEMO.
   python sap.py unity editor       abre el proyecto en el editor de Unity.
                                    Sirve para trabajar en el visor, no
                                    para mostrarlo: hay que apretar Play.
   python sap.py unity build        compila la app de Windows (batch;
                                    --forzar la rehace aunque exista).
   python sap.py unity web          compila el build Web en build/web.
   python sap.py unity android      compila el APK si el editor tiene el
                                    modulo; si no, lo dice y sale SIN
                                    abrir Unity.
   python sap.py unity compilar     compila los C# con el dotnet de Unity,
                                    sin abrir Unity (--solo, --avisos,
                                    --conservar, --dotnet, --verbose).
   python sap.py capturar <modo>    la app compilada saca sus fotos y su
                                    registro.txt (visor, diagramas,
                                    persona, relieve).

 Antes de abrir o compilar, sincroniza (exportar/sincronizar.py): la
 app lee SU copia de StreamingAssets, y la build copia la del proyecto
 tal cual.

 Opciones: --seco (build, web, android: dice lo que haria sin escribir
 ni abrir nada), --forzar, --pantalla-completa.

 Los modos build, web y android corren Unity en batch y necesitan el
 editor CERRADO: con el proyecto abierto en otro Unity, el batch sale
 con error. Desde el editor abierto se usa el menu Laboratorio.

 ----------------------------------------------------------------
 POR QUE NO SE PUEDE "APRETAR PLAY" DESDE PYTHON
 ----------------------------------------------------------------
 El modo Play del editor es interactivo: -batchmode y Play son
 incompatibles. Por eso, para ver el modelo sin tocar el editor, se
 compila una app standalone; eso SI se puede hacer sin interfaz y
 luego ejecutarla es un proceso normal.

 ----------------------------------------------------------------
 COMPILAR LOS C# SIN UNITY (unity compilar)
 ----------------------------------------------------------------
 Compila Assembly-CSharp (unity/Assets/**, fuera de las carpetas
 Editor) y Assembly-CSharp-Editor (unity/Assets/**/Editor/**) con el
 dotnet que trae la instalacion de Unity, y dice cuantos errores CS hay
 y en que archivo. No abre Unity, no usa batchmode y NO escribe nada
 dentro del proyecto. Sirve para que varios editen los C# a la vez con
 Unity cerrado: en Unity un solo error CS bloquea TODOS los scripts
 (Add Component, Play, la build), y aca se ve en segundos.

   1. Copia unity/Assembly-CSharp.csproj y Assembly-CSharp-Editor.csproj
      a un directorio temporal NUEVO (tempfile.mkdtemp). Cada corrida
      tiene el suyo: dos compilando a la vez no comparten obj/.
   2. Vuelve absolutas las rutas relativas (Assets\, Library\,
      Packages\) de los Include y los HintPath. Las de salida
      (Temp\obj, Temp\bin) quedan relativas A PROPOSITO: asi caen en el
      temporal y no en unity/Temp.
   3. Cambia la lista fija de <Compile> por comodines. Los .csproj los
      genera Unity con los .cs que existian la ultima vez que se abrio;
      un archivo nuevo no estaria en la lista y no se compilaria -- el
      peor caso: "compila" porque no se mira.
   4. dotnet build del csproj del editor, que por su ProjectReference
      compila primero Assembly-CSharp.

   Codigo de salida: 0 compila (o, con --solo, tus archivos no tienen
   errores CS); 1 hay errores CS (con --solo, solo si estan en los
   archivos pedidos); 2 no se pudo verificar: faltan los .csproj o el
   dotnet, fallo la herramienta (MSB/NETSDK), el ensamblado de un
   archivo pedido no se llego a compilar, o una ruta de --solo no es un
   .cs existente dentro de unity/Assets (si no, sus errores saldrian como
   ajenos y el OK seria por vacio).

   Con --solo, los errores de otros archivos se imprimen como AVISO
   (probablemente son de alguien a mitad de su edicion). Ojo: un error
   ajeno puede arrastrar errores en tu archivo (un tipo que dejo de
   existir), y si Assembly-CSharp no compila, Assembly-CSharp-Editor no se
   compila: si pediste un archivo del editor, sale con 2.

   LO QUE NO REVISA: los .csproj son los del EDITOR: definen UNITY_EDITOR
   y referencian UnityEditor.dll tambien en Assembly-CSharp. Un script de
   Scripts/ que use UnityEditor sin '#if UNITY_EDITOR', o codigo dentro
   de '#if UNITY_ANDROID' / '#if UNITY_WEBGL' / '#if !UNITY_EDITOR',
   compila aca y recien falla al construir la app.

 ----------------------------------------------------------------
 CAPTURAS (sap.py capturar)
 ----------------------------------------------------------------
 Corre build/LaboratorioEstructural.exe -capturar <modo> <carpeta>: la
 app se maneja sola, saca sus fotos, escribe registro.txt y se cierra.
 La carpeta por defecto es verificacion/registros/capturas/<modo>, donde
 la suite compara el registro con Python. El modo visor hace ademas la
 M1 de la pestana Modificar con los ids de entrada/laboratorio.json
 (-m1 <columna>,<nodo>,<viga>) y usa el servidor (LIBRE y la M1): si
 /ping no responde, se levanta uno para la captura y se apaga al final.
================================================================
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from calculo import rutas
from exportar import sincronizar

PROYECTO_UNITY = rutas.UNITY_PROYECTO
CARPETA_BUILD = rutas.BUILD
APP = os.path.join(CARPETA_BUILD, 'LaboratorioEstructural.exe')
CARPETA_WEB = os.path.join(CARPETA_BUILD, 'web')
APK = os.path.join(CARPETA_BUILD, 'android', 'LaboratorioEstructural.apk')

# La version que se usa si el proyecto no la declara (ProjectVersion.txt).
VERSION_POR_DEFECTO = '6000.5.10f1'


# ============================================================
# 1. ENCONTRAR EL EDITOR DE UNITY
# ============================================================
def buscar_unity(version=None):
    """
    Busca Unity.exe. Si se pide una version concreta, solo devuelve
    esa; si no, la que coincida con ProjectVersion.txt del proyecto,
    y como ultimo recurso la mas nueva instalada.

    Mezclar versiones de Unity en un proyecto de grupo es una fuente
    clasica de conflictos (Unity reescribe assets al abrirlos con otra
    version), asi que por defecto se exige la del proyecto.
    """
    if version is None:
        version = version_del_proyecto()

    bases = [
        r"C:\Program Files\Unity\Hub\Editor",
        r"C:\Program Files\Unity\Editor",
        os.path.expandvars(r"%LOCALAPPDATA%\Unity\Hub\Editor"),
    ]

    candidatos = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for nombre in sorted(os.listdir(base), reverse=True):
            exe = os.path.join(base, nombre, 'Editor', 'Unity.exe')
            if os.path.exists(exe):
                candidatos.append((nombre, exe))
        exe = os.path.join(base, 'Unity.exe')
        if os.path.exists(exe):
            candidatos.append(('?', exe))

    if not candidatos:
        raise FileNotFoundError(
            "No encontre Unity.exe. Instala Unity desde Unity Hub.")

    if version:
        for nombre, exe in candidatos:
            if nombre == version:
                return exe
        disponibles = ", ".join(n for n, _ in candidatos)
        raise FileNotFoundError(
            f"El proyecto pide Unity {version} y no esta instalada.\n"
            f"Instaladas: {disponibles}\n"
            f"Instalala desde Unity Hub, o pasa version='<otra>' "
            f"asumiendo el riesgo de que Unity migre los assets.")

    return candidatos[0][1]


def version_del_proyecto():
    """Lee la version exacta que declara el proyecto (None si no la declara)."""
    ruta = os.path.join(PROYECTO_UNITY, 'ProjectSettings',
                        'ProjectVersion.txt')
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding='utf-8') as f:
        for linea in f:
            if linea.startswith('m_EditorVersion:'):
                return linea.split(':', 1)[1].strip()
    return None


def unity_abierto():
    """
    True si parece que un editor de Unity tiene ESTE proyecto abierto.

    Unity crea unity/Temp/UnityLockfile al abrir el proyecto, lo tiene
    abierto mientras corre y lo borra al cerrarse. Un batch contra un
    proyecto abierto falla despues de cargar Unity entero (minutos), asi
    que conviene decirlo antes. Si el archivo quedo de un cierre brusco
    se puede abrir, y entonces no cuenta como abierto.
    (No comprobado con el editor abierto en esta maquina: si Unity no
    bloqueara el archivo, esto da False y el batch falla como antes.)
    """
    lock = os.path.join(PROYECTO_UNITY, 'Temp', 'UnityLockfile')
    if not os.path.exists(lock):
        return False
    try:
        with open(lock, 'ab'):
            pass
        return False
    except OSError:
        return True


# ============================================================
# 2. SINCRONIZAR ANTES DE ABRIR O COMPILAR
# ============================================================
def sincronizar_para_abrir(seco=False):
    """
    Copia salidas/ a StreamingAssets (del proyecto y de las builds que
    existan) antes de abrir o compilar la app.

    Asi la app muestra SIEMPRE lo ultimo que se exporto sin tener que
    recompilarla. Si se omite este paso, el visor sigue mostrando el
    modelo viejo y no avisa: parece que los cambios no tuvieron efecto.
    Sin el modelo no hay nada que abrir: eso corta. Lo demas (un Excel
    abierto en otra ventana, un anexo que falta) se avisa y sigue.
    """
    registros = sincronizar.sincronizar(seco=seco)
    modelo = [r for r in registros if r['accion'] == 'copiar' and r['obligatorio']]
    if any(r['estado'] == 'no copiado' for r in modelo):
        motivo = modelo[0]['motivo']
        if motivo == 'falta el origen':
            raise FileNotFoundError(
                "No existe %s. Corre antes: python sap.py preparar"
                % rutas.relativa(rutas.salida(sincronizar.OBLIGATORIO)))
        raise RuntimeError("No se copio %s: %s"
                           % (rutas.relativa(rutas.salida(sincronizar.OBLIGATORIO)), motivo))
    errores = [r for r in modelo if r['estado'] == 'error']
    if errores:
        raise RuntimeError("No se pudo escribir %s: %s"
                           % (errores[0]['destino'], errores[0]['motivo']))
    return registros


# ============================================================
# 3. CORRER UNITY EN BATCH
# ============================================================
# Cada destino de compilacion:
#   metodo de ConstruirApp, -buildTarget, carpeta del modulo en
#   <Editor>/Data/PlaybackEngines, lo que deja la build, log.
DESTINOS = {
    'windows': ('ConstruirApp.Construir', 'StandaloneWindows64',
                'WindowsStandaloneSupport', APP, 'unity_build.log'),
    'web': ('ConstruirApp.ConstruirWeb', 'WebGL',
            'WebGLSupport', os.path.join(CARPETA_WEB, 'index.html'),
            'unity_build_web.log'),
    'android': ('ConstruirApp.ConstruirAndroid', 'Android',
                'AndroidPlayer', APK, 'unity_build_android.log'),
}


class FaltaModulo(RuntimeError):
    """El editor no tiene el modulo de la plataforma pedida."""


def modulo_instalado(carpeta_modulo, version=None):
    """True si <Editor>/Data/PlaybackEngines/<carpeta_modulo> existe.

    Es donde Unity Hub instala cada 'Build Support'. Mirarlo desde
    Python evita abrir Unity (minutos) solo para que diga que falta.
    """
    unity = buscar_unity(version)
    motores = os.path.join(os.path.dirname(unity), 'Data', 'PlaybackEngines')
    # Sin distinguir mayusculas: Unity Hub instala 'WebGLSupport' pero
    # 'windowsstandalonesupport' (asi estan en 6000.5.10f1). Windows no
    # distingue, pero la comparacion explicita no depende de eso.
    try:
        instalados = {n.lower() for n in os.listdir(motores)
                      if os.path.isdir(os.path.join(motores, n))}
    except OSError:
        return False
    return carpeta_modulo.lower() in instalados


def correr_batch(metodo, log, timeout=1800, version=None,
                 objetivo='StandaloneWindows64', seco=False):
    """Ejecuta un metodo de Editor sin abrir la interfaz. Devuelve
    (codigo de salida, log); en seco, (None, log) sin abrir Unity.

    -buildTarget va SIEMPRE: sin el, Unity abre el proyecto en la
    ultima plataforma activa. Despues de un build Web o Android, el
    siguiente de Windows arrancaria en esa plataforma y tendria que
    cambiarla a mitad del metodo, reimportando todo.
    """
    unity = buscar_unity(version)
    cmd = [unity, '-batchmode', '-quit', '-nographics',
           '-projectPath', PROYECTO_UNITY,
           '-buildTarget', objetivo,
           '-logFile', log,
           '-executeMethod', metodo]

    if seco:
        print("  EN SECO: no se abre Unity. Se correria:")
        print("    " + subprocess.list2cmdline(cmd))
        return None, log

    os.makedirs(os.path.dirname(log), exist_ok=True)
    if os.path.exists(log):
        os.remove(log)

    print(f"  Unity: {os.path.basename(os.path.dirname(os.path.dirname(unity)))}")
    print(f"  ejecutando {metodo} ({objetivo}) ... (puede tardar varios minutos)")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    print(f"  termino en {time.time()-t0:.0f} s (codigo {proc.returncode})")
    return proc.returncode, log


def errores_del_log(log, n=15):
    """Saca las lineas de error del log de Unity."""
    if not os.path.exists(log):
        return ["(no se genero log)"]
    claves = ('error CS', 'BUILD FALLO', 'Exception', 'Aborting')
    salida = []
    with open(log, encoding='utf-8', errors='replace') as f:
        for linea in f:
            if any(k in linea for k in claves):
                salida.append(linea.rstrip())
    return salida[:n]


def _tamano_mb(ruta):
    if os.path.isfile(ruta):
        return os.path.getsize(ruta) / 1048576
    total = 0
    for base, _, archivos in os.walk(ruta):
        for a in archivos:
            total += os.path.getsize(os.path.join(base, a))
    return total / 1048576


# ============================================================
# 4. COMPILAR, ABRIR
# ============================================================
def construir(destino='windows', version=None, seco=False, timeout=3600):
    """
    Compila la app para 'windows', 'web' o 'android' con Unity en batch.

    Antes de abrir Unity comprueba que el editor tenga el modulo y que
    el proyecto no este abierto en otro Unity, y sincroniza
    StreamingAssets (la build copia esa carpeta tal cual). Con seco=True
    no escribe ni abre nada: dice que haria.
    """
    metodo, objetivo, modulo, salida, nombre_log = DESTINOS[destino]

    if not modulo_instalado(modulo, version):
        raise FaltaModulo(
            f"El editor de Unity no tiene el modulo para {destino} "
            f"(falta PlaybackEngines/{modulo}). No se abrio Unity ni se "
            f"copio nada.\n"
            f"Para instalarlo (baja varios GB): Unity Hub > Installs > "
            f"{version or version_del_proyecto()} > Add modules.")
    if not seco and unity_abierto():
        raise RuntimeError(
            "Unity tiene este proyecto abierto (unity/Temp/UnityLockfile): "
            "un batch no puede abrirlo a la vez. Cierralo, o compila desde "
            "el menu Laboratorio del editor.")

    registros = sincronizar.sincronizar(seco=seco)
    if sincronizar.fallida(registros, solo_modelo=True):
        raise RuntimeError("No se compila: el modelo no quedo en "
                           "StreamingAssets (ver arriba).")

    log = os.path.join(CARPETA_BUILD, nombre_log)
    codigo, log = correr_batch(metodo, log, timeout=timeout, version=version,
                               objetivo=objetivo, seco=seco)
    if seco:
        print(f"  dejaria: {rutas.relativa(salida)}   log: {rutas.relativa(log)}")
        return salida

    if codigo != 0 or not os.path.exists(salida):
        print("\nLa compilacion FALLO. Errores del log:")
        for e in errores_del_log(log):
            print("   ", e)
        raise RuntimeError(f"Unity no genero {rutas.relativa(salida)}. Log: {log}")

    donde = CARPETA_WEB if destino == 'web' else salida
    print(f"Build lista: {rutas.relativa(donde)} ({_tamano_mb(donde):.1f} MB)")
    return salida


def construir_app(forzar=False, version=None, seco=False):
    """
    Compila la aplicacion de Windows. Si ya existe y no se fuerza, no
    la vuelve a compilar (la build tarda varios minutos).
    """
    if os.path.exists(APP) and not forzar:
        # En seco tambien: decir "se correria Unity" cuando en realidad
        # no se correria seria mentir sobre lo que hace el modo.
        print(f"La app ya existe: {rutas.relativa(APP)}"
              + ("  (EN SECO: sin --forzar no se recompilaria)" if seco else ''))
        print("  (usa --forzar para recompilarla)")
        return APP
    return construir('windows', version=version, seco=seco, timeout=1800)


def construir_web(version=None, seco=False):
    """Compila build/web. Se sirve con cualquier servidor estatico."""
    salida = construir('web', version=version, seco=seco)
    if not seco:
        print("Para abrirlo desde el telefono (misma red):")
        print("    cd build\\web")
        print("    ..\\..\\.venv\\Scripts\\python.exe -m http.server 8080 --bind 0.0.0.0")
        print("  y en el navegador del telefono  http://<IPv4 del PC>:8080")
        print("  ('python sap.py sincronizar' actualiza sus datos sin recompilar;")
        print("   para reanalizar desde el telefono: python sap.py servidor --lan)")
    return salida


def construir_android(version=None, seco=False):
    """Compila el APK. Sin el modulo Android lanza FaltaModulo sin abrir Unity."""
    return construir('android', version=version, seco=seco)


def abrir_app(construir_si_falta=True, esperar=False, pantalla_completa=False):
    """
    Lanza el visor.

    construir_si_falta : compila la app la primera vez.
    esperar            : si True, bloquea hasta que se cierre la app.
    pantalla_completa  : abre la app ocupando toda la pantalla.

    La pantalla completa se pide con los argumentos ESTANDAR del player
    de Unity (-screen-fullscreen, -screen-width, -screen-height), no
    tocando la escena: asi no hace falta recompilar la app ni cambiar
    los Player Settings, y el mismo build sirve para las dos formas.
    """
    sincronizar_para_abrir()

    if not os.path.exists(APP):
        if not construir_si_falta:
            raise FileNotFoundError(
                f"No existe {APP}. Compilala con: python sap.py unity build")
        construir_app()

    cmd = [APP]
    if pantalla_completa:
        cmd += ['-screen-fullscreen', '1',
                '-screen-width', '1920', '-screen-height', '1080']
    print(f"Lanzando {os.path.basename(APP)} ..."
          + ("  (pantalla completa: Alt+Enter o Esc para salir)"
             if pantalla_completa else ""))
    proc = subprocess.Popen(cmd, cwd=CARPETA_BUILD)
    if esperar:
        proc.wait()
    else:
        # Un momento para que alcance a fallar de forma visible si el
        # ejecutable esta roto; si no, diria "lanzado" aunque la ventana
        # nunca aparezca.
        time.sleep(2.0)
        if proc.poll() is not None:
            raise RuntimeError(
                f"La app se cerro de inmediato (codigo {proc.returncode}). "
                f"Revisa {os.path.join(CARPETA_BUILD, 'unity_build.log')}")
        print("Visor abierto. Controles: arrastrar=orbitar, "
              "derecho=panear, rueda=zoom, F=encuadrar, click=inspeccionar.")
    return proc


def abrir_editor(version=None):
    """
    Abre el proyecto en el editor de Unity (para trabajar en el visor).
    Hay que apretar Play a mano: el modo Play no se puede automatizar
    desde fuera.
    """
    if unity_abierto():
        raise RuntimeError("Unity ya tiene este proyecto abierto; usa esa ventana "
                           "(para actualizar los datos: 'python sap.py sincronizar').")
    sincronizar_para_abrir()
    unity = buscar_unity(version)
    print(f"Abriendo el editor... (tarda ~1 min)")
    print("Cuando cargue: Assets/Scenes/SampleScene -> boton Play")
    return subprocess.Popen([unity, '-projectPath', PROYECTO_UNITY])


# ============================================================
# 5. EL SERVIDOR, PARA LAS CAPTURAS
# ============================================================
PUERTO = 5000
URL_PING = 'http://localhost:%d/ping'


def servidor_vivo(puerto=PUERTO, espera_s=1.0):
    """True si GET /ping responde en ese puerto."""
    try:
        with urllib.request.urlopen(URL_PING % puerto, timeout=espera_s) as r:
            return r.status == 200
    except Exception:
        return False


def abrir_servidor(puerto=PUERTO, log=None, espera_s=60.0):
    r"""
    Levanta el servidor de reanalisis (python -m exportar.servidor) en
    segundo plano y espera a que /ping responda. Devuelve el proceso; quien
    lo pidio lo apaga (proc.terminate()).

    Por que hace falta un servidor: la app compilada NO puede correr
    OpenSees (es Python). Unity manda el modelo por HTTP, Python lo
    resuelve y devuelve los desplazamientos. Es la misma separacion de
    siempre -- OpenSees calcula, Unity muestra -- solo que en vivo.

    Escucha solo en 127.0.0.1: nadie fuera de este equipo llega. Su salida
    va a `log` (por defecto build/servidor.log) para no mezclarse con la
    de quien lo levanto. /ping responde antes de que termine de armar la
    base de /combinar: /combinar espera al lock y la usa cuando esta.
    """
    import importlib.util
    if importlib.util.find_spec('exportar.servidor') is None:
        raise FileNotFoundError('falta exportar/servidor.py')
    try:
        import flask  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Falta Flask. Instalalo con:\n"
            "    .venv\\Scripts\\python.exe -m pip install flask")

    log = log or os.path.join(CARPETA_BUILD, 'servidor.log')
    os.makedirs(os.path.dirname(log), exist_ok=True)
    print(f"Levantando el servidor en localhost:{puerto} (salida en {rutas.relativa(log)}) ...")
    salida = open(log, 'w', encoding='utf-8')
    proc = subprocess.Popen([sys.executable, '-m', 'exportar.servidor', '--puerto', str(puerto)],
                            cwd=rutas.RAIZ, stdout=salida, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    proc.log_abierto = salida
    t0 = time.time()
    while time.time() - t0 < espera_s:
        if proc.poll() is not None:
            salida.close()
            raise RuntimeError(
                f"El servidor se cerro de inmediato (codigo {proc.returncode}). "
                f"Puede que el puerto {puerto} este ocupado. Ver {rutas.relativa(log)}")
        if servidor_vivo(puerto):
            print(f"  /ping responde ({time.time() - t0:.1f} s)")
            return proc
        time.sleep(0.5)
    apagar_servidor(proc)
    raise RuntimeError(f"El servidor no respondio /ping en {espera_s:.0f} s. Ver {rutas.relativa(log)}")


def apagar_servidor(proc):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log = getattr(proc, 'log_abierto', None)
    if log is not None:
        log.close()


# ============================================================
# 6. CAPTURAS
# ============================================================
# Los modos de la app compilada (Capturas.cs: -capturar <modo> <carpeta>).
MODOS_CAPTURA = ('visor', 'diagramas', 'persona', 'relieve')
# Solo el modo visor usa el servidor: LIBRE (POST /combinar) y la M1
# (POST /analizar). Sin servidor esas dos quedan en el registro como no
# hechas y la captura termina igual.
CON_SERVIDOR = ('visor',)
# La app corta sola (la captura del visor tiene un tope de 900 s); esto es
# por si la app se cuelga antes de llegar a su tope.
TOPE_CAPTURA_S = 1200


def ids_m1():
    """'<columna>,<nodo>,<viga>' de la M1 (entrada/laboratorio.json, modificaciones)."""
    from calculo import laboratorio as lab
    m1 = lab.bloque('modificaciones')['M1']
    return '%d,%d,%d' % (int(m1['borrar_elemento']), int(m1['nodo']), int(m1['elemento']))


def comando_de_captura(modo, carpeta):
    """La linea de comandos de la app para una captura."""
    cmd = [APP, '-capturar', modo, carpeta]
    if modo == 'visor':
        cmd += ['-m1', ids_m1()]
    cmd += ['-logFile', os.path.join(CARPETA_BUILD, 'capturar_%s.log' % modo)]
    return cmd


def capturar(argv=None):
    """
    sap.py capturar <visor|diagramas|persona|relieve> [--carpeta C] [--sin-servidor] [--seco]

    Corre la app compilada en modo captura y espera a que se cierre.
    Devuelve 0 si salio con 0 y dejo un registro.txt nuevo; 1 si no.
    """
    ap = argparse.ArgumentParser(
        prog='sap.py capturar',
        description='La app compilada saca sus fotos y su registro.txt sin intervencion.')
    ap.add_argument('modo', choices=MODOS_CAPTURA)
    ap.add_argument('--carpeta', metavar='C',
                    help='donde deja las fotos y registro.txt '
                         '(por defecto verificacion/registros/capturas/<modo>)')
    ap.add_argument('--sin-servidor', action='store_true',
                    help='no levantar el servidor aunque /ping no responda '
                         '(en el modo visor, LIBRE y la M1 quedan sin hacer)')
    ap.add_argument('--seco', action='store_true',
                    help='decir que correria, sin abrir la app ni el servidor')
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    carpeta = (os.path.abspath(args.carpeta) if args.carpeta
               else os.path.join(rutas.REGISTROS, 'capturas', args.modo))
    cmd = comando_de_captura(args.modo, carpeta)
    usa_servidor = args.modo in CON_SERVIDOR and not args.sin_servidor
    log = cmd[-1]

    print('=' * 72)
    print('  CAPTURA %s   ->  %s' % (args.modo.upper(), rutas.relativa(carpeta)))
    print('=' * 72)
    if args.seco:
        print('  EN SECO: no se abre la app. Se correria:')
        print('    ' + subprocess.list2cmdline(cmd))
        if usa_servidor:
            print('  con el servidor en localhost:%d (%s)'
                  % (PUERTO, 'ya responde' if servidor_vivo() else 'se levantaria para la captura'))
        return 0
    if not os.path.isfile(APP):
        print('  ERROR: no existe %s. Compilala con: python sap.py unity build' % rutas.relativa(APP))
        return 1

    try:
        sincronizar_para_abrir()
    except (FileNotFoundError, RuntimeError) as e:
        print('\nERROR: %s' % e)
        return 1

    proc_srv = None
    if usa_servidor and not servidor_vivo():
        try:
            proc_srv = abrir_servidor()
        except (FileNotFoundError, RuntimeError) as e:
            print('  AVISO: sin servidor (%s): LIBRE y la M1 quedan sin hacer' % e)
    elif usa_servidor:
        print('  el servidor ya responde en localhost:%d' % PUERTO)

    os.makedirs(carpeta, exist_ok=True)
    print('  ' + subprocess.list2cmdline(cmd))
    t0 = time.time()
    codigo = None
    try:
        codigo = subprocess.run(cmd, cwd=CARPETA_BUILD, timeout=TOPE_CAPTURA_S).returncode
    except subprocess.TimeoutExpired:
        print('  la app no termino en %d s: se corto' % TOPE_CAPTURA_S)
    finally:
        apagar_servidor(proc_srv)

    registro = os.path.join(carpeta, 'registro.txt')
    nuevo = os.path.isfile(registro) and os.path.getmtime(registro) >= t0 - 1.0
    fotos = [f for f in os.listdir(carpeta)
             if f.lower().endswith('.jpg') and os.path.getmtime(os.path.join(carpeta, f)) >= t0 - 1.0]
    print('  la app termino en %.0f s (codigo %s): %d foto(s), registro.txt %s'
          % (time.time() - t0, codigo, len(fotos), 'nuevo' if nuevo else 'NO SE ESCRIBIO'))
    if codigo != 0 or not nuevo:
        print('  Errores del log de la app (%s):' % rutas.relativa(log))
        for e in errores_del_log(log):
            print('   ', e)
        return 1
    print('  -> %s' % rutas.relativa(registro))
    return 0


# ============================================================
# 7. COMPILAR LOS C# SIN ABRIR UNITY
# ============================================================
SEP = '\\'

# (ensamblado, csproj, comodin de inclusion, comodin de exclusion)
# Es la regla de Unity para los scripts sin .asmdef: todo lo que esta
# bajo una carpeta 'Editor' va al ensamblado del editor; el resto, al
# del juego. No hay .asmdef ni Plugins en Assets.
ENSAMBLADOS = (
    ('Assembly-CSharp', 'Assembly-CSharp.csproj',
     r'Assets\**\*.cs', r'Assets\**\Editor\**\*.cs'),
    ('Assembly-CSharp-Editor', 'Assembly-CSharp-Editor.csproj',
     r'Assets\**\Editor\**\*.cs', ''),
)

# archivo(linea,col): error CS0103: mensaje [proyecto]
# Tambien sin posicion: 'CSC : error CS2001: ...' o un .targets de MSBuild.
PATRON = re.compile(
    r'^\s*(?P<origen>.*?)'
    r'(?:\((?P<linea>\d+),(?P<col>\d+)(?:,\d+,\d+)?\))?'
    r'\s*:\s*(?P<nivel>error|warning)\s+(?P<codigo>[A-Za-z]+\d+)\s*:\s*'
    r'(?P<mensaje>.*?)'
    r'(?:\s+\[(?P<proyecto>[^\]]+)\])?\s*$')


def buscar_dotnet(explicito=None):
    """El dotnet.exe de la instalacion de Unity de la version del proyecto.

    Se usa ESE y no uno del sistema: trae el SDK con el que se probaron
    los .csproj que genera Unity (netstandard2.1, analizadores de Unity),
    y no exige instalar nada.
    """
    if explicito:
        return explicito if os.path.isfile(explicito) else None
    version = version_del_proyecto() or VERSION_POR_DEFECTO
    bases = [r'C:\Program Files\Unity\Hub\Editor',
             os.path.expandvars(r'%LOCALAPPDATA%\Unity\Hub\Editor'),
             r'C:\Program Files\Unity\Editor']
    for base in bases:
        for sub in ((version, 'Editor'), ('',)):
            exe = os.path.join(base, *sub, 'Data', 'DotNetSdk', 'dotnet.exe')
            if os.path.isfile(exe):
                return exe
    return None


def _escapar_msbuild(ruta):
    """MSBuild interpreta % $ @ ; ' en los atributos: se escapan."""
    for c in '%$@;\'':
        ruta = ruta.replace(c, '%%%02X' % ord(c))
    return ruta


def preparar_csproj(texto, carpeta_unity, incluir, excluir):
    """El csproj de Unity, listo para compilar desde otra carpeta."""
    base = _escapar_msbuild(os.path.abspath(carpeta_unity).rstrip('\\/')) + SEP

    # 1) La lista fija de .cs se reemplaza por comodines.
    texto = re.sub(r'[ \t]*<Compile Include="[^"]*"\s*/>\r?\n?', '', texto)
    compilar = '    <Compile Include="%s%s"%s />\n' % (
        base, incluir, (' Exclude="%s%s"' % (base, excluir)) if excluir else '')
    ancla = '<Import Project="Sdk.targets"'
    if ancla not in texto:
        raise ValueError('el csproj no tiene %s: formato de Unity desconocido' % ancla)
    texto = texto.replace(ancla, '<ItemGroup>\n' + compilar + '  </ItemGroup>\n  ' + ancla, 1)

    # 2) Rutas relativas al proyecto de Unity -> absolutas.
    texto = re.sub(r'(Include=")((?:Assets|Library|Packages)\\)',
                   lambda m: m.group(1) + base + m.group(2), texto)
    texto = re.sub(r'(<HintPath>)((?:Assets|Library|Packages)\\)',
                   lambda m: m.group(1) + base + m.group(2), texto)
    return texto


def _normal(ruta):
    return os.path.normcase(os.path.normpath(os.path.abspath(ruta)))


def resolver_solo(rutas_pedidas):
    """Las rutas de --solo, absolutas, o None si alguna no sirve.

    Acepta relativas a la raiz o al cwd, y un nombre suelto ('PanelUI.cs')
    si hay UN solo .cs con ese nombre en unity/Assets.

    Una ruta que no es un .cs existente dentro de unity/Assets NO se
    acepta: ningun error del compilador calzaria con ella, todos
    saldrian como "ajenos" y el veredicto seria OK sin haber mirado el
    archivo (aprobar por vacio)."""
    assets = _normal(os.path.join(PROYECTO_UNITY, 'Assets'))
    salida, malas = [], []
    for r in rutas_pedidas:
        candidatas = [r] if os.path.isabs(r) else [os.path.join(rutas.RAIZ, r), r]
        elegida = next((c for c in candidatas if os.path.isfile(c)), None)
        if elegida is None and not os.path.isabs(r) and os.path.basename(r) == r:
            hallados = [os.path.join(d, r) for d, _, archivos in os.walk(assets)
                        if r in archivos]
            if len(hallados) == 1:
                elegida = hallados[0]
            elif len(hallados) > 1:
                malas.append('%s: hay %d con ese nombre en unity/Assets; da la ruta'
                             % (r, len(hallados)))
                continue
        if elegida is None:
            malas.append('%s: no existe' % r)
            continue
        normal = _normal(elegida)
        if not normal.lower().endswith('.cs'):
            malas.append('%s: no es un .cs' % r)
        elif not normal.startswith(assets + os.sep):
            malas.append('%s: no esta dentro de unity/Assets (no se compila)' % r)
        else:
            salida.append(normal)
    if malas:
        for m in malas:
            print('  --solo: ' + m)
        return None
    return salida


def ensamblado_de_archivo(ruta_normal):
    """A que ensamblado va un .cs, con la misma regla de los comodines:
    una carpeta 'Editor' DENTRO de Assets (no en la ruta del proyecto)."""
    assets = _normal(os.path.join(PROYECTO_UNITY, 'Assets'))
    rel = os.path.relpath(ruta_normal, assets) if ruta_normal.startswith(assets + os.sep) \
        else ruta_normal
    partes = rel.split(os.sep)[:-1]
    return 'Assembly-CSharp-Editor' if 'editor' in [p.lower() for p in partes] \
        else 'Assembly-CSharp'


def dotnet_build(dotnet, carpeta, verbose=False):
    """dotnet build en la carpeta temporal. Devuelve (codigo, lineas, segundos)."""
    csproj_editor = os.path.join(carpeta, ENSAMBLADOS[1][1])
    cmd = [dotnet, 'build', csproj_editor, '-nologo',
           '-v', 'n' if verbose else 'q',
           '-nodeReuse:false', '-tl:off', '-clp:NoSummary;ForceNoAlign']
    env = dict(os.environ,
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1',
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
               MSBUILDDISABLENODEREUSE='1',
               # Mensajes en ingles: el formato 'error CS' se lee igual,
               # pero asi los textos se pueden buscar en la documentacion.
               DOTNET_CLI_UI_LANGUAGE='en')
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=carpeta, env=env, capture_output=True,
                          timeout=900)
    texto = (proc.stdout or b'').decode('utf-8', errors='replace') + '\n' + \
        (proc.stderr or b'').decode('utf-8', errors='replace')
    return proc.returncode, texto.splitlines(), time.time() - t0


def leer_diagnosticos(lineas):
    """Los error/warning del log, sin repetir (MSBuild los repite)."""
    vistos, salida = set(), []
    for linea in lineas:
        m = PATRON.match(linea)
        if not m:
            continue
        d = m.groupdict()
        proyecto = os.path.basename(d['proyecto'] or '')
        d['ensamblado'] = proyecto[:-len('.csproj')] if proyecto.endswith('.csproj') else ''
        origen = d['origen'].strip()
        d['archivo'] = _normal(origen) if d['linea'] and origen.lower().endswith('.cs') else ''
        if not d['ensamblado'] and d['archivo']:
            d['ensamblado'] = ensamblado_de_archivo(d['archivo'])
        clave = (d['nivel'], d['codigo'], d['archivo'] or origen, d['linea'], d['col'],
                 d['mensaje'], d['ensamblado'])
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(d)
    return salida


def _texto(d):
    if d['archivo']:
        # Se muestra la ruta como la escribio el compilador (con sus
        # mayusculas); 'archivo' esta normalizada solo para comparar.
        rel = os.path.relpath(d['origen'].strip(), rutas.RAIZ)
        return '%s(%s,%s): %s %s: %s' % (rel, d['linea'], d['col'], d['nivel'],
                                         d['codigo'], d['mensaje'])
    return '%s: %s %s: %s' % (d['origen'].strip(), d['nivel'], d['codigo'], d['mensaje'])


def compilar_cs(argv=None):
    """sap.py unity compilar [--solo RUTA ...] [--avisos] [--conservar] [--dotnet RUTA] [--verbose]"""
    ap = argparse.ArgumentParser(
        prog='sap.py unity compilar',
        description='Compila los C# de unity/ con el dotnet de Unity, sin abrir Unity.')
    ap.add_argument('--solo', nargs='+', metavar='RUTA', default=None,
                    help='sale con 1 solo si hay errores CS en estos archivos; '
                         'los demas errores se imprimen como AVISO')
    ap.add_argument('--avisos', action='store_true',
                    help='imprime tambien los warnings (por defecto solo se cuentan, '
                         'salvo los de los archivos de --solo)')
    ap.add_argument('--conservar', action='store_true',
                    help='no borra la carpeta temporal (para mirar el log o el obj/)')
    ap.add_argument('--dotnet', default=None, help='ruta a dotnet.exe (por defecto, el de Unity)')
    ap.add_argument('--verbose', action='store_true', help='log de MSBuild completo')
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    print('=' * 72)
    print('  COMPILAR C# DE UNITY SIN ABRIR UNITY')
    print('=' * 72)

    # --- los .csproj ---
    faltan = [c for _, c, _, _ in ENSAMBLADOS if not os.path.isfile(os.path.join(PROYECTO_UNITY, c))]
    if faltan:
        print('  NO SE PUEDE COMPILAR: faltan %s en %s'
              % (' y '.join(faltan), os.path.relpath(PROYECTO_UNITY, rutas.RAIZ)))
        print('  Los genera Unity y no estan en git (.gitignore: *.csproj). Para crearlos:')
        print('    abrir el proyecto en Unity una vez, o en Unity:')
        print('    Edit > Preferences > External Tools > Regenerate project files')
        return 2

    dotnet = buscar_dotnet(args.dotnet)
    if not dotnet:
        print('  NO SE PUEDE COMPILAR: no encontre dotnet.exe de Unity %s'
              % (version_del_proyecto() or VERSION_POR_DEFECTO))
        print('  (se busca en C:\\Program Files\\Unity\\Hub\\Editor\\<version>\\Editor\\Data\\DotNetSdk;'
              ' o pasa --dotnet <ruta>)')
        return 2

    solo = None
    if args.solo:
        solo = resolver_solo(args.solo)
        if solo is None:
            print('\n  NO VERIFICADO: corrige las rutas de --solo (relativas a la raiz, o solo el'
                  ' nombre si es unico, p. ej. PanelUI.cs)')
            return 2

    carpeta = tempfile.mkdtemp(prefix='compilar_unity_')
    try:
        for _, nombre, incluir, excluir in ENSAMBLADOS:
            with io.open(os.path.join(PROYECTO_UNITY, nombre), encoding='utf-8-sig') as f:
                texto = f.read()
            try:
                preparado = preparar_csproj(texto, PROYECTO_UNITY, incluir, excluir)
            except ValueError as ex:
                print('\n  NO VERIFICADO: %s: %s' % (nombre, ex))
                return 2
            with io.open(os.path.join(carpeta, nombre), 'w', encoding='utf-8') as f:
                f.write(preparado)

        print('  dotnet     %s' % dotnet)
        print('  temporal   %s' % carpeta)
        try:
            codigo, lineas, segundos = dotnet_build(dotnet, carpeta, args.verbose)
        except (subprocess.TimeoutExpired, OSError) as ex:
            # Sin esto Python sale con 1, que aca significa "hay errores
            # CS": un dotnet colgado pareceria un error de tipeo.
            print('\n  NO VERIFICADO: dotnet build no termino (%s)' % ex)
            return 2
        diags = leer_diagnosticos(lineas)
        compilados = {e: os.path.isfile(os.path.join(carpeta, 'Temp', 'bin', 'Debug', e + '.dll'))
                      for e, _, _, _ in ENSAMBLADOS}
        print('  dotnet build termino en %.1f s (codigo %d)' % (segundos, codigo))
        if args.verbose:
            print('\n'.join(lineas))
    finally:
        if args.conservar:
            print('  (se conserva %s)' % carpeta)
        else:
            shutil.rmtree(carpeta, ignore_errors=True)

    errores_cs = [d for d in diags if d['nivel'] == 'error' and d['codigo'].upper().startswith('CS')]
    errores_otros = [d for d in diags if d['nivel'] == 'error' and not d['codigo'].upper().startswith('CS')]
    avisos = [d for d in diags if d['nivel'] == 'warning']

    def es_mio(d):
        return solo is not None and d['archivo'] in solo

    # ------------------------------------------------------------
    print()
    if solo is not None:
        print('  --solo: %s' % ', '.join(args.solo))
    mios = [d for d in errores_cs if solo is None or es_mio(d)]
    ajenos = [d for d in errores_cs if solo is not None and not es_mio(d)]
    for d in mios:
        print('  ERROR  ' + _texto(d))
    for d in ajenos:
        print('  AVISO (error en archivo ajeno)  ' + _texto(d))
    for d in errores_otros:
        print('  ERROR DE HERRAMIENTA  ' + _texto(d))
    for d in avisos:
        if args.avisos or es_mio(d):
            print('  warning  ' + _texto(d))

    # ------------------------------------------------------------
    print()
    print('  %-24s %8s %8s   %s' % ('ensamblado', 'errores', 'avisos', 'estado'))
    for e, _, _, _ in ENSAMBLADOS:
        n_err = sum(1 for d in errores_cs if d['ensamblado'] == e)
        n_av = sum(1 for d in avisos if d['ensamblado'] == e)
        if compilados[e]:
            estado = 'compilado'
        elif e == 'Assembly-CSharp-Editor' and not compilados['Assembly-CSharp']:
            estado = 'NO COMPILADO (depende de Assembly-CSharp, que fallo)'
        else:
            estado = 'NO COMPILADO'
        print('  %-24s %8d %8d   %s' % (e, n_err, n_av, estado))
    if solo is not None:
        print('  en tus archivos: %d errores; en archivos ajenos: %d (AVISO)'
              % (len(mios), len(ajenos)))

    # ------------------------------------------------------------
    # El veredicto. Un error de herramienta sin errores CS significa que
    # no se compilo nada: no es un "OK".
    if solo is None:
        if errores_cs:
            print('\n  FALLA: %d errores CS' % len(errores_cs))
            return 1
        if errores_otros or not all(compilados.values()):
            print('\n  NO VERIFICADO: la herramienta fallo sin errores CS (ver arriba)')
            return 2
        print('\n  OK: los %d ensamblados compilan sin errores' % len(ENSAMBLADOS))
        return 0

    if mios:
        print('\n  FALLA: %d errores CS en tus archivos' % len(mios))
        return 1
    # Un ensamblado con errores ajenos igual se REVISO entero: Roslyn
    # reporta los errores de todos sus archivos, y en los tuyos no hubo.
    # Lo que no sirve es uno que ni se intento: el del editor cuando
    # Assembly-CSharp falla, o cualquiera si la herramienta se cayo.
    revisados = {e for e in compilados if compilados[e]} | {d['ensamblado'] for d in errores_cs}
    necesarios = {ensamblado_de_archivo(s) for s in solo}
    sin_revisar = sorted(necesarios - revisados)
    if sin_revisar:
        print('\n  NO VERIFICADO: %s no se llego a compilar; tus archivos no se revisaron'
              % ', '.join(sin_revisar))
        return 2
    print('\n  OK: tus archivos no tienen errores CS'
          + ('  (hay %d errores ajenos: AVISO)' % len(ajenos) if ajenos else ''))
    return 0


# ============================================================
MODOS = ('app', 'editor', 'build', 'web', 'android', 'compilar')


def main(argv=None):
    """sap.py unity <app|editor|build|web|android|compilar> [...]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'compilar':
        return compilar_cs(argv[1:])
    ap = argparse.ArgumentParser(
        prog='sap.py unity',
        description='Abre o compila el visor Unity.',
        epilog="'compilar' (los C# sin abrir Unity) tiene sus opciones: python sap.py unity "
               "compilar -h. Con --preparar (app, editor), sap.py corre antes 'preparar'.")
    ap.add_argument('modo', nargs='?', default='app', choices=MODOS)
    ap.add_argument('--pantalla-completa', '--fullscreen', action='store_true',
                    dest='pantalla_completa')
    ap.add_argument('--forzar', action='store_true',
                    help='build: recompilar aunque la app exista')
    ap.add_argument('--seco', action='store_true',
                    help='build/web/android: decir que haria, sin escribir ni abrir Unity')
    args = ap.parse_args(argv)

    # Ignorar --seco en 'app' o 'editor' seria peor que fallar: quien lo
    # pide espera que no se escriba ni se abra nada, y esos modos copian a
    # StreamingAssets y lanzan la app o el editor.
    if args.seco and args.modo not in ('build', 'web', 'android'):
        ap.error("--seco no sirve con el modo '%s' (solo build, web, android)" % args.modo)

    try:
        if args.modo == 'editor':
            abrir_editor()
        elif args.modo == 'build':
            construir_app(forzar=args.forzar, seco=args.seco)
        elif args.modo == 'web':
            construir_web(seco=args.seco)
        elif args.modo == 'android':
            construir_android(seco=args.seco)
        else:
            abrir_app(pantalla_completa=args.pantalla_completa)
    except (FileNotFoundError, RuntimeError) as e:
        print("\nERROR: %s" % e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
