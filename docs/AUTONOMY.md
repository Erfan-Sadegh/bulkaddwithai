# عامل نگهداری خودکار

این عامل یک برنامه‌ی جدا از محصول است که روی Windows اجرا می‌شود. عامل مدل را دوباره آموزش نمی‌دهد؛ با لاگ‌های بیشتر، تست‌های regression، نتیجه‌ی reviewها و سابقه‌ی PRها تصمیم‌های بعدی را بهتر می‌کند.

## چیزی که همین حالا پیاده شده است

- لاگ JSON روی stdout/stderr با event، severity، environment، release و فیلدهای قابل جستجو
- حذف query string، token، OAuth state/code، موبایل، transcript و payload از Sentry و گزارش عامل
- Sentry اختیاری برای FastAPI و React و Clarity custom eventهای غیرشخصی
- correlation با `X-Request-ID` مشترک بین مرورگر و backend
- collector فقط‌خواندنی برای فید امن خود محصول، Sentry، Clarity Data Export، health و فایل‌های log محلی
- داشبورد فارسی و شواهد خارج از Git در `%LOCALAPPDATA%\BulkAddWithAi-agent`
- rollout هفت اجرای report-only، چهارده اجرای حداکثر یک fix و سپس سقف سه fix
- worktree جدا، baseline سبز، تست قرمز روی base، تست سبز روی fix، guardrail و reviewer مستقل
- ساخت branch/PR در صورت وجود `gh`؛ بدون merge یا deploy

## راه‌اندازی یک‌باره

### ۱. ابزارها

Backend و frontend را طبق `docs/ONBOARDING.md` نصب کن. سپس مطمئن شو `codex` و `gh` در PowerShell شناخته می‌شوند و یک بار احراز هویت شده‌اند:

```powershell
codex --version
gh auth login
```

دسترسی GitHub باید فقط برای ساخت branch و PR همین repository باشد. عامل هیچ دستور merge ندارد.

### ۲. Sentry محصول

دو project در Sentry برای backend و frontend بساز. در متغیرهای همروش backend این موارد را قرار بده:

```env
APP_ENVIRONMENT=production
APP_RELEASE=build-<commit>
STRUCTURED_LOGS=true
SENTRY_DSN=...
SENTRY_TRACES_SAMPLE_RATE=0
```

برای frontend، Docker build باید `VITE_SENTRY_DSN`، `VITE_APP_ENVIRONMENT=production` و `VITE_APP_RELEASE` را به‌عنوان build argument دریافت کند. DSN کلید مدیریتی نیست، اما token خواندن Sentry هرگز وارد build نمی‌شود.

### ۳. دسترسی فقط‌خواندنی collector

در Sentry یک internal integration با scope فقط `event:read` بساز. در Clarity از Settings → Data Export یک token بساز. سپس تنظیمات را رمزگذاری‌شده برای همان کاربر Windows ذخیره کن:

```powershell
.\automation\configure-secrets.ps1
```

لازم نیست همه‌ی مقدارها را یک‌جا وارد کنی. برای ثبت یا تعویض فقط یک مورد، بدون پاک‌شدن موارد قبلی، از `-Only` استفاده کن:

```powershell
.\automation\configure-secrets.ps1 -Only CLARITY_API_TOKEN
.\automation\configure-secrets.ps1 -Only PRODUCTION_OBSERVABILITY_TOKEN
.\automation\configure-secrets.ps1 -Only PRODUCTION_OBSERVABILITY_URL
.\automation\configure-secrets.ps1 -Only PRODUCTION_HEALTH_URL
.\automation\configure-secrets.ps1 -Only GITHUB_TOKEN
```

مقدار در prompt امن PowerShell وارد می‌شود و روی صفحه نمایش داده نمی‌شود. token را در chat، فایل `.env` داخل Git یا command line قرار نده.

`SENTRY_PROJECTS` می‌تواند چند project slug جداشده با ویرگول باشد. `PRODUCTION_HEALTH_URL` باید به `/health` دامنه production اشاره کند. خالی‌گذاشتن هر مقدار همان collector را غیرفعال می‌کند و عامل اجازه ندارد به‌جای مدرک حدس بزند.

برای تشخیص خطا بدون پنل همروش، یک مقدار تصادفی و قوی را با نام `OBSERVABILITY_READ_TOKEN` در متغیرهای backend همروش قرار بده. همان مقدار را در `PRODUCTION_OBSERVABILITY_TOKEN` و آدرس کامل `https://<domain>/observability/events` را در `PRODUCTION_OBSERVABILITY_URL` وارد کن. این endpoint فقط eventهای مهم و فیلدهای allowlist‌شده را می‌دهد؛ متن لاگ، traceback، موبایل، token و payload را برنمی‌گرداند و داده‌های قدیمی‌تر از ۳۰ روز حذف می‌شوند.

برای ساخت PR یا `gh auth login` را انجام بده، یا یک fine-grained GitHub token محدود به همین repository با دسترسی `Pull requests: write` و در صورت نیاز برچسب `Issues: write` وارد کن. `GITHUB_REPOSITORY` به شکل `Erfan-Sadegh/bulkaddwithai` است. push خود branch همچنان با Git/SSH انجام می‌شود.

### ۴. اجرای آزمایشی امن

```powershell
.\automation\run-nightly.ps1 -ReportOnly
```

برای smoke بدون مصرف Codex:

```powershell
.\backend\.venv\Scripts\python.exe -m automation.runner --report-only --no-agent
```

برای آزمایش کامل و غیرمخرب چرخه‌ی «لاگ ساختگی → تست قرمز → fix → تست سبز → review → داشبورد» در repository موقت:

```powershell
.\backend\.venv\Scripts\python.exe -m automation.simulation
```

گزارش در `%LOCALAPPDATA%\BulkAddWithAi-agent\dashboard\index.html` ساخته می‌شود.

### ۵. نصب زمان‌بندی

پس از بررسی گزارش آزمایشی:

```powershell
.\automation\setup-windows.ps1
```

این command task ساعت 03:17 و shortcut داشبورد روی Desktop می‌سازد. کامپیوتر باید به برق متصل باشد و wake timer در Windows فعال باشد.

## توقف فوری و حذف

با ساخت این فایل اجرای عامل متوقف می‌شود:

```powershell
New-Item "$env:LOCALAPPDATA\BulkAddWithAi-agent\PAUSED"
```

برای ادامه، فایل را حذف کن. برای حذف task:

```powershell
.\automation\setup-windows.ps1 -Uninstall
```

## معنی وضعیت‌ها

- مشکل دیده شده: فقط signal داریم.
- مشکل بازسازی شده: تست روی base شکست خورده است.
- در تست رفع شده: gateها و reviewer سبز هستند، ولی هنوز deploy نشده است.
- آماده بررسی شما: PR ساخته شده است.
- منتشر شده؛ در حال پایش: شما merge/deploy کرده‌ای ولی دوره مشاهده کامل نیست.
- تأیید production: حداقل سه روز و ۱۰۰ مشاهده‌ی مرتبط بدون تکرار مشکل ثبت شده است. این وضعیت خودکار صادر نمی‌شود مگر داده‌ی کافی قابل انتساب وجود داشته باشد.

## چک‌لیست صبحگاهی برای صاحب محصول

1. shortcut با نام `BulkAddWithAI Agent Dashboard` روی Desktop را باز کن.
2. بالاترین اجرای امروز را ببین. اگر وضعیت اجرا `failed` است، فقط متن «علت توقف» را برای بررسی نگه دار؛ چیزی را merge نکن.
3. بخش «سلامت منابع» را ببین. `ok` یعنی داده واقعاً خوانده شده؛ «تنظیم نشده» یعنی آن منبع هیچ مدرکی نداده و عامل هم از آن حدس نزده است.
4. اگر فقط کارت «دیده‌شده» وجود دارد، عکس یا تست اصلاح هنوز نداریم و اقدامی از تو لازم نیست.
5. اگر کارت «آماده بررسی» و لینک PR دارد، قبل/بعد، نتیجه‌ی تست قرمز و سبز، نظر reviewer و ریسک بازگشت را بخوان. فقط اگر توضیح رفتاری برایت قابل‌فهم و شواهد کامل بود PR را برای merge انسانی قبول کن.
6. پس از deploy دستی، کارت تا سه روز یا ۱۰۰ مشاهده در حالت پایش می‌ماند. «رفع‌شده در تست» را با «تأیید production» یکی ندان.

در هفت اجرای شبانه‌ی نخست هیچ PR ساخته نمی‌شود و فقط گزارش جمع می‌شود. اجرای دستی و smoke test در شمارنده‌ی rollout حساب نمی‌شود.

## لاگ همروش

stdout/stderr و پنل Logs همروش مرجع انسانی باقی می‌مانند. عامل نام پاد را hardcode نمی‌کند و با UI پنل login نمی‌کند. فید امن `/observability/events` مسیر مستقیم و مستقل از نام پاد برای خطاهای مهم backend است؛ Sentry stack trace و خطاهای frontend را تکمیل می‌کند. اگر همروش API رسمی فقط‌خواندنی ارائه کند، collector جدا نیز می‌تواند ابتدا پاد Running نسخه فعال را کشف کند.
