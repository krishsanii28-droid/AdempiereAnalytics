@echo off
rem Starts the ADempiere desktop client with the InsightAI launcher on the classpath.
rem Installed into ADEMPIERE_HOME by scripts\adempiere_install.ps1; insightai.jar goes into ADEMPIERE_HOME\lib.
rem teksalah_ai.jar (the separate Ask AI assistant) is included when present, so both menu entries work.
set "HOME_DIR=%~dp0"
if "%HOME_DIR:~-1%"=="\" set "HOME_DIR=%HOME_DIR:~0,-1%"
set "JAVA=java"
if not "%JAVA_HOME%"=="" set "JAVA=%JAVA_HOME%\bin\java"
set "CP=%HOME_DIR%\lib\insightai.jar"
if exist "%HOME_DIR%\lib\teksalah_ai.jar" set "CP=%HOME_DIR%\lib\teksalah_ai.jar;%CP%"
set "CP=%CP%;%HOME_DIR%\lib\Adempiere.jar;%HOME_DIR%\lib\AdempiereCLib.jar;%HOME_DIR%\lib\CompiereJasperReqs.jar"
cd /d "%HOME_DIR%"
"%JAVA%" -Xms32m -Xmx512m -DADEMPIERE_HOME="%HOME_DIR%" -classpath "%CP%" org.compiere.Adempiere %*
if errorlevel 1 pause
