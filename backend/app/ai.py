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


class ProductSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    price_toman: int | None
    confidence: float = Field(ge=0, le=1)
    image_numbers: list[int]


class ExtractionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str | None
    products: list[ProductSchema]
    metadata: dict


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
                    "confidence": {"type": "number"},
                    "image_numbers": {"type": "array", "items": {"type": "integer"}},
                },
                "required": [
                    "title",
                    "description",
                    "price_toman",
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


class AiProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: Asset | None) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def extract_products(self, images: list[Asset], transcript: str | None) -> AiExtraction:
        raise NotImplementedError


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
                    confidence=0.72,
                    image_numbers=[asset.upload_order],
                )
            )
        return AiExtraction(
            transcript=transcript,
            products=products,
            metadata={"provider": "fake", "note": "deterministic local provider"},
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
                    confidence=product.confidence,
                    image_numbers=product.image_numbers,
                )
                for product in parsed.products
            ],
            metadata={"provider": "avalai", "model": self.settings.avalai_vision_model, **parsed.metadata},
        )


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
