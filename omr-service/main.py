import io, os, json, hmac, hashlib, uuid
from typing import List
import cv2, fitz, numpy as np, qrcode
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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
W,H=A4
LIMIT=15*1024*1024
CANON_W,CANON_H=2480,3508
app=FastAPI(title="Dadyar AI OMR",version="0.3.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["*"])

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
    student_id:str
    name:str
    code:str
class Batch(BaseModel):
    exam_id:str
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
    return {"status":"ok","service":"dadyar-omr","version":"0.3.0"}

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
    qrdata={"sheet_id":str(uuid.uuid4()),"exam_id":batch.exam_id,"student_id":s.student_id,
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
    row_gap=19
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
def generate(batch:Batch):
    if not batch.students or len(batch.students)>500:
        raise HTTPException(400,"تعداد دانش‌آموز باید بین ۱ تا ۵۰۰ باشد.")
    if SECRET=="CHANGE-ME-BEFORE-PRODUCTION":
        raise HTTPException(503,"ابتدا DADYAR_QR_SECRET امن را در تنظیمات سرویس تعریف کنید.")
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
            pix=page.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False)
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
            candidates.append((area,(x+bw/2,y+bh/2)))
    if len(candidates)<4: return None
    zones=[(0,0),(1,0),(1,1),(0,1)] # TL,TR,BR,BL
    points=[]
    for zx,zy in zones:
        pool=[p for p in candidates if ((p[1][0]<w*.25) if zx==0 else (p[1][0]>w*.75))
              and ((p[1][1]<h*.25) if zy==0 else (p[1][1]>h*.75))]
        if not pool: return None
        points.append(max(pool,key=lambda p:p[0])[1])
    src=np.array(points,dtype=np.float32)
    # registration-mark centers are 36pt from each A4 edge
    dx=36/W*CANON_W; dy=36/H*CANON_H
    dst=np.array([[dx,dy],[CANON_W-dx,dy],[CANON_W-dx,CANON_H-dy],[dx,CANON_H-dy]],dtype=np.float32)
    M=cv2.getPerspectiveTransform(src,dst)
    return cv2.warpPerspective(img,M,(CANON_W,CANON_H),flags=cv2.INTER_CUBIC)

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

def scan_bubbles(img,n):
    aligned=find_fiducials(img)
    if aligned is None:
        return None,None,"چهار علامت مرجع گوشه‌ها پیدا نشد؛ برگه را کامل، صاف و بدون برش اسکن کنید."
    gray=cv2.cvtColor(aligned,cv2.COLOR_BGR2GRAY)
    answers=[]; uncertain=[]
    left,right=84,W-40; colw=(right-left)/4; top=H-220; gap=19
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
async def inspect(file:UploadFile=File(...),answer_key:str=Form(...),negative_coefficient:float=Form(3)):
    if file.content_type not in {"image/jpeg","image/png","image/webp","application/pdf"}:
        raise HTTPException(415,"فرمت پشتیبانی نمی‌شود.")
    data=await file.read()
    if not data or len(data)>LIMIT: raise HTTPException(413,"فایل خالی یا بزرگ‌تر از ۱۵ مگابایت است.")
    try:key=[int(x) for x in json.loads(answer_key)]
    except Exception: raise HTTPException(400,"کلید پاسخ نامعتبر است.")
    if not 1<=len(key)<=120 or any(x not in [1,2,3,4] for x in key):
        raise HTTPException(400,"کلید باید ۱ تا ۱۲۰ پاسخ از ۱ تا ۴ داشته باشد.")
    if negative_coefficient<0: raise HTTPException(400,"ضریب نمره منفی نمی‌تواند منفی باشد.")
    if SECRET=="CHANGE-ME-BEFORE-PRODUCTION":
        raise HTTPException(503,"کلید امن QR روی سرویس تنظیم نشده است.")
    results=[]; detector=cv2.QRCodeDetector()
    for i,img in enumerate(decode_pdf_or_image(data,file.content_type),1):
        aligned=find_fiducials(img)
        if aligned is None:
            results.append({"page":i,"status":"review_required","reason":"چهار علامت مرجع پیدا نشد؛ احتمال برش یا کیفیت پایین تصویر."}); continue
        qr,_,_=detector.detectAndDecode(aligned)
        student=verify_qr(qr) if qr else None
        if not student:
            results.append({"page":i,"status":"review_required","reason":"QR اختصاصی معتبر پیدا نشد."}); continue
        if student.get("question_count")!=len(key):
            results.append({"page":i,"status":"review_required","reason":"تعداد سؤال با کلید پاسخ یکسان نیست.","student":student}); continue
        answers,uncertain,error=scan_bubbles(aligned,len(key))
        if error:
            results.append({"page":i,"status":"review_required","reason":error,"student":student}); continue
        correct=sum(a==k for a,k in zip(answers,key) if a is not None)
        blank=sum(a is None for a in answers); wrong=len(key)-correct-blank
        score=correct-(wrong/negative_coefficient if negative_coefficient>0 else 0)
        results.append({"page":i,"status":"review_required" if uncertain else "processed",
            "student":student,"answers":answers,"correct":correct,"wrong":wrong,"blank":blank,
            "score":round(score,2),"uncertain":uncertain})
    return {"pages":results,"scoring":"correct - wrong / negative_coefficient; blank=0",
            "warning":"این نسخه باید با چند نمونه چاپ و اسکن واقعی کالیبره شود. وضعیت review_required را بدون بازبینی انسانی نهایی نکنید."}

@app.post("/v1/reports/excel")
def excel(rows:List[ReportRow]):
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
