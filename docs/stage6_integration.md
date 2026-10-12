# Stage 6: ADempiere integration

> Since this was written the dashboard has also been embedded in an ADempiere window. The menu entry described here is now **InsightAI (browser)**, and a new **InsightAI** entry opens the window. See `docs/embedded_window.md`.

Run on 2026-10-12. A backup of the `EV` database was taken first (`data\backups\EV_before_stage6_*.dump`, not in git).

## What was added

**To the Application Dictionary** (`adempiere\dictionary_install.sql`), all under a new entity type `INSAI`:

| Record | Value |
|---|---|
| `AD_EntityType` | `INSAI` "InsightAI" |
| `AD_Process` | `InsightAI_Launch`, class `org.insightai.adempiere.InsightAILauncher`, access level Client+Organization, not a server process, runs on click |
| `AD_Menu` | "InsightAI", last entry under **Performance Analysis** (node 278) |
| `AD_Process_Access` | GardenWorld Admin and SalesRep(Restricted) only |

Translation rows are added for the one extra system language (es_MX). IDs come from ADempiere's own sequences and fall in the customer range (1,000,000 up). No existing dictionary record was changed; the Ask AI records are as they were.

**To `C:\Adempiere`**, three new files and no changes to existing ones:

| File | Purpose |
|---|---|
| `lib\insightai.jar` | The launcher process (one class, 139 lines, Java 8) |
| `RUN_Adempiere_InsightAI.bat` | Starts the desktop client with `insightai.jar` on the classpath, plus `teksalah_ai.jar` if present so Ask AI keeps working |
| `insightai-launcher.properties` | Service address and the shared launch key |

`insightai.jar` is a separate jar on the launcher classpath. It was not merged into `customization.jar`, so `RUN_setup` did not have to be re-run and `Adempiere.jar` is untouched.

**To the service:** `POST /auth/launch-token`, `GET /launch`, and the view `insightai.v_role_process`.

## How the hand-off works

1. The user clicks **InsightAI** in the ADempiere menu. ADempiere only shows it to roles with `AD_Process_Access`.
2. The launcher reads the user and role from the ADempiere login context, signs `user:role:time:nonce` with the shared key (HMAC-SHA256) and posts it to the service.
3. The service checks the signature, that the request is under a minute old, that the nonce has not been seen, that the user holds the role, and that the role has been granted the InsightAI process. Any failure returns a reason, which the launcher shows in ADempiere.
4. The service returns a URL carrying a random code that works once, for one minute. The launcher opens it in the default browser.
5. Opening the URL sets the session cookie and redirects to the dashboard. From there everything is as in Stage 3: client and organisations are read from ADempiere's access tables on every request.

The browser never sees the shared key and cannot choose a user, role, client or organisation.

**What the key protects.** Anyone who can read `insightai-launcher.properties` can ask for a session as any user and role. That matches the trust already placed in the machine (`AdempiereEnv.properties` beside it holds the database password in plain text), but it means the file should be readable only by people who may use ADempiere on that machine. The launch key is separate from the key that signs sessions.

## 2Pack

`adempiere\2pack\InsightAI.zip` was exported with ADempiere's own PackOut process (run headless by `scripts\packout.ps1`). It contains the entity type, the process, the menu entry and its position in the menu tree. `PackOut.xml` beside it is the same content, readable.

Limits of the 2Pack:

- **It does not carry process access.** This ADempiere version has no 2Pack handler for `AD_Process_Access` outside a role export. After a PackIn, grant roles with `scripts\adempiere_install.ps1 -Roles ...` or in the Role window.
- **It does not carry the jar or the properties file.** `adempiere_install.ps1` installs those.
- **PackIn was not tested.** Importing into the database it was exported from would only overwrite the same records, and there is no second ADempiere instance here. The supported install and removal path on this machine is `adempiere_install.ps1`, which was tested both ways.

## Installing and removing

```
powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1
powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1 -Roles 'GardenWorld Admin','GardenWorld User'
powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1 -Uninstall
```

`-Roles` sets the complete list: a role not named loses access. After installing, restart the InsightAI service and open ADempiere with `RUN_Adempiere_InsightAI.bat`.

## Tested

| Check | Result |
|---|---|
| Launcher run inside a headless ADempiere environment as GardenAdmin / GardenWorld Admin | Session opened; sees all 8 organisations |
| Same as test_salerep / SalesRep(Restricted) | Session opened; sees MEKAR only |
| Same as GardenUser / GardenWorld User (not granted) | ADempiere refused to start the process |
| test_salerep claiming the GardenWorld Admin role | Service refused: user does not hold that role |
| Launch link opened a second time | Refused (401) |
| Wrong key, request 10 minutes old, tampered role, repeated nonce | Each refused (401) |
| Ungranted role calling the service directly, bypassing ADempiere | Refused (403) |
| Uninstall, then reinstall | No InsightAI records or files left after uninstall; menu and process counts back to their original values; reinstall and all checks pass again |

The headless test (`scripts\test_launcher.ps1`) starts ADempiere's environment, sets the login context, creates a process instance and runs the real process class loaded by the name stored in the dictionary. That is the same path the desktop client takes, except for two things it cannot cover.

**Not tested, and needing a person at the desktop client:**

- That the **InsightAI** entry appears under Performance Analysis in the Swing menu for GardenWorld Admin and SalesRep(Restricted), and not for GardenWorld User.
- That clicking it opens the default browser. In the headless test the browser step was switched off and the link was followed by the test instead.

Also not tested: the ZK web client. (The launcher's message when the service is not running was added to `scripts\test_launcher.ps1` in Stage 7 and passes.)

## Things to know

- **Role Access Update can widen access.** GardenWorld's roles are automatic (`IsManual = N`). Running ADempiere's Role Access Update gives such roles every process their level allows, which would grant InsightAI to GardenWorld User as it did for Ask AI. The service follows whatever `AD_Process_Access` says. Re-run `adempiere_install.ps1 -Roles ...` afterwards to restrict it again, or make the roles manual.
- **The desktop client must be started with `RUN_Adempiere_InsightAI.bat`.** Started any other way, the menu entry is visible but the class is not on the classpath and ADempiere reports that the process class was not found.
- **ZK web client:** the entry would be visible there too, but the web client loads classes from `tomcat\lib\Adempiere.jar`, which does not contain the launcher, and a server-side process cannot open the user's browser. Supporting ZK means adding the jar to the web application and showing the link instead; that is not done.
- **`dev_login` is still on** in `config.toml`. Now that the menu entry exists, set it to `false` so the only way in is through ADempiere.
- **Each launch writes an `AD_PInstance` row**, as running any ADempiere process does. The uninstall removes those rows for this process.
