@echo off
chcp 65001 >nul
title Creador de presupuestos
cd /d "%~dp0"

rem --- Elegir Python: primero el entorno propio del programa (.venv), si no, el del computador
set "PY="
set "PIP_EXTRA="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo  No se encontró Python en este computador.
    echo  Para instalar todo lo necesario, ejecute el instalador install.ps1.
    echo.
    pause
    exit /b 1
)
if not "%PY%"==".venv\Scripts\python.exe" set "PIP_EXTRA=--user"

rem --- Si falta lo necesario para crear los PDF, instalarlo
%PY% -c "import reportlab" >nul 2>nul
if errorlevel 1 (
    echo  Preparando el programa. Esto puede tardar un minuto...
    %PY% -m pip install %PIP_EXTRA% --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  No se pudo preparar el programa. Revise que haya conexión a internet e intente de nuevo.
        echo.
        pause
        exit /b 1
    )
)

rem --- Abrir el programa en el navegador
%PY% "app\iniciar.py"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
exit /b 0
