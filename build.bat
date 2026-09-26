@echo off
:: ============================================================
::  build.bat – Compila LectorOMR como un .exe portable
::  Ejecuta este archivo desde la raíz del proyecto
:: ============================================================
setlocal

echo ============================================================
echo   LectorOMR – Creando ejecutable portable
echo ============================================================

:: Verificar que Python esté disponible
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python. Descargalo de https://python.org
    pause
    exit /b 1
)

:: Instalar dependencias si no están
echo [1/4] Verificando dependencias...
py -3 -m pip install -r requirements.txt --quiet
py -3 -m pip install pyinstaller --quiet

:: Limpiar compilaciones anteriores
echo [2/4] Limpiando build anterior...
if exist "build" rmdir /s /q build
if exist "dist\LectorOMR.exe" del /q "dist\LectorOMR.exe"

:: Compilar
echo [3/4] Compilando (esto puede tardar 2-5 minutos)...
py -3 -m PyInstaller LectorOMR.spec

echo.
if exist "dist\LectorOMR.exe" (
    echo ============================================================
    echo   [OK] Ejecutable creado exitosamente:
    echo        dist\LectorOMR.exe
    echo.
    echo   Comparte ese archivo .exe con cualquier persona.
    echo   No necesita tener Python instalado.
    echo ============================================================
) else (
    echo ============================================================
    echo   [ERROR] La compilacion fallo. Revisa los mensajes arriba.
    echo ============================================================
    exit /b 1
)

pause
