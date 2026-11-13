# Dadyar AI OMR service

FastAPI container service for generating signed-QR A4 answer sheets and reading scanned images/PDFs. The API is protected by Supabase Auth and uses the caller's access token so Supabase RLS enforces school-level access.

## Required environment variables
- SUPABASE_URL — URL of the dedicated Dadyar Supabase project.
- SUPABASE_ANON_KEY — public anon/publishable key (not the service-role key).
- DADYAR_QR_SECRET — long random secret used to sign and verify QR payloads.
- CORS_ORIGINS — exact website origin, for example https://dadyar-ai-web.vercel.app.
- DADYAR_FONT — optional DejaVu Sans font path; Dockerfile supplies a default.

Never set a service-role key in this service. Database requests use the authenticated user's JWT and RLS.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set SUPABASE_URL, SUPABASE_ANON_KEY, DADYAR_QR_SECRET and CORS_ORIGINS
uvicorn main:app --reload --port 8080
```

Health: GET /health. The response reports whether Supabase and QR secret configuration are present, never the secret values.

## API
- POST /v1/sheets/generate — requires Authorization: Bearer <Supabase access token>. JSON body includes exam_id, question_count, school_name, site_name and students with their database student_id values. The service checks exam and student ownership through Supabase RLS and uses the canonical student names/codes from the database. Returns a multi-page A4 PDF with an individual signed QR per student.
- POST /v1/sheets/inspect — requires Authorization: Bearer <Supabase access token>. Multipart file accepts PNG/JPEG/WebP/PDF. The service reads the signed QR, verifies the exam and student under the caller's RLS scope, fetches the answer key from Supabase and computes the score. The client cannot override the answer key or negative-marking coefficient.
- POST /v1/reports/excel — requires Authorization: Bearer <Supabase access token>. Returns XLSX for supplied report rows.

## Recognition and calibration
- Four corner registration squares and repeated side marks locate the page and support perspective correction.
- The service tries portrait/landscape and 180-degree orientations, then checks the QR location before accepting an aligned page.
- Bubble scoring compares darkness inside each bubble against a local paper-background ring and excludes the printed outline.
- Multiple marks and low-confidence fills are flagged for human review; the uncertain question numbers and scores are returned.
- The printed form has a four-column answer grid, student details, QR, corner fiducials and side ticks.

## Production validation
- This is an improved OMR implementation, not a certified or production-validated grading system. Before relying on grades, test blank sheets, each answer position, light pencil marks, erasures, double marks, 90/180-degree rotations, perspective, shadows and photocopies on the actual printer/scanner.
- Prefer 300 DPI, full-page scans with all corner marks visible.
- Any page with status review_required must be checked by a human before finalizing grades.
- Keep DADYAR_QR_SECRET identical across sheet generation and scanning. Rotate it only when all outstanding answer sheets are reissued.
- Restrict CORS_ORIGINS to the exact production web domain. CORS is not authentication; every protected endpoint also validates the Supabase access token.
- Deploy this service separately from the static Vercel website on a container host that supports the 15 MB upload limit.