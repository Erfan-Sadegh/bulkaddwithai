# Bulk Add With AI

MVP محلی برای ساخت کاتالوگ محصول از عکس و ویس فروشنده‌های حضوری.

- `backend`: FastAPI + SQLite + AvalAI/fake AI provider
- `frontend`: React + Vite + TypeScript با UI راست‌به‌چپ و فونت Vazirmatn

## تجربه کاربر

کاربر با انتخاب فروشنده یا ساخت بچ درگیر نمی‌شود. اپ پشت‌صحنه یک فضای کاری محلی می‌سازد و صفحه اول مستقیم روی کار اصلی است:

1. مسیر باسلام یا ترب را انتخاب کن.
2. عکس محصولات را اضافه کن.
3. اگر لازم بود، ویس ضبط کن.
4. دکمه «ساخت لیست محصولات» را بزن.
5. نام، توضیح و قیمت را در صفحه بازبینی اصلاح کن.
6. در باسلام، اطلاعات لازم مثل موجودی، وزن و زمان آماده‌سازی را کامل کن و مستقیم در غرفه ثبت کن.
7. در ترب، اسم فروشگاه و شماره تماس را وارد کن تا درخواست برای بررسی ادمین ذخیره شود.

در مسیر ترب، اسم فروشگاه و شماره تماس لازم است چون اضافه کردن نهایی فعلا با بررسی ادمین انجام می‌شود. اگر کاربر بدون ویس لیست بسازد و بعدا ببیند اطلاعات کامل نیست، می‌تواند همان‌جا صدا ضبط کند و همان لیست را دوباره با AI بازبینی کند.

ادمین ترب از مسیر `/admin` باز می‌شود. ورود فقط با `ADMIN_PASSWORD` است. ادمین `shop_id` و `base_product_rk` محصولات ترب را وارد می‌کند و بعد bulk add را می‌زند.

## اجرای سریع

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

در ترمینال دوم:

```powershell
cd frontend
npm install
npm run dev
```

اپ روی `http://127.0.0.1:5173` بالا می‌آید.

## AI واقعی

اگر `AVALAI_API_KEY` خالی باشد، backend از provider جعلی استفاده می‌کند تا کل جریان بدون هزینه API تست شود. برای AvalAI واقعی:

```env
AI_PROVIDER=avalai
AVALAI_API_KEY=...
AVALAI_BASE_URL=https://api.avalai.ir/v1
AVALAI_VISION_MODEL=gpt-5.4
AVALAI_TEXT_MODEL=gpt-5.4
AVALAI_STT_MODEL=gpt-4o-mini-transcribe
```

## تست‌ها

```powershell
cd backend
$env:TMP=(Resolve-Path .pytest-tmp).Path
$env:TEMP=$env:TMP
pytest --basetemp .pytest-tmp\run
```

```powershell
cd frontend
npm test
npm run build
npm run e2e
```

جزئیات بیشتر در [docs/ONBOARDING.md](docs/ONBOARDING.md).

## Production Image

برای production یک image واحد ساخته می‌شود که frontend build شده و backend FastAPI را با هم سرو می‌کند.

روی GitHub فقط build/push انجام می‌دهیم و deploy نداریم. بعد از هر push، workflow با نام `Build image` اجرا می‌شود و image را در GitHub Container Registry می‌گذارد.

آدرس image برای دارکوب:

```text
ghcr.io/<github-owner>/<repo-name>
```

تگ پیشنهادی برای دارکوب:

```text
build-<short-commit-sha>
```

مثال:

```text
Image: ghcr.io/my-org/bulkaddwithai
Tag: build-a1b2c3d
```

برای پیدا کردن tag دقیق:

1. در GitHub به تب `Actions` برو.
2. آخرین workflow موفق `Build image` را باز کن.
3. commit همان run را بردار.
4. در دارکوب image را با tag `build-<7 کاراکتر اول commit>` ثبت کن.

متغیرهای لازم runtime در دارکوب:

```env
AI_PROVIDER=avalai
AVALAI_API_KEY=...
AVALAI_BASE_URL=https://api.avalai.ir/v1
AVALAI_VISION_MODEL=gpt-5.4
AVALAI_TEXT_MODEL=gpt-5.4
AVALAI_STT_MODEL=gpt-4o-mini-transcribe
DATABASE_URL=sqlite:////data/catalog.db
UPLOAD_DIR=/data/uploads
FRONTEND_DIST_DIR=/app/frontend-dist
FRONTEND_URL=https://your-production-domain
BASALAM_CLIENT_ID=...
BASALAM_CLIENT_SECRET=...
BASALAM_REDIRECT_URI=https://your-production-domain/integrations/basalam/callback
BASALAM_SCOPES=vendor.profile.read vendor.product.read vendor.product.write customer.profile.read
BASALAM_AUTH_URL=https://basalam.com/accounts/sso
BASALAM_TOKEN_URL=https://auth.basalam.com/oauth/token
BASALAM_API_BASE_URL=https://openapi.basalam.com
BASALAM_LEGACY_CORE_BASE_URL=https://core.basalam.com
BASALAM_CATEGORY_CACHE_TTL_SECONDS=86400
BASALAM_CATEGORY_SUGGESTION_THRESHOLD=0.62
ADMIN_PASSWORD=...
TOROB_BULK_ADD_URL=https://api.torob.com/panel/offline-shop/product-in-store/searched/bulk-add/
TOROB_BULK_ADD_KEY=...
TOROB_AUTH_HEADER_NAME=Authorization
TOROB_AUTH_HEADER_VALUE=...
```

برای SQLite و فایل‌های آپلود، مسیر `/data` باید persistent volume باشد؛ وگرنه با restart داده‌ها از بین می‌روند.

برای اتصال باسلام، `BASALAM_REDIRECT_URI` باید در پنل توسعه‌دهنده باسلام دقیقا با همین مقدار ثبت شده باشد و scope `vendor.product.write` لازم است. دسته‌بندی محصول‌ها از API باسلام پیشنهاد داده می‌شود و اگر دسته‌بندی یک محصول مطمئن نباشد، همان محصول با پیام قابل اصلاح متوقف می‌شود. محصول ناقص قبل از upload/create متوقف می‌شود؛ یعنی قیمت، موجودی، زمان آماده‌سازی، وزن، وزن با بسته‌بندی، تعداد هر فروش، دسته‌بندی و عکس باید کامل باشند.

اگر package در GHCR private بود، دارکوب باید image pull secret/PAT داشته باشد. ساده‌ترین مسیر برای MVP این است که package را در GitHub Packages عمومی کنی یا برای دارکوب token read-only بسازی.
