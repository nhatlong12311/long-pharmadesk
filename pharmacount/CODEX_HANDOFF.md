# CODEX HANDOFF — PharmaCount (2026-11-23)

## Repository and change control
- Repository: `nhatlong12311/long-pharmadesk`
- Work on branch `feature/pharmacount-inventory`, review through **PR #25**.
- PharmaCount lives only inside `pharmacount/`; **do not rewrite PharmaDesk ABC/VEN, ADR, TDM, interactions or other existing modules**.
- Do not merge until browser tests and security review have passed. The main PharmaDesk inventory system remains the authoritative inventory source.

## Backend already connected
- Supabase project **PharmaCount**, ref `jpsywcjmcmvgjswkrnzo`, region `ap-southeast-1`.
- Schema: `pharmacount/supabase.sql`, count concurrency extension `pharmacount/supabase-count-rpc.sql`, followed by safe latest-per-drug snapshot `pharmacount/supabase-latest-counts.sql`.
- 4 RLS-protected tables: `inventory_sessions`, `inventory_members`, `inventory_items`, `inventory_counts`.
- The `pc_create_session` RPC validates the incoming inventory and creates the session + all items **atomically in one PostgreSQL transaction**. It is `SECURITY INVOKER` and may only be called by `authenticated` (not `anon`).
- The `pc_submit_count` RPC writes count records only after checking membership, item revision and idempotent operation ID. Returns `saved` or `conflict`; never directly overwrite a prior count.
- Realtime publication includes `public.inventory_counts`. Frontend refreshes a paginated latest-per-drug snapshot via RPC `pc_latest_counts` every 20s. Do not use a global BIGSERIAL cursor because commits can finish out of ID order.
- Frontend has the **publishable** key only; never embed a Supabase secret/service-role key.

## Working import characteristics from real sample files
The private Excel samples were inspected during development; **do not copy them into public GitHub**.
- `Dmkk t10.xlsx`: 914 medication/source rows, 763 distinct medication codes, 7 sheet XML files, one empty sheet. Header has code, name, unit, lot, expiry and separate chẵn/lẻ. **No independent machine stock** in this example.
- `danh muc(1).xlsx`: 5,706 nonempty code rows in a large worksheet (about 9,100 worksheet rows and 250 columns). Column B is `MÃ`, K is `QUY CÁCH ĐÓNG GÓI`.
- 877 of 914 inventory rows (~96%) match catalog codes exactly; **37 remain unmatched**. Handle as exceptions, not by approximate matching.
- 5 groups repeat the same code/lot/sheet within the inventory source. Preserve each Excel source row and warn to manually verify duplicates, rather than deleting or silently merging.
- If catalog offers multiple pack sizes, factor must remain unconfirmed until authorized person selects the correct size.
- Excel serial expiry date must display as a calendar date; `stock = null` must never be treated as zero stock.

## Frontend
- `pharmacount/index.html`: one-page responsive counting UI, XLSX imports/exports, Supabase OTP auth, email membership, shared inventory sessions.
- `pharmacount/pack-worker.js`: reads large packaging XLSX in a Web Worker and only matches needed codes; avoids blocking the UI.
- `pharmacount/tests/logic.test.cjs`: regression tests. Run `node --test pharmacount/tests/*.test.cjs`. GitHub Actions workflow `.github/workflows/pharmacount-check.yml` added; **verify that the repository permits running Actions**, as workflow status had not yet appeared.
- Cloud exports trigger a fresh Supabase sync; fail visibly if the server cannot confirm up-to-date data.
- Timeouts retry the same operation ID while payload is unchanged. Conflicts explicitly reload the teammate result before re-entry.
- All cloud source data is fetched after sign-in; a full cloud copy is not intentionally persisted in localStorage.

## Critical follow-up work
1. Run all regression tests through GitHub Actions (not only parsing/syntax) and fix any failures.
2. Deploy preview under a known HTTPS URL, configure Supabase **Auth Redirect URLs**, and log in two consenting **test accounts** using fake sample medicine data.
3. Test owner creates session, invites user, both join, simultaneous count on one item, conflict resolution, same-operation retry, multi-lot distinction, error on network loss and XLSX export.
4. Check role authorization and Supabase Security Advisor. The project still flags some intentional SECURITY DEFINER functions; audit their privilege boundaries and search_path before production.
5. Add offline retry queue (IndexedDB), approval and locking of finalized sessions, independent recount and supervisory review before clinical operations.
6. Validate hospital approval for sending stock and drug catalog data to a third-party cloud, and confirm backups and retention policies.
7. **Do not claim production readiness** until a two-device end-to-end test succeeds, including with >1,000 rows.

## Known limits
- Current web app loads XLSX and Supabase SDK through CDN, so no guaranteed full offline operation.
- Magic-link login requires configured Supabase email delivery and redirect settings.
- A record is considered cloud-saved only when server acknowledges; otherwise show a failure.
- Realtime polling is a fallback; devices only receive updates while connected.
