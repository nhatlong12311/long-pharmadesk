# Codex handoff — LONG × PharmaDesk

Updated: 2026-11-18. Project owner communicates in Vietnamese.

## Goal

Continue development of PharmaDesk 3.0 with the **original Python/Flask source as the source of truth**, not an independently invented approximation. The user wants a working online clinical-tools site to share with colleagues, without displaying the personal portfolio there, and has asked to move development into Codex.

## GitHub repository and deployments

- Repository: https://github.com/nhatlong12311/long-pharmadesk
- Branch: `main`. **Public repository** (explicit choice by user).
- Render URL, personal portfolio and backend: https://long-pharmadesk.onrender.com/
- GitHub Pages static-browser beta: https://nhatlong12311.github.io/long-pharmadesk/
- The user created or was creating a second Render service for Tools Only; **its final live URL is not confirmed**. Do not infer it.
- The original authoritative uploaded archive was named `PharmaDesk_3_0_ChiTietSoLuong(1).zip` in the prior ChatGPT conversation. Codex needs a copy if the repo differs from that exact original; do not claim repo is byte-for-byte identical to that upload without comparison.

## Architecture

- `app.py` — Flask server, online authentication, portfolio page, tool page, registered blueprints.
- `abcven.py` — ABC/VEN Excel import, analysis and reports.
- `ttt.py` — interaction rules, analyses and exports.
- `tdm.py` — vancomycin/aminoglycoside calculation endpoints.
- `adr.py` — official 115-field ADR PDF template filling, DOCX generation, drafts, download.
- `common.py` — shared Excel/file utilities.
- `ui/index.html` — **actual original PharmaDesk UI** with six tabs and API calls; Render online tool UI.
- `ADR/Mau_bao_cao_ADR.pdf`, `ADR/fonts/` — necessary ADR report assets.
- `docs/index.html` and `docs/rules.json` — **separate, limited experimental JavaScript browser edition** on GitHub Pages. This is NOT functional parity with the original Python source, especially for ADR/TDM.
- `render.yaml` — default Render service config.
- `RENDER_TOOLS_ONLY.md` — instructions for separate Tools Only deployment.

## User preferences

- Work on the **real uploaded program**, preserving outputs, formulas, fields and reports; do not silently replace the official ADR PDF with a summary.
- Share ABC/VEN, drug interactions, TDM and ADR via fast web UI.
- Keep personal portfolio out of the colleagues' Tools Only UI.
- Can operate GitHub **in browser**, not using local git CLI or phone.
- Wants actual edits, tests and working results rather than repeated instructions or speculative fixes.
- Do not publish or test with identifiable patient data.

## Recent changes on GitHub

1. `app.py`: added `PHARMADESK_TOOLS_ONLY=1` for a second Render service. It redirects `/` to `/tools?module=abc`, removes the portfolio backlink and hides Windows-only tabs in the generated tool UI. Existing personal portfolio service remains unchanged when this env var is not set. **This hides UI only, not source in a public repo.**
2. `app.py`: ADR embedded PDF viewer changed from `X-Frame-Options: DENY` to `SAMEORIGIN`, CSP `frame-ancestors 'self'`.
3. `adr.py`: when `PHARMADESK_ONLINE=1`, `/api/adr/generate` returns base64 `inline_files.pdf` and `inline_files.docx` along with report names to avoid subsequent "Không thấy file" caused by ephemeral server storage / different workers.
4. `ui/index.html`: decodes inline files to Blob URLs for PDF preview and downloading, with Windows/local fallback for file-backed download.
5. `ui/index.html`: central `api()` wrapper was upgraded to inspect HTTP status and Content-Type, showing a meaningful message rather than `SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON`. Commit `64df5215b311e0588a4a55ff555dc58e067c6309`.
6. `docs/index.html`: Browser Edition beta exists and can display an ADR summary; it does **not** output the official PDF/Word template. A link routes users to the real Python ADR on Render.

## Most recent reported problem

The user encountered `SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON` when using online ADR. The central API error handler was changed; **we have not seen the new HTTP status or server logs and have not verified an end-to-end successful online ADR PDF/Word download after the change**.

Likely explanations require verification: Render proxy 502/503/504, a service returning HTML instead of JSON, stale deploy, Basic Auth, worker restart/memory spikes from base64-in-JSON reports. Do not assert a specific cause without logs or a reproducible request.

## Recommended immediate Codex work

1. Inspect recent commits and check GitHub Actions / Render logs and the actual deployed revisions, if account connections permit.
2. Reproduce ADR generation using synthetic data against Flask test client and a production-like Gunicorn process. Verify PDF/DOCX generated, valid, downloadable, and iframe preview; exercise HTTP error responses.
3. Review whether returning base64 PDF + DOCX in one JSON response is safe under Render Free memory constraints. Consider a safer approach if needed (e.g. single response streamed ZIP, or file-backed retrieval with verified per-worker storage semantics), maintaining original ADR template.
4. Ensure browser edition does not imply full parity or clinical validation.
5. For multi-user colleagues, **do not allow real patient data** while using shared Basic Auth, shared server file directories, and no per-user segregation/audit/retention policies. These need separate implementation before actual clinical use.
6. If speed matters, evaluate pricing and deployment options **without replacing authoritative Python modules with unverified approximate formulas**.
7. Keep edits small, test before committing, and communicate confirmed vs unverified behavior in Vietnamese.

## Quick-start

```bash
python -m pip install -r requirements.txt
python -m compileall -q app.py abcven.py adr.py tdm.py ttt.py common.py
# Use synthetic data for Flask tests.
PHARMADESK_ONLINE=1 PHARMADESK_USERNAME=clinical PHARMADESK_PASSWORD='<strong-local-test-password>' python -m flask --app app run
```

The env assignment syntax above is POSIX; Windows CMD/PowerShell require their respective syntax. Never put real passwords into GitHub, commits, issues or chat.

## Handoff prompt to Codex

> Tiếp tục dự án trong repository `nhatlong12311/long-pharmadesk`. Đọc `CODEX_HANDOFF.md`, kiểm tra cấu trúc mã nguồn Python gốc và sửa dứt điểm việc ADR online tạo/xem/tải đúng file PDF/Word theo mẫu. Lỗi gần nhất là `Unexpected token '<'` khi API trả HTML thay vì JSON. Cần xác định nguyên nhân thực qua log/test, kiểm tra memory và luồng file trên Render, sửa bằng PR có test. Giữ portfolio tách khỏi Tools Only và không dùng dữ liệu bệnh nhân thật.
