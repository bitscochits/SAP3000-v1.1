# -*- coding: utf-8 -*-
r"""
================================================================
 exportar/sincronizar.py  -  LAS COPIAS QUE LEEN UNITY Y LA AR
================================================================
 Unity y la app AR no leen salidas/: cada una lee SU copia. Este paso
 las deja al dia, y es lo unico que escribe en esas carpetas:

   salidas/modelo.json        ->  <StreamingAssets>/modelo.json
   salidas/resultados.json    ->  <StreamingAssets>/resultados.json
   salidas/carga_movil.json   ->  <StreamingAssets>/carga_movil.json
   salidas/persona.json       ->  <StreamingAssets>/persona.json
   salidas/relieve.json       ->  <StreamingAssets>/relieve.json
   salidas/resultados.xlsx    ->  <StreamingAssets>/resultados.xlsx
   salidas/ar.json            ->  ar/web/datos/ar.json

 <StreamingAssets> es la del proyecto (unity/Assets/StreamingAssets,
 siempre) y la de cada build que exista. La app compilada lee SU copia,
 no la del proyecto: sin copiar ahi seguiria mostrando lo que tenia al
 compilarse, sin avisar. Windows y Web la tienen como carpeta suelta,
 asi que basta con copiar; en Android queda dentro del .apk y hay que
 recompilar.

 Los nombres son los de rutas.NOMBRES_EN_UNITY, que son las constantes
 ARCHIVO de cada lector C#: la verificacion "nombres y copias" compara
 las dos listas y los md5 de cada copia contra salidas/.

 COMO COPIA
   - Solo lo que cambio (md5 distinto): un archivo igual no se reescribe.
   - De una vez: a un temporal al lado y despues os.replace (ver
     _copiar_atomico), para que un visor que lee justo en ese momento vea
     el viejo o el nuevo, nunca uno a medias.
   - Un JSON que dice ser de OTRO edificio (info.edificio distinto de
     'conjunto') no se copia, y en el destino queda el que habia. Uno que
     no lo dice (modelo.json) se copia.
   - Un origen que falta no borra ni pisa nada: se avisa como generarlo.
   - En las StreamingAssets borra los NOMBRES_VIEJOS con su .meta. Ningun
     lector los abre ya, y si se quedan la app compilada los arrastra a
     la build.

 Correr:
   python sap.py sincronizar                     copia lo que cambio
   python sap.py sincronizar --seco              dice que copiaria y que borraria, sin escribir
   python sap.py sincronizar --destino CARPETA   los siete archivos a esa carpeta y nada mas
                                                 (no toca Unity ni la AR ni borra nada)
================================================================
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys

from calculo import edificio as _ed
from calculo import rutas

# Lo que el visor leia de StreamingAssets antes de que los nombres pasaran
# a ser los de rutas.NOMBRES_EN_UNITY (modelo_unity.json ya no lo leia
# nadie). Se borran con su .meta.
NOMBRES_VIEJOS = ('modelo_unity_edificio.json', 'semana03.json', 'semana04.json',
                  'superposicion.json', 'influencias.json', 'topografia.json',
                  'modelo_unity.json')

# El unico sin el cual el visor no tiene nada que mostrar: abrir o compilar
# la app sin el es inutil. Los demas, si faltan, el visor lo avisa en su panel.
OBLIGATORIO = 'modelo'


def archivos():
    """
    Cada copia: (clave, origen en salidas/, nombre en el destino,
    obligatorio, para) con para = 'unity' (a cada StreamingAssets) o 'ar'
    (a ar/web/datos).
    """
    lista = [(clave, rutas.salida(clave), nombre, clave == OBLIGATORIO, 'unity')
             for clave, nombre in rutas.NOMBRES_EN_UNITY.items()]
    lista.append(('ar', rutas.salida('ar'), 'ar.json', False, 'ar'))
    return lista


def carpetas_streaming():
    """
    Las StreamingAssets que hay que mantener al dia: la del proyecto
    (siempre) y la de cada build que exista.
    """
    carpetas = [rutas.STREAMING]
    for sa in (os.path.join(rutas.BUILD, 'LaboratorioEstructural_Data', 'StreamingAssets'),
               os.path.join(rutas.BUILD, 'web', 'StreamingAssets')):
        if os.path.isdir(sa):
            carpetas.append(sa)
    return carpetas


def carpeta_ar():
    """La carpeta de donde la app AR lee ar.json."""
    return os.path.join(rutas.AR_WEB, 'datos')


def edificio_de(ruta):
    """El edificio que dice un JSON (info.edificio), o None si no dice."""
    try:
        with io.open(ruta, encoding='utf-8') as fh:
            ed = (json.load(fh).get('info') or {}).get('edificio')
        return ed or None
    except Exception:
        return None


def md5(ruta):
    h = hashlib.md5()
    with open(ruta, 'rb') as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b''):
            h.update(bloque)
    return h.hexdigest()


def _copiar_atomico(origen, destino):
    """
    Copia a un temporal al lado y lo renombra encima del destino.

    Asi un visor que lee justo en ese momento ve el archivo viejo o el
    nuevo, nunca uno a medio escribir (JsonUtility fallaria con un error
    que no dice nada del copiado). El temporal empieza con '.' y termina
    en '.tmp': Unity ignora esos nombres y no le crea un .meta si el
    editor esta abierto. Por eso no se usa rutas.escribir_atomico, cuyo
    temporal ('<nombre>.tmp<pid>') Unity si importaria.
    """
    carpeta = os.path.dirname(destino)
    os.makedirs(carpeta, exist_ok=True)
    tmp = os.path.join(carpeta, '.' + os.path.basename(destino) + '.tmp')
    shutil.copyfile(origen, tmp)
    try:
        os.replace(tmp, destino)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _rel(ruta):
    """Relativa a la raiz si esta dentro; si no (--destino afuera), absoluta."""
    try:
        rel = os.path.relpath(ruta, rutas.RAIZ)
    except ValueError:              # otra unidad de disco
        return ruta
    return ruta if rel.startswith('..') else rel


def sincronizar(seco=False, carpetas=None, para_ar=None, borrar_viejos=True, verbose=True):
    """
    Copia salidas/ a las StreamingAssets y a la AR. No abre Unity.

    seco          : no escribe ni borra nada; dice que haria (y compara md5).
    carpetas      : las StreamingAssets de destino; por defecto carpetas_streaming().
    para_ar       : la carpeta de ar.json; por defecto carpeta_ar().
    borrar_viejos : borrar NOMBRES_VIEJOS (y su .meta) de esas StreamingAssets.

    Devuelve una lista de registros (dict). Los de copia ('accion' =
    'copiar') traen 'estado' en: 'copiado', 'igual', 'se copiaria',
    'no copiado', 'error'. Los de nombres viejos ('accion' = 'borrar'):
    'borrado', 'se borraria', 'error'.
    """
    if carpetas is None:
        carpetas = carpetas_streaming()
    if para_ar is None:
        para_ar = carpeta_ar()

    registros = []
    for clave, origen, nombre, obligatorio, para in archivos():
        motivo = None
        ed_origen = None
        if not os.path.exists(origen):
            motivo = 'falta el origen'
        elif nombre.endswith('.json'):
            ed_origen = edificio_de(origen)
            if ed_origen is not None and ed_origen != _ed.NOMBRE:
                motivo = "es de '%s', no de '%s'" % (ed_origen, _ed.NOMBRE)
        md5_origen = md5(origen) if motivo is None else None

        for carpeta in (carpetas if para == 'unity' else [para_ar]):
            destino = os.path.join(carpeta, nombre)
            md5_destino = md5(destino) if os.path.isfile(destino) else None
            reg = {'accion': 'copiar', 'clave': clave, 'nombre': nombre, 'origen': origen,
                   'destino': destino, 'carpeta': carpeta, 'obligatorio': obligatorio,
                   'edificio_origen': ed_origen, 'motivo': motivo,
                   'md5_origen': md5_origen, 'md5_destino': md5_destino}
            if motivo is not None:
                reg['estado'] = 'no copiado'
            elif md5_destino == md5_origen:
                reg['estado'] = 'igual'
            elif seco:
                reg['estado'] = 'se copiaria'
            else:
                try:
                    _copiar_atomico(origen, destino)
                    reg['estado'] = 'copiado'
                    reg['md5_destino'] = md5(destino)
                except OSError as e:
                    reg['estado'] = 'error'
                    reg['motivo'] = '%s (si es el Excel, esta abierto?)' % e
            registros.append(reg)

    if borrar_viejos:
        for carpeta in carpetas:
            for nombre in NOMBRES_VIEJOS:
                ruta = os.path.join(carpeta, nombre)
                meta = ruta + '.meta'
                hay = [r for r in (ruta, meta) if os.path.isfile(r)]
                if not hay:
                    continue
                reg = {'accion': 'borrar', 'clave': None, 'nombre': nombre, 'origen': None,
                       'destino': ruta, 'carpeta': carpeta, 'obligatorio': False,
                       'motivo': None, 'con_meta': os.path.isfile(meta)}
                if seco:
                    reg['estado'] = 'se borraria'
                else:
                    try:
                        for r in hay:
                            os.remove(r)
                        reg['estado'] = 'borrado'
                    except OSError as e:
                        reg['estado'] = 'error'
                        reg['motivo'] = str(e)
                registros.append(reg)

    if verbose:
        _imprimir(registros, carpetas, para_ar, seco)
    return registros


def fallida(registros, solo_modelo=False):
    """True si el modelo no quedo copiado (falta, es de otro edificio o no
    se pudo escribir) o, sin solo_modelo, si algo no se pudo escribir o
    borrar.

    solo_modelo es para abrir o compilar: un Excel abierto en otra ventana
    no deberia impedir ver el edificio (se avisa igual). El comando
    'sincronizar', que existe solo para copiar, falla con cualquier error
    de escritura.
    """
    return any((r['obligatorio'] or not solo_modelo) and r['estado'] == 'error'
               or (r['obligatorio'] and r['estado'] == 'no copiado')
               for r in registros)


def _imprimir(registros, carpetas, para_ar, seco):
    print("  Sincronizar salidas/%s" % ("  (EN SECO: no se escribe nada)" if seco else ''))
    destinos = list(carpetas) + ([para_ar] if para_ar not in carpetas else [])
    indice = {c: i for i, c in enumerate(destinos, 1)}
    for c in destinos:
        print("    [%d] %s%s" % (indice[c], _rel(c), '   (ar.json)' if c == para_ar else ''))

    copias = [r for r in registros if r['accion'] == 'copiar']
    por_nombre = []
    for r in copias:
        if not por_nombre or por_nombre[-1][0] != r['nombre']:
            por_nombre.append((r['nombre'], []))
        por_nombre[-1][1].append(r)

    avisos = []
    for nombre, regs in por_nombre:
        r0 = regs[0]
        print("  %s  <-  %s" % (nombre, _rel(r0['origen'])))
        if r0['motivo'] is not None and r0['estado'] == 'no copiado':
            print("      NO SE COPIA: %s" % r0['motivo'])
        else:
            print("      md5 origen %s" % r0['md5_origen'])
        for r in regs:
            n = indice.get(r['carpeta'], '?')
            if r['estado'] == 'no copiado':
                if r['md5_destino'] is None:
                    queda = 'no hay ninguno'
                else:
                    ed_dest = edificio_de(r['destino']) if nombre.endswith('.json') else None
                    queda = 'queda el que habia%s' % (" (de '%s')" % ed_dest if ed_dest else '')
                print("      [%s] %s" % (n, queda))
            elif r['estado'] == 'error':
                print("      [%s] ERROR al escribir: %s" % (n, r['motivo']))
            elif r['estado'] == 'igual':
                print("      [%s] igual" % n)
            else:
                antes = r['md5_destino'] if r['estado'] == 'se copiaria' else None
                print("      [%s] %s%s" % (n, r['estado'],
                                            '' if r['estado'] == 'copiado'
                                            else '  (hoy %s)' % (antes or 'no existe')))
        if r0['estado'] == 'no copiado':
            avisos.append((nombre, r0['clave'], r0['obligatorio'], r0['motivo']))

    viejos = [r for r in registros if r['accion'] == 'borrar']
    if viejos:
        print("  nombres viejos (ningun lector los abre):")
        for r in viejos:
            n = indice.get(r['carpeta'], '?')
            print("      [%s] %s%s  %s%s" % (n, r['nombre'], ' (+ .meta)' if r['con_meta'] else '',
                                          r['estado'],
                                          ': %s' % r['motivo'] if r['estado'] == 'error' else ''))

    cuenta = {}
    for r in registros:
        cuenta[r['estado']] = cuenta.get(r['estado'], 0) + 1
    print("  resumen: " + ", ".join('%s %d' % (k, cuenta[k]) for k in
                                    ('copiado', 'se copiaria', 'igual', 'no copiado',
                                     'borrado', 'se borraria', 'error') if k in cuenta))

    for nombre, clave, obligatorio, motivo in avisos:
        print()
        como = 'python sap.py exportar %s' % clave
        if obligatorio:
            print("  ERROR: el modelo %s no se copio: %s." % (nombre, motivo))
            print("         Corre antes %s (o python sap.py preparar)" % como)
        else:
            print("  OJO: %s no se copio (%s)." % (nombre, motivo))
            print("       Para tenerlo: %s" % como)
            print("       O todo de una vez: python sap.py preparar")
    print("  (este paso solo copia archivos: Unity no se abre)")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='sap.py sincronizar',
        description='Copia salidas/ a las StreamingAssets de Unity (proyecto y builds) y a ar/web/datos.')
    ap.add_argument('--seco', action='store_true',
                    help='decir que copiaria y que borraria, sin escribir nada')
    ap.add_argument('--destino', metavar='CARPETA',
                    help='copiar los siete archivos a esta carpeta y nada mas')
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.destino:
        carpeta = os.path.abspath(args.destino)
        registros = sincronizar(seco=args.seco, carpetas=[carpeta], para_ar=carpeta,
                                borrar_viejos=False)
    else:
        registros = sincronizar(seco=args.seco)
    return 1 if fallida(registros) else 0


if __name__ == '__main__':
    sys.exit(main())
