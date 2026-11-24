import io, os, json, hmac, hashlib, uuid
from typing import List
import cv2, fitz, numpy as np, qrcode
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from omr_layout import draw_sheet as draw_sheet_mod

SECRET=os.getenv("DADYAR_QR_SECRET","CHANGE-ME-BEFORE-PRODUCTION")
SUPABASE_URL=os.getenv("SUPABASE_URL","").rstrip("/")
SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY",os.getenv("SUPABASE_PUBLISHABLE_KEY",""))
bearer=HTTPBearer(auto_error=False)
W,H=A4
LIMIT=15*1024*1024
CANON_W,CANON_H=2480,3508
app=FastAPI(title="Dadyar AI OMR",version="1.0.0")
# Allow the production Vercel frontends plus explicitly configured origins.
_ALLOWED_ORIGINS={x.strip().rstrip("/") for x in os.getenv("CORS_ORIGINS","").split(",") if x.strip()}
_ALLOWED_ORIGINS.update({"https://dadyar-ai-web.vercel.app","https://dadyar-ai.vercel.app","http://localhost:3000"})
app.add_middleware(CORSMiddleware,allow_origins=sorted(_ALLOWED_ORIGINS),allow_credentials=False,allow_methods=["*"],allow_headers=["*"])

FONT_PATH=os.getenv("DADYAR_FONT","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
try:
    pdfmetrics.registerFont(TTFont("DadyarFa",FONT_PATH))
    FA_FONT="DadyarFa"
except Exception:
    FA_FONT="Helvetica"

def fa(s):
    s=str(s)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(s))
    except Exception:
        return s

def txt(c,x,y,s,size=8,bold=False):
    c.setFont(FA_FONT,size)
    c.drawRightString(x,y,fa(s))

class Student(BaseModel):
    student_id:uuid.UUID
    name:str
    code:str
class Batch(BaseModel):
    exam_id:uuid.UUID
    exam_title:str="آزمون"
    subject:str="ریاضی"
    school_name:str="ایران زمین"
    site_name:str="دادیار AI"
    question_count:int=Field(ge=1,le=300)
    columns:int=Field(default=6,ge=1,le=6)
    students:List[Student]
class ReportRow(BaseModel):
    student:str
    code:str=""
    exam:str=""
    correct:int=0
    wrong:int=0
    blank:int=0
    score:float=0
    total:int=0

def signed_qr(data):
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    sig=hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest()[:24]
    return json.dumps({"data":data,"sig":sig},ensure_ascii=False,separators=(",",":"))

def verify_qr(raw):
    try:
        obj=json.loads(raw); data=obj["data"]
        rawdata=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        sig=hmac.new(SECRET.encode(),rawdata,hashlib.sha256).hexdigest()[:24]
        return data if hmac.compare_digest(sig,obj["sig"]) else None
    except Exception:
        return None

@app.get("/health")
def health():
    return {"status":"ok","service":"dadyar-omr","version":"1.0.0",
            "database_configured":bool(SUPABASE_URL and SUPABASE_ANON_KEY),
            "qr_configured":SECRET!="CHANGE-ME-BEFORE-PRODUCTION"}

async def verify_user(credentials:HTTPAuthorizationCredentials=Depends(bearer)):
    if not credentials or credentials.scheme.lower()!="bearer":
        raise HTTPException(401,"برای استفاده از سرویس وارد حساب کاربری شوید.")
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(503,"اتصال امن Supabase روی سرویس OMR تنظیم نشده است.")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.get(SUPABASE_URL+"/auth/v1/user",
                headers={"apikey":SUPABASE_ANON_KEY,"Authorization":"Bearer "+credentials.credentials})
        if response.status_code!=200:
            raise HTTPException(401,"نشست کاربری معتبر نیست؛ دوباره وارد شوید.")
        return response.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503,"امکان بررسی نشست کاربری وجود ندارد.")

async def supabase_rows(table,token,params):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.get(SUPABASE_URL+"/rest/v1/"+table,params=params,
                headers={"apikey":SUPABASE_ANON_KEY,"Authorization":"Bearer "+token})
        if response.status_code in (401,403):
            raise HTTPException(403,"دسترسی به داده‌های این مدرسه مجاز نیست.")
        if response.status_code>=400:
            raise HTTPException(502,"خطا در خواندن اطلاعات پایگاه داده.")
        return response.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503,"اتصال به پایگاه داده برقرار نشد.")

async def exam_context(exam_id,token):
    rows=await supabase_rows("exams",token,{"select":"id,institution_id,question_count,negative_coefficient","id":"eq."+str(exam_id)})
    return rows[0] if rows else None

async def student_context(student_id,institution_id,token):
    rows=await supabase_rows("students",token,{"select":"id,institution_id,student_code,first_name,last_name","id":"eq."+str(student_id),"institution_id":"eq."+str(institution_id)})
    return rows[0] if rows else None

async def exam_answer_key(exam_id,token):
    rows=await supabase_rows("answer_keys",token,{"select":"answers","exam_id":"eq."+str(exam_id)})
    if not rows:return None
    try:
        values=[int(x) for x in rows[0]["answers"]]
        if not 1<=len(values)<=120 or any(x not in (1,2,3,4) for x in values):return None
        return values
    except Exception:
        return None

def fa_digits(value):
    return str(value).translate(str.maketrans("0123456789","۰۱۲۳۴۵۶۷۸۹"))

def fa_digits(value):
    return str(value).translate(str.maketrans("0123456789","۰۱۲۳۴۵۶۷۸۹"))

def draw_sheet_legacy(c,batch,s)
    """Production A4 OMR: four fixed 30-question blocks, RTL options, signed QR."""
    mm=72/25.4
    margin=20*mm
    mark=10*mm
    c.setFillColorRGB(0,0,0)
    for x,y in [(margin,margin),(W-margin-mark,margin),
                (margin,H-margin-mark),(W-margin-mark,H-margin-mark)]:
        c.rect(x,y,mark,mark,stroke=0,fill=1)

    qrdata={"sheet_id":str(uuid.uuid4()),"exam_id":str(batch.exam_id),
            "student_id":str(s.student_id),"student_code":s.code,
            "question_count":batch.question_count}
    qr=qrcode.QRCode(box_size=8,border=0,error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(signed_qr(qrdata)); qr.make(fit=True)
    qrb=io.BytesIO()
    qr.make_image(fill_color="black",back_color="white").save(qrb,format="PNG")
    qrb.seek(0)
    qr_x=30*mm; qr_y=H-69*mm; qr_size=38*mm
    c.setFillColorRGB(1,1,1); c.rect(qr_x,qr_y,qr_size,qr_size,stroke=0,fill=1)
    c.drawImage(ImageReader(qrb),qr_x+5*mm,qr_y+5*mm,width=28*mm,height=28*mm,mask="auto")
    c.setFillColorRGB(0,0,0); c.setFont(FA_FONT,6.5)
    c.drawCentredString(qr_x+qr_size/2,qr_y-4*mm,fa("شناسه یکتای پاسخ‌برگ"))

    # Brand, exam metadata and student details are separate visual zones.
    brand_x=82*mm
    c.setFillColorRGB(0,0,0); c.setFont(FA_FONT,16)
    c.drawCentredString(brand_x,H-31*mm,fa("دادیار AI"))
    c.setFont(FA_FONT,10); c.drawCentredString(brand_x,H-40*mm,fa("پاسخ‌برگ آزمون"))
    c.setFont(FA_FONT,7); c.drawCentredString(brand_x,H-49*mm,fa("سامانه هوشمند تصحیح پاسخ‌برگ"))
    c.drawCentredString(brand_x,H-61*mm,fa("آزمون: "+str(batch.exam_title or "آزمون")))
    c.drawCentredString(brand_x,H-68*mm,fa("درس: "+str(batch.subject or "................")))

    info_x=112*mm; info_y=H-72*mm; info_w=78*mm; info_h=52*mm
    c.setStrokeColorRGB(0,0,0); c.setLineWidth(.8)
    c.rect(info_x,info_y,info_w,info_h,stroke=1,fill=0)
    c.setFont(FA_FONT,8)
    c.drawRightString(info_x+info_w-4*mm,info_y+info_h-7*mm,fa("مشخصات دانش‌آموز"))
    c.setLineWidth(.45)
    c.line(info_x+3*mm,info_y+info_h-10*mm,info_x+info_w-3*mm,info_y+info_h-10*mm)
    fields=[
        "نام و نام خانوادگی: "+str(s.name),
        "کد دانش‌آموزی: "+str(s.code),
        "کلاس: ................................",
        "تاریخ: .................................",
        "مدت آزمون: .............. دقیقه",
    ]
    for idx,label in enumerate(fields):
        c.setFont(FA_FONT,6.7)
        c.drawRightString(info_x+info_w-4*mm,info_y+info_h-(16+idx*7.2)*mm,fa(label))

    c.setFont(FA_FONT,7)
    c.drawCentredString(W/2,H-82*mm,
        fa("برای هر سؤال فقط یک حباب را کاملاً با مداد مشکی پر کنید."))

    # 4 blocks × 30 rows. Block 1 (questions 1–30) is rightmost.
    row_top=H-103*mm
    row_step=5.0*mm
    bubble_r=2.2*mm
    question_x0=190*mm
    block_step=43.0*mm
    option_offsets=[9.5*mm,17.0*mm,24.5*mm,32.0*mm]
    c.setStrokeColorRGB(0,0,0); c.setLineWidth(.7)
    c.line(20*mm,row_top+6.5*mm,190*mm,row_top+6.5*mm)
    for block in range(4):
        qx=question_x0-block*block_step
        c.setFont(FA_FONT,7)
        c.drawRightString(qx,row_top+1.5*mm,fa("سؤال"))
        for idx,off in enumerate(option_offsets,1):
            c.drawCentredString(qx-off,row_top+1.5*mm,fa(fa_digits(idx)))
        for row in range(30):
            q=block*30+row+1
            if q>batch.question_count: break
            y=row_top-row*row_step
            c.setFillColorRGB(0,0,0); c.setFont(FA_FONT,7)
            c.drawRightString(qx,y-2.0*mm,fa(fa_digits(q)))
            for off in option_offsets:
                c.setStrokeColorRGB(0,0,0); c.setLineWidth(.75)
                c.circle(qx-off,y,bubble_r,stroke=1,fill=0)
            if row<29:
                c.setStrokeColorRGB(.88,.88,.88); c.setLineWidth(.2)
                c.line(qx-36*mm,y-2.45*mm,qx+1*mm,y-2.45*mm)

    c.setStrokeColorRGB(0,0,0); c.setLineWidth(.45)
    c.line(margin+8*mm,30*mm,W-margin-8*mm,30*mm)
    c.setFont("Helvetica",6); c.drawString(margin+8*mm,25*mm,"dadyar-ai-web.vercel.app")
    c.setFont(FA_FONT,6)
    c.drawCentredString(W/2,25*mm,fa("طراحی و توسعه: رضی خادمی"))
    c.drawRightString(W-margin-8*mm,25*mm,fa("شناسه: "+qrdata["sheet_id"][:8]))
    c.drawCentredString(W/2,15*mm,fa("کاغذ A4 · چاپ ۱۰۰٪ · بدون برش اسکن شود"))
    return qrdata

draw_sheet=draw_sheet_mod

@app.get("/")
def root():
    return {"service":"Dadyar AI OMR","status":"ok","health":"/health","docs":"/docs"}

@app.post("/v1/sheets/generate")
async def generate_sheets(batch:Batch,user=Depends(verify_user),credentials:HTTPAuthorizationCredentials=Depends(bearer)):
    """Create one authenticated, signed-QR A4 answer sheet per verified student."""
    token=credentials.credentials
    if SECRET=="CHANGE-ME-BEFORE-PRODUCTION":
        raise HTTPException(503,"کلید امن QR روی سرویس تنظیم نشده است.")
    if not batch.students:
        raise HTTPException(400,"حداقل یک دانش‌آموز برای تولید پاسخ‌برگ انتخاب کنید.")
    if len(batch.students)>300:
        raise HTTPException(400,"در هر نوبت حداکثر ۳۰۰ پاسخ‌برگ تولید می‌شود.")
    exam=await exam_context(batch.exam_id,token)
    if not exam:
        raise HTTPException(404,"آزمون در فضای مدرسه فعلی پیدا نشد.")
    if batch.question_count>batch.columns*50:
        raise HTTPException(400,"تعداد سؤال‌ها از ظرفیت ستون‌های انتخاب‌شده بیشتر است.")
    if int(exam.get("question_count") or 0)!=batch.question_count:
        raise HTTPException(409,"تعداد سؤال‌های درخواستی با آزمون ثبت‌شده یکسان نیست.")
    answer_key=await exam_answer_key(batch.exam_id,token)
    if not answer_key or len(answer_key)!=batch.question_count:
        raise HTTPException(409,"کلید پاسخ معتبر برای این آزمون ثبت نشده است.")
    seen=set()
    verified_students=[]
    for requested in batch.students:
        if requested.student_id in seen:
            continue
        seen.add(requested.student_id)
        db_student=await student_context(requested.student_id,exam["institution_id"],token)
        if not db_student:
            raise HTTPException(403,"یکی از دانش‌آموزان انتخاب‌شده به این آزمون یا مدرسه تعلق ندارد.")
        if str(db_student.get("student_code") or "")!=str(requested.code):
            raise HTTPException(409,"کد دانش‌آموزی با اطلاعات ثبت‌شده مطابقت ندارد.")
        verified_students.append(Student(
            student_id=requested.student_id,
            name=(str(db_student.get("first_name") or "")+" "+str(db_student.get("last_name") or "")).strip(),
            code=str(db_student.get("student_code") or "")
        ))
    if not verified_students:
        raise HTTPException(400,"دانش‌آموز معتبری برای تولید پاسخ‌برگ انتخاب نشده است.")
    output=io.BytesIO()
    pdf=canvas.Canvas(output,pagesize=A4,pageCompression=1)
    pdf.setTitle(fa("پاسخ‌برگ "+batch.exam_title))
    pdf.setAuthor("Dadyar AI")
    for student in verified_students:
        draw_sheet(pdf,batch,student)
        pdf.showPage()
    pdf.save()
    output.seek(0)
    return StreamingResponse(output,media_type="application/pdf",
        headers={"Content-Disposition":'attachment; filename="dadyar-answer-sheets.pdf"',"Cache-Control":"no-store"})

def decode_pdf_or_image(data,ctype):
    if ctype=="application/pdf":
        doc=fitz.open(stream=data,filetype="pdf")
        if len(doc)>50: raise HTTPException(400,"حداکثر ۵۰ صفحه مجاز است.")
        imgs=[]
        for page in doc:
            pix=page.get_pixmap(matrix=fitz.Matrix(4.1667,4.1667),alpha=False)
            imgs.append(cv2.imdecode(np.frombuffer(pix.tobytes("png"),np.uint8),cv2.IMREAD_COLOR))
        return imgs
    img=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if img is None: raise HTTPException(400,"تصویر قابل خواندن نیست.")
    return [img]

def find_fiducials(img):
    """Robustly detect four printed corner registration marks across old/new sheet revisions."""
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    h,w=gray.shape
    mm=72/25.4
    expected_mm=25*mm
    # Otsu and adaptive threshold handle clean PDFs, phone photos and uneven lighting.
    masks=[
        cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY_INV,41,11)
    ]
    candidates=[]
    min_area=w*h*0.000008
    max_area=w*h*0.012
    for th in masks:
        contours,_=cv2.findContours(th,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area=cv2.contourArea(cnt)
            if area<min_area or area>max_area: continue
            x,y,bw,bh=cv2.boundingRect(cnt)
            ratio=bw/max(1,bh)
            fill=area/max(1,bw*bh)
            if not .72<=ratio<=1.28 or fill<.62: continue
            # Ignore tiny QR finder patterns and very large page graphics.
            size_mm=(bw/w)*(W/mm)
            if not 3.0<=size_mm<=16.0: continue
            cx=x+bw/2; cy=y+bh/2
            item=(area,(cx,cy),bw,bh)
            if not any(abs(cx-p[1][0])<3 and abs(cy-p[1][1])<3 for p in candidates):
                candidates.append(item)
    if len(candidates)<4: return None

    # Four corner zones; permit older 5–6 mm marks and camera crop/scale variation.
    # Score by proximity to expected 25 mm centers, while preferring solid, larger marks.
    zones=[(0,0),(1,0),(1,1),(0,1)] # TL, TR, BR, BL
    points=[]
    for zx,zy in zones:
        tx=(expected_mm/W*w) if zx==0 else (w-expected_mm/W*w)
        ty=(expected_mm/H*h) if zy==0 else (h-expected_mm/H*h)
        pool=[]
        for area,center,bw,bh in candidates:
            x,y=center
            if not ((x<w*.24) if zx==0 else (x>w*.76)): continue
            if not ((y<h*.24) if zy==0 else (y>h*.76)): continue
            # Flexible positional tolerance for earlier PDFs and camera perspective.
            dist=((x-tx)/w)**2+((y-ty)/h)**2
            if dist>.035: continue
            size_penalty=abs((bw/w)-(bh/h))
            score=dist+size_penalty*.15- min(area/(w*h),.01)*.02
            pool.append((score,center))
        if not pool: return None
        points.append(min(pool,key=lambda p:p[0])[1])

    src=np.array(points,dtype=np.float32)
    # Normalize to the current A4 scanner coordinate system.
    center_offset=25*72/25.4
    dx=center_offset/W*CANON_W; dy=center_offset/H*CANON_H
    dst=np.array([[dx,dy],[CANON_W-dx,dy],
                  [CANON_W-dx,CANON_H-dy],[dx,CANON_H-dy]],dtype=np.float32)
    M=cv2.getPerspectiveTransform(src,dst)
    aligned=cv2.warpPerspective(img,M,(CANON_W,CANON_H),flags=cv2.INTER_CUBIC)
    return aligned

def orient_and_align(img,detector):
    """Deskew a sheet and decode its QR with several contrast-safe fallbacks."""
    rotations=[img,cv2.rotate(img,cv2.ROTATE_90_CLOCKWISE),
               cv2.rotate(img,cv2.ROTATE_180),cv2.rotate(img,cv2.ROTATE_90_COUNTERCLOCKWISE)]
    marker_found=False
    for candidate in rotations:
        h,w=candidate.shape[:2]
        if w>=h:
            continue
        aligned=find_fiducials(candidate)
        if aligned is None:
            continue
        marker_found=True
        gray=cv2.cvtColor(aligned,cv2.COLOR_BGR2GRAY)
        clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(gray)
        variants=[aligned,gray,clahe,
                  cv2.threshold(clahe,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1],
                  cv2.adaptiveThreshold(clahe,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY,31,9)]
        for variant in variants:
            try:
                raw,points,_=detector.detectAndDecode(variant)
                if raw and points is not None:
                    pts=np.asarray(points,dtype=np.float32).reshape(-1,2)
                    cx,cy=pts.mean(axis=0)
                    if cx<CANON_W*.34 and cy<CANON_H*.28:
                        return aligned,raw,None
            except Exception:
                pass
        crop=clahe[:int(CANON_H*.30),:int(CANON_W*.36)]
        crop=cv2.resize(crop,None,fx=1.7,fy=1.7,interpolation=cv2.INTER_CUBIC)
        try:
            raw,_,_=detector.detectAndDecode(crop)
            if raw:
                return aligned,raw,None
        except Exception:
            pass
    if marker_found:
        return None,None,"QR اختصاصی خوانده نشد؛ وضوح تصویر یا کنتراست QR کافی نیست. فایل PDF اصلی را مستقیم بارگذاری کنید یا با کیفیت ۳۰۰ DPI اسکن بگیرید."
    return None,None,"چهار علامت مرجع گوشه برگه پیدا نشد؛ احتمال برش صفحه، حاشیه کم اسکن یا کج‌بودن زیاد تصویر."

def bubble_score(gray,cx,cy,half_w,half_h):
    # Score the inner area of a circular OMR bubble, excluding its printed ring.
    Hh,Ww=gray.shape
    inner=np.zeros((Hh,Ww),np.uint8); outer=np.zeros((Hh,Ww),np.uint8)
    radius=max(2,int(min(half_w,half_h)))
    cv2.circle(inner,(int(cx),int(cy)),max(1,int(radius*.58)),255,-1)
    cv2.circle(outer,(int(cx),int(cy)),max(2,int(radius*1.75)),255,-1)
    outer[inner>0]=0
    inside=gray[inner>0]; outside=gray[outer>0]
    if inside.size==0 or outside.size==0:return 0.0
    baseline=float(np.median(outside))
    return float(np.mean(np.clip((baseline-inside)/max(35,baseline),0,1)))

def scan_bubbles(aligned,n,columns=6):
    """Read four fixed 30-question blocks using the same RTL geometry as the PDF."""
    gray=cv2.cvtColor(aligned,cv2.COLOR_BGR2GRAY)
    answers=[None]*n; uncertain=[]
    mm=72/25.4
    columns=max(1,min(6,int(columns or 6)))
    rows_per_col=(n+columns-1)//columns
    row_top=H-101*mm
    row_step=3.45*mm
    question_x0=190*mm
    block_step=170*mm/columns
    option_offsets=[8.0*mm,12.2*mm,16.4*mm,20.6*mm]
    sx=CANON_W/W; sy=CANON_H/H
    radius=1.35*mm*sx
    for q in range(1,n+1):
        block=(q-1)//rows_per_col
        row=(q-1)%rows_per_col
        qx=question_x0-block*block_step
        y=row_top-row*row_step
        cy=int(round((H-y)*sy))
        scores=[]
        for off in option_offsets:
            cx=int(round((qx-off)*sx))
            scores.append(bubble_score(gray,cx,cy,radius,radius))
        order=np.argsort(scores)[::-1]
        best=float(scores[order[0]]); second=float(scores[order[1]])
        marked=[j for j,v in enumerate(scores) if v>=.24]
        if len(marked)>1:
            uncertain.append({"question":q,"reason":"بیش از یک گزینه علامت خورده","scores":[round(v,3) for v in scores]})
        elif best<.19:
            answers[q-1]=None
        elif best-second<.07:
            uncertain.append({"question":q,"reason":"علامت کم‌رنگ یا نامطمئن","scores":[round(v,3) for v in scores]})
        else:
            answers[q-1]=int(order[0])+1
    return answers,uncertain,None

@app.post("/v1/sheets/inspect")
async def inspect(file:UploadFile=File(...),user=Depends(verify_user),credentials:HTTPAuthorizationCredentials=Depends(bearer)):
    token=credentials.credentials
    if file.content_type not in {"image/jpeg","image/png","image/webp","application/pdf"}:
        raise HTTPException(415,"فرمت پشتیبانی نمی‌شود.")
    data=await file.read()
    if not data or len(data)>LIMIT:
        raise HTTPException(413,"فایل خالی یا بزرگ‌تر از ۱۵ مگابایت است.")
    if SECRET=="CHANGE-ME-BEFORE-PRODUCTION":
        raise HTTPException(503,"کلید امن QR روی سرویس تنظیم نشده است.")
    results=[]; detector=cv2.QRCodeDetector()
    for i,img in enumerate(decode_pdf_or_image(data,file.content_type),1):
        try:
            aligned,qr,align_error=orient_and_align(img,detector)
        except Exception as exc:
            print(f"OMR alignment failed on page {i}: {type(exc).__name__}: {exc}")
            results.append({"page":i,"status":"review_required","reason":"خطای داخلی هنگام تحلیل تصویر؛ لطفاً فایل را دوباره اسکن کنید یا این صفحه را بازبینی کنید."})
            continue
        if aligned is None:
            results.append({"page":i,"status":"review_required","reason":align_error or "برگه قابل هم‌ترازی نیست."}); continue
        student_qr=verify_qr(qr) if qr else None
        if not student_qr:
            results.append({"page":i,"status":"review_required","reason":"QR اختصاصی معتبر پیدا نشد."}); continue
        try:
            exam_id=uuid.UUID(str(student_qr.get("exam_id")))
            student_id=uuid.UUID(str(student_qr.get("student_id")))
        except Exception:
            results.append({"page":i,"status":"review_required","reason":"شناسه آزمون یا دانش‌آموز در QR معتبر نیست."}); continue
        exam=await exam_context(exam_id,token)
        if not exam:
            results.append({"page":i,"status":"review_required","reason":"آزمون در مدرسه فعلی پیدا نشد یا به آن دسترسی مجاز نیست.","student":student_qr}); continue
        student=await student_context(student_id,exam["institution_id"],token)
        if not student or student.get("student_code")!=student_qr.get("student_code"):
            results.append({"page":i,"status":"review_required","reason":"دانش‌آموز QR با اطلاعات مدرسه مطابقت ندارد.","student":student_qr}); continue
        key=await exam_answer_key(exam_id,token)
        if not key:
            results.append({"page":i,"status":"review_required","reason":"کلید پاسخ معتبر برای آزمون پیدا نشد.","student":student_qr}); continue
        if student_qr.get("question_count")!=len(key) or int(exam["question_count"])!=len(key):
            results.append({"page":i,"status":"review_required","reason":"تعداد سؤال با کلید پاسخ یکسان نیست.","student":student_qr}); continue
        answers,uncertain,error=scan_bubbles(aligned,len(key),student_qr.get('columns',6))
        if error:
            results.append({"page":i,"status":"review_required","reason":error,"student":student_qr}); continue
        uncertain_q={u["question"] for u in uncertain}
        correct=sum(a==k for a,k in zip(answers,key) if a is not None)
        blank=sum(a is None and q not in uncertain_q for q,a in enumerate(answers,1))
        unresolved=len(uncertain_q)
        wrong=len(key)-correct-blank-unresolved
        coefficient=float(exam.get("negative_coefficient") or 3)
        score=correct-(wrong/coefficient if coefficient>0 else 0)
        results.append({"page":i,"status":"review_required" if uncertain else "processed",
            "student":student_qr,"answers":answers,"correct":correct,"wrong":wrong,"blank":blank,
            "unresolved":unresolved,"score":round(score,2),"uncertain":uncertain})
    return {"pages":results,"scoring":"correct - wrong / negative_coefficient; blank=0",
            "warning":"پاسخ‌های مبهم را بازبینی کنید. دقت نهایی باید با برگه‌های چاپ و اسکن واقعی کالیبره شود."}


@app.post("/v1/reports/excel")
def excel(rows:List[ReportRow],user=Depends(verify_user)):
    wb=Workbook(); ws=wb.active; ws.title="گزارش آزمون"
    ws.append(["نام دانش‌آموز","کد","آزمون","صحیح","غلط","سفید","نمره خام","تعداد سؤال"])
    for cell in ws[1]:
        cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17233A")
    for r in rows: ws.append([r.student,r.code,r.exam,r.correct,r.wrong,r.blank,r.score,r.total])
    for col,width in {"A":24,"B":18,"C":28,"D":12,"E":12,"F":12,"G":14,"H":14}.items():
        ws.column_dimensions[col].width=width
    for row in ws.iter_rows():
        for cell in row: cell.alignment=Alignment(horizontal="center")
    out=io.BytesIO(); wb.save(out); out.seek(0)
    return StreamingResponse(out,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":'attachment; filename="dadyar-report.xlsx"'})
