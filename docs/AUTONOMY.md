# عامل نگهداری خودکار

این عامل یک برنامه‌ی جدا از محصول است که روی Windows اجرا می‌شود. عامل مدل را دوباره آموزش نمی‌دهد؛ با لاگ‌های بیشتر، تست‌های regression، نتیجه‌ی reviewها و سابقه‌ی PRها تصمیم‌های بعدی را بهتر می‌کند.

## چیزی که همین حالا پیاده شده است

- لاگ JSON روی stdout/stderr با event، severity، environment، release و فیلدهای قابل جستجو
- حذف query string، token، OAuth state/code، موبایل، transcript و payload از Sentry و گزارش عامل
- Sentry اختیاری برای FastAPI و React و Clarity custom eventهای غیرشخصی
- correlation با `X-Request-ID` مشترک بین مرورگر و backend
- collector فقط‌خواندنی برای فید امن خود محصول، Sentry، Clarity Data Export، health و فایل‌های log محلی
- telemetry مشخص برای کنترل آپلود: چرخهٔ بازشدن، انتخاب یا لغو picker با شناسهٔ تلاش غیرشخصی، و ثبت امن کلیک روی کنترل قفل‌شده در فید محصول
- داشبورد فارسی و شواهد خارج از Git در `%LOCALAPPDATA%\BulkAddWithAi-agent`
- زمان هر اجرا به وقت تهران، مدت اجرا، روایت مرحله‌به‌مرحله، میزان قطعیت و «اقدام بعدی» به زبان ساده در داشبورد
- پایش هر سه ساعت، rollout هفت روز report-only، چهارده روز حداکثر یک fix و سپس سقف سه fix در پنجرهٔ روزانه
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

برای تشخیص خطا بدون پنل همروش، یک مقدار تصادفی و قوی را با نام `OBSERVABILITY_READ_TOKEN` در متغیرهای backend همروش قرار بده. همان مقدار را در `PRODUCTION_OBSERVABILITY_TOKEN` و آدرس کامل `https://<domain>/observability/events` را در `PRODUCTION_OBSERVABILITY_URL` وارد کن. این endpoint فقط eventهای مهم و فیلدهای allowlist‌شده را می‌دهد؛ متن لاگ، traceback، موبایل، token و payload را برنمی‌گرداند و داده‌های قدیمی‌تر از ۳۰ روز حذف می‌شوند. عامل شبانه فقط رخدادهای ۲۴ ساعت اخیر را درخواست می‌کند تا یک خطای قدیمی را هر شب دوباره تازه حساب نکند.

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

این command task را با فاصلهٔ سه‌ساعته و نقطهٔ شروع 03:17 و shortcut داشبورد روی Desktop می‌سازد. پایش هر سه ساعت انجام می‌شود، اما تغییر کد حداکثر یک بار در ۲۳ ساعت مجاز است و هفت اجرای روز اول به‌عنوان یک روز rollout حساب می‌شوند. کامپیوتر باید به برق متصل باشد و wake timer در Windows فعال باشد.

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

- سیگنال نیازمند بررسی: فقط یک نشانه داریم و هنوز معلوم نیست باگ، ورودی نامعتبر یا رفتار عادی محصول بوده است.
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

در هفت روز تقویمی نخست هیچ PR ساخته نمی‌شود و فقط گزارش جمع می‌شود. اجرای دستی و smoke test در شمارنده‌ی rollout حساب نمی‌شود.

## ماندگاری دادهٔ کاربران

عامل و Sentry مانع کار کاربران نیستند. با تنظیم فعلی، داده‌ها و فایل‌های آپلودشده تا وقتی همان کانتینر فعال است در SQLite و `/data/uploads` در دسترس‌اند و عملیات کاربر انجام می‌شود. اما بدون persistent volume، restart، جایگزینی پاد یا deploy می‌تواند draftها، سابقهٔ batchها و فایل‌های داخل کانتینر را پاک کند. محصولی که قبلاً در باسلام یا ترب منتشر شده روی همان پلتفرم باقی می‌ماند. این محدودیت با داشبورد عامل حل نمی‌شود و برای ماندگاری واقعی باید storage پایدار یا سرویس بیرونی انتخاب شود.

## لاگ همروش

stdout/stderr و پنل Logs همروش مرجع انسانی باقی می‌مانند. عامل نام پاد را hardcode نمی‌کند و با UI پنل login نمی‌کند. فید امن `/observability/events` مسیر مستقیم و مستقل از نام پاد برای خطاهای مهم backend است؛ Sentry stack trace و خطاهای frontend را تکمیل می‌کند. اگر همروش API رسمی فقط‌خواندنی ارائه کند، collector جدا نیز می‌تواند ابتدا پاد Running نسخه فعال را کشف کند.

## محدودیت Clarity و رفع بلک‌باکس UX

عدد traffic در Clarity تعداد session است، نه تعداد ویدئویی که عامل تماشا کرده باشد. Data Export API آمار تجمیعی dead click، rage click، script error و URL/device را می‌دهد، اما selector دقیق کنترل را برنمی‌گرداند. برای مسیر آپلود، frontend رویدادهای غیرشخصی `image_picker_opened`، `image_files_selected` و `image_picker_cancelled` را هم به Clarity و هم به فید امن محصول می‌فرستد. این سه رویداد یک `attempt_id` تصادفی مشترک دارند؛ اگر دست‌کم دو تلاش روی یک کنترل باز شوند ولی انتخاب یا لغو متناظر نداشته باشند، collector سیگنال قابل‌اقدام `image_picker_unresponsive` با نام همان کنترل می‌سازد. اگر کاربر روی کنترل قفل‌شده کلیک کند، `image_picker_blocked` با علت محدود `list_exists` یا `processing` ثبت می‌شود. نام فایل، محتوای عکس، مقدار input و شناسه کاربر ارسال نمی‌شود.

ماسک‌بودن مقدار inputها در recordingهای Clarity عمدی است: خود Clarity محتوای input را در همهٔ حالت‌های masking پنهان می‌کند و این رفتار برای input قابل سفارشی‌سازی نیست. عامل به‌جای مقدار کاربر، نام فنی فیلد نامعتبر و کد خطا را دریافت می‌کند؛ مثلاً شکست باسلام روی `package_weight` بدون ثبت عدد واردشده یا نام محصول گزارش می‌شود.
