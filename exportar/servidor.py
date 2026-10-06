# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/servidor.py  -  LO QUE UNITY PIDE EN VIVO
================================================================
 Un solo servidor, un solo puerto (5000), cuatro rutas:

   GET  /ping       chequear que el servidor vive
   POST /analizar   el modelo que Unity edito -> OpenSees: desplazamientos,
                    reacciones y fuerzas por caso, el equilibrio de cada
                    caso y el Excel del reanalisis (salidas/reanalisis.xlsx)
   POST /combinar   {"edificio": "conjunto", "G": 1.2, "Q": 1.0, "EX": -1.4, "EY": 0}
                    -> {ok, error, edificio, parametros, caso, equilibrio}
   GET  /estados    -> {ok, error, estados [E1..E3 sin caso], rangos de los sliders}

 Correr:
   python sap.py servidor                    solo este equipo, puerto 5000
   python sap.py servidor --lan              toda la red local (telefono, build Web)
   python sap.py servidor --puerto 5057
   python sap.py servidor --cs 0.20          la base de /combinar con otros parametros
                                             (los flags del laboratorio)
   python sap.py servidor --sin-precalentar  no armar la base al arrancar

 Formato exacto de pedidos y respuestas: CONTRATO.md, "Servidor".

 ----------------------------------------------------------------
 DOS FUENTES DE CASOS, CADA UNA EN SU RUTA
 ----------------------------------------------------------------
 /analizar resuelve los casos que trae el modelo que manda Unity (los
 casos DEL MODELO: G, Q, EX y EY de modelo.json, editados o no). /combinar
 combina los casos DEL LABORATORIO (q y Cs de entrada/laboratorio.json),
 los mismos de resultados.json. Solo G coincide entre las dos.

 ----------------------------------------------------------------
 QUE HACE /combinar
 ----------------------------------------------------------------
 La base -- los cuatro casos del laboratorio resueltos en OpenSees y las
 curvas P-M (calculo/superposicion.base, unos 15 a 30 s en el edificio)
 -- se arma UNA vez y queda en memoria. Desde ahi cada combinacion es
 superposicion.caso_combinado, suma lineal en Python sin volver a
 OpenSees, y la demanda-capacidad se rehace entera con los f combinados
 porque no es lineal. Unity no suma nada. Al arrancar la base se arma en
 segundo plano, para que el primer slider no espere; --sin-precalentar
 lo evita.

 ----------------------------------------------------------------
 POR QUE EL LOCK
 ----------------------------------------------------------------
 OpenSees es un singleton: ops.wipe() borra EL modelo, no "un" modelo.
 Flask atiende en hilos, y armar la base resuelve el modelo y corre las
 secciones de fibras: si un /analizar entra a la vez, uno hace ops.wipe()
 sobre el modelo del otro. Por eso /analizar y la base van bajo el MISMO
 lock, opensees.LOCK. Combinar no toca OpenSees y no lo toma.

 ----------------------------------------------------------------
 ERRORES
 ----------------------------------------------------------------
 TODA respuesta es JSON, tambien los errores: Unity lee el cuerpo en un
 ProtocolError y con una pagina HTML mostraria "JSON ilegible" en vez del
 motivo. 400 si el pedido es invalido (se arregla cambiando el pedido),
 500 si fallo algo nuestro, y 404/405 los que arma Flask solo. Los
 errores de /combinar y /estados se atrapan con BaseException (salvo
 Ctrl+C): el laboratorio corta con SystemExit, y un SystemExit dentro de
 un hilo de Flask terminaria la peticion sin respuesta.
================================================================
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time
import traceback

from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, HTTPException, RequestEntityTooLarge as Pesado

from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo import superposicion as sp

PUERTO = 5000

app = Flask(__name__)

# Tope al tamano de la peticion. Sin esto, un POST gigante se carga
# entero en memoria antes de que nadie lo mire.
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024   # 32 MB

# Mostrar el traceback completo en la respuesta HTTP (OPENSEES_DEBUG=1).
# Apagado por defecto: el traceback incluye rutas ABSOLUTAS del disco, o
# sea el nombre de usuario y la estructura de carpetas de quien lo corre.
# Con esto apagado el error igual se ve completo en la consola.
MOSTRAR_TRACEBACK = os.environ.get('OPENSEES_DEBUG', '') == '1'

# Access-Control-Allow-Origin: * en todas las respuestas, para que el
# build Web de Unity (que corre en el navegador, en otro origen) pueda
# leerlas. Lo que se abre: una pagina cualquiera abierta en el navegador
# de este equipo puede LEER la respuesta, que trae la ruta absoluta del
# Excel (con el nombre de usuario). Mandar el POST ya podia sin esto.
# OPENSEES_CORS=0 lo apaga.
PERMITIR_CORS = os.environ.get('OPENSEES_CORS', '1') != '0'

# Dos /analizar seguidos escriben el MISMO libro (salidas/reanalisis.xlsx).
# Escribirlo fuera del lock de OpenSees deja que el motor atienda al
# siguiente mientras tanto, pero dos escrituras a la vez sobre el mismo
# archivo en Windows fallan al reemplazarlo.
_lock_excel = threading.Lock()

# Flags de los parametros del laboratorio con que se arma la base (--cs
# 0.20 ...). Tienen que ser los de resultados.json que Unity tiene
# abierto: la respuesta trae las lineas de 'parametros' y el visor avisa
# si no son las suyas.
ARGV_PARAMETROS = []

_base = None
_lock_base = threading.Lock()


class PedidoInvalido(ValueError):
    """Lo que se arregla cambiando el pedido: HTTP 400."""


# ============================================================
# /ping Y LAS CABECERAS
# ============================================================
@app.route('/ping', methods=['GET'])
def ping():
    """Chequeo de vida. Unity lo llama para ver si el servidor esta."""
    return jsonify({'estado': 'vivo', 'motor': 'OpenSees'})


@app.after_request
def _cabeceras_cors(respuesta):
    """Ver PERMITIR_CORS. Content-Type en Allow-Headers porque un POST
    con application/json hace que el navegador pregunte antes (OPTIONS)."""
    if PERMITIR_CORS:
        respuesta.headers['Access-Control-Allow-Origin'] = '*'
        respuesta.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        respuesta.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return respuesta


@app.errorhandler(HTTPException)
def _error_http_en_json(e):
    """
    Los errores que Flask arma solo, sin pasar por una ruta: 404 (ruta mal
    escrita) y 405 (un GET a /analizar o /combinar). Sin esto salen como
    pagina HTML. Las redirecciones del enrutador (RequestRedirect, codigo
    3xx) se dejan pasar tal cual.
    """
    if e.code is None or e.code < 400:
        return e
    return jsonify({'ok': False,
                    'error': '%d %s: %s' % (e.code, e.name, e.description)}), e.code


# ============================================================
# /analizar: EL MODELO EDITADO, RESUELTO
# ============================================================
def edificio_del_modelo(data, del_pedido=None):
    """
    El nombre del modelo que llega: info.edificio si viene no vacio; si no,
    el parametro ?edificio= del pedido; si no, 'modelo'. Solo se aceptan
    letras, digitos, '_' y '-': lo que no calza se descarta entero en vez
    de limpiarlo a medias. JsonUtility manda info.edificio = "" cuando el
    JSON no lo traia. El libro es siempre salidas/reanalisis.xlsx (un
    edificio); el nombre identifica el pedido en la consola.
    """
    info = data.get('info') if isinstance(data, dict) else None
    for candidato in ((info or {}).get('edificio') if isinstance(info, dict) else None,
                      del_pedido):
        if isinstance(candidato, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,40}',
                                                        candidato.strip()):
            return candidato.strip()
    return 'modelo'


def modelo_como_lista(data):
    """
    El modelo con 'secciones' en la forma de LISTA, la que manda Unity y la
    que espera el libro del reanalisis. El motor acepta tambien el
    diccionario (opensees.normalizar_secciones), y un modelo que se resolvio
    no puede quedarse sin libro por eso: con el diccionario el escritor
    fallaba con "'str' object has no attribute 'get'". Copia superficial:
    'data' no se toca.
    """
    secciones = data.get('secciones')
    if not isinstance(secciones, dict):
        return data
    copia = dict(data)
    copia['secciones'] = [dict(s, nombre=nombre) for nombre, s in secciones.items()]
    return copia


def escribir_excel(data, resultados):
    """
    (ruta, None) si escribio salidas/reanalisis.xlsx, o (None, motivo) si no.

    El escritor se importa ACA ADENTRO: si exportar/excel.py falta o no
    carga, /analizar responde igual y el motivo va en 'excel_error'.

    Atrapa BaseException y no solo Exception: el escritor carga codigo del
    laboratorio que corta con SystemExit, y un SystemExit dentro de un hilo
    de Flask mataria la peticion sin respuesta. Un Excel que no se pudo
    escribir NUNCA rompe /analizar: el analisis ya esta hecho y Unity lo
    necesita igual.
    """
    try:
        from exportar import excel
        with _lock_excel:
            ruta = excel.escribir_libro_reanalisis(
                modelo_como_lista(data), resultados, rutas.salida('reanalisis'))
        return os.path.abspath(str(ruta)), None
    except BaseException as e:           # noqa: B902 -- ver docstring
        if isinstance(e, KeyboardInterrupt):
            raise
        traceback.print_exc()
        return None, '%s: %s' % (type(e).__name__, e)


@app.route('/analizar', methods=['POST'])
def analizar():
    """
    Recibe el modelo de Unity, lo resuelve (opensees.construir_y_resolver,
    con el equilibrio de cada caso) y deja el Excel del reanalisis.

    Errores: HTTP 400 si el pedido es invalido (JSON roto, falta una
    clave, una seccion inexistente: lo que se arregla cambiando el
    modelo) y 500 si es una falla nuestra. Siempre con cuerpo JSON
    {"ok": false, "error": ...}.
    """
    t0 = time.time()
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            raise ValueError('el cuerpo tiene que ser un objeto JSON con el modelo')
        with opensees.LOCK:
            resultados = opensees.construir_y_resolver(data)
    except (BadRequest, Pesado, ValueError, KeyError, TypeError) as e:
        return _respuesta_de_error(e, 400)
    except Exception as e:
        return _respuesta_de_error(e, 500)

    resultados['excel'], resultados['excel_error'] = escribir_excel(data, resultados)
    print('  POST /analizar %s: %.3f s'
          % (edificio_del_modelo(data, request.args.get('edificio')), time.time() - t0))
    return jsonify(resultados)


def _respuesta_de_error(e, codigo):
    """El error de /analizar, con la forma de su respuesta (avisos, excel)."""
    # El detalle completo siempre queda en la consola del servidor.
    traceback.print_exc()
    texto = str(e)
    if isinstance(e, KeyError):
        texto = 'falta la clave %s en el modelo' % texto
    elif isinstance(e, BadRequest):
        texto = 'el cuerpo no es JSON valido: %s' % (e.description or texto)
    elif isinstance(e, Pesado):
        # RequestEntityTooLarge NO hereda de BadRequest: sin esto, un
        # modelo por sobre MAX_CONTENT_LENGTH salia como HTTP 500 ("falla
        # nuestra") cuando es el pedido el que hay que achicar.
        texto = ('el modelo pesa mas de %.3g MB (MAX_CONTENT_LENGTH)'
                 % (app.config['MAX_CONTENT_LENGTH'] / (1024 * 1024)))
    salida = {'ok': False, 'error': texto, 'avisos': [],
              'excel': None, 'excel_error': 'no se resolvio el modelo'}
    if MOSTRAR_TRACEBACK:
        salida['traceback'] = traceback.format_exc()
    return jsonify(salida), codigo


# ============================================================
# /combinar Y /estados: LA SUPERPOSICION CON LAMBDAS LIBRES
# ============================================================
def obtener_base():
    """(base, recien_armada). La base del laboratorio, armada una vez."""
    global _base
    with _lock_base:
        if _base is not None:
            return _base, False
        with opensees.LOCK:
            # silenciar=False: AvisosDeOpenSees redirige el DESCRIPTOR 2
            # (os.dup2) para contar los 'analyze failed'. En un hilo del
            # servidor, con Flask escribiendo su log en ese descriptor desde
            # otro hilo, la consola de Windows invalida el handle y la base
            # falla con 'WinError 6 Controlador no valido'. Los avisos se ven
            # en esta consola: son los esperados de capacidad.interaccion.
            b = sp.base(ARGV_PARAMETROS, silenciar=False)
        _base = b
        print('  [base] %s armada en %.1f s (%d nodos, %d elementos)%s'
              % (_ed.NOMBRE, b['segundos'], len(b['modelo']['nodos']), len(b['largos']),
                 ('; ' + b['avisos_opensees']) if b['avisos_opensees'] else ''))
        return b, True


def edificio_del_pedido(pedido):
    """
    El servidor resuelve UN edificio, el de entrada/edificio.json. Unity
    manda en el pedido el info.edificio de su resultados.json: si nombra
    otro (o viene vacio), el pedido no se puede atender y es un 400, no
    una combinacion del modelo equivocado. Sin la clave, es este.
    """
    nombre = pedido.get('edificio', _ed.NOMBRE)
    if nombre != _ed.NOMBRE:
        raise PedidoInvalido('este servidor resuelve el edificio %r, el pedido es de %r'
                             % (_ed.NOMBRE, nombre))
    return nombre


def _error(e, codigo):
    """El error de /combinar y /estados: {ok: false, error}, la forma de
    RespuestaCombinar (la de /analizar trae ademas avisos y excel)."""
    if codigo >= 500:
        traceback.print_exc()
    texto = str(e)
    if isinstance(e, BadRequest):
        texto = 'el cuerpo no es JSON valido: %s' % (e.description or texto)
    elif isinstance(e, SystemExit):
        texto = 'el laboratorio corto: %s' % texto
    return jsonify({'ok': False, 'error': texto}), codigo


@app.route('/combinar', methods=['POST'])
def combinar():
    """POST /combinar: un caso 'LIBRE' para los lambdas pedidos."""
    t0 = time.time()
    try:
        pedido = request.get_json(force=True)
        if not isinstance(pedido, dict):
            raise PedidoInvalido('el cuerpo tiene que ser un objeto JSON '
                                 '{"edificio", "G", "Q", "EX", "EY"}')
        edificio = edificio_del_pedido(pedido)
        try:
            lambdas = sp.lambdas_de(pedido)
        except ValueError as e:
            raise PedidoInvalido(str(e))
        b, nueva = obtener_base()
        cuerpo = sp.respuesta_combinar(b, lambdas)
    except (PedidoInvalido, BadRequest, OverflowError) as e:   # lambda ~1e300 desborda: pedido
        return _error(e, 400)
    except BaseException as e:           # noqa: B902 -- ver el encabezado
        if isinstance(e, KeyboardInterrupt):
            raise
        return _error(e, 500)
    # El tiempo incluye escribir el JSON: es lo que espera Unity, no solo
    # la suma.
    respuesta = jsonify(cuerpo)
    print('  POST /combinar %s %s: %.3f s%s'
          % (edificio, cuerpo['caso']['descripcion'], time.time() - t0,
             ' (armando la base)' if nueva else ''))
    return respuesta


@app.route('/estados', methods=['GET'])
def estados():
    """GET /estados: E1..E3 (sin caso) y los rangos de los sliders."""
    try:
        return jsonify(sp.respuesta_estados())
    except BaseException as e:           # noqa: B902
        if isinstance(e, KeyboardInterrupt):
            raise
        return _error(e, 500)


def _precalentar():
    try:
        obtener_base()
    except BaseException as e:           # noqa: B902
        if isinstance(e, KeyboardInterrupt):
            raise
        print('  [base] no se pudo armar la de %s: %s' % (_ed.NOMBRE, e))


# ============================================================
def main(argv=None):
    """sap.py servidor [--lan] [--puerto 5000] [--sin-precalentar] [flags de los parametros]"""
    ap = argparse.ArgumentParser(
        prog='sap.py servidor',
        description='Servidor: /analizar, /ping, /combinar, /estados',
        allow_abbrev=False)
    ap.add_argument('--lan', action='store_true',
                    help='escuchar en toda la red local (telefono). No en una red publica.')
    ap.add_argument('--puerto', type=int, default=PUERTO)
    ap.add_argument('--sin-precalentar', action='store_true',
                    help='no armar la base de /combinar al arrancar')
    args, resto = ap.parse_known_args(argv)

    # Lo que no es de este servidor son flags de los parametros. Se validan
    # ahora: un --cs mal escrito tiene que cortar al arrancar, no en la
    # primera peticion de Unity.
    lab.cargar(resto)
    ARGV_PARAMETROS[:] = resto

    # Por defecto 127.0.0.1: solo este equipo. Con '0.0.0.0' (--lan),
    # cualquiera en el mismo WiFi puede mandarle peticiones: no puede
    # robar nada -- el servidor no ejecuta codigo y el unico archivo que
    # escribe es salidas/reanalisis.xlsx -- pero si tumbarlo con un modelo
    # enorme.
    host = '0.0.0.0' if args.lan else '127.0.0.1'
    print('=' * 64)
    print('  SERVIDOR OPENSEES <-> UNITY   %s' % _ed.NOMBRE.upper())
    print('=' * 64)
    print('  Escuchando en: http://%s:%d' % ('0.0.0.0' if args.lan else 'localhost',
                                             args.puerto))
    if args.lan:
        print('  *** ABIERTO A TODA LA RED LOCAL (--lan) ***')
    else:
        print('  Solo accesible desde este equipo (--lan para el telefono).')
    print('  POST /analizar  -> reanalisis del modelo editado (+ %s)'
          % rutas.relativa(rutas.salida('reanalisis')))
    print('  GET  /ping      -> chequear conexion')
    print('  POST /combinar  -> superposicion con lambdas libres')
    print('  GET  /estados   -> E1..E3 y rangos de los sliders')
    print('  parametros de la base: %s'
          % (' '.join(resto) or 'los de %s' % rutas.relativa(rutas.LABORATORIO)))
    print('=' * 64)

    if not args.sin_precalentar:
        threading.Thread(target=_precalentar, daemon=True).start()
    app.run(host=host, port=args.puerto, debug=False, threaded=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
