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
- پایش هر سه ساعت و بازسازی خودکار حداکثر پنج مشکل با regression test در worktree جدا
- worktree جدا، baseline سبز، تست قرمز روی base، تست سبز روی fix، guardrail و reviewer مستقل
- تشخیص و اثبات خودکار است؛ اصلاح، branch و PR فقط پس از دستور صریح انسان انجام می‌شود و merge/deploy خودکار وجود ندارد

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

این command task را با فاصلهٔ سه‌ساعته و نقطهٔ شروع 03:17 و shortcut داشبورد روی Desktop می‌سازد. هر اجرا می‌تواند سیگنال‌ها را تحلیل و حداکثر پنج مشکل را با تست قرمز در worktree جدا اثبات کند، اما اجازهٔ تغییر کد محصول، ساخت branch یا PR ندارد. برای اصلاح باید انسان همان مورد را صریحاً تأیید کند. کامپیوتر باید به برق متصل باشد و wake timer در Windows فعال باشد.

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
4. اگر کارت «دیده‌شده» وجود دارد، سیگنال پیدا شده ولی هنوز با تست اثبات نشده است.
5. اگر کارت «با تست بازسازی شد» وجود دارد، مشکل اثبات شده ولی هیچ اصلاحی انجام نشده است؛ اگر می‌خواهی رفع شود، دستور اصلاح همان مورد را بده. سپس TDD، تست کامل، review مستقل و PR اجرا می‌شوند.
6. پس از deploy دستی، کارت تا سه روز یا ۱۰۰ مشاهده در حالت پایش می‌ماند. «رفع‌شده در تست» را با «تأیید production» یکی ندان.

اجرای زمان‌بندی‌شده هیچ‌وقت خودسرانه PR نمی‌سازد. محدودیت زمانی هفت‌روزه حذف شده است: تشخیص و تست بازسازی از اولین اجرا فعال‌اند و اصلاح همیشه نیازمند دستور صریح انسان است.

## ماندگاری دادهٔ کاربران

عامل و Sentry مانع کار کاربران نیستند. با تنظیم فعلی، داده‌ها و فایل‌های آپلودشده تا وقتی همان کانتینر فعال است در SQLite و `/data/uploads` در دسترس‌اند و عملیات کاربر انجام می‌شود. اما بدون persistent volume، restart، جایگزینی پاد یا deploy می‌تواند draftها، سابقهٔ batchها و فایل‌های داخل کانتینر را پاک کند. محصولی که قبلاً در باسلام یا ترب منتشر شده روی همان پلتفرم باقی می‌ماند. این محدودیت با داشبورد عامل حل نمی‌شود و برای ماندگاری واقعی باید storage پایدار یا سرویس بیرونی انتخاب شود.

## لاگ همروش

stdout/stderr و پنل Logs همروش مرجع انسانی باقی می‌مانند. عامل نام پاد را hardcode نمی‌کند و با UI پنل login نمی‌کند. فید امن `/observability/events` مسیر مستقیم و مستقل از نام پاد برای خطاهای مهم backend است؛ Sentry stack trace و خطاهای frontend را تکمیل می‌کند. اگر همروش API رسمی فقط‌خواندنی ارائه کند، collector جدا نیز می‌تواند ابتدا پاد Running نسخه فعال را کشف کند.

## محدودیت Clarity و رفع بلک‌باکس UX

عدد traffic در Clarity تعداد session است، نه تعداد ویدئویی که عامل تماشا کرده باشد. Data Export API آمار تجمیعی dead click، rage click، script error و URL/device را می‌دهد، اما selector دقیق کنترل را برنمی‌گرداند. برای مسیر آپلود، frontend رویدادهای غیرشخصی `image_picker_opened`، `image_files_selected` و `image_picker_cancelled` را هم به Clarity و هم به فید امن محصول می‌فرستد. این سه رویداد یک `attempt_id` تصادفی مشترک دارند؛ اگر دست‌کم دو تلاش روی یک کنترل باز شوند ولی انتخاب یا لغو متناظر نداشته باشند، collector سیگنال قابل‌اقدام `image_picker_unresponsive` با نام همان کنترل می‌سازد. اگر کاربر روی کنترل قفل‌شده کلیک کند، `image_picker_blocked` با علت محدود `list_exists` یا `processing` ثبت می‌شود. نام فایل، محتوای عکس، مقدار input و شناسه کاربر ارسال نمی‌شود.

Clarity Data Export ممکن است `429` بدهد. collector خطاهای موقت `429` و `5xx` و قطع شبکه را سه بار retry می‌کند، نتیجه موفق را ۱۵۰ دقیقه cache می‌کند و هنگام rate limit فقط از آخرین cache یا گزارش واقعی حداکثر ۲۴ ساعت گذشته استفاده می‌کند. داشبورد در این حالت منبع را صریحاً `cached` همراه سن داده نشان می‌دهد؛ داده قدیمی هرگز به‌عنوان خواندن زنده پنهان نمی‌شود و خطای احراز هویت `401/403` با cache پوشانده نمی‌شود.

کنترل‌های اصلی محصول یک funnel امن مشترک نیز دارند: `ui_action_started` و یکی از `ui_action_accepted`، `ui_action_blocked` یا `ui_action_failed` با `attempt_id` مشترک. این قرارداد روی آپلود، ساخت لیست، اتصال باسلام، ثبت در باسلام و ارسال ترب فعال است. علت‌ها فقط enumهای محدود `validation`، `state`، `network`، `server` یا `unknown` هستند و متن خطا یا دادهٔ کاربر پذیرفته نمی‌شود. اگر دست‌کم دو تلاش روی یک کنترل بیش از پنج دقیقه بدون outcome بمانند، collector رویداد مشتق‌شدهٔ `ui_action_unresponsive` می‌سازد؛ تلاش‌های دارای outcome هرگز dead/unresponsive شمرده نمی‌شوند. rage click نیز با `ui_rage_click` و نام دقیق همان کنترل ثبت می‌شود.

برای توقف‌های اعتبارسنجی، نام فیلد نیز فقط به‌صورت enum امن مثل `stock` یا `package_weight_grams` ثبت می‌شود؛ مقدار input، نام محصول و متن کاربر همچنان ارسال نمی‌شود. بنابراین ماسک‌ماندن input در recordingهای Clarity مانع تشخیص این نیست که کاربر روی «وزن با بسته‌بندی» یا «موجودی» گیر کرده است. تشخیص rage click بر پایهٔ `pointerdown` است تا تلاش‌های تکراری روی دکمهٔ disabled نیز دیده شوند.

برای کنترل‌های غیرآپلود، هر `pointerdown` فقط یک مهلت محلی ۱٫۵ ثانیه‌ای ایجاد می‌کند. اگر handler همان کنترل با `beginObservedAction` شروع شود، مهلت لغو و هیچ رخداد اضافی ذخیره نمی‌شود؛ اگر handler اصلاً شروع نشود، `ui_dead_click` با نام allowlist‌شدهٔ همان کنترل ثبت می‌شود. در نتیجه یک دکمهٔ disabled یا overlay خراب نیز بدون نیاز به دیدن recording قابل‌شناسایی است. کنترل عکس قرارداد تخصصی picker خودش را دارد و از این تشخیص عمومی مستثناست تا false positive ساخته نشود.

فایل `automation/ux_contract.json` منبع ممیزی پوشش است. هر کنترل باید هم‌زمان wiring قابل مشاهده در UI، lifecycle در handler، allowlist frontend و allowlist backend داشته باشد. collector در هر اجرا این لایه‌ها را جدا بررسی می‌کند و حذف یا اضافه‌شدن ناقص هر کنترل را با `ux_observability_gap` گزارش می‌دهد. این ممیزی شامل باکس و دکمهٔ عکس، ساخت لیست، اتصال و ثبت باسلام، ارسال ترب، ضبط صدا، تغییر مسیر، حذف و جداسازی عکس و شروع محصولات جدید است.

خطاهای runtime رابط کاربری فقط با enum امن `frontend_runtime_failed` و کد `script_error` یا `unhandled_rejection` ثبت می‌شوند. تنها سطح `catalog` یا `admin` همراه آن است؛ message، stack، URL، query string و مقدار input به endpoint فرستاده یا پذیرفته نمی‌شود. این feed مستقل از Sentry است تا نبود build secret برای `VITE_SENTRY_DSN` تشخیص پایه را از کار نیندازد.

هر اجرای سه‌ساعته یک browser probe فقط‌خواندنی نیز روی frontend واقعی production اجرا می‌کند. probe در viewport موبایل و دسکتاپ، بازشدن سند، خطای page/console، شکست فایل‌های اصلی، وجود shell و دو CTA آغازین و overflow افقی را بررسی و `production-mobile.png` و `production-desktop.png` را داخل پوشه همان run ذخیره می‌کند. درخواست‌های bootstrap seller و observability داخل مرورگر mock می‌شوند، analytics بیرونی با پاسخ خالی جایگزین می‌شود و هر POST/PATCH/PUT/DELETE ناشناخته abort و به‌عنوان `browser_mutation_attempt` گزارش می‌شود؛ بنابراین probe اجازه تغییر داده production یا عملیات باسلام/ترب ندارد.

همان probe سپس با backend کاملاً ساختگی مسیر باسلام را باز می‌کند، file chooser واقعی مرورگر را دریافت می‌کند، یک PNG یک‌پیکسلی ساختگی انتخاب می‌کند، نمایش عکس، فعال‌شدن دکمه ساخت لیست و رسیدن به کارت بازبینی محصول را می‌سنجد و تصویرهای `production-mobile-journey.png` و `production-desktop-journey.png` را می‌سازد. endpointهای batch، upload، job، item و category در خود مرورگر mock هستند؛ هیچ AI، باسلام، ترب یا داده production مصرف یا تغییر نمی‌کند.

ماسک‌بودن مقدار inputها در recordingهای Clarity عمدی است: خود Clarity محتوای input را در همهٔ حالت‌های masking پنهان می‌کند و این رفتار برای input قابل سفارشی‌سازی نیست. عامل به‌جای مقدار کاربر، نام فنی فیلد نامعتبر و کد خطا را دریافت می‌کند؛ مثلاً شکست باسلام روی `package_weight` بدون ثبت عدد واردشده یا نام محصول گزارش می‌شود.
