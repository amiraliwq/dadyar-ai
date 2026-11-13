# Dadyar AI OMR service

FastAPI service for generating personalized QR answer sheets, scanning generated answer sheets from images/PDFs, and exporting XLSX reports.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set DADYAR_QR_SECRET to a long random value before production.
uvicorn main:app --reload --port 8080
```

Health: `GET /health`

- `POST /v1/sheets/generate`: JSON body with exam_id, exam_title, question_count (1-120), and students [{student_id,name,code}]. Returns a multi-page PDF with a signed unique QR per student.
- `POST /v1/sheets/inspect`: multipart file + answer_key JSON array + negative_coefficient. Accepts PNG/JPEG/WebP/PDF. Returns answers, score and uncertainty flags.
- `POST /v1/reports/excel`: JSON array of report rows. Returns XLSX.

## Important limitations
- OMR coordinates are calibrated for this service's own generated A4 template. Scans should be 300 DPI, uncropped, and retain the four corner registration marks.
- Test with real printer/scanner combinations and tune thresholds before official grading. Ambiguous marks are flagged, never guessed.
- The QR signature secret must be identical for sheet generation and scanning. Set it in the hosting provider's secret environment; never commit it.
- This service is not yet connected to Supabase. Persisting generated sheets, students and grading results is the next integration step after selecting the dedicated Supabase project.
- The QR embeds an opaque student identifier/code and exam identifier. Avoid putting unnecessary personal data in the QR.
