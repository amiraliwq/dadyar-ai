from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Dadyar AI OMR API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to the production dashboard domain before launch.
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "dadyar-omr", "omr_ready": False}

@app.post("/v1/sheets/inspect")
async def inspect_sheet(file: UploadFile = File(...)):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp", "application/pdf"}:
        raise HTTPException(status_code=415, detail="فرمت فایل پشتیبانی نمی‌شود.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="فایل خالی است.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حداکثر حجم فایل ۱۵ مگابایت است.")
    # TODO: implement PDF rasterization, QR decoding, fiducial detection,
    # perspective correction, bubble scoring and uncertainty reporting.
    return {
        "status": "received",
        "filename": file.filename,
        "bytes": len(data),
        "processed": False,
        "message": "فایل دریافت شد؛ موتور واقعی OMR هنوز فعال نشده است."
    }
