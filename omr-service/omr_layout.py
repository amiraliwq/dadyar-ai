import io, json, uuid, qrcode
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

W,H=A4
FONT_PATH="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
try:
    pdfmetrics.registerFont(TTFont("DadyarFaOMR",FONT_PATH))
    FONT="DadyarFaOMR"
except Exception:
    FONT="Helvetica"

def fa(text):
    text=str(text or "")
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text

def draw_sheet(c,batch,student):
    # One geometry definition is shared with scan_bubbles in main.py.
    columns=max(1,min(6,int(getattr(batch,"columns",6) or 6)))
    n=int(batch.question_count)
    rows_per_col=(n+columns-1)//columns
    if rows_per_col>50:
        raise ValueError("حداکثر ۵۰ سؤال در هر ستون و ۶ ستون مجاز است.")
    margin=15*mm
    c.setFillColorRGB(0,0,0)
    c.setStrokeColorRGB(0,0,0)
    # Four circular targets with a solid square center for robust contour detection.
    centers=[(25*mm,H-25*mm),(W-25*mm,H-25*mm),
             (W-25*mm,25*mm),(25*mm,25*mm)]
    for x,y in centers:
        c.setLineWidth(1.2); c.circle(x,y,4.2*mm,stroke=1,fill=0)
        c.setLineWidth(.8); c.circle(x,y,2.5*mm,stroke=1,fill=0)
        c.rect(x-2*mm,y-2*mm,4*mm,4*mm,stroke=0,fill=1)

    sheet_id=str(uuid.uuid4())
    qrdata={"sheet_id":sheet_id,"exam_id":str(batch.exam_id),
            "student_id":str(student.student_id),"student_code":student.code,
            "question_count":n,"columns":columns}
    from main import signed_qr
    qr=qrcode.QRCode(box_size=7,border=2,error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(signed_qr(qrdata)); qr.make(fit=True)
    qrb=io.BytesIO(); qr.make_image(fill_color="black",back_color="white").save(qrb,format="PNG"); qrb.seek(0)

    # Compact heading and independently bordered identity / code panels.
    c.setFont(FONT,14); c.drawCentredString(W/2,H-19*mm,fa(batch.school_name or ""))
    c.setFont(FONT,10); c.drawCentredString(W/2,H-25*mm,fa(batch.exam_title or "پاسخ‌برگ آزمون"))
    c.setFont(FONT,7); c.drawCentredString(W/2,H-30*mm,fa("پاسخ‌برگ هوشمند دادیار"))
    # Student identity panel
    ix,iy,iw,ih=55*mm,H-69*mm,138*mm,32*mm
    c.setLineWidth(.8); c.rect(ix,iy,iw,ih,stroke=1,fill=0)
    c.setFont(FONT,8); c.drawRightString(ix+iw-4*mm,iy+ih-6*mm,fa("مشخصات دانش‌آموز"))
    c.setFont(FONT,7)
    c.drawRightString(ix+iw-4*mm,iy+ih-13*mm,fa("نام: "+str(student.name)))
    c.drawRightString(ix+iw-4*mm,iy+ih-20*mm,fa("کد دانش‌آموزی: "+str(student.code)))
    c.drawRightString(ix+iw-4*mm,iy+ih-27*mm,fa("کلاس: ........................   تاریخ: ........................"))
    # QR and unique code area
    qx,qy,qs=18*mm,H-67*mm,29*mm
    c.rect(qx-2*mm,qy-2*mm,qs+4*mm,qs+8*mm,stroke=1,fill=0)
    c.drawImage(ImageReader(qrb),qx,qy,width=qs,height=qs,mask="auto")
    c.setFont(FONT,5.5); c.drawCentredString(qx+qs/2,qy-5*mm,fa("کد یکتای برگه"))
    c.setFont("Helvetica",5); c.drawCentredString(qx+qs/2,qy-7.3*mm,sheet_id[:12])

    # Instructions with explicit correct / incorrect examples.
    bx,by,bw,bh=17*mm,H-91*mm,176*mm,15*mm
    c.rect(bx,by,bw,bh,stroke=1,fill=0)
    c.setFont(FONT,7); c.drawRightString(bx+bw-3*mm,by+bh-5*mm,fa("راهنما: برای هر سؤال فقط یک گزینه را کاملاً با مداد مشکی پر کنید."))
    c.setFont(FONT,6); c.drawRightString(bx+bw-3*mm,by+3*mm,fa("درست: ● پرکردن کامل حباب     نادرست: خط‌زدن، تیک‌زدن یا علامت‌گذاری چند گزینه"))
    c.setFont(FONT,7); c.drawString(bx+4*mm,by+4*mm,"A   B   C   D")

    # Answer grid: right-to-left columns, up to 50 rows in each column.
    top=H-101*mm
    row_step=3.45*mm
    block_width=170*mm/columns
    qx0=190*mm
    offsets=[8.0*mm,12.2*mm,16.4*mm,20.6*mm]
    bubble_r=1.35*mm
    # Header baseline and column separators.
    c.setLineWidth(.65); c.line(17*mm,top+4*mm,193*mm,top+4*mm)
    c.setFont(FONT,6.3)
    for col in range(columns):
        qx=qx0-col*block_width
        c.drawRightString(qx,top+1*mm,fa("سؤال"))
        for oi,off in enumerate(offsets):
            c.drawCentredString(qx-off,top+1*mm,fa("۱۲۳۴"[oi]))
        if col:
            sx=qx+3*mm
            c.setLineWidth(.35); c.line(sx,top+3*mm,sx,top-rows_per_col*row_step+1*mm)
    # Left calibration strip; one black bar per printed question row.
    strip_x=18.5*mm
    for row in range(rows_per_col):
        y=top-row*row_step
        c.rect(strip_x,y-1.0*mm,1.8*mm,2.0*mm,stroke=0,fill=1)
    for q in range(1,n+1):
        col=(q-1)//rows_per_col
        row=(q-1)%rows_per_col
        qx=qx0-col*block_width
        y=top-row*row_step
        c.setFont(FONT,6.1); c.drawRightString(qx,y-1.8*mm,fa(str(q)))
        for off in offsets:
            c.setLineWidth(.65); c.circle(qx-off,y,bubble_r,stroke=1,fill=0)
    # Footer stays within the safe print zone.
    c.setLineWidth(.5); c.line(17*mm,15*mm,193*mm,15*mm)
    c.setFont(FONT,5.5); c.drawCentredString(W/2,10*mm,fa("A4 · چاپ در مقیاس ۱۰۰٪ · تمام نشانگرهای گوشه در تصویر اسکن دیده شوند"))
    return qrdata
