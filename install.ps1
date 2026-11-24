<#
.SYNOPSIS
    Instala o actualiza el "Creador de presupuestos".

.DESCRIPTION
    - Revisa e instala lo que falte: Git y Python (con winget o, si no existe, con los instaladores oficiales).
    - Descarga el programa desde GitHub (o lo actualiza si ya estaba instalado).
    - Crea su entorno de Python (.venv) e instala las dependencias.
    - Comprueba que todo funcione y deja en el Escritorio el archivo para abrirlo con doble clic.

    Los presupuestos se guardan FUERA de la carpeta del programa (por defecto en Documentos\Presupuestos),
    por lo que instalar o actualizar nunca los borra ni los modifica.

.EXAMPLE
    # Instalar (o actualizar) desde PowerShell, en una sola línea:
    irm https://raw.githubusercontent.com/Bastian444/creador-presupuestos/main/install.ps1 -OutFile "$env:TEMP\install.ps1"; powershell -ExecutionPolicy Bypass -File "$env:TEMP\install.ps1"
    # (No usar "irm ... | iex": el archivo lleva BOM para que PowerShell 5.1 lea bien los acentos.)

.EXAMPLE
    # Desde una copia local del archivo:
    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
[CmdletBinding()]
param(
    # Carpeta donde se instala el programa
    [string]$Carpeta = (Join-Path $env:LOCALAPPDATA 'Programs\CreadorPresupuestos'),
    # Carpeta donde se guardan los presupuestos (.json) y los PDF
    [string]$CarpetaDatos = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Presupuestos'),
    [string]$Repositorio = 'https://github.com/Bastian444/creador-presupuestos.git',
    [string]$Rama = 'main',
    # Usado por "Actualizar Creador de presupuestos.bat": actualiza la instalación donde está este archivo
    [switch]$Actualizar,
    # No abrir el programa al terminar
    [switch]$NoAbrir,
    # No crear el acceso en el Escritorio
    [switch]$SinAccesoEscritorio
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # las descargas son mucho más rápidas sin la barra de progreso
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

$CarpetaIndicada = $PSBoundParameters.ContainsKey('Carpeta')
$CarpetaDatosIndicada = $PSBoundParameters.ContainsKey('CarpetaDatos')
$NOMBRE = 'Creador de presupuestos'
$PYTHON_VERSION_INSTALAR = '3.12.10'      # usada solo si hay que descargar Python sin winget
$PUERTOS = 8765..8775

# ============================================================== mensajes

function Write-Paso([string]$Texto) {
    Write-Host ''
    Write-Host "==> $Texto" -ForegroundColor Cyan
}
function Write-Bien([string]$Texto) { Write-Host "    [OK] $Texto" -ForegroundColor Green }
function Write-Info([string]$Texto) { Write-Host "    $Texto" -ForegroundColor Gray }
function Write-Aviso([string]$Texto) { Write-Host "    [!] $Texto" -ForegroundColor Yellow }

# Error pensado para que lo entienda cualquier persona: qué pasó y qué hacer.
function Stop-Instalacion([string]$Mensaje, [string]$Solucion) {
    $ex = New-Object System.Exception $Mensaje
    $ex.Data['Solucion'] = $Solucion
    throw $ex
}

# ============================================================== utilidades

function Update-RutaSesion {
    # Después de instalar algo, vuelve a leer el PATH para poder usarlo sin cerrar PowerShell.
    $maquina = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $usuario = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($maquina, $usuario) | Where-Object { $_ }) -join ';'
}

function Invoke-Programa {
    # Ejecuta un programa externo y falla con un mensaje claro si termina con error.
    param([string]$Programa, [string[]]$Argumentos, [string]$QueHace, [string]$Solucion)
    $ErrorActionPreference = 'Continue'   # muchos programas escriben avisos normales en stderr
    & $Programa @Argumentos
    if ($LASTEXITCODE -ne 0) {
        Stop-Instalacion "No se pudo $QueHace (código de error $LASTEXITCODE)." $Solucion
    }
}

function Test-Internet {
    try {
        Invoke-WebRequest -Uri 'https://github.com' -Method Head -UseBasicParsing -TimeoutSec 20 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Install-ConWinget([string]$Id, [string]$Nombre, [string[]]$Extra = @()) {
    Write-Info "Instalando $Nombre con winget. Puede aparecer una ventana pidiendo permiso: acéptela."
    $argumentos = @('install', '--id', $Id, '--exact', '--source', 'winget', '--silent',
                    '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity') + $Extra
    & winget @argumentos
    # winget puede devolver códigos distintos de 0 aunque haya quedado instalado; se comprueba después.
    Update-RutaSesion
}

function Save-Archivo([string]$Url, [string]$Destino) {
    Write-Info "Descargando $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Destino -UseBasicParsing
}

function Write-TextoSinBom([string]$Ruta, [string]$Texto) {
    [IO.File]::WriteAllText($Ruta, $Texto, (New-Object System.Text.UTF8Encoding($false)))
}

# ============================================================== Git

function Find-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($ruta in @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
        if (Test-Path $ruta) { return $ruta }
    }
    return $null
}

function Install-Git {
    if (Test-Winget) {
        Install-ConWinget 'Git.Git' 'Git'
    } else {
        Write-Info 'winget no está disponible; se usará el instalador oficial de Git.'
        $api = Invoke-RestMethod -Uri 'https://api.github.com/repos/git-for-windows/git/releases/latest' -UseBasicParsing
        $patron = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { '^Git-.*-arm64\.exe$' } else { '^Git-.*-64-bit\.exe$' }
        $recurso = $api.assets | Where-Object { $_.name -match $patron } | Select-Object -First 1
        if (-not $recurso) { Stop-Instalacion 'No se encontró el instalador de Git.' 'Instale Git manualmente desde https://git-scm.com y vuelva a ejecutar este instalador.' }
        $instalador = Join-Path $env:TEMP $recurso.name
        Save-Archivo $recurso.browser_download_url $instalador
        Write-Info 'Instalando Git. Puede aparecer una ventana pidiendo permiso: acéptela.'
        $p = Start-Process -FilePath $instalador -ArgumentList '/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/SUPPRESSMSGBOXES' -Wait -PassThru
        Remove-Item $instalador -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0) { Stop-Instalacion "El instalador de Git terminó con error ($($p.ExitCode))." 'Si apareció una ventana pidiendo permiso, debe aceptarla. Vuelva a ejecutar el instalador.' }
        Update-RutaSesion
    }
}

# ============================================================== Python

function Get-PythonValido([string]$Programa, [string[]]$Prefijo = @()) {
    # Devuelve la ruta real de python.exe si es versión 3.10 o superior; si no, $null.
    $ErrorActionPreference = 'Continue'
    try {
        $codigo = 'import sys, venv; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 10) else 1)'
        $salida = & $Programa @Prefijo '-c' $codigo 2>$null
        if ($LASTEXITCODE -eq 0 -and $salida) {
            $ruta = ($salida | Select-Object -Last 1).Trim()
            if (Test-Path $ruta) { return $ruta }
        }
    } catch { }
    return $null
}

function Find-Python {
    $candidatos = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidatos += @{ Exe = 'py'; Args = @('-3') } }
    foreach ($cmd in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        # El "python" de la carpeta WindowsApps es un acceso a la Microsoft Store, no un Python real.
        if ($cmd.Source -notlike '*\WindowsApps\*') { $candidatos += @{ Exe = $cmd.Source; Args = @() } }
    }
    $patrones = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                  "$env:ProgramFiles\Python3*\python.exe", "C:\Python3*\python.exe")
    foreach ($exe in (Get-ChildItem -Path $patrones -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
        $candidatos += @{ Exe = $exe.FullName; Args = @() }
    }
    foreach ($c in $candidatos) {
        $ruta = Get-PythonValido $c.Exe $c.Args
        if ($ruta) { return $ruta }
    }
    return $null
}

function Install-Python {
    if (Test-Winget) {
        Install-ConWinget 'Python.Python.3.12' 'Python' @('--scope', 'user')
    } else {
        Write-Info 'winget no está disponible; se usará el instalador oficial de Python.'
        $arq = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
        $nombre = "python-$PYTHON_VERSION_INSTALAR-$arq.exe"
        $instalador = Join-Path $env:TEMP $nombre
        Save-Archivo "https://www.python.org/ftp/python/$PYTHON_VERSION_INSTALAR/$nombre" $instalador
        Write-Info 'Instalando Python (solo para este usuario)...'
        $p = Start-Process -FilePath $instalador -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1',
            'Include_launcher=1', 'Include_test=0', 'Include_pip=1' -Wait -PassThru
        Remove-Item $instalador -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0) { Stop-Instalacion "El instalador de Python terminó con error ($($p.ExitCode))." 'Instale Python manualmente desde https://www.python.org/downloads/ y vuelva a ejecutar este instalador.' }
        Update-RutaSesion
    }
}

# ============================================================== programa

function Stop-ServidorEnMarcha {
    # Si el programa está abierto, se cierra para poder actualizar sus archivos sin problemas.
    foreach ($puerto in $PUERTOS) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$puerto/api/ping" -TimeoutSec 1 -UseBasicParsing
            if ($r.app -eq 'creador-presupuestos') {
                Invoke-RestMethod -Uri "http://127.0.0.1:$puerto/api/apagar" -Method Post -Body '{}' `
                    -ContentType 'application/json' -TimeoutSec 3 -UseBasicParsing | Out-Null
                Start-Sleep -Seconds 1
                Write-Info 'Se cerró el programa que estaba abierto para poder actualizarlo.'
            }
        } catch { }
    }
}

function Get-CarpetaPrograma {
    # Con -Actualizar (o si este archivo está dentro de una instalación) se usa esa carpeta.
    if (-not $CarpetaIndicada -and $PSScriptRoot) {
        if ((Test-Path (Join-Path $PSScriptRoot 'app\servidor.py')) -and (Test-Path (Join-Path $PSScriptRoot '.git'))) {
            return $PSScriptRoot
        }
    }
    return $Carpeta
}

function Sync-Repositorio([string]$Git, [string]$Destino) {
    $env:GIT_TERMINAL_PROMPT = '0'   # nunca quedarse esperando una contraseña
    $sinConexion = 'Revise que el computador tenga internet y que la dirección del repositorio sea correcta.'
    if (Test-Path (Join-Path $Destino '.git')) {
        Write-Info "Actualizando el programa en $Destino"
        Invoke-Programa $Git @('-C', $Destino, 'fetch', '--quiet', 'origin', $Rama) 'descargar la nueva versión desde GitHub' $sinConexion
        $antes = (& $Git -C $Destino rev-parse --short HEAD).Trim()
        # Solo reemplaza archivos del programa. Los archivos ignorados (.venv, config.local.json,
        # presupuestos y PDF) no se tocan: no se usa "git clean".
        Invoke-Programa $Git @('-C', $Destino, 'reset', '--quiet', '--hard', "origin/$Rama") 'aplicar la nueva versión' 'Cierre el programa si está abierto y vuelva a intentar.'
        $despues = (& $Git -C $Destino rev-parse --short HEAD).Trim()
        if ($antes -eq $despues) { Write-Bien "Ya tenía la última versión ($despues)." }
        else { Write-Bien "Programa actualizado ($antes -> $despues)." }
        return
    }
    if ((Test-Path $Destino) -and (Get-ChildItem -Force $Destino | Select-Object -First 1)) {
        $respaldo = "$Destino.anterior-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Write-Aviso "La carpeta $Destino ya tenía archivos; se movieron a $respaldo"
        Move-Item -LiteralPath $Destino -Destination $respaldo
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Destino -Parent) | Out-Null
    Write-Info "Descargando el programa en $Destino"
    Invoke-Programa $Git @('clone', '--quiet', '--branch', $Rama, $Repositorio, $Destino) 'descargar el programa desde GitHub' $sinConexion
    Write-Bien 'Programa descargado.'
}

function Set-CarpetaDatos([string]$Destino, [string]$Datos) {
    $config = Join-Path $Destino 'config.local.json'
    if ((Test-Path $config) -and -not $CarpetaDatosIndicada) {
        try {
            $actual = (Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json).carpeta_datos
            if ($actual) { $Datos = $actual }
        } catch { }
    }
    New-Item -ItemType Directory -Force -Path $Datos | Out-Null
    foreach ($sub in 'Presupuestos guardados', 'Presupuestos en PDF') {
        New-Item -ItemType Directory -Force -Path (Join-Path $Datos $sub) | Out-Null
        # Si había presupuestos dentro de la carpeta del programa (versión antigua), se mueven sin pisar nada.
        $viejo = Join-Path $Destino $sub
        if (Test-Path $viejo) {
            Get-ChildItem -LiteralPath $viejo -Recurse -File | ForEach-Object {
                $relativo = $_.FullName.Substring($viejo.Length).TrimStart('\')
                $nuevo = Join-Path (Join-Path $Datos $sub) $relativo
                if (-not (Test-Path -LiteralPath $nuevo)) {
                    New-Item -ItemType Directory -Force -Path (Split-Path $nuevo -Parent) | Out-Null
                    Move-Item -LiteralPath $_.FullName -Destination $nuevo
                }
            }
        }
    }
    Write-TextoSinBom $config (@{ carpeta_datos = $Datos } | ConvertTo-Json)
    return $Datos
}

function Initialize-Entorno([string]$Python, [string]$Destino) {
    $venv = Join-Path $Destino '.venv'
    $pyVenv = Join-Path $venv 'Scripts\python.exe'
    if (Test-Path $pyVenv) {
        $ErrorActionPreference = 'Continue'
        & $pyVenv -c 'import sys' 2>$null
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) {
            Write-Aviso 'El entorno anterior estaba dañado; se creará de nuevo.'
            Remove-Item -LiteralPath $venv -Recurse -Force
        }
    }
    if (-not (Test-Path $pyVenv)) {
        Write-Info 'Creando el entorno de Python del programa...'
        Invoke-Programa $Python @('-m', 'venv', $venv) 'crear el entorno de Python' 'Vuelva a ejecutar el instalador. Si el problema sigue, reinstale Python.'
    }
    Write-Info 'Instalando las librerías necesarias (puede tardar un minuto)...'
    Invoke-Programa $pyVenv @('-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', '-r', (Join-Path $Destino 'requirements.txt')) `
        'instalar las librerías necesarias' 'Revise la conexión a internet y vuelva a ejecutar el instalador.'
    Write-Bien 'Entorno listo.'
    return $pyVenv
}

function New-AccesoEscritorio([string]$Destino) {
    $escritorio = [Environment]::GetFolderPath('Desktop')
    $bat = Join-Path $escritorio "$NOMBRE.bat"
    $iniciar = Join-Path $Destino 'Iniciar Creador de presupuestos.bat'
    $contenido = "@echo off`r`nchcp 65001 >nul`r`nrem Abre el $NOMBRE (instalado en $Destino)`r`ncall `"$iniciar`"`r`n"
    Write-TextoSinBom $bat $contenido
    return $bat
}

# ============================================================== instalación

function Install-CreadorPresupuestos {
    Write-Host ''
    Write-Host '  ==================================================' -ForegroundColor DarkCyan
    if ($Actualizar) { Write-Host "    Actualizando: $NOMBRE" -ForegroundColor White }
    else { Write-Host "    Instalando: $NOMBRE" -ForegroundColor White }
    Write-Host '  ==================================================' -ForegroundColor DarkCyan
    Write-Host '  No cierre esta ventana hasta que termine.' -ForegroundColor Gray

    $destino = Get-CarpetaPrograma

    Write-Paso '1/7  Revisando la conexión a internet'
    if (-not (Test-Internet)) {
        Stop-Instalacion 'No hay conexión a internet (o no se puede llegar a github.com).' 'Conecte el computador a internet y vuelva a ejecutar el instalador.'
    }
    Write-Bien 'Hay conexión.'

    Write-Paso '2/7  Revisando Git (sirve para descargar y actualizar el programa)'
    $git = Find-Git
    if ($git) { Write-Bien "Git ya está instalado." }
    else {
        Write-Info 'Git no está instalado.'
        Install-Git
        $git = Find-Git
        if (-not $git) { Stop-Instalacion 'Git no quedó instalado.' 'Cierre esta ventana, abra PowerShell de nuevo y vuelva a ejecutar el instalador. Si sigue fallando, instale Git desde https://git-scm.com' }
        Write-Bien 'Git instalado.'
    }

    Write-Paso '3/7  Revisando Python (el programa está hecho en Python)'
    $python = Find-Python
    if ($python) { Write-Bien "Python ya está instalado ($python)." }
    else {
        Write-Info 'No hay un Python 3.10 o más nuevo.'
        Install-Python
        $python = Find-Python
        if (-not $python) { Stop-Instalacion 'Python no quedó instalado.' 'Cierre esta ventana, abra PowerShell de nuevo y vuelva a ejecutar el instalador. Si sigue fallando, instale Python desde https://www.python.org/downloads/' }
        Write-Bien "Python instalado ($python)."
    }

    Write-Paso '4/7  Descargando el programa desde GitHub'
    Stop-ServidorEnMarcha
    Sync-Repositorio $git $destino

    Write-Paso '5/7  Preparando la carpeta de los presupuestos'
    $datos = Set-CarpetaDatos $destino $CarpetaDatos
    Write-Bien "Los presupuestos se guardan en: $datos"

    Write-Paso '6/7  Preparando el entorno y las librerías'
    $pyVenv = Initialize-Entorno $python $destino

    Write-Paso '7/7  Comprobando que todo funcione'
    Push-Location (Join-Path $destino 'app')
    $ErrorActionPreference = 'Continue'
    try { $resultado = & $pyVenv 'verificar.py' 2>&1 | Out-String; $codigo = $LASTEXITCODE }
    finally { $ErrorActionPreference = 'Stop'; Pop-Location }
    if ($codigo -ne 0 -or $resultado -notmatch 'OK\|') {
        Write-Host $resultado
        Stop-Instalacion 'La prueba final del programa falló.' 'Vuelva a ejecutar el instalador. Si el problema sigue, envíe a quien le ayuda una foto de esta ventana.'
    }
    Write-Bien 'El programa funciona correctamente (se creó un PDF de prueba).'

    if (-not $SinAccesoEscritorio) {
        $bat = New-AccesoEscritorio $destino
        Write-Bien "Acceso creado en el Escritorio: $(Split-Path $bat -Leaf)"
    }

    Write-Host ''
    Write-Host '  ==================================================' -ForegroundColor Green
    if ($Actualizar) { Write-Host '    Listo. El programa quedó actualizado.' -ForegroundColor Green }
    else { Write-Host '    Listo. El programa quedó instalado.' -ForegroundColor Green }
    Write-Host '  ==================================================' -ForegroundColor Green
    Write-Host ''
    if ($SinAccesoEscritorio) { Write-Host "  Para abrirlo: doble clic en $(Join-Path $destino 'Iniciar Creador de presupuestos.bat')" }
    else { Write-Host "  Para abrirlo: doble clic en '$NOMBRE' en el Escritorio." }
    Write-Host "  Sus presupuestos y PDF están en: $datos"
    Write-Host "  Para actualizarlo más adelante: doble clic en"
    Write-Host "     $(Join-Path $destino 'Actualizar Creador de presupuestos.bat')"
    Write-Host ''

    if (-not $NoAbrir) {
        Start-Process -FilePath (Join-Path $destino 'Iniciar Creador de presupuestos.bat') -WindowStyle Minimized
    }
}

# ============================================================== inicio
$fallo = $false
try {
    Install-CreadorPresupuestos
} catch {
    $fallo = $true
    $solucion = $_.Exception.Data['Solucion']
    if (-not $solucion) {
        $solucion = 'Vuelva a ejecutar el instalador. Si se repite, envíe una foto de esta ventana a quien le ayuda.'
    }
    Write-Host ''
    Write-Host '  ==================================================' -ForegroundColor Red
    Write-Host '    No se pudo terminar la instalación' -ForegroundColor Red
    Write-Host '  ==================================================' -ForegroundColor Red
    Write-Host "  Qué pasó:   $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  Qué hacer:  $solucion" -ForegroundColor Yellow
    Write-Host '  Sus presupuestos guardados no se modificaron.' -ForegroundColor Gray
}

# "exit" solo se usa al ejecutarlo como archivo (con -File); así nunca se cierra una ventana interactiva.
if ($PSCommandPath -and $fallo) { exit 1 }
