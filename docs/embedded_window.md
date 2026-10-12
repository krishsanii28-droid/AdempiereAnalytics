# InsightAI inside ADempiere

Added on 2026-10-12, after Stage 7. The dashboard opens as a window of the ADempiere desktop client, from a button on the **Performance** tab of ADempiere's main window. There is no menu entry.

## What you see

When ADempiere opens, its main window shows the Performance tab. At the top of that tab, above ADempiere's own goal gauges, is one button:

**Open InsightAI dashboard**

Pressing it opens a maximized ADempiere window containing the dashboard, signed in as your ADempiere user and role. Pressing it again while that window is open brings the window to the front. The window is listed in ADempiere's Window menu like any other, and has two buttons of its own: **Reload**, which signs in again and reloads the page (use it after the 8-hour session ends), and **Open in browser**, which opens the same dashboard in your default web browser.

The button is shown only to roles that have been granted InsightAI. Other roles see the Performance tab exactly as before.

## How it works

- **The option on the Performance tab.** ADempiere has no extension point for that tab: its own dashboard content can link only to standard windows, not to a form. So `RUN_Adempiere_InsightAI.bat` starts a small class, `org.insightai.adempiere.Start`, which arranges for the button to be added and then runs ADempiere's own main class unchanged. Once the main window appears after login, the tab's existing panel is placed, untouched, underneath a strip holding the button. No ADempiere class or file is modified, and if anything in this step fails the Performance tab is simply left as it was.
- **The window.** An ADempiere form: an `AD_Form` record whose class, `org.insightai.adempiere.InsightAIForm`, ADempiere creates when the button is pressed.
- **The page.** The form shows the dashboard with JavaFX WebView, the browser engine that ships with Oracle JDK 8. On this machine that is JavaFX 8.0.501 with WebKit 623.1, which runs the dashboard without changes: no script errors, all cards and charts drawn.
- **Sign-in.** The same hand-off as Stage 6: the form signs the logged-in user and role with the shared key, gets a link that works once for one minute, and loads it in the web view. Nothing about the user is typed in or chosen in the page.
- **The service.** The dashboard itself is unchanged and still served by the InsightAI service, so the service must be running. Model inference stays in the service, not in the ADempiere client.

## Access

- The form is granted to roles with `AD_Form_Access`, set by `adempiere_install.ps1 -Roles`. The button is added only when ADempiere's own role object reports access to the form.
- ADempiere does not itself stop a form class from being opened by other means, so the service checks too: it signs a role in only if the role holds the InsightAI form (or the browser launcher process) in ADempiere. A role without either sees "This role has not been granted access to InsightAI in ADempiere" and no data.

## Earlier placements

The option was first a menu entry inside the Performance Analysis folder, then a top-level menu entry after that folder. Both are gone. Re-running `adempiere_install.ps1` removes menu entries left by those versions and restores the menu to its original order; this was checked against the order recorded before any change.

## Tested

| Test | What it does | Result |
|---|---|---|
| `scripts\test_client.ps1` | Starts the real desktop client the way the start script does, logs in with the saved login, and checks the main window. Then presses the button and reads the dashboard window | Tabs are Performance, Menu, Workflow Activities, Workflow; Performance is selected at start; the button is on it and visible. After the press the dashboard is loaded, signed in as GardenAdmin / GardenWorld Admin, 8 organisations, 8 KPI cards, 8 charts |
| `scripts\test_form.ps1` | Opens the window off-screen through ADempiere's `FormFrame.openForm` for three logins | Admin: all 8 organisations. `test_salerep`: MEKAR only. GardenWorld User: ADempiere reports no access to the form, and when the window is forced open it shows the refusal and no data |

`test_client.ps1` shows an ADempiere main window and the InsightAI window on screen for about half a minute. It uses a temporary copy of `Adempiere.properties` and presses OK on the login dialog; your own settings file is not changed.

**Not tested:** a person using it. The tests press the button and read what the page shows, but nobody has typed in the page, resized the window, or used it for a working session. The button's absence for an ungranted role is tested through ADempiere's role object, not by logging in to the real client as that role.

## Limits

- **Start ADempiere with `RUN_Adempiere_InsightAI.bat`.** Started any other way (the stock `RUN_Adempiere.bat`, the Ask AI start script, or the web client), ADempiere works as before but there is no InsightAI button, and no other way in from inside ADempiere. The dashboard can still be reached at the service's address while the development login is on.
- **Needs JavaFX.** Oracle JDK 8 has it. On a Java runtime without it (most OpenJDK 8 builds, and Java 11 or later) the window says so and offers **Open in browser**; nothing else in ADempiere is affected.
- **Date fields are plain text boxes** in this web view: type dates as `2026-01-31`. The Period presets work normally.
- **A user with no performance goals has no Performance tab.** For such a user the button is put on a first tab of its own named InsightAI. Every GardenWorld user has goals, so this path has not been seen in practice.
- **Desktop client only.** The ZK web client is not supported.
- **Depends on ADempiere's main window layout.** The button is added by finding the tab that holds ADempiere's Performance panel. A different ADempiere version could arrange that window differently; the code then leaves the tab alone rather than fail.
