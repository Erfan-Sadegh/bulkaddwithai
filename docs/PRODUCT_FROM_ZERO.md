# BulkAddWithAI از صفر: داده، جدول‌ها و منطق کسب‌وکار

این سند برای خواننده‌ای نوشته شده که هیچ دانش قبلی درباره برنامه‌نویسی، دیتابیس، شبکه یا معماری نرم‌افزار ندارد. هر مفهوم ابتدا ساده، سپس فنی و بعد با مثال واقعی همین محصول توضیح داده می‌شود.

## ۱. نقشه ذهنی بسیار ساده محصول

کاربر عکس و ویس می‌دهد. برنامه از آن‌ها محصول پیشنهادی می‌سازد. کاربر محصول را اصلاح می‌کند و سپس آن را به مسیر باسلام یا ترب می‌برد.

```text
Photos + Voice
      |
      v
Create editable products
      |
      v
Human review and correction
      |
      +---------------------+
      |                     |
      v                     v
Basalam direct publish    Torob reviewed submission
```

مسیر تا ساخته‌شدن محصولات میان باسلام و ترب مشترک است. تفاوت اصلی بعد از آماده‌شدن محصول‌ها شروع می‌شود.

## ۲. فایل‌سیستم و دیتابیس چه تفاوتی دارند؟

### ۲.۱ فایل‌سیستم

فایل‌سیستم همان پوشه‌ها و فایل‌های روی هارد است:

```text
C:\
├── Users\
├── Pictures\
└── data\
    ├── photo.jpg
    └── voice.webm
```

در server ما نیز عکس و ویس به‌صورت فایل واقعی ذخیره می‌شوند. مسیر production:

```text
/data/uploads/<batch-id>/<asset-type>/<generated-name>
```

مثال:

```text
/data/uploads/42/image/0001.jpg
/data/uploads/42/image/0002.jpg
/data/uploads/42/audio/0001.webm
```

نام دقیق ممکن است برای جلوگیری از برخورد فایل‌ها suffix اضافه داشته باشد، اما ساختار پوشه همین است.

### ۲.۲ دیتابیس

دیتابیس اطلاعات مرتب و قابل جست‌وجو را در table یا «جدول» نگه می‌دارد:

```text
TABLE: assets

+-----+----------+-------+-----------------------------------------+
| id  | batch_id | type  | file_path                               |
+-----+----------+-------+-----------------------------------------+
| 101 | 42       | image | /data/uploads/42/image/0001.jpg         |
| 102 | 42       | audio | /data/uploads/42/audio/0001.webm        |
+-----+----------+-------+-----------------------------------------+
```

خود بایت‌های عکس و ویس در این جدول نیستند. جدول فقط می‌گوید فایل کجاست و به چه Batchی تعلق دارد.

### ۲.۳ SQLite چیست؟

SQLite نرم‌افزار مدیریت دیتابیس ماست. کل tableها را داخل یک فایل نگه می‌دارد:

```text
/data/catalog.db
```

پس `catalog.db` از دید سیستم‌عامل یک فایل است، اما محتوای آن ساختار دیتابیس دارد.

```text
/data/
├── catalog.db          <- tables and rows
└── uploads/            <- real image and audio bytes
```

### ۲.۴ چرا عکس و ویس را داخل دیتابیس نگذاشتیم؟

فایل‌های رسانه‌ای بزرگ‌اند. نگه‌داری آن‌ها در filesystem برای MVP ساده‌تر است و دیتابیس را برای اطلاعات ساختاریافته نگه می‌دارد. در معماری بزرگ‌تر، فایل‌ها معمولاً وارد Object Storage مانند S3 می‌شوند و دیتابیس همچنان فقط آدرس را نگه می‌دارد.

### ۲.۵ خطر دو محل ذخیره‌سازی

SQLite و filesystem یک transaction مشترک واقعی ندارند. ممکن است:

```text
Database row exists, but file is missing.

OR

File exists, but database row is missing.
```

حالت دوم orphan file یا «فایل بی‌صاحب» است. کد هنگام شکست تلاش می‌کند هم database را rollback کند و هم فایل نوشته‌شده را پاک کند، اما crash ناگهانی می‌تواند پیش از cleanup رخ دهد.

## ۳. ویس دقیقاً کجا و چگونه ذخیره می‌شود؟

### ۳.۱ در مرورگر

کاربر اجازه microphone می‌دهد. `MediaRecorder` مرورگر صدا را ضبط می‌کند. format به قابلیت مرورگر وابسته است:

- Chrome معمولاً WebM/Opus؛
- Safari ممکن است MP4/M4A؛
- بعضی مرورگرها OGG یا format دیگر پشتیبانی‌شده.

frontend پسوند جعلی تحمیل نمی‌کند؛ MIME type و پسوند واقعی recorder را حفظ می‌کند. فایل خالی نیز نباید upload شود.

### ۳.۲ انتقال به backend

ویس از همان endpoint عمومی assetها ارسال می‌شود که عکس‌ها از آن استفاده می‌کنند:

```text
POST /batches/42/assets
Content-Type: multipart/form-data
```

backend از MIME type یا پسوند تشخیص می‌دهد که فایل `audio` است.

### ۳.۳ در فایل‌سیستم backend

کد مسیر زیر را می‌سازد:

```text
<UPLOAD_DIR>/<batch_id>/audio/
```

در production با تنظیم فعلی:

```text
/data/uploads/42/audio/0001.webm
```

برای جلوگیری از فایل نصفه، بایت‌ها ابتدا در یک فایل موقت مانند زیر نوشته می‌شوند:

```text
/data/uploads/42/audio/.<random-id>.upload
```

اگر فایل خالی نباشد، فایل موقت به نام نهایی منتقل می‌شود. عکس normalize می‌شود، اما audio با format واقعی خودش نگه داشته می‌شود.

### ۳.۴ در دیتابیس

یک row در جدول `assets` ساخته می‌شود:

```text
id                = 104
batch_id          = 42
type              = audio
upload_order      = 1
file_path         = /data/uploads/42/audio/0001.webm
original_filename = voice.webm
mime_type         = audio/webm
size_bytes        = 183204
checksum          = <sha256>
```

`checksum` یک اثر انگشت محاسباتی از محتوای فایل است. خود صدا از checksum قابل بازسازی نیست.

### ۳.۵ هنگام AI کدام ویس انتخاب می‌شود؟

ProcessingJob تمام Assetهای صوتی همان Batch را می‌خواند، آن‌ها را بر اساس `upload_order` از جدید به قدیم مرتب می‌کند و جدیدترین ویس را انتخاب می‌کند:

```text
Audio upload_order=1  old
Audio upload_order=2  new  <-- selected for transcription
```

سپس فایل از `audio.file_path` باز و به سرویس transcription فرستاده می‌شود.

### ۳.۶ متن ویس کجا می‌رود؟

خود فایل ویس در filesystem می‌ماند. متن استخراج‌شده در ستون زیر روی Batch ذخیره می‌شود:

```text
batches.raw_transcript
```

متن ویس داده حساس است و نباید وارد log، Sentry، داشبورد عامل یا telemetry شود.

### ۳.۷ نکته طراحی فعلی هنگام ضبط دوباره

frontend بعد از ضبط جدید، ویس قبلی را از state نمایشی خودش کنار می‌گذارد. backend ممکن است row صوتی قبلی را همچنان نگه دارد؛ ProcessingJob جدیدترین `upload_order` را استفاده می‌کند. بنابراین رفتار پردازش درست است، ولی cleanup ویس‌های قدیمی می‌تواند یک بهبود آینده باشد.

## ۴. مفاهیم ابتدایی جدول

### ۴.۱ Table، row و column

Table شبیه یک sheet مرتب است. هر سطر یک نمونه و هر ستون یک ویژگی است.

```text
TABLE: batches

+----+-----------+--------------+
| id | seller_id | status       |
+----+-----------+--------------+
| 42 | 7         | upload_ready |
| 43 | 7         | ready        |
+----+-----------+--------------+
```

- table: کل `batches`؛
- row: Batch شماره ۴۲؛
- column: مثلاً `status`.

### ۴.۲ Primary Key

Primary Key یا PK شناسه یکتای هر row است:

```text
batches.id = 42
```

دو Batch نمی‌توانند همزمان id برابر ۴۲ داشته باشند.

### ۴.۳ Foreign Key

Foreign Key یا FK به row جدول دیگر اشاره می‌کند:

```text
batches.seller_id = 7
```

یعنی Batch شماره ۴۲ متعلق به Seller شماره ۷ است.

### ۴.۴ NULL و صفر

`NULL` یعنی مقدار هنوز وجود ندارد یا نامشخص است. صفر یک مقدار واقعی است.

```text
stock = NULL  -> موجودی هنوز تکمیل نشده
stock = 0     -> محصول واقعاً ناموجود است
```

یکی‌گرفتن این دو باعث خطای کسب‌وکار می‌شود.

## ۵. Table، SQLAlchemy Model، Pydantic Schema و Payload یکی نیستند

### ۵.۱ SQLAlchemy Model

کلاسی در `models.py` که `__tablename__` دارد به table دیتابیس وصل است:

```python
class BatchItem(Base):
    __tablename__ = "batch_items"
```

`BatchItem` مدل table واقعی `batch_items` است.

### ۵.۲ Pydantic Schema

Schema شکل مجاز داده ورودی یا خروجی API است:

```python
class BatchItemPatch(BaseModel):
    title: str | None
    price_toman: int | None
```

`BatchItemPatch` table نیست. هیچ row مستقلی برای آن ذخیره نمی‌شود. فقط request ویرایش را بررسی می‌کند.

```text
Browser JSON
      |
      v
BatchItemPatch validates shape and values
      |
      v
update_item applies business rules
      |
      v
BatchItem row changes in database
```

### ۵.۳ Validation

Validation یعنی بررسی معتبر بودن داده یا عملیات.

Schema validation:

```json
{"price_toman": "hello"}
```

رد می‌شود چون price باید عدد باشد.

Business validation:

```json
{"asset_ids": [101, 999]}
```

ممکن است شکل داده درست باشد، ولی اگر Asset شماره ۹۹۹ متعلق به Batch دیگری باشد service آن را رد می‌کند.

### ۵.۴ Payload

Payload پیام نهایی است که از شبکه برای سرویس دیگر ارسال می‌شود. هیچ table خامی مستقیماً به باسلام یا ترب ارسال نمی‌شود. کد چند table را می‌خواند و payload مخصوص مقصد را می‌سازد.

## ۶. Uvicorn، FastAPI، ASGI، Dependency و Replica

### ۶.۱ Uvicorn

Uvicorn processی است که روی پورت شبکه منتظر HTTP request می‌ماند و آن را به برنامه FastAPI می‌دهد.

```text
Browser -> Uvicorn -> FastAPI -> Endpoint -> Service
Browser <- Uvicorn <- FastAPI <- Response <- Service
```

FastAPI route و validation را تعریف می‌کند؛ Uvicorn آن را واقعاً به شبکه وصل می‌کند.

### ۶.۲ ASGI

ASGI قرارداد استاندارد میان Python web server و web framework است:

```text
Uvicorn ---- ASGI contract ---- FastAPI
```

مثل استاندارد دوشاخه و پریز است. برای توسعه معمول این محصول لازم نیست ASGI بنویسیم.

### ۶.۳ Dependency

Dependency یعنی چیزی که یک بخش برای کارش لازم دارد. `update_item` برای خواندن و نوشتن محصول به DB Session نیاز دارد؛ آن Session dependency تابع است. کتابخانه FastAPI نیز dependency نرم‌افزاری کل پروژه است. معنی دقیق کلمه به context بستگی دارد.

### ۶.۴ Dependency Injection

FastAPI می‌تواند Session آماده را به endpoint بدهد، به‌جای اینکه endpoint خودش connection بسازد. این کار test را ساده می‌کند چون Session آزمایشی می‌تواند جای واقعی قرار گیرد.

### ۶.۵ Replica

Replica یک نمونه درحال اجرای دیگر از همان برنامه است:

```text
                   +--> Replica A
Requests -> Router |
                   +--> Replica B
```

چند replica فقط وقتی درست‌اند که storage مشترک داشته باشند. دو container با دو SQLite مستقل داده یکسان نمی‌بینند. معماری چند replica معمولاً database مشترک و object storage مشترک می‌خواهد.

## ۷. فهرست کامل tableهای فعلی

سیستم فعلی ۱۳ table دارد:

| table | مشترک یا اختصاصی؟ | مسئولیت |
|---|---|---|
| `sellers` | مشترک | صاحب Batchها و اتصال‌ها |
| `batches` | مشترک | یک نوبت ساخت catalog |
| `assets` | مشترک | metadata عکس و ویس |
| `processing_jobs` | مشترک | یک تلاش پردازش AI |
| `batch_items` | مشترک | محصول مرکزی قابل ویرایش |
| `batch_item_assets` | مشترک | اتصال محصول به عکس‌ها |
| `batch_item_platform_data` | ساختار generic؛ فعلاً عمدتاً باسلام | داده نسبتاً پایدار محصول برای یک پلتفرم |
| `platform_connections` | فعلاً باسلام | اتصال OAuth و credential غرفه |
| `publish_jobs` | فعلاً باسلام | وضعیت کل عملیات انتشار |
| `published_products` | فعلاً باسلام | نتیجه هر محصول منتشرشده |
| `torob_submissions` | ترب | یک تلاش/درخواست کلی ترب |
| `torob_submission_items` | ترب | تصمیم و نتیجه هر item در همان درخواست |
| `operational_events` | مشترک | evidence فنی پاک‌سازی‌شده |

«مشترک» یعنی قبل از جداشدن مسیر باسلام و ترب استفاده می‌شود. «اختصاصی» یعنی lifecycle آن فقط متعلق به workflow همان پلتفرم است.

## ۸. رابطه tableهای مشترک

سناریو:

- Seller شماره ۷؛
- Batch شماره ۴۲؛
- عکس‌های ۱۰۱، ۱۰۲ و ۱۰۳؛
- یک ویس ۱۰۴؛
- محصول کیف ۵۰۱؛
- محصول کفش ۵۰۲.

```text
Seller 7
   |
   v
Batch 42
   |
   +-- Asset 101: image #1
   +-- Asset 102: image #2
   +-- Asset 103: image #3
   +-- Asset 104: latest audio
   +-- ProcessingJob 90
   +-- BatchItem 501: bag
   +-- BatchItem 502: shoes
```

AI تشخیص داده عکس ۱ و ۲ کیف و عکس ۳ کفش است. جدول واسط:

```text
TABLE: batch_item_assets

+---------------+----------+------------+
| batch_item_id | asset_id | sort_order |
+---------------+----------+------------+
| 501           | 101      | 0          |
| 501           | 102      | 1          |
| 502           | 103      | 0          |
+---------------+----------+------------+
```

ویس وارد `batch_item_assets` نمی‌شود چون آن جدول برای عکس محصول است. ویس به Batch تعلق دارد و برای استخراج اطلاعات همه محصول‌ها استفاده می‌شود.

## ۹. چرا این مدل مشترک انتخاب شده است؟

### Seller بالاتر از Batch

یک فروشنده چند نوبت کاری دارد:

```text
Seller 7
├── Batch 42: bags
├── Batch 43: shoes
└── Batch 44: scarves
```

### Asset جدا از BatchItem

هنگام upload هنوز نمی‌دانیم عکس‌ها چگونه محصول می‌شوند. ابتدا Assetها ساخته می‌شوند؛ بعد AI یا کاربر link آن‌ها به BatchItem را تعیین می‌کند.

### ProcessingJob جدا از Batch

یک Batch ممکن است چند attempt داشته باشد:

```text
ProcessingJob 90 -> failed
ProcessingJob 91 -> succeeded
```

Job جدا تاریخچه و retry را قابل فهم می‌کند.

### BatchItemAsset به‌عنوان table واسط

محصول می‌تواند چند عکس داشته باشد و هر اتصال ترتیب خودش را دارد. merge و split linkها را جابه‌جا می‌کنند، نه فایل واقعی را.

## ۱۰. منطق کسب‌وکار مشترک از ابتدا تا محصول آماده

Business logic یعنی قوانین واقعی محصول، نه صرفاً جزئیات فنی.

```text
Resolve Seller/Workspace
        |
        v
Create Batch
        |
        v
Upload images and optional audio
        |
        v
Create/reuse ProcessingJob
        |
        v
Transcribe latest audio
        |
        v
Extract products from images + transcript
        |
        v
Match products to assets
        |
        v
Preserve human edits
        |
        v
Human review / merge / split / reorder
        |
        +------------------+
        |                  |
        v                  v
Basalam workflow       Torob workflow
```

قوانین اصلی:

1. یک Batch باید حداقل یک عکس برای پردازش داشته باشد.
2. double-click نباید ProcessingJob تکراری فعال بسازد.
3. خطای AI نباید عکس، ویس یا draft را حذف کند.
4. اطلاعاتی که کاربر ویرایش کرده نباید بی‌اجازه با AI overwrite شود.
5. asset مربوط به Batch دیگر نباید وارد item شود.
6. هر عکس استفاده‌نشده باید fallback product بگیرد تا گم نشود.

## ۱۱. آخر چه چیزی به باسلام ارسال می‌شود؟

هیچ row یا object خامی مستقیماً ارسال نمی‌شود.

### ۱۱.۱ upload عکس‌ها

backend فایل عکس را از `Asset.file_path` باز و به API فایل باسلام می‌فرستد. باسلام یک photo id می‌دهد:

```text
Our Asset 101 -> Basalam photo 8801
Our Asset 102 -> Basalam photo 8802
```

### ۱۱.۲ جمع‌کردن داده محصول

برای Item شماره ۵۰۱ کد این منابع را می‌خواند:

```text
BatchItem
  title, description, price, stock, preparation, weights, quantity

BatchItemAsset -> Asset
  ordered photos

BatchItemPlatformData(platform=basalam)
  category and unit information

PlatformConnection
  booth identity and OAuth token
```

سپس `BasalamProductPayload` می‌سازد:

```json
{
  "name": "کیف چرمی قهوه‌ای",
  "description": "کیف دست‌دوز چرمی",
  "primary_price": 4200000,
  "photo": 8801,
  "photos": [8801, 8802],
  "category_id": 123,
  "stock": 5,
  "preparation_days": 2,
  "weight": 600,
  "package_weight": 750,
  "unit_quantity": 1,
  "unit_type": 1,
  "status": 2976,
  "is_wholesale": false
}
```

قیمت database تومان و payload باسلام ریال است، پس در مرز integration در ۱۰ ضرب می‌شود.

```text
BatchItem is not sent.
BatchItemAsset is not sent.

Several rows are read and transformed into one provider-specific payload.
```

## ۱۲. مسیر ترب: کدام tableها واقعاً داریم؟

این بخش تفاوت «table مشترک»، «table قابل استفاده برای چند پلتفرم» و «table اختصاصی ترب» را دقیق می‌کند.

### ۱۲.۱ tableهای مشترکی که ترب نیز استفاده می‌کند

#### `batches`

ترب از همان Batch کاتالوگ استفاده می‌کند. Batch مخصوص باسلام نیست.

#### `assets`

عکس و ویس مسیر ترب نیز Asset هستند. فایل جداگانه یا table اختصاصی عکس ترب نداریم.

#### `processing_jobs`

محصول مسیر ترب با همان AI pipeline مشترک ساخته می‌شود. ProcessingJob قبل از انشعاب پلتفرم اتفاق می‌افتد، پس ProcessingJob اختصاصی ترب لازم نیست.

#### `batch_items`

عنوان، توضیح و قیمت اصلی محصول ترب نیز از همان BatchItem می‌آید.

#### `batch_item_assets`

ترب این table را دارد و استفاده می‌کند؛ اما table مشترک است، نه tableی با نام Torob.

```text
TorobSubmissionItem
        |
        | batch_item_id
        v
BatchItem
        |
        | asset_links
        v
BatchItemAsset
        |
        | asset_id
        v
Asset -> image URL for admin UI
```

تابع تبدیل submission به response ادمین، `BatchItem.asset_links` را مرتب می‌کند و `image_numbers` و `image_urls` را می‌سازد. پس پنل ادمین ترب عکس‌ها را از رابطه مشترک می‌بیند.

### ۱۲.۲ table generic پلتفرم که فعلاً برای ترب استفاده عملی ندارد

`batch_item_platform_data` ستون `platform` دارد و از نظر ساختار می‌تواند row زیر داشته باشد:

```text
batch_item_id = 501
platform      = torob
```

اما implementation فعلی برای ترب چنین rowای ایجاد یا مصرف نمی‌کند. فیلدهای موجود آن عمدتاً برای category باسلام طراحی و استفاده شده‌اند.

پس جمله دقیق:

> table generic وجود دارد، ولی داده workflow ترب در نسخه فعلی داخل آن ذخیره نمی‌شود.

این تفاوت مهم است: «قابلیت ساختاری» با «رفتار پیاده‌سازی‌شده» یکی نیست.

### ۱۲.۳ tableهای اختصاصی ترب

دو table اختصاصی داریم:

```text
torob_submissions
torob_submission_items
```

#### `torob_submissions`

نماینده یک تلاش کلی برای یک Batch و فروشگاه است:

```text
id             = 300
seller_id      = 7
batch_id       = 42
shop_name      = فروشگاه علی
contact_mobile = ...
status         = pending
shop_id        = NULL initially
admin_note     = NULL initially
```

#### `torob_submission_items`

هر row یک BatchItem را در همان Submission نمایندگی می‌کند:

```text
id              = 400
submission_id   = 300
batch_item_id   = 501
base_product_rk = NULL initially
price           = 420000
status          = pending
```

قیمت هنگام ساخت Submission از BatchItem کپی می‌شود. ادمین بعداً می‌تواند `base_product_rk` و price همان تلاش را تغییر دهد.

## ۱۳. چرا عکس ترب را دوباره در table اختصاصی کپی نکردیم؟

رابطه عکس از قبل اینجاست:

```text
BatchItem 501 -> BatchItemAsset -> Asset 101, 102
```

اگر دوباره رابطه زیر را بسازیم:

```text
TorobSubmissionItem -> TorobSubmissionItemAsset -> Asset
```

دو نسخه از grouping عکس خواهیم داشت. ممکن است یکی تغییر کند و دیگری نه. استفاده از رابطه مشترک duplication را کم می‌کند.

### محدودیت صریح طراحی فعلی

`TorobSubmissionItem` فقط به BatchItem زنده اشاره می‌کند. title، description و photo linkها را کامل snapshot نمی‌کند. در response ادمین، این موارد از BatchItem فعلی خوانده می‌شوند.

پس اگر پس از ساخت Submission، BatchItem یا عکس‌هایش تغییر کنند، پنل ادمین ممکن است نسخه جدید را ببیند. اگر requirement این باشد که Submission یک سند تاریخی کاملاً immutable باشد، طراحی فعلی کافی نیست.

راه‌های آینده:

1. کپی title، description و photo ids هنگام ساخت Submission؛
2. ساخت `torob_submission_item_assets`؛
3. یا ممنوع‌کردن edit Batch پس از ورود Submission به review.

انتخاب میان آن‌ها به requirement تاریخی، هزینه storage و UX ویرایش بستگی دارد.

## ۱۴. چرا ProcessingJob اختصاصی ترب نداریم؟

ProcessingJob مشترک وظیفه ساخت محصول از عکس/ویس را دارد:

```text
Assets -> ProcessingJob -> BatchItems -> platform workflows
```

ترب دوباره عکس را با AI پردازش نمی‌کند؛ از BatchItem آماده استفاده می‌کند.

برای ارسال نهایی ترب نیز `TorobPublishJob` جدا نداریم. عملیات فعلی synchronous است:

```text
Admin publish click
      |
      v
Submission = submitting
      |
      v
Call Torob bulk_add
      |
      +-- success -> submitted
      +-- failure -> failed
```

اگر ارسال طولانی، پرتعداد یا نیازمند retry durable شود، اضافه‌کردن `TorobPublishJob` منطقی خواهد بود.

## ۱۵. چرا `base_product_rk` داخل PlatformData نیست؟

در مدل فعلی `base_product_rk` تصمیم یک Submission مشخص است، نه ویژگی قطعی و همیشگی BatchItem.

```text
Submission 300: Item 501 -> base_product_rk=A
Submission 301: Item 501 -> base_product_rk=B
```

اگر تنها یک مقدار در `BatchItemPlatformData(platform=torob)` ذخیره شود، Submission دوم مقدار اول را overwrite می‌کند و تاریخچه از بین می‌رود.

مدل آینده می‌تواند هر دو را داشته باشد:

```text
TorobSubmissionItem
  history and result of each attempt

BatchItemPlatformData(platform=torob)
  latest approved canonical mapping
```

اما بخش دوم فعلاً پیاده‌سازی نشده است.

## ۱۶. چرا Submission از Batch جداست؟

Batch پاسخ می‌دهد:

> از این عکس‌ها و ویس چه محصول‌هایی ساخته شدند؟

Submission پاسخ می‌دهد:

> در این تلاش مشخص چه محصول‌هایی با چه فروشگاه، تماس، تطبیق و نتیجه‌ای به ترب رفتند؟

```text
Batch 42: ready
├── ProcessingJob 90: succeeded
├── TorobSubmission 300: failed
└── TorobSubmission 301: submitted
```

این stateها تناقض ندارند. Catalog موفق ساخته شده، اما تلاش اول ترب شکست خورده است.

اگر status ترب داخل Batch قرار گیرد، `failed` مبهم می‌شود: آیا AI، upload، باسلام یا ترب شکست خورده؟ جداکردن lifecycleها ابهام را کم می‌کند و تاریخچه چند تلاش را حفظ می‌کند.

## ۱۷. Payload واقعی ترب چیست؟

Admin برای هر Submission، shop id و itemهای منتخب را می‌فرستد. backend ownership آن itemها را بررسی می‌کند و payload API ترب را می‌سازد:

```json
{
  "bulk_product_adding_key": "<secret>",
  "shop_id": 900,
  "items": [
    {
      "base_product_rk": "torob-product-123",
      "price": 420000
    },
    {
      "base_product_rk": "torob-product-456",
      "price": 680000
    }
  ]
}
```

API فعلی `bulk_add` عکس، title یا description را نمی‌گیرد. عکس‌ها فقط در پنل ادمین خود ما برای تطبیق انسانی نمایش داده می‌شوند.

```text
Admin review data:
BatchItem + BatchItemAsset + Asset + TorobSubmissionItem

Actual Torob network payload:
shop_id + base_product_rk + price
```

## ۱۸. چرا یک table JSON عظیم برای همه پلتفرم‌ها نساختیم؟

می‌توانستیم table مبهمی بسازیم:

```text
platform_operations
├── platform
├── operation_type
├── status
└── data_json
```

اما باسلام و ترب فقط نام پلتفرم متفاوت ندارند؛ actor، credential، validation، side effect و lifecycle متفاوت دارند.

مشکلات JSON عمومی:

- database نمی‌تواند وجود fieldهای لازم را خوب enforce کند؛
- Foreign Keyها ضعیف می‌شوند؛
- query و گزارش سخت‌تر است؛
- typo و شکل‌های ناسازگار راحت‌تر وارد می‌شوند؛
- statusها معنای مبهم پیدا می‌کنند.

طراحی فعلی hybrid است:

```text
SHARED CORE
Seller, Batch, Asset, ProcessingJob, BatchItem, BatchItemAsset

GENERIC STABLE PROJECTION
BatchItemPlatformData

BASALAM WORKFLOW
PlatformConnection, PublishJob, PublishedProduct

TOROB WORKFLOW
TorobSubmission, TorobSubmissionItem
```

قاعده:

> داده‌هایی که واقعاً یک معنا و lifecycle مشترک دارند مشترک‌اند؛ فرآیندهایی که فقط ظاهراً شبیه‌اند ولی قانون متفاوت دارند جدا هستند.

## ۱۹. خلاصه نهایی اینکه چه چیزی ارسال می‌شود

```text
                         SHARED DATABASE MODEL

Assets <--> BatchItemAsset <--> BatchItem
                                  |
                 +----------------+----------------+
                 |                                 |
                 v                                 v
         BASALAM ASSEMBLY                  TOROB ASSEMBLY
         PlatformData                      TorobSubmissionItem
         PlatformConnection                shop_id
         uploaded photo ids                base_product_rk
                 |                         price
                 v                                 |
       BasalamProductPayload                       v
                                        Torob bulk_add payload
```

نه Batch، نه BatchItem و نه join table به‌صورت خام ارسال نمی‌شوند. Integration داده‌های لازم را می‌خواند، تبدیل واحد و mapping انجام می‌دهد و payload مخصوص قرارداد مقصد را می‌سازد.

## ۲۰. پرامپت پیشنهادی برای توضیحات بعدی

```text
فرض کن من از نظر فنی کاملاً مبتدی هستم و هیچ اصطلاحی را از قبل نمی‌دانم.

موضوع را مثل یک مربی صبور از صفر آموزش بده، اما در نهایت تا سطح مهندسی عمیق جلو برو.

هر مفهوم را به این ترتیب بگو:
1. تعریف خیلی ساده
2. تعریف فنی
3. مثال واقعی از همین پروژه
4. محل آن در کد
5. دلیل انتخاب طراحی
6. مشکلات و جایگزین‌های احتمالی

هیچ اصطلاح تخصصی را بدون تعریف استفاده نکن. تفاوت table، model، schema، payload، class و database row را صریح بگو. یک سناریو را با idهای فرضی مرحله‌به‌مرحله دنبال کن. دقیقاً بگو چه چیزی ذخیره و چه چیزی از شبکه ارسال می‌شود. برای رابطه‌ها دیاگرام متنی LTR بساز و تک‌تک فلش‌ها را توضیح بده. هیچ دانش قبلی از برنامه‌نویسی، شبکه، دیتابیس یا معماری از من فرض نکن.
```
