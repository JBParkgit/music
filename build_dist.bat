@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [오류] venv\Scripts\python.exe 를 찾을 수 없습니다.
    echo 프로젝트 루트에서 가상환경(venv)을 먼저 만들어주세요.
    pause
    exit /b 1
)

venv\Scripts\python.exe build_dist.py
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% neq 0 (
    echo.
    echo [실패] 배포판 빌드 중 오류가 발생했습니다. ^(코드 %EXIT_CODE%^)
) else (
    echo.
    echo [완료] 배포판 빌드가 끝났습니다. dist\musicsheetviewer.zip 을 확인하세요.
)

pause
exit /b %EXIT_CODE%
