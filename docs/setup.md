# Setup, daily use, troubleshooting and removal (Windows)

All commands are run from the project folder (`C:\InsightAI`) in PowerShell or Command Prompt.

## What you need

| Requirement | Used for | Checked with |
|---|---|---|
| ADempiere 3.9.3 on PostgreSQL, with `AdempiereEnv.properties` in the ADempiere folder | Everything | `C:\Adempiere\AdempiereEnv.properties` exists |
| PostgreSQL client tools (`psql`) | Installing and checking the database objects | `"C:\Program Files\PostgreSQL\14\bin\psql.exe" --version` |
| Python 3.12 through the `py` launcher | The analytics service | `py -3.12 --version` |
| A JDK 8 with `JAVA_HOME` set | Compiling the ADempiere launcher | `"%JAVA_HOME%\bin\javac" -version` |
| Internet access, once | Python packages and the two models | |
| About 2.5 GB of disk | Python environment about 1.3 GB, models about 270 MB, plus pip cache | |

Other Python installations on the machine, including 3.6.5, are not touched. Everything Python-related goes into `.venv` inside the project.

If your ADempiere folder or `psql` is somewhere else, the scripts take `-AdempiereHome` and `-Psql` parameters.

## Install

Run these in order. Each is safe to run again.

| Step | Command | What it does |
|---|---|---|
| 1 | `powershell -ExecutionPolicy Bypass -File scripts\db_install.ps1` | Creates the `insightai` schema, views and the two database roles; writes the service's database login to `.env` |
| 2 | `powershell -ExecutionPolicy Bypass -File scripts\setup_service.ps1 -ML` | Creates `.venv`, installs the packages including PyTorch, Chronos and sentence-transformers; adds the session signing key to `.env` |
| 3 | `.venv\Scripts\python.exe -m insightai.forecast` | Downloads the forecasting model on first use and builds the forecast files |
| 4 | `powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1` | Compiles the InsightAI classes, adds three files to the ADempiere folder, adds the InsightAI form and launcher records and grants them to the roles in `-Roles`. It adds no menu entry |
| 5 | `powershell -ExecutionPolicy Bypass -File scripts\run_service.ps1` | Starts the service. Leave this window open |
| 6 | Start ADempiere with `C:\Adempiere\RUN_Adempiere_InsightAI.bat` | The desktop client with the launcher on its classpath |

Without `-ML` in step 2 the service still works: forecasts use a statistical baseline and the assistant matches by keywords, and both say so on the page. Step 3 can then be skipped or run as is.

By default step 4 grants access to `GardenWorld Admin` and `SalesRep(Restricted)`. To choose roles:

```
powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1 -Roles 'GardenWorld Admin','GardenWorld User'
```

The list is complete: a role you leave out loses access.

## Daily use

1. Start the service: `scripts\run_service.ps1`. The first question to the assistant is fast only after the model has loaded, a few seconds after start-up.
2. Start ADempiere with `RUN_Adempiere_InsightAI.bat` and log in.
3. When ADempiere opens, the **Performance** tab is showing, with an **Open InsightAI dashboard** button at the top. Press it: the dashboard opens in an ADempiere window, signed in as your ADempiere user and role. The window has an **Open in browser** button if you prefer your web browser.
4. Use **Run forecast** on the page, or step 3 above, after stock or shipments change. The forecast is a snapshot of the moment it was run.

Settings are in `config.toml`: port, default period, forecast horizon and thresholds, model names, assistant threshold. Restart the service after changing it.

**Before letting other people use it,** set `dev_login = false` in `config.toml`. While it is `true`, anyone on this machine can open `http://127.0.0.1:8765/dev/login` and pick any user and role without going through ADempiere.

## Checking that it works

```
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
```

This runs the Python tests, the read-only role check, the comparison with ADempiere's own figures, the launcher hand-off for four logins, the embedded window for three (opened off-screen), and the real desktop client: it starts ADempiere, logs in with the saved login, presses the button on the Performance tab and closes again after about half a minute. It needs the service running for the last part (`-SkipLauncher` leaves that part out). Every line of the summary should say PASS.

## Troubleshooting

| What you see | Cause | What to do |
|---|---|---|
| ADempiere: "The InsightAI service is not running at http://127.0.0.1:8765" | The service is not started, or is on another port | Run `scripts\run_service.ps1`. If you changed the port in `config.toml`, run `scripts\adempiere_install.ps1` again so the launcher gets the new address |
| There is no **Open InsightAI dashboard** button on the Performance tab | ADempiere was not started with `RUN_Adempiere_InsightAI.bat`, or the role has not been granted InsightAI, or the client was open during install | Close ADempiere and start it with that file. If the button is still missing, run `adempiere_install.ps1 -Roles ...` with that role and log in again |
| The stock start script still shows ADempiere without any InsightAI button | Expected: only `RUN_Adempiere_InsightAI.bat` adds it | Use that file to start ADempiere |
| The InsightAI window says "This Java runtime has no JavaFX web view" | ADempiere is running on a Java without JavaFX (most OpenJDK 8 builds) | Use **Open in browser** in that window or the **InsightAI (browser)** menu entry, or run ADempiere on Oracle JDK 8 |
| The InsightAI window stays on "Opening InsightAI..." or shows a service message | The service is not running or was restarted | Start the service, then press **Reload** in the window |
| Date boxes in the InsightAI window have no calendar | The embedded web view shows date fields as text | Type dates as `2026-01-31`, or use the Period list |
| ADempiere: "InsightAI is not set up: ...insightai-launcher.properties was not found" | Step 4 was not run, or ADempiere was moved | Run `scripts\adempiere_install.ps1` |
| ADempiere: "The launch request was not signed with this installation's key" | The key in the ADempiere folder and the one in `.env` differ, or the service was not restarted after install | Run `adempiere_install.ps1`, then restart the service |
| The InsightAI window says "This role has not been granted access to InsightAI" | Access was removed from the role while ADempiere was open | Log out of ADempiere and back in; grant the role with `adempiere_install.ps1 -Roles ...` if it should have access |
| ADempiere: "The launch request has expired" | The clocks of the two programs differ by more than a minute | Only possible if the service runs on another machine; synchronise the clocks |
| Browser: "This link has expired" | The link was opened twice, or more than a minute after it was made | Click **InsightAI** in ADempiere again |
| Browser: "Not signed in" or the page asks you to open InsightAI from ADempiere | The session ended (8 hours) or the service was reinstalled | Click **InsightAI** in ADempiere again |
| Service will not start: "Missing INSIGHTAI_DB_PASSWORD, INSIGHTAI_SECRET_KEY in .env" | Steps 1 or 2 were skipped | Run `db_install.ps1`, then `setup_service.ps1` |
| Service will not start: the port is in use | Another copy is running | Close the other window, or change `port` in `config.toml` and re-run `adempiere_install.ps1` |
| Page: "The ADempiere database is not reachable" | PostgreSQL is stopped, or the `insightai_ro` password in `.env` no longer matches | Start the `postgresql-x64-14` service. If the password is wrong, run `db_install.ps1` again |
| Page: every card shows "Could not load" after an ADempiere upgrade or restore | The `insightai` schema or its grants are gone | Run `db_install.ps1` and `adempiere_install.ps1` again |
| Receivables suddenly show zero | ADempiere's `invoiceOpen()` hides permission errors and returns nothing | Run `db_install.ps1` again to restore the grants, then `scripts\db_crosscheck.ps1` |
| Forecast panel: "No forecast has been run yet" | Step 3 was not run | Click **Run forecast** or run step 3 |
| Forecast panel: "Model unavailable, baseline used instead" | The forecasting packages are missing, or the model is not downloaded and there is no internet | Run `setup_service.ps1 -ML` and step 3 while online. Afterwards it works offline |
| Forecast panel, real data: every row "Not forecast" | The product has too little shipment history (26 weeks with demand in at least 8 are needed) | Expected on GardenWorld. Use the synthetic demo view to see the feature |
| Assistant: answers end with "Matched by keywords" | The embedding model could not load | As for the forecasting model above |
| Assistant declines a reasonable question | It is not one of the approved question types, or the wording is far from the examples | Use one of the suggested questions. To add a question type, add an intent in `insightai\assistant\intents.py` |
| `pip` fails in step 2 | No internet, or a proxy | Set the proxy for pip, or copy a prepared `.venv` and `models` folder from another machine |
| `javac not found` in step 4 | `JAVA_HOME` points at a JRE or is not set | Set `JAVA_HOME` to a JDK 8 folder |
| A GardenWorld role gained access to InsightAI unexpectedly | ADempiere's Role Access Update re-granted all processes to automatic roles | Run `adempiere_install.ps1 -Roles ...` again |

The service log is the window `run_service.ps1` runs in. It never contains passwords, keys or query results.

## Removing InsightAI

Do these in order.

| Step | Command | What it removes |
|---|---|---|
| 1 | Close the ADempiere client and stop the service (Ctrl+C in its window) | |
| 2 | `powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1 -Uninstall` | The form, process, entity type, role access and run history for the process; the three files in the ADempiere folder |
| 3 | `powershell -ExecutionPolicy Bypass -File scripts\db_install.ps1 -Uninstall` | The `insightai` schema, both database roles and their grants; restores the two PostgreSQL defaults that install tightened |
| 4 | Delete the project folder | The service, `.venv`, models, forecast files, `.env` |

After step 3 nothing of InsightAI remains in the database or the ADempiere folder. Both uninstalls were run and checked on this installation: record counts returned to their earlier values and no files were left.

Three things are deliberately not reversed:

- ADempiere's ID counters are not wound back, so the next custom record gets a higher number than it otherwise would. Reusing IDs would be unsafe.
- The database backup taken before Stage 6 (`data\backups`) is yours to keep or delete.
- ADempiere itself, the Ask AI customization and `erp_ai_reader` are not part of InsightAI and are left alone.

## Moving to another machine

Copy the project folder without `.venv`, `data`, `models`, `build` and `.env`, then run the install steps. To avoid downloads, copy `models` as well. `adempiere\2pack\InsightAI.zip` can be imported with ADempiere's PackIn instead of letting step 4 create the dictionary records, but step 4 is still needed for the jar, the properties file and role access, and importing the 2Pack has not been tested.
