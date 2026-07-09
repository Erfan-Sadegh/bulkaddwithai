import base64
import json
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings
from .models import Asset
from .schemas import AiExtraction, AiProduct


class CategoryCandidate(BaseModel):
    id: int
    title: str
    path: str
    confidence: float | None = None


class CategoryChoice(BaseModel):
    candidate_id: int | None
    confidence: float = Field(ge=0, le=1)
    reason: str = ""


class CategoryChoiceRequest(BaseModel):
    item_key: str
    title: str
    description: str = ""
    candidates: list[CategoryCandidate]


class CategoryChoiceResult(BaseModel):
    item_key: str
    candidate_id: int | None
    confidence: float = Field(ge=0, le=1)
    reason: str = ""


class ProductSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    price_toman: int | None
    stock: int | None
    preparation_days: int | None
    weight_grams: int | None
    package_weight_grams: int | None
    unit_quantity: int | None
    confidence: float = Field(ge=0, le=1)
    image_numbers: list[int]


class ExtractionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str | None
    products: list[ProductSchema]
    metadata: dict


class CategoryChoiceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: int | None
    confidence: float = Field(ge=0, le=1)
    reason: str


class CategoryChoicesSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choices: list[CategoryChoiceResult]


AVALAI_EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": ["string", "null"]},
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "price_toman": {"type": ["integer", "null"]},
                    "stock": {"type": ["integer", "null"]},
                    "preparation_days": {"type": ["integer", "null"]},
                    "weight_grams": {"type": ["integer", "null"]},
                    "package_weight_grams": {"type": ["integer", "null"]},
                    "unit_quantity": {"type": ["integer", "null"]},
                    "confidence": {"type": "number"},
                    "image_numbers": {"type": "array", "items": {"type": "integer"}},
                },
                "required": [
                    "title",
                    "description",
                    "price_toman",
                    "stock",
                    "preparation_days",
                    "weight_grams",
                    "package_weight_grams",
                    "unit_quantity",
                    "confidence",
                    "image_numbers",
                ],
                "additionalProperties": False,
            },
        },
        "metadata": {
            "type": "object",
            "properties": {
                "currency_assumption": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["currency_assumption", "warnings"],
            "additionalProperties": False,
        },
    },
    "required": ["transcript", "products", "metadata"],
    "additionalProperties": False,
}


AVALAI_CATEGORY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": ["integer", "null"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["candidate_id", "confidence", "reason"],
    "additionalProperties": False,
}


AVALAI_CATEGORY_BATCH_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "candidate_id": {"type": ["integer", "null"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["item_key", "candidate_id", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["choices"],
    "additionalProperties": False,
}


def _validate_category_choice_result(
    request: CategoryChoiceRequest, result: CategoryChoiceResult
) -> CategoryChoiceResult:
    candidate_ids = {candidate.id for candidate in request.candidates}
    if result.candidate_id is not None and result.candidate_id not in candidate_ids:
        return CategoryChoiceResult(
            item_key=request.item_key,
            candidate_id=None,
            confidence=0.0,
            reason="AI selected an unknown candidate",
        )
    return result


class AiProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: Asset | None) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def extract_products(self, images: list[Asset], transcript: str | None) -> AiExtraction:
        raise NotImplementedError

    @abstractmethod
    def choose_basalam_category(
        self, title: str, description: str, candidates: list[CategoryCandidate]
    ) -> CategoryChoice:
        raise NotImplementedError

    def choose_basalam_categories(
        self, requests: list[CategoryChoiceRequest]
    ) -> list[CategoryChoiceResult]:
        return [
            CategoryChoiceResult(
                item_key=request.item_key,
                **self.choose_basalam_category(
                    request.title, request.description, request.candidates
                ).model_dump(),
            )
            for request in requests
        ]


class FakeAiProvider(AiProvider):
    def transcribe(self, audio: Asset | None) -> str | None:
        if not audio:
            return None
        return "ویس تستی: عکس ۱ و ۲ یک محصول هستند و قیمت آن ۱۲۳۰۰۰ تومان است."

    def extract_products(self, images: list[Asset], transcript: str | None) -> AiExtraction:
        products: list[AiProduct] = []
        remaining = sorted(images, key=lambda asset: asset.upload_order)
        if len(remaining) >= 2:
            first_two = remaining[:2]
            products.append(
                AiProduct(
                    title="محصول تستی گروه‌شده",
                    description="این محصول از دو عکس اول ساخته شده و برای تست pipeline است.",
                    price_toman=123000 if transcript else None,
                    stock=None,
                    preparation_days=None,
                    weight_grams=None,
                    package_weight_grams=None,
                    unit_quantity=None,
                    confidence=0.86,
                    image_numbers=[asset.upload_order for asset in first_two],
                )
            )
            remaining = remaining[2:]
        for asset in remaining:
            products.append(
                AiProduct(
                    title=f"محصول عکس {asset.upload_order}",
                    description=f"توضیح پیشنهادی برای عکس شماره {asset.upload_order}.",
                    price_toman=None,
                    stock=None,
                    preparation_days=None,
                    weight_grams=None,
                    package_weight_grams=None,
                    unit_quantity=None,
                    confidence=0.72,
                    image_numbers=[asset.upload_order],
                )
            )
        return AiExtraction(
            transcript=transcript,
            products=products,
            metadata={"provider": "fake", "note": "deterministic local provider"},
        )

    def choose_basalam_category(
        self, title: str, description: str, candidates: list[CategoryCandidate]
    ) -> CategoryChoice:
        if not candidates:
            return CategoryChoice(candidate_id=None, confidence=0.0, reason="no candidates")
        best = candidates[0]
        return CategoryChoice(
            candidate_id=best.id,
            confidence=best.confidence or 0.0,
            reason="fake provider chooses top candidate",
        )


class AvalAiProvider(AiProvider):
    def __init__(self, settings: Settings):
        if not settings.avalai_api_key:
            raise RuntimeError("AVALAI_API_KEY is not set")
        self.settings = settings
        self.client = OpenAI(api_key=settings.avalai_api_key, base_url=settings.avalai_base_url)

    def transcribe(self, audio: Asset | None) -> str | None:
        if not audio:
            return None
        with open(audio.file_path, "rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                model=self.settings.avalai_stt_model,
                file=audio_file,
                language="fa",
                response_format="text",
                prompt="فروشنده فارسی درباره محصولات، شماره عکس‌ها و قیمت‌ها صحبت می‌کند.",
            )
        return _transcription_text(result)

    def extract_products(self, images: list[Asset], transcript: str | None) -> AiExtraction:
        if not images:
            return AiExtraction(transcript=transcript, products=[], metadata={"provider": "avalai"})

        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    "از تصاویر شماره‌دار محصولات فروشنده و متن ویس، محصولات را استخراج کن. "
                    "چند عکس می‌تواند متعلق به یک محصول یا چند رنگ/مدل از یک محصول باشد؛ اگر فروشنده گفت عکس‌ها یکی هستند، همان‌ها را در یک product گروه کن. "
                    "قیمت‌ها معمولاً فقط در متن ویس گفته می‌شوند؛ قیمت هر بخش از ویس را به محصول همان شماره عکس وصل کن و فقط به خاطر نبودن قیمت در تصویر، price_toman را null نگذار. "
                    "شماره عکس فقط برای اتصال عکس به محصول است؛ هرگز در title یا description ننویس «عکس شماره»، «محصول شماره»، «شماره ۱ و ۲» یا توضیح عملیاتی مشابه. "
                    "title باید برای جستجوی خریدار مناسب باشد و description فقط ویژگی‌های قابل فروش محصول را بگوید، نه یادداشت‌های پردازشی یا حرف‌های فروشنده درباره یکی بودن عکس‌ها. "
                    "قیمت را به تومان نرمال کن: «سی هزار» یعنی 30000، «دویست هزار» یعنی 200000، «۳۰۰ تومن» در ادبیات فروشنده یعنی 300000، «۹۰۰ تومن» یعنی 900000، و «۱ تومن/یک تومن/یه تومن» یعنی 1000000. "
                    "اگر فروشنده عدد قیمت را گفته، آن را معتبر بدان؛ فقط وقتی هیچ قیمت مرتبطی گفته نشده null بده. عددهای کوتاه رایج فروشنده‌ای را صفر کمتر ذخیره نکن. "
                    "stock، preparation_days، weight_grams، package_weight_grams و unit_quantity را حدس نزن. فقط اگر فروشنده در ویس صریحاً گفته بود مقدار بده؛ در غیر این صورت null بگذار. "
                    "preparation_days یعنی چند روز تا آماده‌سازی/ارسال. weight_grams و package_weight_grams همیشه به گرم باشند. "
                    "عبارت‌هایی مثل «موجودی ۵ تا»، «زمان آماده‌سازی ۲ روز»، «وزن محصول ۳۰۰ گرم»، «وزن با بسته‌بندی ۵۰۰ گرم» و «چندتایی می‌فروشی ۱ واحد» را به فیلدهای عملیاتی متناظر تبدیل کن. "
                    "confidence را بین 0 و 1 بده. metadata.currency_assumption را درباره تومان/ریال پر کن. "
                ),
            },
            {
                "type": "text",
                "text": (
                    "متن کامل ویس فروشنده برای اتصال قیمت و توضیح به شماره عکس‌ها:\n"
                    f"{transcript or 'ویس وجود ندارد.'}"
                ),
            },
        ]
        for asset in sorted(images, key=lambda item: item.upload_order):
            content.append(
                {
                    "type": "text",
                    "text": f"تصویر شماره {asset.upload_order}: {asset.original_filename}",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_data_url(Path(asset.file_path), asset.mime_type),
                        "detail": "low",
                    },
                }
            )

        response = self.client.chat.completions.create(
            model=self.settings.avalai_vision_model or self.settings.avalai_text_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "تو دستیار ساخت کاتالوگ محصول برای فروشنده حضوری هستی. "
                        "خروجی را دقیقاً مطابق JSON schema بده. فارسی، کوتاه، فروشگاهی و قابل ویرایش بنویس. "
                        "اطلاعات داخلی مثل شماره عکس و گروه‌بندی را فقط در image_numbers نگه دار، نه در متن محصول."
                    ),
                },
                {"role": "user", "content": content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "catalog_batch_extraction_v1",
                    "strict": True,
                    "schema": AVALAI_EXTRACTION_JSON_SCHEMA,
                }
            },
        )
        try:
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                raise RuntimeError(f"AI refused extraction: {message.refusal}")
            data = json.loads(message.content or "{}")
            parsed = ExtractionSchema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"AI returned invalid extraction JSON: {exc}") from exc

        return AiExtraction(
            transcript=parsed.transcript,
            products=[
                AiProduct(
                    title=product.title,
                    description=product.description,
                    price_toman=product.price_toman,
                    stock=product.stock,
                    preparation_days=product.preparation_days,
                    weight_grams=product.weight_grams,
                    package_weight_grams=product.package_weight_grams,
                    unit_quantity=product.unit_quantity,
                    confidence=product.confidence,
                    image_numbers=product.image_numbers,
                )
                for product in parsed.products
            ],
            metadata={"provider": "avalai", "model": self.settings.avalai_vision_model, **parsed.metadata},
        )

    def choose_basalam_category(
        self, title: str, description: str, candidates: list[CategoryCandidate]
    ) -> CategoryChoice:
        if not candidates:
            return CategoryChoice(candidate_id=None, confidence=0.0, reason="no candidates")
        candidate_payload = [
            {
                "id": candidate.id,
                "title": candidate.title,
                "path": candidate.path,
                "score": candidate.confidence,
            }
            for candidate in candidates[:20]
        ]
        response = self.client.chat.completions.create(
            model=self.settings.avalai_text_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "تو فقط دسته‌بندی باسلام را برای یک محصول فروشگاهی انتخاب می‌کنی. "
                        "حتماً فقط از candidate_idهای داده‌شده انتخاب کن و هرگز دسته جدید نساز. "
                        "اگر هیچ candidate واقعاً مناسب نیست، candidate_id را null بگذار. "
                        "هدف کم‌کردن زحمت فروشنده سنتی است، اما ثبت محصول در دسته اشتباه بدتر از پرسیدن از کاربر است."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "محصول:\n"
                        f"title: {title}\n"
                        f"description: {description or '-'}\n\n"
                        "candidateهای واقعی باسلام:\n"
                        f"{json.dumps(candidate_payload, ensure_ascii=False)}\n\n"
                        "اگر title یا description با path یک candidate واضحاً مرتبط است، همان را انتخاب کن. "
                        "برای محصولات کالای دیجیتال مثل ایرپاد، هندزفری، اسپیکر، شارژر، قاب، ساعت و مچ‌بند هوشمند، "
                        "مسیرهای کالای دیجیتال و لوازم جانبی را به دسته‌های عمومی مثل خانه و آشپزخانه یا سرگرمی ترجیح بده."
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "basalam_category_choice_v1",
                    "strict": True,
                    "schema": AVALAI_CATEGORY_JSON_SCHEMA,
                },
            },
        )
        try:
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                raise RuntimeError(f"AI refused category choice: {message.refusal}")
            parsed = CategoryChoiceSchema.model_validate(json.loads(message.content or "{}"))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"AI returned invalid category choice JSON: {exc}") from exc

        candidate_ids = {candidate.id for candidate in candidates}
        if parsed.candidate_id is not None and parsed.candidate_id not in candidate_ids:
            return CategoryChoice(candidate_id=None, confidence=0.0, reason="AI selected an unknown candidate")
        return CategoryChoice(
            candidate_id=parsed.candidate_id,
            confidence=parsed.confidence,
            reason=parsed.reason,
        )

    def choose_basalam_categories(
        self, requests: list[CategoryChoiceRequest]
    ) -> list[CategoryChoiceResult]:
        if not requests:
            return []
        payload = [
            {
                "item_key": request.item_key,
                "title": request.title,
                "description": request.description or "",
                "candidates": [
                    {
                        "id": candidate.id,
                        "title": candidate.title,
                        "path": candidate.path,
                        "score": candidate.confidence,
                    }
                    for candidate in request.candidates[:20]
                ],
            }
            for request in requests
        ]
        response = self.client.chat.completions.create(
            model=self.settings.avalai_text_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "تو دسته‌بندی باسلام را برای چند محصول فروشگاهی انتخاب می‌کنی. "
                        "برای هر item_key دقیقاً یک choice بده. "
                        "فقط از candidate_idهای همان item انتخاب کن و هرگز دسته جدید نساز. "
                        "اگر هیچ candidate واقعاً مناسب نیست، candidate_id را null بگذار. "
                        "هدف کاهش زحمت فروشنده سنتی است، اما ثبت محصول در دسته اشتباه بدتر از پرسیدن از کاربر است."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "برای هر محصول از بین candidateهای واقعی باسلام انتخاب کن:\n"
                        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
                        "برای کالاهای دیجیتال مثل ایرپاد، هندزفری، اسپیکر، شارژر، قاب، ساعت و مچ‌بند هوشمند، "
                        "مسیرهای کالای دیجیتال و لوازم جانبی را به دسته‌های عمومی مثل خانه و آشپزخانه یا سرگرمی ترجیح بده."
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "basalam_category_batch_choice_v1",
                    "strict": True,
                    "schema": AVALAI_CATEGORY_BATCH_JSON_SCHEMA,
                },
            },
        )
        try:
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                raise RuntimeError(f"AI refused category choice: {message.refusal}")
            parsed = CategoryChoicesSchema.model_validate(json.loads(message.content or "{}"))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"AI returned invalid category choice JSON: {exc}") from exc

        result_by_key = {result.item_key: result for result in parsed.choices}
        return [
            _validate_category_choice_result(
                request,
                result_by_key.get(
                    request.item_key,
                    CategoryChoiceResult(
                        item_key=request.item_key,
                        candidate_id=None,
                        confidence=0.0,
                        reason="AI did not return a choice for this item",
                    ),
                ),
            )
            for request in requests
        ]


def get_ai_provider(settings: Settings) -> AiProvider:
    if settings.ai_provider == "fake":
        return FakeAiProvider()
    if settings.ai_provider == "avalai":
        return AvalAiProvider(settings)
    if settings.avalai_api_key:
        return AvalAiProvider(settings)
    return FakeAiProvider()


def _image_data_url(path: Path, mime_type: str | None) -> str:
    guessed_type = mime_type or mimetypes.guess_type(path.name)[0] or "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{guessed_type};base64,{payload}"


def _transcription_text(result: object) -> str:
    if isinstance(result, str):
        raw = result.strip()
    else:
        text = getattr(result, "text", None)
        if text:
            return str(text).strip()
        if hasattr(result, "model_dump"):
            dumped = result.model_dump()
            if isinstance(dumped, dict) and dumped.get("text"):
                return str(dumped["text"]).strip()
        if isinstance(result, dict) and result.get("text"):
            return str(result["text"]).strip()
        raw = str(result).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict) and parsed.get("text"):
        return str(parsed["text"]).strip()
    return raw
