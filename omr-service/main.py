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

SECRET=os.getenv("DADYAR_QR_SECRET","CHANGE-ME-BEFORE-PRODUCTION")
SUPABASE_URL=os.getenv("SUPABASE_URL","").rstrip("/")
SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY",os.getenv("SUPABASE_PUBLISHABLE_KEY",""))
bearer=HTTPBearer(auto_error=False)
W,H=A4
LIMIT=15*1024*1024
CANON_W,CANON_H=2480,3508
app=FastAPI(title="Dadyar AI OMR",version="0.3.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:3000").split(",") if x.strip()],allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["*"])

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
    question_count:int=Field(ge=1,le=120)
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
    return {"status":"ok","service":"dadyar-omr","version":"0.4.0",
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

def draw_sheet(c,batch,s):
    # Four large registration squares + repeated side ticks make deskew/crop detection reliable.
    mark=14
    for x,y in [(36,36),(W-36,36),(36,H-36),(W-36,H-36)]:
        c.setFillColorRGB(0,0,0); c.rect(x-mark/2,y-mark/2,mark,mark,stroke=0,fill=1)
    for side in (48,W-48):
        for y in range(155,int(H-155),43):
            c.rect(side-2.2,y-5.5,4.4,11,stroke=0,fill=1)

    # Main information panel, modeled on the supplied reference sheet.
    c.setStrokeColorRGB(.55,.55,.55); c.setLineWidth(.55)
    c.rect(84,H-164,W-120,132,stroke=1,fill=0)
    qrdata={"sheet_id":str(uuid.uuid4()),"exam_id":str(batch.exam_id),"student_id":str(s.student_id),
            "student_code":s.code,"question_count":batch.question_count}
    qr=qrcode.QRCode(box_size=5,border=2,error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(signed_qr(qrdata)); qr.make(fit=True)
    qrb=io.BytesIO(); qr.make_image(fill_color="black",back_color="white").save(qrb,format="PNG"); qrb.seek(0)
    c.drawImage(ImageReader(qrb),99,H-139,width=66,height=66)
    c.setFillColorRGB(0,0,0)
    txt(c,164,H-145,"شناسه اختصاصی",6)

    # Student information box
    c.rect(W-264,H-156,224,110,stroke=1,fill=0)
    txt(c,W-50,H-63,"مشخصات دانش‌آموز",9)
    c.line(W-255,H-70,W-49,H-70)
    txt(c,W-50,H-88,"نام: "+s.name,7)
    txt(c,W-50,H-103,"کد دانش‌آموزی: "+s.code,7)
    txt(c,W-50,H-118,"کلاس: —",7)
    txt(c,W-50,H-133,"تاریخ آزمون: ....................",7)
    txt(c,W-50,H-147,"مدت آزمون: ............ دقیقه",7)

    c.setFont(FA_FONT,13); c.drawCentredString(W/2+8,H-87,fa(batch.school_name))
    c.setFont(FA_FONT,6); c.drawCentredString(W/2+8,H-101,fa(batch.site_name))
    c.setFont(FA_FONT,12); c.drawCentredString(W/2+8,H-126,fa("پاسخ‌برگ آزمون"))
    c.setFont(FA_FONT,9); c.drawCentredString(W/2+8,H-143,fa(batch.subject))

    c.setFont(FA_FONT,7); c.drawCentredString(W/2,H-184,fa("در هر سؤال فقط یک گزینه را کاملاً پر کنید؛ از مداد نرم استفاده کنید."))

    # Four RTL columns; each question has four numbered bubbles.
    left,right=84,W-40
    colw=(right-left)/4
    top=H-220
    row_gap=17.2
    for col in range(4):
        x0=right-(col+1)*colw
        c.setFont(FA_FONT,7); c.drawString(x0+5,top+17,fa("سؤال"))
        for opt in range(4):
            c.setFont("Helvetica-Bold",7); c.drawCentredString(x0+49+opt*18,top+17,str(opt+1))
        for row in range(30):
            q=col*30+row+1
            if q>batch.question_count: break
            y=top-row*row_gap
            c.setFont("Helvetica-Bold",7); c.drawString(x0+8,y-2,str(q))
            for opt in range(4):
                bx=x0+49+opt*18
                c.setLineWidth(.65); c.circle(bx,y,6.1,stroke=1,fill=0)

    # Column separators and footer.
    for k in range(1,4):
        x=right-k*colw
        c.setStrokeColorRGB(.78,.78,.78); c.line(x,H-205,x,105)
    c.setStrokeColorRGB(.65,.65,.65); c.line(84,82,W-40,82)
    c.setFont("Helvetica",6); c.drawString(84,69,"dadyar-ai.vercel.app")
    c.setFont(FA_FONT,6); c.drawCentredString(W/2,69,fa(batch.school_name))
    c.setFont("Helvetica",6); c.drawRightString(W-40,69,"شناسه برگه: "+qrdata["sheet_id"][:8])
    c.setFont(FA_FONT,6); c.drawCentredString(W/2,47,fa("برای تصحیح دقیق، برگه را کامل و بدون برش اسکن کنید."))
    return qrdata

@app.post("/v1/sheets/generate")
async def generate(batch:Batch,user=Depends(verify_user),credentials:HTTPAuthorizationCredentials=Depends(bearer)):
    token=credentials.credentials
    if not batch.students or len(batch.students)>500:
        raise HTTPException(400,"تعداد دانش‌آموز باید بین ۱ تا ۵۰۰ باشد.")
    if SECRET=="CHANGE-ME-BEFORE-PRODUCTION":
        raise HTTPException(503,"ابتدا DADYAR_QR_SECRET امن را در تنظیمات سرویس تعریف کنید.")
    exam=await exam_context(batch.exam_id,token)
    if not exam:
        raise HTTPException(404,"آزمون پیدا نشد یا به آن دسترسی ندارید.")
    if int(exam["question_count"])!=batch.question_count:
        raise HTTPException(400,"تعداد سؤال با آزمون ثبت‌شده در پایگاه داده یکسان نیست.")
    ids=[str(s.student_id) for s in batch.students]
    if len(set(ids))!=len(ids):
        raise HTTPException(400,"شناسه دانش‌آموز تکراری است.")
    rows=await supabase_rows("students",token,{"select":"id,institution_id,student_code,first_name,last_name",
        "id":"in.("+",".join(ids)+")","institution_id":"eq."+exam["institution_id"]})
    by_id={r["id"]:r for r in rows}
    if len(by_id)!=len(ids):
        raise HTTPException(403,"یک یا چند دانش‌آموز متعلق به مدرسه شما نیستند یا پیدا نشدند.")
    batch.students=[Student(student_id=uuid.UUID(r["id"]),
        name=(r.get("first_name","")+" "+r.get("last_name","")).strip(),code=r["student_code"])
        for r in (by_id[str(s.student_id)] for s in batch.students)]
    batch.exam_id=uuid.UUID(exam["id"])
    bio=io.BytesIO(); c=canvas.Canvas(bio,pagesize=A4)
    for s in batch.students:
        draw_sheet(c,batch,s); c.showPage()
    c.save(); bio.seek(0)
    return StreamingResponse(bio,media_type="application/pdf",
        headers={"Content-Disposition":'attachment; filename="dadyar-answer-sheets.pdf"',
                 "X-Sheet-Count":str(len(batch.students))})


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
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    th=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    contours,_=cv2.findContours(th,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    h,w=gray.shape; candidates=[]
    for cnt in contours:
        area=cv2.contourArea(cnt)
        if area < w*h*0.000035: continue
        x,y,bw,bh=cv2.boundingRect(cnt)
        ratio=bw/max(1,bh)
        if .72<=ratio<=1.28 and area/(bw*bh)>.68:
            candidates.append((area,(x+bw/2,y+bh/2),bw,bh))
    if len(candidates)<4: return None
    # Match the four printed registration squares by their expected normalized
    # corner positions and approximate physical size. Do not simply choose the
    # largest dark square: QR finder patterns also look like square contours.
    zones=[(0,0),(1,0),(1,1),(0,1)] # TL,TR,BR,BL
    points=[]
    expected_size_x=14/W* w
    expected_size_y=14/H* h
    for zx,zy in zones:
        tx=(36/W*w) if zx==0 else (w-36/W*w)
        ty=(36/H*h) if zy==0 else (h-36/H*h)
        pool=[]
        for area,center,bw,bh in candidates:
            x,y=center
            if not ((x<w*.18) if zx==0 else (x>w*.82)): continue
            if not ((y<h*.18) if zy==0 else (y>h*.82)): continue
            # Match the printed square's expected physical size and corner offset.
            if abs(bw-expected_size_x)/max(1,expected_size_x)>.60: continue
            if abs(bh-expected_size_y)/max(1,expected_size_y)>.60: continue
            contour_match=abs(x-tx)/max(1,w)+abs(y-ty)/max(1,h)
            if contour_match>.12: continue
            pool.append((contour_match,center))
        if not pool: return None
        points.append(min(pool,key=lambda p:p[0])[1])
    src=np.array(points,dtype=np.float32)
    # registration-mark centers are 36pt from each A4 edge
    dx=36/W*CANON_W; dy=36/H*CANON_H
    dst=np.array([[dx,dy],[CANON_W-dx,dy],[CANON_W-dx,CANON_H-dy],[dx,CANON_H-dy]],dtype=np.float32)
    M=cv2.getPerspectiveTransform(src,dst)
    return cv2.warpPerspective(img,M,(CANON_W,CANON_H),flags=cv2.INTER_CUBIC)

def orient_and_align(img,detector):
    # Normalize portrait orientation and resolve 180-degree scans by locating
    # the signed QR in its expected upper-left area after perspective correction.
    rotations=[
        img,
        cv2.rotate(img,cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(img,cv2.ROTATE_180),
        cv2.rotate(img,cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]
    for candidate in rotations:
        h,w=candidate.shape[:2]
        if w>=h:
            continue
        aligned=find_fiducials(candidate)
        if aligned is None:
            continue
        raw,points,_=detector.detectAndDecode(aligned)
        if not raw or points is None:
            continue
        pts=np.asarray(points,dtype=np.float32).reshape(-1,2)
        cx,cy=pts.mean(axis=0)
        if cx < CANON_W*.30 and cy < CANON_H*.25:
            return aligned,raw
    return None,None

def bubble_score(gray,cx,cy,r):
    # Estimate darkness inside the bubble while excluding its printed outline.
    inner=np.zeros(gray.shape,np.uint8); ring=np.zeros(gray.shape,np.uint8)
    cv2.circle(inner,(cx,cy),int(r*.58),255,-1)
    cv2.circle(ring,(cx,cy),int(r*1.45),255,-1)
    cv2.circle(ring,(cx,cy),int(r*1.12),0,-1)
    inside=gray[inner>0]; outside=gray[ring>0]
    if inside.size==0 or outside.size==0:return 0.0
    baseline=float(np.median(outside))
    return float(np.mean(np.clip((baseline-inside)/max(35,baseline),0,1)))

def scan_bubbles(aligned,n):
    gray=cv2.cvtColor(aligned,cv2.COLOR_BGR2GRAY)
    answers=[]; uncertain=[]
    left,right=84,W-40; colw=(right-left)/4; top=H-220; gap=17.2
    sx=CANON_W/W; sy=CANON_H/H
    for q in range(1,n+1):
        col=(q-1)//30; row=(q-1)%30; x0=right-(col+1)*colw; y=top-row*gap
        cy=int((H-y)*sy); scores=[]
        for opt in range(4):
            x=x0+49+opt*18; cx=int(x*sx); r=6.1*sx
            scores.append(bubble_score(gray,cx,cy,r))
        order=np.argsort(scores)[::-1]; best=float(scores[order[0]]); second=float(scores[order[1]])
        marked=[j for j,v in enumerate(scores) if v>=.22]
        if len(marked)>1:
            answers.append(None); uncertain.append({"question":q,"reason":"بیش از یک گزینه علامت خورده","scores":[round(v,3) for v in scores]})
        elif best<.20:
            answers.append(None)
        elif best-second<.075:
            answers.append(None); uncertain.append({"question":q,"reason":"علامت کم‌رنگ یا نامطمئن","scores":[round(v,3) for v in scores]})
        else:
            answers.append(int(order[0])+1)
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
        aligned,qr=orient_and_align(img,detector)
        if aligned is None:
            results.append({"page":i,"status":"review_required","reason":"علامت‌های مرجع یا QR در جهت معتبر پیدا نشد؛ احتمال چرخش، برش یا کیفیت پایین تصویر."}); continue
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
        answers,uncertain,error=scan_bubbles(aligned,len(key))
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
