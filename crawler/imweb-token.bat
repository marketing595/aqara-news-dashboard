@echo off
chcp 65001 >nul
rem Client ID/Secret 은 crawler\imweb-config.txt 에서 읽는다.
rem 인자로 넘길 수도 있다:  imweb-token.bat -ClientId "아이디" -ClientSecret "시크릿"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Get-ImwebToken.ps1" %*
