# ================================================================
#  setup.ps1  -  DEJAR SAP3000 LISTO PARA CORRER
# ================================================================
#  Crea el entorno virtual (.venv) e instala lo que pide
#  requirements.txt. Se corre UNA vez:
#
#      .\setup.ps1
#
#  Si PowerShell bloquea el script ("la ejecucion de scripts esta
#  deshabilitada"), correr antes, en esa misma terminal:
#
#      Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
#  Este archivo es ademas la MARCA DE LA RAIZ: el Python del
#  programa encuentra la carpeta del proyecto subiendo hasta el.
#  No moverlo ni renombrarlo.
# ================================================================

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot
$venv = Join-Path $raiz '.venv'
$py = Join-Path $venv 'Scripts\python.exe'

Write-Host ''
Write-Host '=== SAP3000 - Laboratorio estructural, Grupo 7 ===' -ForegroundColor Cyan
Write-Host ''

# --- 1. Python del sistema ---
$sistema = Get-Command python -ErrorAction SilentlyContinue
if (-not $sistema) {
    Write-Host 'No encuentro Python. Instalalo desde python.org (3.12)' -ForegroundColor Red
    Write-Host 'y marca "Add python.exe to PATH" durante la instalacion.'
    exit 1
}
Write-Host ("Python del sistema : " + (& python --version 2>&1))

# --- 2. Entorno virtual ---
if (Test-Path $py) {
    Write-Host 'Entorno virtual    : ya existe (.venv)'
} else {
    Write-Host 'Entorno virtual    : creando .venv ...'
    & python -m venv $venv
}

# --- 3. Dependencias ---
Write-Host 'Dependencias       : instalando (puede tardar unos minutos) ...'
& $py -m pip install --upgrade --quiet pip
& $py -m pip install --quiet -r (Join-Path $raiz 'requirements.txt')

# --- 4. Verificacion ---
Write-Host ''
Write-Host 'Verificando...' -ForegroundColor Cyan
& $py -c @"
import openseespy.opensees as ops, numpy, flask, openpyxl, matplotlib, PIL
print('  openseespy', ops.version())
print('  numpy     ', numpy.__version__)
print('  flask     ', flask.__version__)
print('  openpyxl  ', openpyxl.__version__)
print('  matplotlib', matplotlib.__version__)
print('  pillow    ', PIL.__version__)
"@

# --- 5. Unity (no se instala con pip) ---
Write-Host ''
$version = (Select-String -Path (Join-Path $raiz 'unity\ProjectSettings\ProjectVersion.txt') `
                          -Pattern 'm_EditorVersion:').Line.Split(':')[1].Trim()
$unity = "C:\Program Files\Unity\Hub\Editor\$version\Editor\Unity.exe"
if (Test-Path $unity) {
    Write-Host "Unity $version   : instalada" -ForegroundColor Green
} else {
    Write-Host "Unity $version   : NO instalada" -ForegroundColor Yellow
    Write-Host '  El calculo y las verificaciones corren igual; solo el visor 3D'
    Write-Host '  necesita Unity. Instalala desde Unity Hub con ESA version exacta:'
    Write-Host '  abrir el proyecto con otra version hace que Unity migre los assets.'
}

Write-Host ''
Write-Host 'Listo. Para empezar:' -ForegroundColor Green
Write-Host '  .\.venv\Scripts\python.exe sap.py               lista de comandos'
Write-Host '  .\.venv\Scripts\python.exe sap.py preparar      calcula y exporta todo'
Write-Host '  .\.venv\Scripts\python.exe sap.py abrir         abre el visor'
Write-Host '  .\.venv\Scripts\python.exe sap.py verificar     la suite entera'
Write-Host ''
