# InsightAI inside ADempiere

Added on 2026-10-12, after Stage 7. The dashboard now opens as a window of the ADempiere desktop client instead of in an external browser.

## What you see

Under **Performance Analysis** there are two entries:

| Menu entry | What it does |
|---|---|
| **InsightAI** | Opens an ADempiere window containing the dashboard, signed in as your ADempiere user and role |
| **InsightAI (browser)** | Opens the same dashboard in your default web browser, as before |

The window has ADempiere's usual File / View / Tools menu and two buttons: **Reload**, which signs in again and reloads the page (use it after the 8-hour session ends), and **Open in browser**.

## How it works

- The window is an ADempiere form: an `AD_Form` record whose class, `org.insightai.adempiere.InsightAIForm`, ADempiere creates when the menu entry is clicked.
- The form shows the web page with JavaFX WebView, the browser engine that ships with Oracle JDK 8. On this machine that is JavaFX 8.0.501 with WebKit 623.1, which runs the dashboard without changes: no script errors, all cards and charts drawn.
- Sign-in is the same hand-off as the browser launcher (Stage 6): the form signs the logged-in user and role with the shared key, gets a link that works once for one minute, and loads it in the web view. Nothing about the user is typed in or chosen in the page.
- The dashboard itself is unchanged and still served by the InsightAI service, so the service must be running. Model inference stays in the service, not in the ADempiere client.

## Access

- The form is granted to the same roles as the browser launcher (`AD_Form_Access`), set by `adempiere_install.ps1 -Roles`.
- ADempiere leaves both entries out of the menu of a role that has not been granted them.
- ADempiere does not itself stop the form class from being opened by other means, so the service checks too: it signs a role in only if the role holds the form or the process in ADempiere. A role without either sees "This role has not been granted access to InsightAI in ADempiere" and no data.

## Tested

`scripts\test_form.ps1` opens the window off-screen through ADempiere's own `FormFrame.openForm`, builds the menu tree the way the client does for that role, waits for the page, reads what it shows and saves a picture to `build\`.

| Login | Menu shows the entries | Window shows |
|---|---|---|
| GardenAdmin / GardenWorld Admin | Yes | Dashboard, 8 organisations, 8 KPI cards, 8 charts |
| test_salerep / SalesRep(Restricted) | Yes | Dashboard, MEKAR only |
| GardenUser / GardenWorld User (not granted) | No | Forced open: the refusal message, no data |

**Not tested:** a person clicking the entry in the real client, typing in the page, and resizing the window. The test covers opening, sign-in, loading and what is displayed; it does not click anything inside the page.

## Limits

- **Needs JavaFX.** Oracle JDK 8 has it. On a Java runtime without it (most OpenJDK 8 builds, and Java 11 or later) the window says so and offers **Open in browser**; nothing else in ADempiere is affected.
- **Date fields are plain text boxes** in this web view: type dates as `2026-01-31`. The Period presets work normally.
- **The window must be opened from a client started with `RUN_Adempiere_InsightAI.bat`**, as for the browser launcher.
- **Desktop client only.** The ZK web client is still not supported.
- **One session per window.** Closing the window ends the page; reopening signs in again.
