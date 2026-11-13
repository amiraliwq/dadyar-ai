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
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

SECRET=os.getenv("DADYAR_QR_SECRET","CHANGE-ME-BEFORE-PRODUCTION")
W,H=A4; LIMIT=15*1024*1024
app=FastAPI(title="Dadyar AI OMR",version="0.2.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["*"])

class Student(BaseModel):
 student_id:str
 name:str
 code:str
class Batch(BaseModel):
 exam_id:str
 exam_title:str="Exam"
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
 except Exception:return None

@app.get("/health")
def health():return {"status":"ok","service":"dadyar-omr","version":"0.2.0"}

@app.post("/v1/sheets/generate")
def generate(batch:Batch):
 if not batch.students or len(batch.students)>500:raise HTTPException(400,"تعداد دانش‌آموز باید بین ۱ تا ۵۰۰ باشد.")
 bio=io.BytesIO(); c=canvas.Canvas(bio,pagesize=A4); manifest=[]
 for s in batch.students:
  payload={"sheet_id":str(uuid.uuid4()),"exam_id":batch.exam_id,"student_id":s.student_id,"student_code":s.code,"question_count":batch.question_count}
  qr=qrcode.QRCode(box_size=4,border=2);qr.add_data(signed_qr(payload));qr.make(fit=True)
  qrb=io.BytesIO();qr.make_image(fill_color="black",back_color="white").save(qrb,format="PNG");qrb.seek(0)
  c.setFont("Helvetica-Bold",16);c.drawString(32,H-35,"DADYAR AI | ANSWER SHEET")
  c.setFont("Helvetica",9);c.drawString(32,H-55,f"Exam: {batch.exam_title[:48]}   Student: {s.name[:32]}   Code: {s.code[:18]}")
  c.drawImage(ImageReader(qrb),W-112,H-150,width=76,height=76)
  c.setFont("Helvetica",8);c.drawString(32,H-90,"Fill one bubble per question. Use a dark pen. Keep all corner marks visible.")
  colw=(W-64)/4; top=H-190; rh=19
  for col in range(4):
   base=32+col*colw
   for row in range(30):
    q=col*30+row+1
    if q>batch.question_count:break
    y=top-row*rh;c.setFont("Helvetica-Bold",8);c.drawRightString(base+22,y-2,str(q))
    for opt in range(4):
     x=base+39+opt*20;c.circle(x,y,5.3,stroke=1,fill=0);c.setFont("Helvetica",6);c.drawCentredString(x,y-2,str(opt+1))
  for x,y in [(18,18),(W-18,18),(18,H-18),(W-18,H-18)]:c.rect(x-5,y-5,10,10,stroke=0,fill=1)
  c.setFont("Helvetica",7);c.drawCentredString(W/2,22,"Scan at 300 DPI • Do not crop the corner marks");c.showPage();manifest.append(payload)
 c.save();bio.seek(0)
 return StreamingResponse(bio,media_type="application/pdf",headers={"Content-Disposition":'attachment; filename="dadyar-sheets.pdf"',"X-Sheet-Count":str(len(manifest))})

def images_from_file(data,ctype):
 if ctype=="application/pdf":
  doc=fitz.open(stream=data,filetype="pdf")
  if len(doc)>50:raise HTTPException(400,"حداکثر ۵۰ صفحه مجاز است.")
  return [cv2.imdecode(np.frombuffer(p.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).tobytes("png"),np.uint8),cv2.IMREAD_COLOR) for p in doc]
 img=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
 if img is None:raise HTTPException(400,"تصویر قابل خواندن نیست.")
 return [img]
def scan_bubbles(img,n):
 sx,sy=img.shape[1]/W,img.shape[0]/H;gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY);answers=[];uncertain=[]
 for q in range(1,n+1):
  col=(q-1)//30;row=(q-1)%30;base=32+col*((W-64)/4);y=H-190-row*19;scores=[]
  for opt in range(4):
   x=base+39+opt*20;cx,cy=int(x*sx),int((H-y)*sy);mask=np.zeros(gray.shape,np.uint8);cv2.circle(mask,(cx,cy),max(3,int(3.2*(sx+sy)/2)),255,-1)
   px=gray[mask>0];scores.append(float(np.mean(px<125)) if len(px) else 0)
  order=np.argsort(scores)[::-1];top=scores[int(order[0])];second=scores[int(order[1])]
  if top<.22:answers.append(None)
  elif top-second<.10:answers.append(None);uncertain.append({"question":q,"reason":"علامت مبهم یا چندگانه","scores":[round(v,3) for v in scores]})
  else:answers.append(int(order[0])+1)
 return answers,uncertain

@app.post("/v1/sheets/inspect")
async def inspect(file:UploadFile=File(...),answer_key:str=Form(...),negative_coefficient:float=Form(3)):
 if file.content_type not in {"image/jpeg","image/png","image/webp","application/pdf"}:raise HTTPException(415,"فرمت پشتیبانی نمی‌شود.")
 data=await file.read()
 if not data or len(data)>LIMIT:raise HTTPException(413,"فایل خالی یا بزرگ‌تر از ۱۵ مگابایت است.")
 try:key=[int(x) for x in json.loads(answer_key)]
 except Exception:raise HTTPException(400,"کلید پاسخ نامعتبر است.")
 if not 1<=len(key)<=120 or any(x not in [1,2,3,4] for x in key):raise HTTPException(400,"کلید باید ۱ تا ۱۲۰ پاسخ از ۱ تا ۴ داشته باشد.")
 results=[];det=cv2.QRCodeDetector()
 for i,img in enumerate(images_from_file(data,file.content_type),1):
  qr,_,_=det.detectAndDecode(img);student=verify_qr(qr) if qr else None
  if not student:results.append({"page":i,"status":"review_required","reason":"QR معتبر پیدا نشد"});continue
  if student.get("question_count")!=len(key):results.append({"page":i,"status":"review_required","reason":"تعداد سؤال با کلید هم‌خوان نیست","student":student});continue
  ans,unc=scan_bubbles(img,len(key));correct=sum(a==k for a,k in zip(ans,key) if a is not None);blank=sum(a is None for a in ans);wrong=len(key)-correct-blank;score=correct-wrong/(negative_coefficient if negative_coefficient>0 else 1)
  results.append({"page":i,"status":"review_required" if unc else "processed","student":student,"answers":ans,"correct":correct,"wrong":wrong,"blank":blank,"score":round(score,2),"uncertain":unc})
 return {"pages":results,"warning":"پیش از استفاده رسمی، دقت تشخیص را با برگه‌های چاپ و اسکن واقعی کالیبره کنید. موارد نامطمئن نیازمند بازبینی هستند."}

@app.post("/v1/reports/excel")
def excel(rows:List[ReportRow]):
 wb=Workbook();ws=wb.active;ws.title="گزارش آزمون";ws.append(["نام دانش‌آموز","کد","آزمون","صحیح","غلط","سفید","نمره خام","تعداد سؤال"])
 for cell in ws[1]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="17233A")
 for r in rows:ws.append([r.student,r.code,r.exam,r.correct,r.wrong,r.blank,r.score,r.total])
 for col,width in {"A":24,"B":18,"C":28,"D":12,"E":12,"F":12,"G":14,"H":14}.items():ws.column_dimensions[col].width=width
 for row in ws.iter_rows():
  for cell in row:cell.alignment=Alignment(horizontal="center")
 out=io.BytesIO();wb.save(out);out.seek(0)
 return StreamingResponse(out,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="dadyar-report.xlsx"'})
