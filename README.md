# دادیار AI

سامانه فارسی مدیریت آزمون و تصحیح پاسخ‌برگ با احراز هویت، مدیریت مدرسه، کلاس و دانش‌آموز، تولید PDF/QR، تصحیح تصویر/PDF و گزارش Excel.

## وضعیت پیاده‌سازی
- رابط واکنش‌گرای فارسی و راست‌چین با صفحات داشبورد، آزمون‌ها، دانش‌آموزان، پاسخ‌برگ، تصحیح، گزارش و تنظیمات.
- احراز هویت Supabase Auth و دریافت تنظیمات عمومی از `/api/config`؛ برای فعال‌شدن به متغیرهای محیطی پروژه نیاز است.
- فایل `supabase/schema.sql` با جداول هم‌خوان با رابط، سیاست‌های RLS و bucket خصوصی؛ هنوز روی پروژه‌ای اجرا نشده است.
- سرویس FastAPI برای تولید پاسخ‌برگ A4 و QR امضاشده، خواندن QR، اصلاح پرسپکتیو و تحلیل حباب‌ها.
- خروجی Excel از گزارش‌های ذخیره‌شده در Supabase.

## ساختار
- `index.html` رابط کاربری
- `api/config.js` تحویل تنظیمات عمومی Supabase و OMR از متغیرهای محیطی Vercel
- `supabase/schema.sql` جداول، RLS و Storage خصوصی
- `omr-service/main.py` موتور تولید و تصحیح پاسخ‌برگ
- `omr-service/Dockerfile` بسته‌بندی سرویس OMR

## متغیرهای محیطی Vercel
- `SUPABASE_URL` — نشانی پروژه مستقل دادیار
- `SUPABASE_ANON_KEY` یا `SUPABASE_PUBLISHABLE_KEY` — کلید عمومی قابل استفاده در مرورگر، همراه با RLS
- `OMR_API_URL` — آدرس HTTPS سرویس OMR مستقرشده

هرگز `SUPABASE_SERVICE_ROLE_KEY`، کلید secret یا `DADYAR_QR_SECRET` را در کد مرورگر یا مخزن عمومی قرار ندهید.

## اجرای سرویس OMR
در پوشه `omr-service` وابستگی‌ها را نصب و یک secret تصادفی طولانی تعریف کنید:

```bash
pip install -r requirements.txt
export DADYAR_QR_SECRET="replace-with-a-long-random-secret"
export CORS_ORIGINS="https://dadyar-ai-web.vercel.app"
uvicorn main:app --host 0.0.0.0 --port 8080
```

در Windows PowerShell برای تنظیم متغیرها از `$env:NAME="value"` استفاده کنید.

## API
- `GET /health`
- `POST /v1/sheets/generate` — ساخت PDF چندصفحه‌ای A4 با QR اختصاصی و امضاشده
- `POST /v1/sheets/inspect` — دریافت تصویر/PDF، اصلاح پرسپکتیو، خواندن QR و تحلیل پاسخ‌ها
- `POST /v1/reports/excel` — تولید فایل XLSX

## راه‌اندازی پایگاه داده
۱. یک پروژه Supabase مستقل برای دادیار ایجاد کنید.
۲. `supabase/schema.sql` را در SQL Editor همان پروژه اجرا کنید.
۳. URL و کلید publishable/anon را در Environment Variables پروژه Vercel قرار دهید.
۴. در تنظیمات Auth، دامنه سایت و redirect URLهای واقعی را مجاز کنید.

## محدودیت‌های پیش از انتشار
- اصلاح OMR و هم‌ترازی مختصات در کد بهبود یافته، اما هنوز با نمونه چاپ/اسکن واقعی کاربر اعتبارسنجی نشده است.
- صفحات `review_required` و پاسخ‌های مبهم باید پیش از ثبت نمره قطعی بازبینی انسانی شوند.
- تا زمان ساخت پروژه Supabase، اجرای SQL، تنظیم متغیرهای Vercel و استقرار مستقل Python، سامانه end-to-end فعال نیست.
- آزمون نهایی باید شامل برگه صاف، کج، چرخیده، کم‌رنگ، پاک‌شده، چندعلامتی، عکس موبایل و PDF اسکنر باشد.