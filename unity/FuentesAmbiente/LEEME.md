# Fuentes de la vista realista que no van a la build

`cielo_2k.hdr` es el HDRI tal como se bajo de Poly Haven (CC0, ver `FUENTE.txt`).
Unity usa `Assets/Resources/Ambiente/Texturas/cielo/cielo_2k_suelo.hdr`, el mismo con el
hemisferio de abajo cambiado por pasto lejano, que arma `python comun/recursos_realistas.py`.
Esta carpeta queda fuera de `Assets` para que el original no entre a la build.
