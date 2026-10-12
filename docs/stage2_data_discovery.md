# Stage 2: data discovery

Run on 2026-10-12 against database `EV`, schema `adempiere`, client GardenWorld (`AD_Client_ID = 11`).

## Tables and columns

All tables and columns the prompt listed exist under those names, with one exception: `RV_OpenItem` has no `DocStatus` column (it already filters to `CO`/`CL` internally). Stock is in `M_Storage`; `M_StorageOnHand` does not exist.

## Data volume

| Table | Rows | Date range | Created since install (2026-09-15) |
|---|---|---|---|
| `C_Order` | 34 | 2018-10-22 to 2026-10-07 | 27 |
| `C_Invoice` | 32 | 2018-10-22 to 2026-10-06 | 24 |
| `M_InOut` | 21 | 2018-10-22 to 2026-10-06 | 12 |
| `M_Transaction` | 48 | 2018-10-22 to 2026-10-06 | 20 |
| `M_Product` | 64 | | 2 |
| `C_BPartner` | 21 | | 4 |

Completed documents fall in only 8 calendar months (2018-10, 2019-04, 2019-05, 2019-09, 2019-10, 2026-06, 2026-09, 2026-10). Only two organisations have documents: HQ and MEKAR AIR HANDLING UNITS LLC.

## Document status and type

| Document | Counted (`CO`/`CL`) | Excluded |
|---|---|---|
| Sales orders | 16 | 3 draft, 2 invalid, 1 voided |
| Purchase orders | 9 | 3 draft |
| Customer invoices | 9 | none |
| Vendor invoices | 11 | 6 voided, 6 reversed |
| Shipments | 11 | none |
| Receipts | 9 | 1 draft |

- Order types present: Standard, POS and On Credit sales orders; Purchase Order. Return Material, Proposal and Quotation types exist but have no documents.
- Invoice types present: AR Invoice, AR Invoice Indirect, AP Invoice. No credit memos (`ARC`/`APC`).
- Movement types in `M_Transaction`: `C-`, `V+`, `I+`, `I-`, `M+`, `M-`. No customer or vendor returns.
- Draft and voided orders carry the placeholder document type `** New **`, so filtering on `DocBaseType` also removes them.

## Currency

- Accounting schema: "GardenWorld US/A/US Dollar", currency USD.
- Documents: USD, plus one order and one invoice in EUR. EUR↔USD rates exist from 1999 to 2072, so every document converts; no view row has a NULL base amount.

## Costing

- Accounting schema costing method is Average Invoice, costing level Client (`M_Cost` rows carry org 0).
- Two cost types: "Average Invoice" (the schema's) and "Default" (standard cost).
- Of the 20 products with stock, 5 have a non-zero Average Invoice material cost and all 20 have a standard cost.

## Organisation access

`v_user_role_org` reproduces `MRole`'s rules, including expansion of the summary organisation "Stores" into its five stores.

| User | Role | Organisations |
|---|---|---|
| GardenAdmin | GardenWorld Admin | all 8 |
| GardenUser | GardenWorld User | all 8 (HQ, Furniture, MEKAR, and the 5 stores via "Stores") |
| test_salerep | SalesRep(Restricted) | MEKAR only |
| WebService | Web Service Execution | HQ, Store Central |

## What was installed

`scripts\db_install.ps1` ran `db\01_install.sql` and `db\02_login_role.sql`.

- **Roles:** `insightai_owner` (no login; owns the schema; SELECT on a fixed list of ADempiere tables and views named in `01_install.sql`, and on 4 non-secret columns of `AD_User`) and `insightai_ro` (the service login; password in `.env`).
- **Schema `insightai`:** 16 views and 3 helper functions. No tables yet.
- **Database-wide hardening:** `CREATE` on schema `public` and `TEMPORARY` on the database were revoked from `PUBLIC`. Without this the service role could switch off its read-only default and create tables. This also applies to `erp_ai_reader`; the `adempiere` superuser is unaffected.
- **Nothing in schema `adempiere` was created, altered or dropped.**

`scripts\db_install.ps1 -Uninstall` removes all of it and restores the two `PUBLIC` privileges.

### Why there are helper functions

ADempiere's PL/pgSQL functions (`currencyConvert`, `invoiceOpen`, `paymentTermDueDate`) read tables with the caller's rights, and `insightai_ro` has no rights on `adempiere`. Three `SECURITY DEFINER` wrappers run them as `insightai_owner`.

`invoiceOpen()` catches its own errors and returns NULL. A missing grant therefore produced zero open invoices with no error during testing. The grant list in `01_install.sql` now covers `C_Invoice_v` and `C_NonBusinessDay`, and the open-item row count is part of the cross-check in `kpi_definitions.md`.

## Tests run

- `scripts\db_verify.ps1` as `insightai_ro`: all 16 views return rows; reading `adempiere.c_invoice`, `ad_user.password` and `ad_sysconfig`, calling `adempiere.invoiceopen`, and creating a table in `public`, `insightai` or as a temp table are all refused.
- Cross-checks against ADempiere's Performance goals, `M_Storage` and `RV_OpenItem`: all match (see `kpi_definitions.md`).

Corrected in Stage 7: `v_demand_daily` originally included service and expense items that appear on shipment documents but move no stock. It now holds stocked items only, and `scripts\db_crosscheck.ps1` compares it with `M_Transaction`.

Not yet tested: returns and credit-memo sign handling (no such documents exist), and `IsUseUserOrgAccess` roles (none exist).
