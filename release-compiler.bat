@echo off
chcp 65001 >nul
echo =========================================
echo   Shuen Auto - Release Builder
echo =========================================
echo.

:: Запрос имени папки у пользователя
set /p FOLDER_NAME=Enter release folder name (e.g. v1.0):

:: Проверка, что пользователь не ввел пустую строку
if "%FOLDER_NAME%"=="" (
    echo.
    echo [ERROR] Name folder is empty!
    pause
    exit /b
)

echo.
echo Building the app: releases\%FOLDER_NAME%
echo Please, wait...
echo.

:: Запуск PyInstaller
pyinstaller --noconfirm --onedir --console --name "Shuen Auto" --icon=static/logo.ico --add-data "templates;templates" --add-data "static;static" --add-data "locales;locales" --distpath "releases\%FOLDER_NAME%" app.py

echo.
echo =========================================
echo   Build has been finished!
echo   Compiled app can be found in: releases\%FOLDER_NAME%\Shuen Auto\
echo =========================================
pause