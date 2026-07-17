# راهنمای جامع مهندسی و طراحی BulkAddWithAI

این سند مرجع واحد برای فهم محصول، کد، داده، جریان‌های کسب‌وکار، هوش مصنوعی، انتشار، مشاهده‌پذیری و عامل نگه‌داری خودکار است. هرجا میان «چیزی که مطلوب است» و «چیزی که اکنون در کد وجود دارد» تفاوت باشد، وضعیت فعلی صریح نوشته شده است.

## ۱. قبل از ورود به کد: این سیستم اصلاً از چه تکه‌هایی ساخته شده است؟

ابتدا بدون اصطلاحات فنی: کاربر در مرورگر عکس و ویس می‌دهد. مرورگر این داده‌ها را به برنامه‌ای روی سرور می‌فرستد. برنامه سرور فایل‌ها و اطلاعات را نگه می‌دارد، برای فهم عکس و صدا به سرویس AI درخواست می‌زند و نتیجه را به مرورگر برمی‌گرداند. اگر کاربر بخواهد، همان سرور با باسلام یا ترب صحبت می‌کند. چند ابزار دیگر نیز فقط سلامت و خطاهای این رفت‌وبرگشت را مشاهده می‌کنند.

### ۱.۱ دیاگرام کل سیستم و راه خواندن آن

در تمام دیاگرام‌های این سند:

- کادر یعنی یک component، process، storage یا سرویس مستقل.
- فلش `---->` یعنی مبدأ چیزی را به مقصد می‌فرستد یا تابع مقصد را صدا می‌زند.
- فلش نقطه‌چین `....>` یعنی مسیر اصلی کسب‌وکار نیست و فقط telemetry یا monitoring می‌فرستد.
- عدد روی فلش ترتیب معمول اتفاق‌ها را نشان می‌دهد.
- نام‌ها داخل دیاگرام انگلیسی‌اند تا در نمایش راست‌به‌چپ خطوط به‌هم نریزند؛ توضیح هر شماره بلافاصله زیر آن فارسی است.

```text
                                      THIRD-PARTY SERVICES
                          +----------------------------------------+
                          |  +----------+  +---------+  +-------+ |
                          |  | AvalAI   |  | Basalam |  | Torob | |
                          |  +----^-----+  +----^----+  +---^---+ |
                          +-------|-------------|-----------|------+
                                  | (5)         | (6)       | (7)
                                  |             |           |
+---------+   (1)    +------------+-------------+-----------+---------+
|  User   | -------> | Browser: React UI                            |
+---------+          +----------------------+-------------------------+
                            | (2) HTTP       ^ (4) JSON response
                            v                |
                     +------+----------------+------+
                     | Uvicorn + FastAPI Backend    |
                     | validation + business logic |
                     +------+-------------+---------+
                            | (3a)         | (3b)
                            v              v
                      +-----+-----+   +----+---------+
                      |  SQLite  |   | Upload Files |
                      | database |   | images/audio |
                      +-----------+   +--------------+

 Browser ............> Clarity / Frontend Sentry       (8)
 Backend ............> Logs / Backend Sentry            (9)
 Local Agent ........> Logs + Sentry + Clarity + API   (10, read-only)
```

معنای گام‌ها:

1. کاربر با UI تعامل می‌کند؛ مثلاً دو عکس انتخاب می‌کند.
2. React با HTTP یک request به backend می‌فرستد.
3. backend metadata را در SQLite و خود فایل را در filesystem ذخیره می‌کند. عکس داخل ستون database قرار نمی‌گیرد؛ مسیر عکس در DB قرار می‌گیرد.
4. backend یک response ساختاریافته، معمولاً JSON، به frontend می‌دهد و React صفحه را update می‌کند.
5. هنگام پردازش، backend با AvalAI صحبت می‌کند؛ browser مستقیماً کلید AI را نمی‌بیند.
6. برای OAuth، دسته‌بندی و ثبت محصول، backend با API باسلام صحبت می‌کند.
7. برای ارسال گروهی ترب، backend با API ترب صحبت می‌کند.
8. frontend فقط رخدادهای غیرحساس UX و خطاها را برای مشاهده‌پذیری می‌فرستد.
9. backend log ساختاریافته و exception امن می‌فرستد.
10. عامل محلی این evidenceها را فقط می‌خواند و در اجرای زمان‌بندی‌شده اجازه تغییر production ندارد.

### ۱.۲ تعریف ساده و فنی اجزای پایه

#### Client و server

**ساده:** client همان چیزی است که درخواست می‌کند؛ server چیزی است که پاسخ می‌دهد. در این محصول browser معمولاً client و FastAPI server است.

**فنی:** client و server «نقش» هستند، نه الزاماً دو دستگاه. backend ما وقتی از باسلام اطلاعات می‌گیرد خودش client باسلام می‌شود. یک process می‌تواند نسبت به browser سرور و نسبت به AvalAI کلاینت باشد.

#### Frontend

**ساده:** صفحه، دکمه، input و رفتار قابل مشاهده کاربر.

**فنی:** برنامه React/TypeScript در browser اجرا می‌شود. state موقت UI را نگه می‌دارد، input را پیش‌اعتبارسنجی می‌کند و با `fetch` به API درخواست می‌زند. frontend نباید secretهای backend را داشته باشد.

#### Backend

**ساده:** بخش پشت‌صحنه که تصمیم واقعی، ذخیره‌سازی و ارتباط با سرویس‌های بیرونی را انجام می‌دهد.

**فنی:** یک برنامه Python/FastAPI است. request را parse و validate می‌کند، business rule را اجرا می‌کند، transaction DB را مدیریت می‌کند و integration client را صدا می‌زند. frontend validation برای UX است؛ backend validation مرز اعتماد است.

#### API و endpoint

**ساده:** API فهرست درهایی است که برنامه‌های دیگر اجازه دارند از آن‌ها وارد شوند. endpoint یک در مشخص است.

**فنی:** endpoint ترکیب یک HTTP method و path است. مثلاً `POST /batches/42/process` یعنی «برای batch شماره ۴۲ یک پردازش را شروع کن». همان path با method دیگری می‌تواند معنای دیگری داشته باشد.

#### Database و filesystem

**ساده:** database اطلاعات مرتب و قابل جست‌وجو را نگه می‌دارد؛ filesystem فایل‌های بزرگ مثل عکس و صدا را.

**فنی:** SQLite داده رابطه‌ای را در `catalog.db` ذخیره می‌کند. فایل binary در `UPLOAD_DIR` نوشته می‌شود و جدول Asset فقط path، checksum، MIME type و metadata را نگه می‌دارد. این دو storage transaction مشترک واقعی ندارند؛ بعداً اثرش را بررسی می‌کنیم.

#### Process، service و provider

- **Process سیستم‌عامل:** نمونه درحال اجرای یک برنامه؛ مثلاً process مربوط به Uvicorn.
- **Service در معماری:** بخشی از کد که یک مسئولیت کسب‌وکار دارد؛ مثلاً `run_processing_job`.
- **External service:** سامانه بیرونی مانند AvalAI یا باسلام.
- **Provider:** implementation قابل تعویض یک قرارداد؛ `FakeAiProvider` و `AvalAiProvider` هر دو قرارداد `AiProvider` را اجرا می‌کنند.

### ۱.۳ واژه‌های دامنه محصول

| واژه | توضیح ساده | تعریف دقیق در کد |
|---|---|---|
| Seller | صاحب یک نوبت کاری | row جدول `sellers` و ریشه ownership؛ هنوز account احراز هویت‌شده کامل نیست |
| Workspace | برچسب همان فضای مرورگر | UUID در localStorage برای جلوگیری از قاطی‌شدن context؛ مرز امنیتی مستقل نیست |
| Batch | یک پوشه کاری برای یک بار ساخت لیست | aggregate شامل asset، processing job، item و publish context |
| Asset | یک ورودی عکس یا صدا | row شامل path و metadata فایل متعلق به یک batch |
| BatchItem | یک محصول پیشنهادی و قابل ویرایش | داده مرکزی محصول به‌اضافه link به یک یا چند asset |
| Draft | چیزی که کاربر تایپ کرده ولی ممکن است هنوز کامل save نشده باشد | state و localStorage frontend به تفکیک platform و batch |
| Job | کار زمان‌بر با وضعیت قابل polling | `ProcessingJob` یا `PublishJob` با status و step |
| PlatformConnection | اجازه صحبت با غرفه باسلام | OAuth token و هویت غرفه، فقط سمت backend |
| Journey | کل یک سناریوی چندمرحله‌ای | transitionهای مرتبط با یک `journey_id`، مثل redirect و restore |
| Invariant | قانونی که همیشه باید درست بماند | شرطی مانند «OAuth نباید عکس و draft را از بین ببرد» |
| Signal | یک مشاهده، نه لزوماً اثبات باگ | داده امن از log/Sentry/Clarity/Black Box |
| Candidate | مسئله‌ای که ارزش بررسی دارد | یک یا چند Signal گروه‌بندی‌شده و رتبه‌بندی‌شده |
| Regression test | ماشین اثبات باگ | تستی که روی نسخه معیوب قرمز و بعد از fix سبز است |

## ۲. مسئله کسب‌وکار، مرز دامنه و invariantها

### ۲.۱ محصول چه درد واقعی را حل می‌کند؟

فروشنده معمولاً چند عکس دارد و اطلاعات محصول را شفاهی بهتر از فرم طولانی بیان می‌کند. سیستم باید اطلاعات غیرساختاریافته را به catalog ساختاریافته تبدیل کند؛ سپس اجازه دهد انسان اشتباه AI را اصلاح کند و محصول را به پلتفرم مقصد ببرد.

```text
Unstructured Input       Structured Draft        Human-owned Result
+----------------+       +----------------+       +-------------------+
| photos + voice | ----> | AI suggestions | ----> | reviewed products |
+----------------+       +----------------+       +---------+---------+
                                                           |
                                              +------------+------------+
                                              v                         v
                                        +-----------+             +-----------+
                                        | Basalam   |             | Torob     |
                                        | publish   |             | request   |
                                        +-----------+             +-----------+
```

نکته طراحی: AI پیشنهاددهنده است، نه مالک نهایی داده. به همین دلیل بعد از دخالت کاربر، حفظ edit او مهم‌تر از خروجی تازه AI است.

### ۲.۲ invariant با مثال

Invariant یک requirement معمولی مثل «دکمه آبی باشد» نیست؛ قانونی است که نقضش اعتماد یا صحت سیستم را می‌شکند.

| invariant | نمونه درست | نمونه نقض |
|---|---|---|
| جداسازی پلتفرم | category باسلام فقط در platform data باسلام است | تغییر مسیر به ترب category باسلام را وارد submission کند |
| جداسازی seller/workspace | غرفه متصل‌شده متعلق به همان context است | seller شماره ۲ token غرفه seller شماره ۱ را بگیرد |
| حفظ ورودی در failure | AI fail می‌شود ولی عکس و ویس باقی می‌ماند | exception باعث حذف batch یا upload شود |
| حفظ edit انسانی | AI فقط وزن خالی را پر می‌کند | عنوان ویرایش‌شده کاربر overwrite شود |
| خطای امن | «اتصال برقرار نشد؛ دوباره تلاش کن» | response خام provider یا token نمایش داده شود |
| عدم side effect زودهنگام | ابتدا همه itemها validate می‌شوند | قبل از کشف نقص item سوم، دو محصول بیرونی ساخته شوند |
| جلوگیری از تکرار | double-click همان job فعال را برگرداند | دو publish همزمان محصول تکراری بسازند |

این قانون‌ها باید در سه جا دیده شوند: کد service، تست regression/integration و telemetry که نقض production را نشان دهد.

## ۳. نقشه کامل repository و روش پیدا کردن کد

### ۳.۱ repository چیست؟

Repository فقط «یک پوشه» نیست؛ تاریخچه version-controlled کد، تست، تنظیمات build و مستندات است. Git commitها تغییرات آن را ثبت می‌کنند. چیزهایی مثل `.venv`، `node_modules`، database محلی و upload واقعی generated یا sensitive هستند و نباید commit شوند.

### ۳.۲ درخت فایل‌های پروژه

```text
BulkAddWithAi/
|
+-- backend/                         Python application
|   +-- app/
|   |   +-- __init__.py              marks app as a Python package
|   |   +-- main.py                  creates FastAPI app; routes and wiring
|   |   +-- config.py                reads environment into typed Settings
|   |   +-- database.py              SQLAlchemy engine, Base and DB sessions
|   |   +-- models.py                database tables and relationships
|   |   +-- schemas.py               validated API/AI data shapes
|   |   +-- services.py              core catalog business logic
|   |   +-- image_processing.py      decode, normalize and resize images
|   |   +-- ai.py                    AI contract + fake/AvalAI implementations
|   |   +-- basalam_categories.py    category cache/search structures
|   |   +-- platform_services.py     Basalam OAuth/category/publish workflow
|   |   +-- torob_services.py        Torob submission/admin/publish workflow
|   |   +-- observability.py         safe logs, Sentry and event persistence
|   |   +-- integrations/
|   |       +-- __init__.py
|   |       +-- basalam.py           low-level HTTP client for Basalam
|   |       +-- torob.py             low-level HTTP client for Torob
|   +-- tests/
|   |   +-- conftest.py              shared pytest fixtures and test app
|   |   +-- helpers.py               reusable fake data/test helpers
|   |   +-- test_api_flow.py         catalog/upload/edit/processing flows
|   |   +-- test_ai.py               deterministic AI behavior
|   |   +-- test_ai_live.py          optional real-provider checks
|   |   +-- test_basalam_*.py        category/OAuth/publish contracts
|   |   +-- test_torob_integration.py
|   |   +-- test_observability.py    redaction/events/request-id contracts
|   |   +-- test_static_frontend.py  serving the built frontend
|   +-- requirements.txt             pinned Python dependencies
|   +-- pytest.ini                   pytest configuration
|   +-- alembic.ini                  migration-tool configuration
|   +-- alembic/env.py               Alembic connection/model bootstrap
|
+-- frontend/                        Browser application
|   +-- src/
|   |   +-- main.tsx                 browser entry; mounts React
|   |   +-- App.tsx                  main catalog and admin UI/state
|   |   +-- App.test.tsx             component/integration behavior tests
|   |   +-- styles.css               visual rules and responsive layout
|   |   +-- vite-env.d.ts            Vite TypeScript declarations
|   |   +-- lib/
|   |   |   +-- api.ts               fetch wrapper and all API calls
|   |   |   +-- telemetry.ts         observed actions, Clarity and Sentry
|   |   |   +-- telemetry.test.ts    privacy/interaction telemetry tests
|   |   |   +-- types.ts             TypeScript domain/API types
|   |   +-- test/setup.ts            browser-like test environment setup
|   +-- tests/catalog-flow.spec.ts   Playwright end-to-end scenarios
|   +-- scripts/production-probe.mjs deterministic production browser probe
|   +-- index.html                   HTML shell loaded before React
|   +-- package.json                 npm scripts and dependency declarations
|   +-- package-lock.json            exact dependency resolution
|   +-- vite.config.ts               frontend build configuration
|   +-- vitest.config.ts             component test configuration
|   +-- playwright.config.ts         E2E browser/server configuration
|   +-- tsconfig*.json               TypeScript compiler rules
|   +-- public/                      static logo/favicon copied into build
|
+-- automation/                      Local autonomous diagnosis program
|   +-- runner.py                    one full collect/triage/diagnose run
|   +-- collectors.py                reads each evidence source
|   +-- models.py                    Signal, Candidate and RunReport types
|   +-- state.py                     state.json, retention, lock and phases
|   +-- security.py                  sanitization and diff guardrails
|   +-- dashboard.py                 writes Persian HTML reports
|   +-- simulation.py                controlled end-to-end agent simulation
|   +-- policy.json                  limits, forbidden paths and test gates
|   +-- journey_contracts.json       required stages/invariants per journey
|   +-- ux_contract.json             expected observed UI controls
|   +-- prompts/                     strict roles for reproducer/fixer/reviewer
|   +-- schemas/                     JSON output contracts for agent sessions
|   +-- tests/test_automation.py     deterministic automation tests
|   +-- configure-secrets.ps1        encrypted per-user secret setup
|   +-- setup-windows.ps1            Task Scheduler/dashboard shortcut setup
|   +-- run-nightly.ps1              scheduled-process launcher
|
+-- docs/
|   +-- ENGINEERING_GUIDE.md         this document
|   +-- TDD.md                       test-first rules
|   +-- AUTONOMY.md                  autonomous-agent operations
|   +-- RELEASE.md                   current milestone and go/no-go
|   +-- ONBOARDING.md                local setup instructions
|
+-- .github/workflows/build-image.yml CI tests and container-image build
+-- Dockerfile                       reproducible production image recipe
+-- AGENTS.md                        mandatory repository/agent rules
+-- README.md                        quick product and setup overview
```

### ۳.۳ package، module و import یعنی چه؟

در Python هر فایل `.py` یک module است. پوشه دارای `__init__.py` یک package قابل import است. مثلاً در `main.py`:

```python
from .config import Settings
from .services import create_batch
```

نقطه یعنی «از همین package یعنی `app`». این import به Python می‌گوید تعریف `Settings` را از `config.py` و تابع `create_batch` را از `services.py` بگیرد؛ کد را copy نمی‌کند.

در TypeScript نیز `import { api } from './lib/api'` همان ایده dependency را دارد، ولی Vite در build moduleها را برای browser bundle می‌کند.

### ۳.۴ composition root دقیقاً چیست؟

**ساده:** جایی که قطعات ساخته و به هم وصل می‌شوند؛ مثل تابلو برق که سیم هر اتاق را به مدار درست وصل می‌کند.

**فنی:** composition root بالاترین نقطه برنامه است که dependencyهای concrete را انتخاب می‌کند. در این پروژه `create_app()` داخل `backend/app/main.py`:

1. `Settings` را می‌گیرد؛
2. logging و Sentry را پیکربندی می‌کند؛
3. FastAPI instance را می‌سازد؛
4. middlewareهای CORS و request-id را اضافه می‌کند؛
5. dependencyهایی مانند DB session و admin/observability auth را وصل می‌کند؛
6. endpointها را register می‌کند؛
7. در production فایل‌های frontend را mount می‌کند.

چرا business logic نباید همان‌جا انباشته شود؟ چون endpoint به HTTP وابسته است. اگر منطق upload در route نوشته شود، تست آن بدون request سخت و reuse آن از job ناممکن می‌شود. الگوی مطلوب:

```text
HTTP Route  -->  Schema Validation  -->  Domain Service  -->  DB / Integration
   thin              shape               decision             side effect
```

مثال: endpoint پردازش فقط batch id را می‌گیرد، `create_processing_job` را صدا می‌زند، background task را schedule می‌کند و `job_id` برمی‌گرداند. retry و حفظ edit در service است، نه route.

### ۳.۵ فرق schema، model، service و integration

فرض کن frontend این payload را می‌فرستد:

```json
{"title": "کیف چرمی", "price_toman": 420000}
```

- `BatchItemPatch` در `schemas.py` می‌سنجد title طول معتبر و price غیرمنفی باشد.
- `BatchItem` در `models.py` می‌گوید این داده در کدام table/column ذخیره شود.
- `update_item` در `services.py` تصمیم می‌گیرد کدام field تغییر کند و `edited_by_user` چه شود.
- integration در این مرحله درگیر نیست؛ هنگام publish داده را به قرارداد باسلام تبدیل می‌کند.

## ۴. runtime topology، build، image، container و deployment از صفر

### ۴.۱ topology یعنی چه؟

Topology یعنی «در زمان اجرا چه جزءهایی وجود دارند، کجا هستند و چگونه به هم وصل می‌شوند». repository structure درباره چیدمان **کد** است؛ runtime topology درباره چیدمان **چیزهای درحال اجرا**.

مثال: `App.tsx` یک فایل در repository است، ولی پس از build دیگر browser فایل TypeScript خام را اجرا نمی‌کند؛ JavaScript bundle حاصل را اجرا می‌کند. `main.py` فایل است، Uvicorn processی است که آن را import و اجرا می‌کند.

### ۴.۲ source، build و artifact

- **Source:** کدی که ما می‌نویسیم؛ TSX، Python، CSS.
- **Build:** تبدیل/بررسی source برای اجرا یا توزیع.
- **Artifact:** خروجی ثابت build؛ مثلاً پوشه `frontend/dist` یا Docker image.

Python در این پروژه عمدتاً هنگام runtime اجرا می‌شود، اما TypeScript/JSX برای browser باید توسط Vite تبدیل شود:

```text
App.tsx + styles.css + dependencies
                 |
                 | npm run build
                 v
       dist/index.html + hashed JS/CSS
```

نام hashدار مثل `assets/index-a1b2.js` کمک می‌کند browser نسخه قدیمی را cache نکند.

### ۴.۳ Docker image و container

**Image** یک بسته immutable شامل filesystem و دستور شروع برنامه است. **Container** یک نمونه درحال اجرای همان image با network، environment و filesystem قابل نوشتن خودش است.

تشبیه دقیق: image شبیه template خام ماشین مجازی است، نه خود process؛ container نمونه ساخته‌شده از آن template است. چند container می‌توانند از یک image یکسان اجرا شوند ولی حافظه و فایل writable جدا داشته باشند.

```text
                  ONE IMMUTABLE IMAGE
                 +---------------------+
                 | Python + app        |
                 | dependencies        |
                 | built frontend      |
                 | start command       |
                 +----------+----------+
                            |
             +--------------+--------------+
             | instantiate                 | instantiate
             v                             v
      +------+-------+              +------+-------+
      | Container A  |              | Container B  |
      | own process  |              | own process  |
      | own writable |              | own writable |
      +--------------+              +--------------+
```

نسخه فعلی عملاً برای یک replica و SQLite طراحی شده است. اجرای دو container با دو SQLite مستقل یعنی هرکدام داده متفاوت می‌بینند؛ صرفاً زیادکردن replica بدون database مشترک درست نیست.

### ۴.۴ Dockerfile این پروژه، مرحله‌به‌مرحله

این Dockerfile **multi-stage build** دارد؛ یعنی مرحله build ابزارهای سنگین را استفاده می‌کند ولی همه آن‌ها را وارد image نهایی نمی‌کند.

```text
STAGE 1: frontend-builder (Node 20)
+---------------------------------------------------+
| copy package files -> npm ci -> copy frontend     |
| -> npm run build -> /app/frontend/dist            |
+---------------------------+-----------------------+
                            | copy only dist
                            v
STAGE 2: runtime (Python 3.12)
+---------------------------------------------------+
| install Python deps                              |
| copy backend source                              |
| copy built frontend to /app/frontend-dist        |
| start Uvicorn on 0.0.0.0:8000                    |
+---------------------------------------------------+
```

فایده: Node، source frontend و cacheهای npm لازم نیستند در image runtime باشند؛ image کوچک‌تر و سطح حمله محدودتر می‌شود.

### ۴.۵ Uvicorn و FastAPI چه فرقی دارند؟

FastAPI framework است: route، validation، dependency injection و response را تعریف می‌کند. Uvicorn application server است: روی socket شبکه گوش می‌دهد، HTTP را به ساختار ASGI تبدیل می‌کند و تابع FastAPI را اجرا می‌کند.

```text
Internet request
      |
      v
[TCP port 8000] -> [Uvicorn / ASGI server] -> [FastAPI app] -> [route/service]
      ^                                                |
      +---------------- HTTP response -----------------+
```

`0.0.0.0:8000` یعنی Uvicorn روی همه interfaceهای شبکه داخل container و پورت ۸۰۰۰ گوش می‌دهد. این به معنی public شدن مستقیم نیست؛ پلتفرم hosting یک domain/ingress را به آن route می‌کند.

### ۴.۶ یک request production دقیقاً کجا می‌رود؟

```text
User Browser
     |
     | HTTPS https://addwithai.darkube.ir
     v
Darkube Ingress / Domain Router
     |
     | forwards to container port 8000
     v
Uvicorn Process
     |
     +--> path starts with /batches, /assets, ... --> FastAPI endpoint
     |
     +--> browser page/static asset path -----------> built React files
```

TLS/HTTPS معمولاً در ingress terminate می‌شود؛ Uvicorn داخل شبکه پلتفرم request forwardشده را می‌گیرد. یک image واحد باعث شده frontend و backend از یک origin سرو شوند و در production معمولاً نیاز به URL جداگانه API نباشد.

### ۴.۷ CI، registry و deploy سه چیز متفاوت‌اند

```text
Developer -> git push -> GitHub Actions -> tests -> docker build -> GHCR
                                                                  |
                                              human selects tag    |
                                                                  v
                                                        Darkube deployment
                                                                  |
                                                                  v
                                                         running container
```

- **CI:** تست و build خودکار روی GitHub Actions.
- **Registry:** انبار image؛ اینجا GitHub Container Registry یا GHCR.
- **Deploy:** انتخاب image و اجرای آن در محیط production؛ اینجا با کنترل انسانی در Darkube.

merge به‌تنهایی production را عوض نمی‌کند. پس از merge، workflow image با tag مثل `build-abc1234` می‌سازد. وقتی همان tag در Darkube اعمال شود container جدید جای قبلی را می‌گیرد.

### ۴.۸ persistence: چرا داده ممکن است با restart بپرد؟

filesystem writable خود container موقتی است. اگر container جدید ساخته شود، فایل‌های نوشته‌شده داخل نمونه قبلی الزاماً به نمونه جدید نمی‌آیند. Volume یک storage جدا با عمر مستقل از container است.

```text
WITHOUT VOLUME                       WITH PERSISTENT VOLUME

Container v1                         Container v1
  /data/catalog.db                     |
        X replaced                     v
Container v2                         [Persistent /data]
  /data is fresh                       ^
                                       |
                                     Container v2
```

این برنامه SQLite و upload را زیر `/data` می‌گذارد. بدون volume پایدار، کاربر در همان عمر container کارش را انجام می‌دهد ولی restart/deploy می‌تواند داده را حذف کند. علاوه بر داده محصول، OperationalEventهای عامل نیز از بین می‌روند.

### ۴.۹ configuration و secret، با مثال قابل فهم

Configuration یعنی مقداری که رفتار یک build یا اجرا را بدون تغییر source تعیین می‌کند. Environment variable یک جفت نام/مقدار است که سیستم‌عامل به process می‌دهد:

```text
Name:  APP_ENVIRONMENT
Value: production
```

`config.py` با `pydantic-settings` آن‌ها را به یک object typed به نام `Settings` تبدیل می‌کند. اگر `SENTRY_TRACES_SAMPLE_RATE=abc` باشد validation اجازه عدد نامعتبر نمی‌دهد.

#### build-time در برابر runtime

```text
VITE_* variable --(docker build)--> embedded in browser JS bundle
BACKEND variable --(container start)--> read by Python Settings
```

چرا؟ browser روی دستگاه کاربر به environment سرور دسترسی ندارد. Vite مقدار `VITE_*` را هنگام build داخل JavaScript جایگزین می‌کند. پس تغییر `VITE_SENTRY_DSN` در environment container بدون rebuild اثری ندارد. Python داخل همان container اجرا می‌شود و متغیر backend را هنگام start می‌خواند.

#### secret چیست؟

Secret مقداری است که داشتنش اختیار یا دسترسی می‌دهد؛ مثل `AVALAI_API_KEY` یا `BASALAM_CLIENT_SECRET`. نام model یا URL عمومی secret نیست. DSN ingest Sentry کلید مدیریت نیست، ولی auth token خواندن رخدادهای Sentry secret است.

| گروه | مثال | چه زمانی خوانده می‌شود؟ | نبود مقدار چه می‌کند؟ |
|---|---|---|---|
| AI backend | `AI_PROVIDER`, `AVALAI_API_KEY`, modelها | start/request | بدون key، حالت auto به fake می‌رود |
| storage | `DATABASE_URL`, `UPLOAD_DIR` | start | default محلی استفاده می‌شود |
| release | `APP_ENVIRONMENT`, `APP_RELEASE` | start | log/Sentry context ضعیف‌تر می‌شود |
| frontend telemetry | `VITE_SENTRY_DSN`, `VITE_APP_RELEASE` | build | Sentry frontend خاموش یا release نامشخص |
| backend telemetry | `SENTRY_DSN`, sample rate | start | Sentry backend خاموش |
| agent feed | `OBSERVABILITY_READ_TOKEN` | start | endpoint read-only تنظیم نیست |
| Basalam OAuth | client id/secret/redirect URI | start/request | `configured=false` و اتصال شروع نمی‌شود |
| Torob/Admin | API credentials/admin password | start/request | عملیات مربوط رد می‌شود |

مقدار secret نباید داخل Git، chat، image layer، frontend bundle یا log قرار گیرد. Secret مربوط به backend در environment امن hosting و secret مربوط به عامل در credential store کاربر Windows نگهداری می‌شود.

## ۵. دیتامدل از صفر تا سطح طراحی

### ۵.۱ اول مفاهیم database رابطه‌ای

SQLite یک relational database است. داده در tableها قرار می‌گیرد:

```text
TABLE: batches
+----+-----------+--------------+----------------------+
| id | seller_id | status       | created_at           |
+----+-----------+--------------+----------------------+
| 42 | 7         | upload_ready | 2026-07-17T08:30:00Z |
+----+-----------+--------------+----------------------+
```

- **Table:** مجموعه rowهای هم‌نوع؛ مثل batchها.
- **Row:** یک نمونه؛ مثلاً batch شماره ۴۲.
- **Column:** یک ویژگی با نوع مشخص؛ مثلاً status.
- **Primary key یا PK:** شناسه یکتای row؛ اینجا `id=42`.
- **Foreign key یا FK:** اشاره به PK جدول دیگر؛ `seller_id=7` یعنی این batch متعلق به seller شماره ۷ است.
- **Nullable:** آیا column اجازه `NULL` یعنی «مقدار موجود نیست» دارد.
- **Index:** ساختار کمکی برای جست‌وجوی سریع‌تر، با هزینه فضای بیشتر و write کندتر.
- **Unique constraint:** database اجازه دو row با ترکیب تکراری مشخص را نمی‌دهد.

### ۵.۲ entity، model و aggregate

Entity چیزی است که identity پایدار دارد؛ دو محصول با عنوان یکسان اگر id متفاوت داشته باشند دو entity هستند. SQLAlchemy model کلاس Python متناظر با table است. Aggregate مجموعه entityهایی است که برای یک consistency boundary با هم دیده می‌شوند. در این محصول Batch aggregate اصلی catalog است.

### ۵.۳ cardinality یا تعداد رابطه‌ها

- `1 ---- N`: یک Seller می‌تواند چند Batch داشته باشد؛ هر Batch دقیقاً یک Seller دارد.
- `1 ---- 0..N`: ممکن است seller هنوز هیچ batch نداشته باشد.
- `N ---- N`: چند item می‌توانند به چند asset وصل شوند؛ برای این رابطه یک join table لازم است.

### ۵.۴ نقشه رابطه‌ها، مرحله‌ای و خوانا

نخست هسته catalog:

```text
+-------------+       1 : many       +-------------+
|   Seller    | --------------------> |    Batch    |
| seller.id   |                       | seller_id FK|
+-------------+                       +------+------+
                                               |
                   +---------------------------+---------------------------+
                   | 1 : many                  | 1 : many                  | 1 : many
                   v                           v                           v
            +------+-------+           +-------+--------+          +-------+-------+
            |    Asset     |           | ProcessingJob |          |   BatchItem   |
            | image/audio  |           | AI run status |          | product draft |
            +------+-------+           +----------------+          +-------+-------+
                   |                                                       |
                   |             many : many via join table                |
                   +--------------------+---------------------------+------+
                                        v
                              +---------+----------+
                              | BatchItemAsset    |
                              | asset_id + item_id|
                              | role + sort_order |
                              +-------------------+
```

سپس publish باسلام:

```text
+-------------+     owns      +--------------------+
|   Seller    | ------------> | PlatformConnection |
+------+------+               | Basalam OAuth token|
       |                      +----------+---------+
       | owns Batch                      | authorizes
       v                                 v
+------+-------+     publish      +-------+-------+
|    Batch    | ----------------> |  PublishJob  |
+------+-------+                   +-------+-------+
       |                                   |
       | contains items                    | produces one result per item
       v                                   v
+------+-------+                  +--------+----------+
|  BatchItem  | <--------------- | PublishedProduct |
+------+-------+    refers to     | success / failure|
       |                          +-------------------+
       | 0..1 row per platform
       v
+-----------------------+
| BatchItemPlatformData |
| Basalam category etc. |
+-----------------------+
```

و مسیر ترب:

```text
+--------+       +-------+       +-----------------+
| Seller | ----> | Batch | ----> | TorobSubmission |
+--------+       +---+---+       +--------+--------+
                   |                     |
                   |                     | snapshots many items
                   v                     v
              +----+-----+      +--------+-----------+
              |BatchItem| <----|TorobSubmissionItem |
              +----------+      |base_product_rk     |
                                |price + status      |
                                +--------------------+
```

### ۵.۵ مدل هر table با یک سناریوی واقعی

#### Seller: صاحب داده

فیلدها: `id`, `name`, `mobile`, `shop_name`, زمان ساخت و ویرایش.

اگر علی وارد همان مرورگر شود، frontend seller را می‌سازد و id را نگه می‌دارد. batchهای بعدی با `seller_id` به او وصل می‌شوند. با این حال login واقعی نداریم؛ کسی که id را حدس بزند از نظر معماری نهایی نباید مجاز تلقی شود. پس Seller فعلی مدل دامنه است، نه security principal کامل.

#### Batch: ظرف یک نوبت ساخت catalog

نمونه: علی امروز سه عکس کیف و یک ویس می‌دهد. همه متعلق به `batch_id=42` هستند. فردا عکس کفش می‌دهد؛ باید batch دیگری باشد تا grouping و publish قاطی نشود.

فیلدهای حساس:

- `raw_transcript`: متن کامل ویس؛ برای منطق محصول لازم، برای log ممنوع.
- `ai_metadata`: provider/model و failure metadata امن؛ نباید dump ورودی کاربر باشد.

state:

```text
draft --upload succeeds--> upload_ready --process starts--> processing
                                                        |          |
                                                  success          failure
                                                        v          v
                                                      ready      failed
```

`failed` به معنی حذف asset نیست. کاربر باید بتواند دوباره پردازش کند.

#### Asset: metadata فایل

نمونه row:

```text
id=101, batch_id=42, type=image, upload_order=1,
file_path=/data/uploads/42/image/..., mime_type=image/jpeg,
size_bytes=183204, checksum=<sha256>
```

`upload_order` پلی میان «عکس شماره ۱» در prompt AI و فایل واقعی است. `checksum` fingerprint محتوای فایل است و می‌تواند در تشخیص duplicate/corruption مفید باشد. خود بایت تصویر داخل DB نیست.

#### ProcessingJob: تاریخچه یک اجرای AI

Batch وضعیت کلی دارد، Job وضعیت یک attempt مشخص. اگر پردازش اول fail و پردازش دوم succeed شود، داشتن دو job تاریخچه را حفظ می‌کند. endpoint روی double-click job فعال `queued/running` را reuse می‌کند.

```text
queued -> running/transcribing -> running/vision_extracting
       -> running/matching     -> succeeded/ready
                              \-> failed/failed
```

#### BatchItem: محصول مرکزی و مستقل از پلتفرم

فیلدها به چهار گروه تقسیم می‌شوند:

- content: title و description؛
- commerce: price و stock؛
- fulfillment/shipping: preparation، وزن و وزن بسته؛
- AI/human ownership: confidence و `edited_by_user`.

چرا price `NULL` می‌شود ولی title نه؟ AI ممکن است قیمت قابل اعتماد پیدا نکند و «ناموجود بودن مقدار» با صفر فرق دارد. title برای render یک item لازم است و fallback ساخته می‌شود. صفر برای stock می‌تواند «ناموجود» باشد، اما `NULL` یعنی هنوز تکمیل نشده؛ این دو نباید یکی شوند.

`edited_by_user` در DB برای کل item است. frontend touched fieldها را دقیق‌تر نگه می‌دارد. این تفاوت یک trade-off است: backend می‌فهمد انسان دخالت کرده، ولی همیشه نمی‌داند دقیقاً کدام field مگر payload/update history جدا داشته باشیم.

#### BatchItemAsset: چرا join table لازم است؟

فرض کن عکس‌های ۱ و ۲ دو زاویه یک کیف‌اند و عکس ۳ یک کفش است. item کیف به assetهای ۱ و ۲ و item کفش به asset ۳ وصل می‌شود. اگر بعداً merge/split کنیم linkها تغییر می‌کنند، نه خود فایل‌ها.

```text
Item 501 ---- Link(sort=0) ---- Asset 101
Item 501 ---- Link(sort=1) ---- Asset 102
Item 502 ---- Link(sort=0) ---- Asset 103
```

`role` فعلاً معمولاً `product_photo` و `sort_order` ترتیب نمایش/ارسال است.

#### BatchItemPlatformData: چرا category داخل BatchItem نیست؟

Category مفهوم باسلام است و ممکن است ترب taxonomy دیگری داشته باشد. گذاشتن `basalam_category_id` در core item coupling ایجاد می‌کند. جدول جدا اجازه می‌دهد core product ثابت و projection هر پلتفرم مستقل باشد.

قید unique روی `(batch_item_id, platform)` می‌گوید یک item نمی‌تواند دو snapshot همزمان باسلام داشته باشد. فیلد `category_source` فرق انتخاب `ai` و `user` را نگه می‌دارد؛ این فرق روی retry اثر دارد.

#### PlatformConnection: OAuth credential و ownership غرفه

این table external shop identity، access/refresh token، scope و expiry را نگه می‌دارد. response عمومی schema token ندارد. قید unique روی `(platform, external_shop_id)` جلوی duplicate connection همان غرفه را می‌گیرد.

`workspace_id` داخل metadata است. این تصمیم flexible است ولی constraint مستقیم DB روی workspace ایجاد نمی‌کند؛ ownership عمدتاً در service enforce می‌شود.

#### PublishJob و PublishedProduct: کل عملیات در برابر نتیجه هر محصول

فرض کن سه item publish می‌شوند: دو موفق و یکی ناموفق.

```text
PublishJob #80: status=partial_failed
  |
  +-- PublishedProduct(item=501): published, external_id=...
  +-- PublishedProduct(item=502): failed, safe error=...
  +-- PublishedProduct(item=503): published, external_id=...
```

اگر فقط status کل job را داشتیم نمی‌دانستیم چه چیزی ثبت شده و retry کور ممکن بود duplicate بسازد. نتیجه per-item برای reconciliation ضروری است.

#### TorobSubmission و TorobSubmissionItem: snapshot برای review انسانی

Submission نام فروشگاه، موبایل تماس، batch و status کل درخواست را دارد. child itemها `base_product_rk`، price و status را نگه می‌دارند. ادمین روی snapshot تصمیم می‌گیرد. reference به BatchItem برای traceability باقی می‌ماند.

#### OperationalEvent: database کوچک evidence، نه log کامل

این جدول فقط eventهای allowlistشده، severity، release، شناسه‌های فنی و context محدود را نگه می‌دارد. متن ویس، عکس و payload محصول در آن جایی ندارند. عامل با read token از feed همین داده استفاده می‌کند. اگر storage موقت از بین برود، evidence نیز از بین می‌رود.

### ۵.۶ relationship، cascade و orphan را بفهمیم

SQLAlchemy `relationship` کار با objectها را ساده می‌کند؛ ForeignKey قید داده است. `cascade="all, delete-orphan"` یعنی childی که فقط در مالکیت parent معنا دارد با حذف parent یا جداشدن از آن قابل حذف است.

نمونه: BatchItemPlatformData بدون BatchItem معنایی ندارد، پس delete-orphan منطقی است. اما فایل فیزیکی Asset داخل SQLAlchemy نیست؛ حذف row خودبه‌خود فایل `/data/...jpg` را پاک نمی‌کند. service باید آن side effect را انجام دهد.

Cascade اشتباه خطرناک است: اگر PublishedProduct موفق را با یک edit عادی item حذف کنیم، audit انتشار از بین می‌رود. به همین دلیل باید ownership و lifecycle هر relationship را جدا تصمیم گرفت.

### ۵.۷ constraint در DB یا rule در service؟

| قانون | enforce فعلی | پیامد |
|---|---|---|
| یک platform-data برای هر item/platform | unique constraint در DB | حتی race هم duplicate را رد می‌کند |
| یک external shop برای هر platform | unique constraint در DB | اتصال duplicate رد می‌شود |
| itemهای merge متعلق به یک batch | service | پیام domain خوب، ولی DB constraint مستقیم ندارد |
| asset split متعلق به همان item | service | payload بیگانه رد می‌شود |
| یک processing/publish job فعال | query در service | زیر concurrency چند replica احتمال race دارد |
| upload_order یکتا در batch | service | unique constraint فعلاً وجود ندارد |
| connection متعلق به seller/workspace | service + signed OAuth state | مرز بسیار حساس امنیتی |

Database constraint آخرین خط دفاع در برابر race است. service rule می‌تواند context بهتر و پیام مناسب بدهد. در سیستم بالغ اغلب هر دو لازم‌اند.

### ۵.۸ stateها و transitionهای مجاز

| entity | statusها | معنی |
|---|---|---|
| Batch | `draft`, `upload_ready`, `processing`, `ready`, `failed` | آمادگی catalog، نه نتیجه publish |
| ProcessingJob | `queued`, `running`, `succeeded`, `failed` | یک attempt AI |
| PlatformConnection | `connected` | credential قابل استفاده |
| PublishJob | `queued`, `running`, `succeeded`, `partial_failed`, `failed` | نتیجه کل publish |
| PublishedProduct | `pending`, `published`, `failed` | نتیجه یک item |
| TorobSubmission | `pending`, `submitting`, `submitted`, `failed` | نتیجه کل درخواست ترب |
| TorobSubmissionItem | `pending`, `submitted`, `failed` | نتیجه یک item ترب |

statusها فعلاً String هستند و DB enum/check constraint ندارند. پس typo از نظر DB ممکن است. service و تست مانع عملی‌اند، اما state machine صریح یا check constraint مسیر بلوغ بهتری است.

## ۶. HTTP، API، endpoint و قرارداد داده از صفر

### ۶.۱ HTTP request از چه چیزهایی تشکیل می‌شود؟

```text
POST /batches/42/process HTTP/1.1       <- method + path
Host: addwithai.darkube.ir              <- header
X-Request-ID: 8f...                     <- correlation header
Content-Type: application/json

{}                                      <- optional body
```

- `GET`: خواندن بدون تغییر مورد انتظار.
- `POST`: ساخت resource یا شروع command.
- `PATCH`: تغییر بخشی از resource.
- `DELETE`: حذف.
- path parameter مثل `42` resource مشخص را تعیین می‌کند.
- query parameter مثل `?seller_id=7` filter/context است.
- header metadata پروتکل است؛ body داده اصلی request.

### ۶.۲ response و status code

```text
HTTP/1.1 202 Accepted
Content-Type: application/json
X-Request-ID: 8f...

{"job_id": 91}
```

`202` یعنی request پذیرفته شده ولی کار طولانی هنوز تمام نشده است. frontend باید `GET /jobs/91` را poll کند. کدهای مهم:

- `200`: موفق و response حاضر است.
- `201`: resource جدید ساخته شد.
- `202`: کار پذیرفته شد و async ادامه دارد.
- `204`: موفق بدون body، مانند delete.
- `404`: resource پیدا نشد.
- `422`: shape/value ورودی با schema سازگار نیست.
- `500`: خطای پیش‌بینی‌نشده server؛ نباید جزئیات خام به کاربر نشت کند.

### ۶.۳ Pydantic schema چه کاری می‌کند؟

Schema قرارداد مرز API است. مثلاً `BatchItemPatch` می‌گوید price اگر ارسال شد باید integer و حداقل صفر باشد. قبل از رسیدن payload به service، FastAPI آن را به object معتبر تبدیل می‌کند.

```text
Raw JSON -> parsing -> Pydantic validation -> typed object -> service
                |              |
          invalid JSON      invalid value
                +-------> 4xx response
```

Schema با SQLAlchemy model یکی نیست: schema تعیین می‌کند بیرون چه چیزی اجازه ورود/خروج دارد؛ model تعیین می‌کند داخل DB چگونه ذخیره شود. حذف token از response schema حتی وقتی token در model هست یک کنترل امنیتی است.

### ۶.۴ یک endpoint واقعی را خط‌به‌خط ذهنی بخوانیم

برای `POST /batches/{batch_id}/process`:

1. router عدد path را به `batch_id` تبدیل می‌کند.
2. dependency یک DB session برای عمر request فراهم می‌کند.
3. service وجود batch و داشتن حداقل یک عکس را بررسی می‌کند.
4. اگر job فعال هست، id همان را می‌دهد؛ double-click side effect جدید ندارد.
5. وگرنه ProcessingJob queued می‌سازد و commit می‌کند.
6. FastAPI BackgroundTasks اجرای job را بعد از response schedule می‌کند.
7. response با `202` و `job_id` برمی‌گردد.
8. frontend تا terminal status polling می‌کند.

### ۶.۵ endpointهای پروژه بر اساس use case

| use case | method و path | ورودی/نتیجه اصلی |
|---|---|---|
| health | `GET /health` | اثبات زنده‌بودن process، نه صحت همه integrationها |
| ساخت seller | `POST /sellers` | profile اولیه → SellerRead |
| ساخت batch | `POST /batches` | seller id → Batch |
| upload | `POST /batches/{id}/assets` | multipart files → Asset list |
| حذف asset | `DELETE /assets/{id}` | 204 یا خطای attached بودن |
| پردازش AI | `POST /batches/{id}/process` | 202 + job id |
| وضعیت AI | `GET /jobs/{id}` | status/step/error امن |
| ویرایش item | `PATCH /batch-items/{id}` | partial fields → item جدید |
| merge/split/reorder | `/batch-items/...` | تغییر linkهای item/asset |
| OAuth باسلام | `/integrations/basalam/oauth-url` و callback | URL، exchange و connection |
| category | `/integrations/basalam/categories` و item category | search/suggest/manual selection |
| publish باسلام | `POST /batches/{id}/publish/basalam` | 202 + publish job id |
| درخواست ترب | `POST /batches/{id}/torob-submissions` | contact/shop → submission |
| ادمین ترب | `/admin/torob-submissions/...` | review، patch و publish |
| event ingest | `POST /observability/*-events` | schema بسته، response 204 |
| agent feed | `GET /observability/events` | bearer read-only + داده پاک‌سازی‌شده |

### ۶.۶ X-Request-ID برای چیست؟

اگر frontend بگوید «request شکست خورد» و backend صدها log داشته باشد باید همان request را پیدا کنیم. browser یک id امن در sessionStorage می‌سازد، در header می‌فرستد، middleware آن را در response و log استفاده می‌کند.

```text
Browser error breadcrumb: request_id=R1
             |
             +-------- correlation --------+
                                                Backend log: request_id=R1
```

خود id نباید هویت کاربر یا موبایل باشد. query string نیز log نمی‌شود چون callback OAuth حاوی code/state است.

### ۶.۷ BackgroundTasks queue واقعی نیست

BackgroundTasks فقط می‌گوید «بعد از فرستادن response، همین process این function را اجرا کند». اگر container restart شود، حافظه process و task از بین می‌رود. queue durable مانند Celery/RQ همراه Redis یا broker، task را خارج از حافظه web process نگه می‌دارد و worker جدا آن را claim می‌کند.

پس معماری فعلی برای MVP ساده است، ولی تضمین job در restart، retry پس از crash و scale چند worker را ندارد.

## ۷. معماری frontend

Frontend با React، TypeScript و Vite ساخته شده است:

- **React** مدل ساخت UI از component و state است. وقتی state عوض می‌شود React بخش لازم DOM را دوباره render می‌کند.
- **TypeScript** همان JavaScript با type checking قبل از اجراست؛ مثلاً نمی‌گذارد به‌اشتباه `Seller` را جای `Batch` پاس بدهیم، البته type در runtime browser حذف می‌شود.
- **Vite** development server و build tool است؛ moduleها را resolve و خروجی مناسب browser تولید می‌کند.
- **Component** تابعی است که از props/state یک تکه UI می‌سازد.
- **Hook** تابع React مانند `useState` و `useEffect` برای state و side effect است.

`main.tsx` نقطه ورود browser است و `<App />` را در HTML mount می‌کند. `App` تشخیص می‌دهد path ادمین است یا catalog. `App.tsx` اکنون component بسیار بزرگی است و هم state machine اصلی، هم UI و هم پنل ادمین را در خود دارد. این کار برای MVP سریع بوده، اما coupling یعنی تغییر یک concern احتمال اثر روی concernهای دیگر را بالا می‌برد.

### stateهای مهم

- platform انتخابی: `basalam | torob | null`
- seller و workspace مرورگر
- batch، assets، items و job پردازش
- draftهای قابل‌ویرایش و touched fields
- connection، OAuth restore و publish job
- اطلاعات submission ترب و state پنل ادمین

State یعنی داده‌ای که تغییرش باید UI را تغییر دهد. برای مثال `assets=[]` یعنی grid عکس خالی است؛ پس از upload، response در `setAssets(...)` قرار می‌گیرد و React grid جدید را render می‌کند. متغیر عادی local پس از render حفظ نمی‌شود؛ state React حفظ می‌شود.

### localStorage و sessionStorage

| کلید | کاربرد | نکته |
|---|---|---|
| `bulkadd_seller_id` | seller همان مرورگر | authentication نیست |
| `bulkadd_workspace_id` | جداسازی workspace | UUID محلی |
| `bulkadd_basalam_active_batch_id` | بازگشت به batch پس از OAuth | مانع گم‌شدن کار |
| `bulkadd_basalam_oauth_snapshot` | batch id، تعداد asset/item و journey id | برای invariant restore |
| `bulkadd_product_drafts...` | draft و touched fields به تفکیک platform/batch | حفظ تایپ‌های ذخیره‌نشده |
| `bulkadd_request_id` در sessionStorage | correlation requestها | با بستن session تغییر می‌کند |

localStorage پایدارتر از state حافظه React است، اما database نیست: کاربر می‌تواند آن را پاک کند، مرورگر دیگری آن را ندارد و داده آن قابل اعتماد امنیتی نیست.

```text
React state       survives re-render, lost on page reload
sessionStorage    survives reload, isolated per browser tab/session
localStorage      survives browser restart until explicitly removed
Backend database  shared source of truth, subject to server persistence
```

Frontend draft و backend item دو نسخه از داده‌اند. touched map می‌گوید کاربر کدام field را دست زده تا response دیررس یا AI آن را بی‌صدا overwrite نکند.

### چرخه یک action مشاهده‌شده

```text
TIME FLOWS DOWNWARD

User              React UI            Telemetry           FastAPI
 |                   |                    |                   |
 | click Publish     |                    |                   |
 |------------------>|                    |                   |
 |                   | action_started     |                   |
 |                   |------------------->|                   |
 |                   |                    |                   |
 |          +--------+--------+           |                   |
 |          | validate fields |           |                   |
 |          +--------+--------+           |                   |
 |                   |                    |                   |
 |       INVALID     |                    |                   |
 |<------------------| action_blocked ---->                   |
 | Persian guidance  | (field=weight)     |                   |
 |                   |                    |                   |
 |       OR VALID    | action_accepted    |                   |
 |                   |------------------->|                   |
 |                   | POST + request-id  |                   |
 |                   |--------------------------------------->|
 |                   |                    |      JSON / error |
 |                   |<---------------------------------------|
 |<------------------|                    |                   |
```

این یک sequence diagram متنی است: ستون‌ها actorها و جهت عمودی گذر زمان است. دو شاخه INVALID و VALID همزمان رخ نمی‌دهند؛ یکی انتخاب می‌شود. Telemetry payload محصول را نمی‌گیرد، فقط control، outcome و در validation نام field مجاز را می‌گیرد.

Observer عمومی روی elementهای `data-observe-control` سه کلیک در ۱.۵ ثانیه را rage click می‌داند. اگر action غیر-upload پس از pointer-up در ۱.۵ ثانیه توسط handler مصرف نشود، dead click ثبت می‌شود. این event نام control را دارد؛ بنابراین برخلاف metric کلی Clarity می‌توان فهمید مشکل روی کدام کنترل بوده است.

## ۸. جریان upload و مدیریت asset

Upload یعنی انتقال بایت فایل از browser به server. File picker پنجره انتخاب فایل سیستم‌عامل و drop zone ناحیه drag-and-drop صفحه است. `multipart/form-data` قالب HTTP مناسب ارسال چند فایل به‌همراه metadata است؛ JSON برای حمل مستقیم فایل binary انتخاب معمول این endpoint نیست.

MIME type ادعای نوع محتوا مانند `image/jpeg` است، suffix همان پسوند نام مثل `.jpg` و decode تلاش واقعی برای خواندن ساختار تصویر است. فقط اعتماد به MIME یا پسوند ناامن است؛ backend تصویر را واقعاً decode و normalize می‌کند.

### frontend

1. کاربر picker یا drop zone را فعال می‌کند.
2. lifecycle picker با `attempt_id` ثبت می‌شود: opened، selected یا cancelled.
3. آماده‌سازی فایل با concurrency برابر ۲ انجام می‌شود تا حافظه مرورگر با ده‌ها عکس همزمان اشباع نشود.
4. عکس بزرگ resize/normalize و سپس FormData ارسال می‌شود.
5. پاسخ assetها state UI را به‌روزرسانی می‌کند.

### backend

1. وجود batch و MIME/suffix مجاز بررسی می‌شود.
2. فایل موقت نوشته می‌شود.
3. تصویر decode و JPEG استاندارد تولید می‌شود؛ audio با format واقعی نگه داشته می‌شود.
4. checksum و size محاسبه می‌شود.
5. فایل در `<upload_dir>/<batch>/<type>/` قرار می‌گیرد.
6. رکورد Asset ساخته و batch به `upload_ready` می‌رود.

برای upload چند فایل، DB transaction و حذف جبرانی فایل استفاده می‌شود. این atomic transaction واقعی میان filesystem و SQLite نیست. اگر process در نقطه نامناسب crash کند ممکن است orphan file بماند؛ reconciliation job آینده باید فایل‌های بدون رکورد و رکوردهای بدون فایل را پیدا کند.

«Atomic» یعنی عملیات از بیرون یا کاملاً انجام‌شده دیده شود یا اصلاً انجام‌نشده؛ حالت نصفه نباشد. SQLite rollback می‌تواند rowها را برگرداند، اما از فایل JPEG نوشته‌شده خبر ندارد. پس service در `except` فایل را به‌صورت compensating action پاک می‌کند. اگر process قبل از cleanup ناگهان کشته شود compensation اجرا نمی‌شود.

حذف asset وقتی به item وصل است ممنوع است. پس از حذف، upload_orderها دوباره متوالی می‌شوند و حذف فایل فیزیکی best effort است.

## ۹. جریان پردازش AI

```text
                         POST /batches/42/process
Browser UI ----------------------------------------------------+
                                                               v
                                                    +----------+----------+
                                                    | Find active AI job? |
                                                    +----+-----------+----+
                                                         |           |
                                                   YES   |           | NO
                                                         v           v
                                                +--------+--+  +-----+---------+
                                                | reuse id  |  | create queued |
                                                +-----+-----+  | job + commit  |
                                                      |        +-----+---------+
                                                      +------+-------+
                                                             v
                                                     return 202 + job_id
                                                             |
                                          background only ---+
                                                             v
  +------------+    +--------------+    +----------------+    +----------------+
  | transcribe | -> | vision/text  | -> | match products | -> | preserve edits |
  | latest audio|   | strict JSON  |    | to asset sets  |    | and save items |
  +------------+    +--------------+    +----------------+    +--------+-------+
                                                                        |
                                                             +----------+----------+
                                                             |                     |
                                                           success               failure
                                                             v                     v
                                                    job/batch ready       safe error + logs

Browser UI -- GET /jobs/{id} repeatedly --> terminal status
```

خط افقی بالایی request کوتاه HTTP است. زنجیره پایین بعد از response و داخل background task اجرا می‌شود. polling یعنی frontend هر فاصله کوتاه status را می‌پرسد؛ backend connection را برای کل مدت AI باز نگه نمی‌دارد.

### provider interface

`AiProvider` سه capability دارد:

- `transcribe(audio)`
- `extract_products(images, transcript)`
- `choose_basalam_category(...)` یا نسخه batch آن

Interface یا abstract base class می‌گوید «هر provider قابل قبول باید این methodها را داشته باشد» بدون اینکه orchestration بداند پشت آن fake است یا network واقعی. این همان Dependency Inversion در مقیاس کوچک است:

```text
services.py ---> AiProvider contract <--- FakeAiProvider
                                      <--- AvalAiProvider
```

در تست، fake خروجی ثابت می‌دهد؛ در production، settings provider واقعی را انتخاب می‌کند. در نتیجه تست business logic به اینترنت و شانس پاسخ مدل وابسته نیست.

`FakeAiProvider` deterministic است و برای تست بدون هزینه و flakiness استفاده می‌شود. `AvalAiProvider` از API سازگار با OpenAI در `https://api.avalai.ir/v1` استفاده می‌کند. تنظیم فعلی مدل‌ها:

```text
vision/text: gpt-5.4
speech-to-text: gpt-4o-mini-transcribe
service provider: AvalAI
```

مدل AI با schema سخت JSON محدود می‌شود: فیلد اضافه ممنوع، confidence بین صفر و یک و `image_numbers` اجباری است. سپس همان خروجی دوباره با Pydantic validate می‌شود. این دو لایه احتمال خروجی آزاد و خراب را کم می‌کنند، ولی صحت معنایی را تضمین نمی‌کنند.

AI اجازه حدس stock، وزن و زمان آماده‌سازی را ندارد؛ فقط اگر صریحاً در ویس آمده باشد پر می‌کند. price به تومان normalize می‌شود و parser backend نیز الگوهای عدد فارسی/عربی و عبارت‌های رایج را بررسی می‌کند.

### retry

timeout، network error، HTTP 408/409/429/5xx، JSON نامعتبر و خروجی خالی موقت تلقی می‌شوند. حداکثر سه attempt با delayهای کنترل‌شده انجام می‌شود. عکس/صوت نامعتبر و خطاهای قطعی بی‌دلیل retry نمی‌شوند.

### حفظ ویرایش کاربر

محصول‌های قدیم و جدید بر اساس مجموعه assetها match می‌شوند:

- item ویرایش‌نشده می‌تواند با خروجی AI refresh شود.
- item ویرایش‌شده عنوان/توضیح/قیمت موجود خود را حفظ می‌کند و AI فقط خانه خالی را پر می‌کند.
- فیلدهای عددی فقط در صورت خالی‌بودن یا ویرایش‌نشده‌بودن item update می‌شوند.
- عکس استفاده‌نشده به fallback item مستقل تبدیل می‌شود تا هیچ ورودی گم نشود.

## ۱۰. ویرایش، merge، split و reorder

`PATCH /batch-items/{id}` فقط fieldهای ارسال‌شده را تغییر و `edited_by_user=true` می‌کند. frontend draft را پیش از response و پس از آن با touched map merge می‌کند.

- **merge:** همه itemها باید در یک batch باشند. item اول primary است؛ assetها بدون تکرار به آن منتقل و بقیه حذف می‌شوند.
- **split:** assetهای انتخابی باید subset همان item باشند و انتخاب همه assetها مجاز نیست؛ یک item جدید ساخته می‌شود.
- **reorder:** request باید دقیقاً همان مجموعه assetهای فعلی را داشته باشد؛ فقط ترتیب عوض می‌شود.

این preconditionها جلوی attach کردن asset بیگانه یا گم‌شدن عکس بر اثر payload ناقص را می‌گیرند.

## ۱۱. اتصال باسلام و بازگردانی کار

OAuth پروتکلی است که اجازه می‌دهد کاربر در خود باسلام رضایت دهد و برنامه ما token محدود بگیرد، بدون اینکه password باسلام را به ما بدهد. `code` کوتاه‌عمر با token عوض می‌شود. `state` جلوی این را می‌گیرد که callback یک جریان دیگر به seller/workspace اشتباه وصل شود.

Redirect یعنی browser صفحه برنامه ما را ترک و صفحه باسلام را load می‌کند. در نتیجه state صرفاً داخل حافظه React از بین می‌رود. به همین دلیل snapshot محلی و state امضاشده سرور هر دو لازم‌اند.

```text
Browser UI                  Our Backend                    Basalam
    |                           |                             |
    | (1) save local snapshot   |                             |
    | batch=42, assets=3        |                             |
    |                           |                             |
    | (2) request OAuth URL     |                             |
    |-------------------------->|                             |
    |                           | create signed state         |
    |<--------------------------| authorization URL           |
    |                                                         |
    | (3) redirect browser ----------------------------------->|
    |                                                         |
    |                          user approves booth             |
    |                                                         |
    |                           |<-----------------------------|
    |                           | (4) callback: code + state   |
    |                           | verify state                 |
    |                           | exchange code for token ---->|
    |                           |<---- profile + booth + token |
    |                           | save/update connection       |
    |<--------------------------| (5) redirect to frontend     |
    |                           |                             |
    | (6) reload batch -------->|                             |
    | (7) reload assets ------->|                             |
    | (8) reload items -------->|                             |
    | verify seller/counts      |                             |
    | clear snapshot only after complete success              |
```

اگر asset reload در مرحله ۷ fail شود، نباید snapshot فوراً پاک شود یا UI وانمود کند restore کامل شده است. Black Box اولین stage ناموفق و count قبل/بعد را ثبت می‌کند تا «داده پرید» به نقطه مشخص تبدیل شود.

Black Box این journey را در پنج stage پوشش می‌دهد: `oauth_redirect`, `batch_restored`, `assets_restored`, `items_restored`, `restore_complete`. تعداد قبل و بعد، seller mismatch و request failure با داده غیرشخصی ثبت می‌شود.

تفاوت دو شناسه:

- OAuth `state`: داده امضاشده برای جلوگیری از جعل callback و اتصال اشتباه.
- `journey_id`: UUID تصادفی برای وصل‌کردن stepهای یک تجربه؛ مجوز امنیتی نیست.

## ۱۲. انتخاب دسته و انتشار باسلام

### category

دسته‌های واقعی از باسلام fetch و cache می‌شوند. برای هر محصول shortlist ساخته می‌شود و AI فقط حق انتخاب یکی از candidate idها را دارد؛ ساخت category خیالی ممنوع است. انتخاب دستی با `source=user` و confidence برابر ۱ ثبت می‌شود.

اگر confidence پیشنهاد خودکار زیر threshold باشد، UI از کاربر انتخاب می‌خواهد. اگر باسلام category خودکار را هنگام create رد کند، service candidateهای بعدی همان shortlist را امتحان می‌کند؛ انتخاب دستی کاربر بدون اجازه جایگزین نمی‌شود.

### validation قبل از side effect

پیش از upload عکس یا create محصول، همه itemها از نظر قیمت، موجودی، روز آماده‌سازی، وزن محصول، وزن بسته، تعداد واحد، category و داشتن عکس validate می‌شوند. قاعده بسته نیز مانع وزن بسته غیرمنطقی بیش از سه برابر وزن محصول در وزن‌های بالاتر می‌شود.

این ترتیب مهم است: اگر item سوم ناقص باشد، نباید ابتدا دو عکس و دو محصول بیرونی ایجاد و سپس متوقف شویم.

### publish

1. connection باید connected و متعلق به seller/workspace batch باشد.
2. job فعال تکراری برگردانده می‌شود.
3. validation کل batch اجرا می‌شود.
4. تصاویر batch یک‌بار upload می‌شوند.
5. برای هر item payload ساخته می‌شود؛ تومان در مرز API به ریال `×10` تبدیل می‌شود.
6. هر نتیجه مستقل در PublishedProduct ثبت می‌شود.
7. 401 یک‌بار refresh token و retry می‌شود.
8. status نهایی `succeeded`, `partial_failed` یا `failed` است.

خطای provider ممکن است برای تشخیص داخلی نگهداری شود، اما UI فقط ترجمه فارسی امن را می‌بیند.

## ۱۳. مسیر ترب

مسیر فعلی دو actor دارد:

1. فروشنده batch را آماده و با shop name و mobile یک submission می‌سازد.
2. ادمین در `/admin` با password، shop id و `base_product_rk` هر item را بررسی و حداکثر ۱۰۰ item را publish می‌کند.

درخواست فعال pending/submitting برای همان context دوباره ساخته نمی‌شود. هنگام publish، itemها باید متعلق به همان submission باشند. شکست provider submission و itemها را به failed می‌برد و پیام خام بیرونی به کاربر داده نمی‌شود.

تطبیق هوشمند واقعی محصول ترب هنوز کامل نیست؛ ورود دستی `base_product_rk` fallback فعلی است. نباید UI موجود را با موتور matching production اشتباه گرفت.

## ۱۴. transaction، concurrency و idempotency

سه مفهوم متفاوت‌اند:

- **Transaction:** چند تغییر DB یا همه commit می‌شوند یا rollback.
- **Idempotency:** تکرار یک فرمان اثر بیرونی تکراری ایجاد نکند.
- **Concurrency control:** دو actor همزمان invariant را نشکنند.

نمونه‌های فعلی:

- upload گروهی rollback DB و cleanup جبرانی فایل دارد.
- process و publish job فعال را reuse می‌کنند.
- frontend برای بعضی requestهای platform از sequence id استفاده می‌کند تا response قدیمی state جدید را overwrite نکند.
- SQLite و BackgroundTasks برای بار کم مناسب‌اند ولی lock توزیع‌شده، queue durable و exactly-once ندارند.

برای scale چند replica باید PostgreSQL، unique idempotency key، row locking یا optimistic version، object storage و queue worker اضافه شود.

## ۱۵. خطا و تجربه کاربر

خطا سه نمایش دارد:

| سطح | محتوا | مخاطب |
|---|---|---|
| UI | فارسی، کوتاه و دارای اقدام بعدی | فروشنده |
| domain/job | code و stage امن | API و dashboard |
| diagnostic | exception type، stack trace و provider status پاک‌سازی‌شده | توسعه‌دهنده/Sentry |

`api.ts` خطاهای شناخته‌شده مانند batch/asset/item not found را ترجمه می‌کند. اگر detail فارسی امن باشد می‌تواند نمایش داده شود؛ JSON یا متن انگلیسی ناشناخته به پیام عمومی تبدیل می‌شود.

Failure mode مهم: صرفاً catch کردن exception و نمایش «خطا شد» مشاهده‌پذیری نیست. باید مشخص باشد کدام action، stage، release و outcome شکست خورده، بدون اینکه داده کاربر ثبت شود.

## ۱۶. امنیت و حریم خصوصی

### threat boundary فعلی

- DSN Sentry secret مدیریتی نیست، اما auth token خواندن Sentry secret است.
- token OAuth و client secret فقط server-side هستند.
- frontend localStorage قابل دستکاری است؛ شناسه‌های آن input غیرقابل اعتمادند.
- `X-Admin-Password` کنترل ساده MVP است و جای RBAC/session امن را نمی‌گیرد.
- endpoint observability فقط با bearer read token و response allowlistشده قابل خواندن است.

### داده‌های ممنوع در telemetry

token، secret، authorization/cookie، موبایل، نام، title/description، transcript، voice، تصویر، payload کامل، query string و request/session id خام.

Sentry frontend با `sendDefaultPii=false` راه‌اندازی می‌شود؛ user/cookie/body حذف، query URL strip و headerهای حساس پاک می‌شوند. traces فعلاً صفر است. backend نیز event processor و structured logging امن دارد.

### مسئله چندکاربره

Seller/workspace فعلی isolation کاربردی ایجاد می‌کند اما احراز هویت production-grade نیست. قبل از چندکاربره واقعی باید principal معتبر، authorization روی تمام resourceها و testهای IDOR اضافه شود.

## ۱۷. مشاهده‌پذیری: از metric تا Black Box

Monitoring فقط گفتن «سایت بالا است یا نه» است؛ observability یعنی از خروجی‌های سیستم بتوانیم وضعیت داخلی و محل failure را استنتاج کنیم. سه پایه کلاسیک log، metric و trace هستند:

- **Log:** یک رخداد با جزئیات؛ مثلاً publish job شماره ۸۰ در stage ساخت محصول fail شد.
- **Metric:** عدد تجمیعی در زمان؛ مثلاً نرخ موفقیت upload در پنج دقیقه.
- **Trace:** زنجیره یک request میان componentها؛ request id فعلی correlation ساده می‌دهد، نه distributed tracing کامل.
- **Stack trace:** مسیر function callها تا exception؛ برای developer مفید و برای کاربر نامناسب است.
- **Telemetry:** نام کلی داده‌ای که برای مشاهده رفتار/سلامت فرستاده می‌شود.

چهار لایه مکمل داریم:

1. **Structured log:** جزئیات عملیاتی backend روی stdout/stderr.
2. **Sentry:** exception و stack trace frontend/backend.
3. **Clarity:** replay انسانی و aggregateهای رفتاری؛ منبع ثانویه.
4. **Product Black Box:** state transitionهای allowlistشده خود محصول؛ منبع اصلی برای مکان و علت.

### چرا Clarity به‌تنهایی کافی نیست؟

Data Export عمدتاً aggregate می‌دهد. «۴۰ dead click» نمی‌گوید handler کدام button چه stateای داشته است. replay برای انسان مفید است اما عامل نباید ویدئوی واقعی کاربر را دانلود یا با حدس تفسیر کند. بنابراین خود محصول control و outcome را ثبت می‌کند و Clarity فقط شدت و فراوانی را تقویت می‌کند.

### Black Box دقیقاً چیست؟

Black Box یک ضبط ویدئویی یا dump state نیست. یک دفتر ثبت گذارهای حالت با schema بسته است:

```json
{
  "event": "journey_step",
  "journey": "basalam_connect_restore",
  "journey_id": "uuid-random",
  "stage": "assets_restored",
  "outcome": "progress",
  "expected_asset_count": 4,
  "actual_asset_count": 4,
  "duration_ms": 380
}
```

Backend هر field اضافه، journey ناشناخته، stage خارج از قرارداد یا failure بدون reason امن را با validation رد می‌کند. شناسه journey بعداً از signal عمومی حذف/هش می‌شود تا گزارش عامل session قابل ردیابی انسانی نداشته باشد.

یک journey contract تعریف می‌کند:

- چه stageهایی باید وجود داشته باشند؛
- ترتیب مورد انتظار چیست؛
- terminal success چیست؛
- چه invariantهایی در هر stage سنجیده می‌شوند؛
- چه eventهایی اثبات failure هستند.

اگر contract پنج stage بخواهد ولی instrumentation فقط دو stage داشته باشد، «نمی‌دانیم» به `journey_observability_gap` تبدیل می‌شود. این signal باید به اقدام مهندسی برای افزودن telemetry/test منجر شود، نه حدس درباره کاربر.

### پوشش فعلی journeyها

Schema شش journey را می‌شناسد: مدیریت asset، ساخت catalog، ویرایش محصول، اتصال/restore باسلام، publish باسلام و submit ترب. اما audit فعلی فقط journey اتصال/restore باسلام را ۵ از ۵ کامل می‌داند. پنج مورد دیگر gap دارند. تعریف stage در schema به معنای emit شدن واقعی همه stageها نیست.

### eventهای مهم backend

- فوری: `http_request_failed`, `upload_batch_failed`, `basalam_publish_failed`
- بالا: `processing_job_failed`, `basalam_product_failed`
- UX/validation: `image_upload_rejected`, `basalam_publish_validation_failed`
- integration: `basalam_oauth_failed`, `torob_publish_failed`

## ۱۸. عامل نگه‌داری خودکار

عامل یک برنامه جدا روی Windows است، نه بخشی از request path محصول. Task Scheduler هر سه ساعت آن را اجرا می‌کند. مسیر state و گزارش:

```text
%LOCALAPPDATA%\BulkAddWithAi-agent\
├── state.json
├── agent.lock
├── cache/
├── worktrees/
├── dashboard/index.html
└── runs/<UTC-run-id>/
```

run id مانند `20260714T234702Z` زمان UTC با قالب `YYYYMMDDTHHMMSSZ` است؛ dashboard آن را به وقت تهران و مدت اجرا ترجمه می‌کند.

واژه‌های pipeline عامل:

- **Collector:** adapter فقط‌خواندنی یک منبع، مانند Sentry یا product event feed.
- **Sanitize:** حذف یا جایگزینی داده حساس پیش از ذخیره/ارسال به مدل.
- **Fingerprint:** شناسه پایدار ساخته‌شده از نوع و محل مسئله برای گروه‌بندی تکرارها.
- **Deduplicate:** یکی‌کردن signalهای دارای fingerprint یکسان و جمع‌کردن count.
- **Triage:** اولویت‌بندی اینکه کدام مسئله اول بررسی شود.
- **Portfolio:** انتخاب متنوع چند خانواده مشکل، تا پنج تکرار یک event همه ظرفیت را نگیرند.
- **Baseline:** وضعیت سالم source قبل از افزودن تست جدید.
- **Worktree:** checkout جداگانه Git که branch اصلی و فایل‌های باز کاربر را لمس نمی‌کند.
- **Gate:** شرط اجباری عبور، مثل سبزبودن تمام تست‌ها.

### pipeline واقعی اجرای زمان‌بندی‌شده

```text
[Windows Task Scheduler: every 3 hours]
                    |
                    v
            +-------+--------+
            | Is agent.lock  |
            | already held?  |
            +---+---------+--+
                |         |
              YES         NO
                |         |
                v         v
             [Exit]  [Collect all sources]
                              |
                              v
                    [Sanitize sensitive data]
                              |
                              v
                    [Deduplicate fingerprints]
                              |
                              v
                    [Rank max 5 event families]
                              |
                              v
                    [Create isolated worktree]
                              |
                              v
                    +---------+---------+
                    | Is baseline green?|
                    +----+----------+----+
                         |          |
                        NO         YES
                         |          |
                         v          v
                 [Stop diagnosis] [Codex may add tests only]
                                           |
                                           v
                                  +--------+---------+
                                  | Does new test    |
                                  | fail on source?  |
                                  +----+----------+--+
                                       |          |
                                      NO         YES
                                       |          |
                                       v          v
                             [insufficient]   [reproduced]
                                       \          /
                                        v        v
                                  [report + dashboard]
```

Baseline یعنی همه تست‌های موجود پیش از diagnosis سبز باشند. اگر base از قبل قرمز باشد، قرمزشدن تست جدید را نمی‌توان با اطمینان به candidate نسبت داد. Worktree یک checkout جدا از Git است، نه یک VM یا container؛ فایل‌های کد جدا هستند ولی CPU و سیستم‌عامل مشترک‌اند.

Collectorها: local logs، product event feed، Sentry، cache/API Clarity، health، UX contract، journey contract و browser probe deterministic.

Signalها fingerprint می‌شوند تا رخداد تکراری یک مسئله دوباره‌کاری نشود. portfolio ابتدا failureهای first-party و control دقیق را انتخاب می‌کند و اجازه نمی‌دهد یک event family هر پنج slot را پر کند. aggregate خالص Clarity پایین‌تر رتبه می‌گیرد.

### وضعیت دقیق autonomy فعلی

اجرای scheduler اکنون فقط **تشخیص** انجام می‌دهد:

- می‌تواند candidate بسازد؛
- می‌تواند در worktree جدا baseline را اجرا کند؛
- می‌تواند فقط test file اضافه کند؛
- فقط اگر تست روی کد فعلی قرمز شد، status را `reproduced` می‌گذارد؛
- خودش product source، branch یا PR نمی‌سازد.

تابع `attempt_fix` پیاده‌سازی شده و در simulation/جریان صریح قابل استفاده است، اما `run_once` زمان‌بندی‌شده آن را فراخوانی نمی‌کند. این guardrail عمدی است: اصلاح نیازمند دستور صریح انسان است.

### pipeline اصلاحِ مجازشده

```text
[Explicit human instruction to fix]
                  |
                  v
[New branch + worktree from origin/main]
                  |
                  v
[Run baseline gates: must be GREEN]
                  |
                  v
[Reproducer adds TEST FILES ONLY]
                  |
                  v
[Run relevant test: must be RED]
                  |
                  v
[Fixer changes smallest product code]
                  |
                  v
+-----------------+------------------+
| Test patch digest unchanged?       |-- NO --> [Reject]
+-----------------+------------------+
                  | YES
                  v
[Apply test alone to clean base: RED]
                  |
                  v
[Fixed tree: same test + all gates GREEN]
                  |
                  v
[Independent reviewer session]
                  |
                  v
+-----------------+------------------+
| Any medium/high finding?           |-- YES --> [Reject]
+-----------------+------------------+
                  | NO
                  v
[Push branch + open PR]
                  |
                  v
[Human merge and human deploy]
```

`policy.json` حداکثر ۸ فایل و ۵۰۰ خط تغییر را اجازه می‌دهد و workflow، policy/prompt/schema عامل، migration، model/config، integration، dependency، Docker و secretها را ممنوع کرده است.

### معنای exclusive lock و worktree

Lock یعنی دو **run کامل orchestrator** همزمان روی state/dashboard کار نکنند. worktree یعنی هر diagnosis یا fix checkout مستقل دارد و main checkout کاربر لمس نمی‌شود. از نظر فنی می‌توان چند worktree را parallel اجرا کرد، اما implementation فعلی diagnosisها را sequential اجرا می‌کند تا CPU/RAM، lock فایل‌های تست و نرخ API کنترل شود.

### retention و kill switch

- ایجاد فایل `PAUSED` در state root عامل را متوقف می‌کند.
- timeout policy سه ساعت است.
- گزارش عادی پس از ۳۰ روز حذف می‌شود.
- evidence مربوط به PR باز، rollback، failure یا diagnosis بازسازی‌شده محافظت می‌شود.
- state با write موقت و replace ذخیره می‌شود تا فایل نیمه‌نوشته کمتر ایجاد شود.

## ۱۹. داشبورد و خواندن یک گزارش

هر کارت باید پاسخ پنج سؤال را بدهد:

1. چه چیزی و چه زمانی مشاهده شد؟
2. evidence دقیق از کدام منبع آمد؟
3. آیا فقط signal است یا با تست بازسازی شده؟
4. خطر برای کاربر چیست؟
5. اقدام بعدی مشخص چیست؟

وضعیت‌ها را این‌گونه بخوان:

| وضعیت | ادعای مجاز |
|---|---|
| detected | سیگنال دیده شده؛ هنوز باگ اثبات نشده |
| insufficient_evidence | تست قرمز معتبر ساخته نشد |
| reproduced | تست regression روی source فعلی قرمز شد |
| fixed_in_test | fix همان تست را سبز و gateها را پاس کرد |
| ready_for_review | review قبول و PR باز شده |
| published | انسان deploy کرده؛ هنوز اثر production تأیید نشده |
| verified_in_production | پس از پنجره مشاهده، signal مرتبط برنگشته یا معیار بهبود یافته |

فایل‌های فنی مانند report JSON و log پاک‌سازی‌شده برای audit هستند؛ خلاصه انسانی نباید شما را مجبور به خواندن JSON کند.

## ۲۰. TDD و استراتژی تست

قاعده تغییر behavior:

```text
تعریف رفتار → نوشتن تست → اثبات قرمز → کوچک‌ترین fix → اثبات سبز → refactor → full gates
```

تست قرمز باید به علت درست fail شود. اگر test به خاطر setup خراب یا selector اشتباه fail شود، وجود باگ را اثبات نمی‌کند. سپس fixer اجازه تغییر test اثبات‌کننده را ندارد؛ digest patch قبل و بعد مقایسه می‌شود.

### لایه‌های تست

- unit: parser، validation، redaction و helperهای pure
- backend integration: endpoint + SQLite موقت + fake providers
- frontend component: state، validation، draft preservation و telemetry
- E2E Playwright: مسیر واقعی مرورگر desktop/mobile با API کنترل‌شده
- contract: schema event، journey coverage و provider payload
- smoke production: health و سناریوی کنترل‌شده غیرمخرب

فرمان‌های رسمی:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\run

cd ..\frontend
npm test
npm run build
npm run e2e

cd ..
git diff --check
```

AI behavior ابتدا با fake deterministic تست می‌شود. test suite نباید برای assertion اصلی به شبکه یا پاسخ احتمالی مدل واقعی وابسته باشد.

## ۲۱. CI، release و rollback

روی PR و main، backend tests، automation tests، frontend tests/build/E2E و diff check اجرا می‌شوند. روی push غیر-PR image به GHCR فرستاده می‌شود. CI موفق یعنی artifact قابل بررسی ساخته شده؛ به معنی deploy یا موفقیت business flow واقعی نیست.

Release درست:

1. commit و PR کوچک با evidence.
2. تمام gateها سبز.
3. review انسانی و در تغییر خودکار review مستقل.
4. merge انسانی.
5. یافتن tag دقیق build همان commit.
6. تغییر دستی tag در Darkube/Hamravesh.
7. health و smoke.
8. مشاهده Sentry/event/Black Box.
9. در regression، بازگشت به image tag قبلی؛ migration ناسازگار در scope خودکار نیست.

## ۲۲. راهنمای عیب‌یابی عملی

### «عکس انتخاب می‌شود ولی چیزی دیده نمی‌شود»

1. eventهای picker را به ترتیب opened → files_selected بررسی کن.
2. نبود files_selected یعنی picker cancel/مرورگر؛ وجود آن یعنی مسیر upload آغاز شده.
3. `ui_action_failed` یا `http_request_failed` را با control/path ببین.
4. backend `image_upload_rejected` یا `upload_batch_failed` و request id را بررسی کن.
5. فایل fake با format/size مشابه بساز و test قرمز اضافه کن.

### «بعد از اتصال غرفه داده پرید»

1. snapshot قبل redirect باید batch/assets/items count داشته باشد.
2. پنج stage journey را بررسی کن.
3. اولین stage missing یا failed مرز خطاست.
4. seller mismatch با count mismatch فرق دارد؛ اولی امنیت/ownership، دومی restore/data است.
5. E2E باید draft typed، redirect mock، reload و حفظ دقیق valueها را assert کند.

### «ثبت باسلام ناموفق شد»

1. ابتدا validation frontend و backend را جدا کن.
2. اگر side effect شروع نشده، PublishedProductهای validation را بخوان.
3. اگر partial failure است، نتایج موفق را حفظ کن.
4. status/category rejection را از metadata امن و Sentry بررسی کن.
5. payload خام یا token را هرگز برای debug log نکن.

### «AI خروجی بد داد»

1. مشخص کن schema failure است یا semantic error.
2. ورودی را با assetهای synthetic و transcript غیرشخصی بازسازی کن.
3. fake provider test برای رفتار orchestration بنویس.
4. prompt/schema change، model change و dependency در محدوده عامل خودکار نیستند و review انسانی می‌خواهند.

## ۲۳. چگونه یک تغییر را مهندسی کنیم

مثال: «حذف عکس از product card».

1. invariant بنویس: حذف join نباید فایل متعلق به batch یا itemهای دیگر را حذف کند.
2. actor و precondition: item و asset باید وجود و ownership مشترک داشته باشند.
3. API contract: route، status، response و خطا.
4. ابتدا service/API test قرمز.
5. سپس component test برای update UI و rollback optimistic failure.
6. E2E برای مسیر کاربر.
7. journey stage و outcome امن اضافه کن؛ title/image را telemetry نکن.
8. کوچک‌ترین implementation را انجام بده.
9. full gates و threat review.
10. release/rollback و معیار production را تعریف کن.

پرسش‌های review سنیور:

- source of truth کجاست؟
- اگر request دوبار برسد چه می‌شود؟
- اگر process وسط DB commit و filesystem operation بمیرد چه می‌شود؟
- آیا resource متعلق به همین seller/workspace است؟
- آیا شکست provider draft را حفظ می‌کند؟
- چه evidenceای ثابت می‌کند رفتار production درست شد؟
- آیا log برای تشخیص کافی و در عین حال بدون PII است؟
- آیا پاسخ قدیمی async می‌تواند state جدید UI را overwrite کند؟
- rollback code/image/data چیست؟

## ۲۴. بدهی فنی و مسیر بلوغ

### محدودیت‌های واقعی فعلی

- persistence بدون volume تضمین‌شده نیست.
- authentication و authorization چندکاربره production-grade نداریم.
- SQLite و BackgroundTasks برای multi-replica/durable jobs کافی نیستند.
- `App.tsx` بیش از حد مسئولیت دارد.
- پوشش Black Box پنج journey از شش journey تعریف‌شده ناقص است.
- عامل scheduled تشخیص می‌دهد، خودکار fix نمی‌کند.
- Clarity aggregate به‌تنهایی مکان و علت باگ را اثبات نمی‌کند.
- matching خودکار واقعی ترب کامل نیست.
- operational event store با database همان container به persistence آن وابسته است.

### ترتیب منطقی بلوغ

1. تکمیل journey instrumentation و تست contract برای مسیرهای حیاتی.
2. persistence مطمئن یا انتقال DB/file به سرویس‌های پایدار.
3. authentication/authorization و ownership server-side.
4. durable queue و idempotency key برای process/publish.
5. شکستن frontend به state machine/hook و feature moduleها.
6. metricهای SLO: نرخ موفقیت upload، build، restore و publish و latency هر stage.
7. canary و verification production مبتنی بر release.
8. فقط پس از نرخ تشخیص درست و rollback پایین، افزایش محدود autonomy اصلاح.

هیچ سیستمی نمی‌تواند «تمام باگ‌های قابل تصور دنیا» را تضمینی پیدا کند. هدف مهندسی قابل دفاع این است که برای هر مسیر مهم contract، invariant، telemetry، test و failure budget داشته باشیم و هر «نمی‌دانیم» ثبت‌شده، backlog مشخص برای بستن نقطه کور بسازد.

## ۲۵. نقشه مطالعه کد

برای تسلط تدریجی این ترتیب را دنبال کن:

1. `models.py` و این سند: اسم‌ها و ownership.
2. `schemas.py`: مرز معتبر ورودی/خروجی.
3. `services.py`: upload، processing و حفظ ویرایش.
4. `platform_services.py`: OAuth، category و publish.
5. `App.tsx` همراه `api.ts`: state و request flow.
6. `telemetry.ts` و `observability.py`: evidence و privacy.
7. تست متناظر هر behavior؛ تست‌ها معمولاً قرارداد دقیق‌تر از comment هستند.
8. `automation/runner.py`: تفاوت detect، prove، fix و publish PR.

وقتی یک تابع را می‌خوانی، فقط «چه می‌کند» نپرس. input معتبر، side effect، transaction boundary، retry، idempotency، data owner، failure state، telemetry و test آن را هم پیدا کن. این شیوه خواندن، تفاوت میان آشنایی با syntax و تسلط مهندسی بر سیستم است.

## ۲۶. خلاصه تصمیم‌های معماری

| تصمیم | دلیل | هزینه/محدودیت |
|---|---|---|
| batch به‌عنوان aggregate اصلی | حفظ ارتباط عکس، صدا، item و job | aggregate بزرگ و نیازمند ownership سخت‌گیرانه |
| fake AI deterministic | TDD سریع و ارزان | کیفیت مدل واقعی را اندازه نمی‌گیرد |
| strict JSON schema | کاهش خروجی آزاد مدل | semantic correctness همچنان نیازمند review/test است |
| platform data جدا | جلوگیری از نشت باسلام/ترب | mapping و merge پیچیده‌تر |
| job + polling | پاسخ سریع HTTP | بدون queue durable در restart آسیب‌پذیر است |
| structured event + Sentry + Black Box | تشخیص دقیق بدون PII | instrumentation باید برای هر journey تکمیل شود |
| Clarity به‌عنوان secondary | رفتار انسانی را نشان می‌دهد | export aggregate علت دقیق را ثابت نمی‌کند |
| worktree ایزوله | checkout کاربر لمس نمی‌شود | مصرف disk/setup بیشتر |
| scheduled diagnosis-only | جلوگیری از تغییر حدسی production | fix نیازمند دستور انسان است |
| merge/deploy انسانی | کنترل blast radius | زمان پاسخ کاملاً خودکار نیست |

این سیستم را باید به‌عنوان مجموعه‌ای از قراردادها دید: قرارداد داده، ownership، transition، provider، خطا، telemetry و release. هر feature زمانی کامل است که همه این قراردادها با هم سازگار و با تست قابل اثبات باشند.
