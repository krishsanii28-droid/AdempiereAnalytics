@echo off
rem Starts the ADempiere desktop client with InsightAI.
rem Installed into ADEMPIERE_HOME by scripts\adempiere_install.ps1; insightai.jar goes into ADEMPIERE_HOME\lib.
rem
rem It runs org.insightai.adempiere.Start, which adds the InsightAI option to the Performance tab
rem and then starts ADempiere's own main class unchanged. No ADempiere file is modified.
rem teksalah_ai.jar (the separate Ask AI assistant) is included when present, so its menu entry keeps working.
set "HOME_DIR=%~dp0"
if "%HOME_DIR:~-1%"=="\" set "HOME_DIR=%HOME_DIR:~0,-1%"
set "JAVA=java"
if not "%JAVA_HOME%"=="" set "JAVA=%JAVA_HOME%\bin\java"
set "CP=%HOME_DIR%\lib\insightai.jar"
if exist "%HOME_DIR%\lib\teksalah_ai.jar" set "CP=%HOME_DIR%\lib\teksalah_ai.jar;%CP%"
set "CP=%CP%;%HOME_DIR%\lib\Adempiere.jar;%HOME_DIR%\lib\AdempiereCLib.jar;%HOME_DIR%\lib\CompiereJasperReqs.jar"
cd /d "%HOME_DIR%"
"%JAVA%" -Xms32m -Xmx512m -DADEMPIERE_HOME="%HOME_DIR%" -classpath "%CP%" org.insightai.adempiere.Start %*
if errorlevel 1 pause
