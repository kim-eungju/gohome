@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ================================================
echo   gohome.exe 빌드
echo ================================================

set "PY=python"
where py >nul 2>nul && set "PY=py"

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 가상환경 생성...
    %PY% -m venv .venv || goto :error
)

echo [2/4] 패키지 설치...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto :error

echo [3/4] 테스트 실행...
".venv\Scripts\python.exe" -m pytest -q tests || goto :error

echo [4/4] EXE 빌드...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name gohome ^
    --icon "assets\gohome.ico" ^
    --add-data "ui\styles.qss;ui" ^
    --add-data "assets\gohome.ico;assets" ^
    --add-data "assets\fonts;assets\fonts" ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.QtMultimedia ^
    --exclude-module PySide6.QtPdf ^
    main.py || goto :error

rem .env 는 EXE 외부(같은 폴더)에서 관리
if exist ".env" (
    copy /y ".env" "dist\.env" >nul
) else (
    copy /y ".env.example" "dist\.env" >nul
    echo [안내] dist\.env 에 API KEY 를 입력하세요.
)
copy /y ".env.example" "dist\.env.example" >nul

echo.
echo 완료: dist\gohome.exe
pause
exit /b 0

:error
echo.
echo [오류] 빌드에 실패했습니다. 위 메시지를 확인하세요.
pause
exit /b 1
