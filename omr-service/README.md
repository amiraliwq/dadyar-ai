# Dadyar AI OMR service

FastAPI service for generating personalized Persian A4 answer sheets, reading scanned images/PDFs, and exporting XLSX reports.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set a long random secret before starting:
# Windows PowerShell: $env:DADYAR_QR_SECRET="a-long-random-secret"
# macOS/Linux: export DADYAR_QR_SECRET="a-long-random-secret"
uvicorn main:app --reload --port 8080
```

Health: `GET /health`

- `POST /v1/sheets/generate`: JSON body with exam_id, exam_title, subject, school_name, site_name, question_count (1-120), and students [{student_id,name,code}]. Returns a multi-page A4 PDF with an individual signed QR per student.
- `POST /v1/sheets/inspect`: multipart file + answer_key JSON array + negative_coefficient. Accepts PNG/JPEG/WebP/PDF. Returns detected answers, score and uncertainty flags.
- `POST /v1/reports/excel`: JSON array of report rows. Returns XLSX.

## Recognition improvements in version 0.3
- Four large corner registration squares and repeated side marks are used to find the page boundary and correct rotation/perspective before reading answers.
- Bubble scoring estimates darkness inside each bubble against a local paper-background ring; printed outlines are excluded from the fill measurement.
- Multiple filled bubbles and low-confidence marks are sent to `review_required`; uncertain answers are reported separately from genuinely blank answers.
- The Persian PDF layout includes the student information panel, QR, four answer columns, corner markers and side ticks based on the supplied reference image.

## Calibration and safety
- This is an improved first-pass OMR engine, not yet a certified or production-validated grading system. Test blank sheets, every answer option, light pencil marks, erasures, double marks, tilted scans and photocopies from the actual printer/scanner.
- Use 300 DPI scans, full page, no crop, flat paper, grayscale or color. Keep all four corner squares visible.
- Review every `review_required` page manually. Do not use uncertain results as final grades.
- The QR signature secret must be identical for sheet generation and scanning. Set a unique long random `DADYAR_QR_SECRET` in the hosting provider's secret environment. The service refuses QR generation/scanning when the default placeholder secret is in use.
- Restrict `CORS_ORIGINS` to the deployed website domain in production. Do not leave wildcard CORS enabled on a public production service.
- The service is not yet connected to Supabase. Student records and scan results are not centrally persisted yet.
