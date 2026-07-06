import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Mic,
  Pause,
  RotateCcw,
  Save,
  Send,
  Sparkles,
  SplitSquareHorizontal,
  Store,
  Upload,
} from 'lucide-react';
import type { ChangeEvent, MutableRefObject } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE, api } from './lib/api';
import type { Asset, BasalamCategory, Batch, Job, PlatformConnection, ProductItem, PublishedProduct, PublishJob, Seller } from './lib/types';

type ProductDraft = Pick<ProductItem, 'title' | 'description'> & {
  price_toman: string;
  stock: string;
  preparation_days: string;
  weight_grams: string;
  package_weight_grams: string;
  unit_quantity: string;
};
type DraftMap = Record<number, ProductDraft>;
const BASALAM_AUTO_CATEGORY_THRESHOLD = 0.62;
const PHOTO_GROUP_WARNING_THRESHOLD = 0.65;

const jobLabels: Record<Job['step'], string> = {
  upload_ready: 'آماده شروع',
  transcribing: 'در حال خواندن صدا',
  vision_extracting: 'در حال بررسی عکس‌ها',
  matching: 'در حال ساخت لیست محصولات',
  ready: 'لیست آماده است',
  failed: 'ساخت لیست ناموفق بود',
};

const publishLabels: Record<PublishJob['step'], string> = {
  uploading_photos: 'در حال فرستادن عکس‌ها به باسلام',
  creating_products: 'در حال ثبت محصول‌ها در غرفه',
  ready: 'ثبت در غرفه تمام شد',
  failed: 'ثبت در غرفه ناموفق بود',
};

export function App() {
  const [seller, setSeller] = useState<Seller | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [items, setItems] = useState<ProductItem[]>([]);
  const [drafts, setDrafts] = useState<DraftMap>({});
  const [connections, setConnections] = useState<PlatformConnection[]>([]);
  const [publishJob, setPublishJob] = useState<PublishJob | null>(null);
  const [publishedProducts, setPublishedProducts] = useState<PublishedProduct[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [booting, setBooting] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [savingList, setSavingList] = useState(false);
  const [suggestingCategories, setSuggestingCategories] = useState(false);
  const [connectingBasalam, setConnectingBasalam] = useState(false);
  const [publishingBasalam, setPublishingBasalam] = useState(false);
  const [savingShop, setSavingShop] = useState(false);
  const [splittingPhotoKey, setSplittingPhotoKey] = useState<string | null>(null);
  const [freshConfirmOpen, setFreshConfirmOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);
  const resultsAutoScrolledRef = useRef(false);

  const imageAssets = useMemo(
    () => assets.filter((asset) => asset.type === 'image').sort((a, b) => a.upload_order - b.upload_order),
    [assets],
  );
  const audioAssets = useMemo(() => assets.filter((asset) => asset.type === 'audio'), [assets]);
  const basalamConnection = useMemo(
    () => connections.find((connection) => connection.platform === 'basalam' && connection.status === 'connected') ?? null,
    [connections],
  );

  useEffect(() => {
    bootstrapWorkspace();
  }, []);

  useEffect(() => {
    if (!job || job.status === 'succeeded' || job.status === 'failed') return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await api.getJob(job.id);
        setJob(nextJob);
        if (nextJob.status === 'succeeded' && batch) {
          await loadItemsWithCategorySuggestions(batch.id);
          setProcessing(false);
        }
        if (nextJob.status === 'failed') {
          setProcessing(false);
        }
      } catch (err) {
        setProcessing(false);
        setError(err instanceof Error ? err.message : 'وضعیت پردازش خوانده نشد. دوباره تلاش کن.');
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [batch, job]);

  useEffect(() => {
    if (!publishJob || ['succeeded', 'partial_failed', 'failed'].includes(publishJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await api.getPublishJob(publishJob.id);
        setPublishJob(nextJob);
        if (['succeeded', 'partial_failed', 'failed'].includes(nextJob.status)) {
          setPublishingBasalam(false);
          if (batch) {
            setPublishedProducts(await api.listPublishedProducts(batch.id));
          }
          if (nextJob.status === 'succeeded') showToast('محصول‌ها در غرفه باسلام ثبت شدند.');
          if (nextJob.status === 'partial_failed') showToast('بعضی محصول‌ها ثبت نشدند. پایین لیست را چک کن.');
        }
      } catch (err) {
        setPublishingBasalam(false);
        setError(err instanceof Error ? err.message : 'وضعیت ثبت در باسلام خوانده نشد. دوباره تلاش کن.');
      }
    }, 1100);
    return () => window.clearInterval(timer);
  }, [batch, publishJob]);

  useEffect(() => {
    if (items.length === 0) {
      setDrafts({});
      return;
    }
    setDrafts(buildDrafts(items));
    if (resultsAutoScrolledRef.current) return;
    resultsAutoScrolledRef.current = true;
    window.setTimeout(() => {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
  }, [items]);

  async function bootstrapWorkspace() {
    setBooting(true);
    setError(null);
    try {
      const oauthResult = readBasalamReturn();
      const sellers = await api.listSellers();
      const oauthSeller = oauthResult?.sellerId
        ? sellers.find((candidate) => candidate.id === oauthResult.sellerId)
        : null;
      const currentSeller = oauthSeller ?? sellers[0] ?? (await api.createSeller({}));
      if (oauthResult?.status === 'success') showToast('غرفه باسلام وصل شد.');
      if (oauthResult?.status === 'failed') setError('اتصال غرفه باسلام انجام نشد. دوباره تلاش کن.');
      const currentBatch = await api.createBatch(currentSeller.id);
      const currentConnections = await api.listPlatformConnections(currentSeller.id).catch(() => []);
      setSeller(currentSeller);
      setBatch(currentBatch);
      setConnections(Array.isArray(currentConnections) ? currentConnections : []);
      setAssets([]);
      setItems([]);
      setDrafts({});
      resultsAutoScrolledRef.current = false;
      setPublishedProducts([]);
      setPublishJob(null);
      setJob(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'صفحه آماده نشد. دوباره تلاش کن.');
    } finally {
      setBooting(false);
    }
  }

  async function startFreshList() {
    if (!seller) return;
    setFreshConfirmOpen(false);
    setProcessing(false);
    setUploading(false);
    setError(null);
    try {
      const created = await api.createBatch(seller.id);
      setBatch(created);
      setAssets([]);
      setItems([]);
      setDrafts({});
      resultsAutoScrolledRef.current = false;
      setPublishedProducts([]);
      setPublishJob(null);
      setJob(null);
      showToast('صفحه برای محصولات جدید آماده شد.');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'شروع دوباره ناموفق بود.');
    }
  }

  async function upload(files: File[]) {
    if (!batch || files.length === 0) return;
    if (items.length > 0) {
      setError('برای عکس‌های جدید، اول روی «افزودن محصولات جدید» بزن.');
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const uploaded = await api.uploadAssets(batch.id, files);
      const hasNewAudio = uploaded.some((asset) => asset.type === 'audio');
      setAssets((current) => {
        const base = hasNewAudio ? current.filter((asset) => asset.type !== 'audio') : current;
        return [...base, ...uploaded].sort((a, b) => a.type.localeCompare(b.type) || a.upload_order - b.upload_order);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'فایل‌ها اضافه نشدند. دوباره امتحان کن.');
    } finally {
      setUploading(false);
    }
  }

  async function processBatch() {
    if (!batch || imageAssets.length === 0) return;
    setProcessing(true);
    setError(null);
    resultsAutoScrolledRef.current = false;
    try {
      const result = await api.processBatch(batch.id);
      const firstJob = await api.getJob(result.job_id);
      setJob(firstJob);
      if (firstJob.status === 'succeeded') {
        await loadItemsWithCategorySuggestions(batch.id);
        setProcessing(false);
      }
      if (firstJob.status === 'failed') {
        setProcessing(false);
      }
    } catch (err) {
      setProcessing(false);
      setError(err instanceof Error ? err.message : 'پردازش انجام نشد. فایل‌ها باقی مانده‌اند و می‌توانی دوباره تلاش کنی.');
    }
  }

  async function saveShopInfo(payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) {
    if (!seller) return;
    setSavingShop(true);
    setError(null);
    try {
      const saved = await api.updateSeller(seller.id, payload);
      setSeller(saved);
      showToast('اطلاعات فروشگاه ذخیره شد.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'اطلاعات فروشگاه ذخیره نشد.');
    } finally {
      setSavingShop(false);
    }
  }

  async function persistDrafts() {
    setSavingList(true);
    setError(null);
    try {
      const savedItems = await Promise.all(
        items.map((item) => {
          const draft = drafts[item.id];
          if (!draft) return item;
          return api.updateItem(item.id, {
            title: draft.title.trim() || item.title,
            description: draft.description,
            price_toman: parsePersianPrice(draft.price_toman),
            stock: parseNullableInt(draft.stock),
            preparation_days: parseNullableInt(draft.preparation_days),
            weight_grams: parseNullableInt(draft.weight_grams),
            package_weight_grams: parseNullableInt(draft.package_weight_grams),
            unit_quantity: parseNullableInt(draft.unit_quantity),
          });
        }),
      );
      setItems(savedItems);
      return savedItems;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تغییرات محصول‌ها ثبت نشد. دوباره تلاش کن.');
      return null;
    } finally {
      setSavingList(false);
    }
  }

  async function loadItemsWithCategorySuggestions(batchId: number) {
    const readyItems = await api.listItems(batchId);
    setItems(readyItems);
    setSuggestingCategories(true);
    try {
      const suggestedItems = await api.suggestBasalamCategories(batchId);
      setItems(suggestedItems);
    } catch {
      setItems(readyItems);
    } finally {
      setSuggestingCategories(false);
    }
  }

  async function selectBasalamCategory(itemId: number, category: BasalamCategory) {
    setError(null);
    try {
      const updated = await api.setBasalamCategory(itemId, category.id);
      setItems((current) => current.map((item) => (item.id === itemId ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'دسته‌بندی محصول ذخیره نشد.');
    }
  }

  async function connectBasalam() {
    if (!seller) return;
    setConnectingBasalam(true);
    setError(null);
    try {
      const result = await api.getBasalamOAuthUrl(seller.id);
      if (!result.url) throw new Error(result.error || 'اتصال باسلام هنوز تنظیم نشده است.');
      window.location.href = result.url;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'لینک اتصال باسلام ساخته نشد.');
      setConnectingBasalam(false);
    }
  }

  async function publishToBasalam() {
    if (!batch) return;
    if (!basalamConnection) {
      await connectBasalam();
      return;
    }
    setPublishingBasalam(true);
    setError(null);
    try {
      const saved = await persistDrafts();
      if (!saved) return;
      const started = await api.publishToBasalam(batch.id);
      const firstJob = await api.getPublishJob(started.job_id);
      setPublishJob(firstJob);
      if (['succeeded', 'partial_failed', 'failed'].includes(firstJob.status)) {
        setPublishingBasalam(false);
        setPublishedProducts(await api.listPublishedProducts(batch.id));
      }
    } catch (err) {
      setPublishingBasalam(false);
      setError(err instanceof Error ? err.message : 'ثبت محصول‌ها در باسلام انجام نشد.');
    }
  }

  async function splitPhoto(itemId: number, assetId: number) {
    if (!batch) return;
    const key = `${itemId}-${assetId}`;
    setSplittingPhotoKey(key);
    setError(null);
    try {
      await api.splitItem(itemId, [assetId]);
      setItems(await api.listItems(batch.id));
      showToast('عکس به‌عنوان محصول جدا نمایش داده شد.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'عکس جدا نشد. دوباره تلاش کن.');
    } finally {
      setSplittingPhotoKey(null);
    }
  }

  function updateDraft(itemId: number, patch: Partial<ProductDraft>) {
    setDrafts((current) => ({ ...current, [itemId]: { ...current[itemId], ...patch } }));
  }

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 1800);
  }

  const hasPhotos = imageAssets.length > 0;
  const canProcess = hasPhotos && !uploading && !processing && items.length === 0;

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <h1>محصولاتت رو با عکس و وُیس به فروشگاهت اضافه کن</h1>
        </div>
      </header>

      {error && (
        <div className="error" role="alert">
          <strong>مشکلی پیش آمد.</strong>
          <span>{error}</span>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}

      {booting ? (
        <LoadingPanel label="در حال آماده‌سازی صفحه" />
      ) : (
        <section className="workspace">
          <UploadPanel
            images={imageAssets}
            audios={audioAssets}
            uploading={uploading}
            uploadDisabled={items.length > 0 || processing}
            voiceDisabled={items.length > 0 || uploading || processing}
            onUpload={upload}
          />

          {seller && (
            <aside className="side-rail">
              <BasalamPanel
                connection={basalamConnection}
                connecting={connectingBasalam}
                onConnect={connectBasalam}
              />
              <ShopInfoPanel seller={seller} saving={savingShop} onSave={saveShopInfo} />
            </aside>
          )}

          {(processing || job?.status === 'failed') && (
            <ProgressPanel
              job={job}
              processing={processing}
              canRetry={Boolean(job?.status === 'failed' && hasPhotos)}
              onRetry={processBatch}
            />
          )}

          {hasPhotos && items.length === 0 && (
            <div className="sticky-action">
              <button className="button primary action-button" type="button" onClick={processBatch} disabled={!canProcess}>
                {processing ? <Loader2 className="spin" size={19} /> : <Sparkles size={19} />}
                {processing ? 'در حال ساخت لیست' : 'ساخت لیست محصولات با هوش مصنوعی'}
              </button>
            </div>
          )}

          <PreviewPanel
            refNode={resultsRef}
            batch={batch}
            items={items}
            drafts={drafts}
            saving={savingList}
            suggestingCategories={suggestingCategories}
            publishing={publishingBasalam}
            basalamConnected={Boolean(basalamConnection)}
            publishJob={publishJob}
            publishedProducts={publishedProducts}
            splittingPhotoKey={splittingPhotoKey}
            onDraftChange={updateDraft}
            onApplyPreparationDays={(days) => {
              setDrafts((current) =>
                Object.fromEntries(
                  items.map((item) => [
                    item.id,
                    {
                      ...(current[item.id] ?? toDraft(item)),
                      preparation_days: String(days),
                    },
                  ]),
                ),
              );
            }}
            onSelectBasalamCategory={selectBasalamCategory}
            onPublishBasalam={publishToBasalam}
            onSplitPhoto={splitPhoto}
            onAskStartFresh={() => setFreshConfirmOpen(true)}
          />
        </section>
      )}

      {freshConfirmOpen && (
        <ConfirmDialog
          title="محصولات جدید اضافه می‌کنی؟"
          body="اگر ادامه بدهی، صفحه برای عکس‌های جدید خالی می‌شود. لیست آماده‌شده قبلی پاک نمی‌شود."
          confirmLabel="بله، صفحه را خالی کن"
          cancelLabel="نه، برگرد"
          onConfirm={startFreshList}
          onCancel={() => setFreshConfirmOpen(false)}
        />
      )}

    </main>
  );
}

function UploadPanel({
  images,
  audios,
  uploading,
  uploadDisabled,
  voiceDisabled,
  onUpload,
}: {
  images: Asset[];
  audios: Asset[];
  uploading: boolean;
  uploadDisabled: boolean;
  voiceDisabled: boolean;
  onUpload: (files: File[]) => void;
}) {
  function handleFileInput(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    onUpload(files);
  }

  return (
    <section className="panel upload-panel">
      <div className="upload-head">
        <div>
          <h2>عکس محصولات</h2>
          <p>هرچی محصول داری می‌تونی عکسش رو بذاری.</p>
        </div>
        {images.length > 0 && (
          <label className={`button primary file-button ${uploadDisabled ? 'disabled' : ''}`} aria-disabled={uploadDisabled}>
            {uploading ? <Loader2 className="spin" size={18} /> : <Upload size={18} />}
            افزودن عکس
            <input type="file" accept="image/*" multiple disabled={uploading || uploadDisabled} onChange={handleFileInput} />
          </label>
        )}
      </div>

      {images.length === 0 ? (
        <label className={`drop-zone ${uploading || uploadDisabled ? 'disabled' : ''}`}>
          <input type="file" accept="image/*" multiple disabled={uploading || uploadDisabled} onChange={handleFileInput} />
          <span className="camera-mark">
            {uploading ? <Loader2 className="spin" size={30} /> : <Upload size={30} />}
          </span>
          <strong>{uploading ? 'در حال اضافه کردن عکس‌ها' : 'افزودن عکس'}</strong>
          <span>چند عکس را با هم انتخاب کن.</span>
        </label>
      ) : (
        <div className="photo-grid uploaded" aria-label="عکس‌های اضافه شده">
          {images.map((asset) => (
            <figure className="photo-tile" key={asset.id}>
              <img src={`${API_BASE}${asset.url}`} alt={`عکس شماره ${toPersianDigits(asset.upload_order)}`} />
              <figcaption>شماره {toPersianDigits(asset.upload_order)}</figcaption>
            </figure>
          ))}
          {uploading && (
            <div className="photo-tile loading-tile">
              <Loader2 className="spin" size={24} />
              <span>در حال اضافه کردن</span>
            </div>
          )}
        </div>
      )}

      {images.length > 0 && (
        <div className="upload-summary">
          <span>{toPersianDigits(images.length)} عکس اضافه شده</span>
        </div>
      )}

      <VoicePanel audios={audios} disabled={voiceDisabled} onUpload={onUpload} inline />
    </section>
  );
}

function VoicePanel({
  audios,
  disabled,
  inline = false,
  onUpload,
}: {
  audios: Asset[];
  disabled: boolean;
  inline?: boolean;
  onUpload: (files: File[]) => void;
}) {
  const [recording, setRecording] = useState(false);
  const [askingMic, setAskingMic] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    setAskingMic(true);
    setVoiceError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => chunksRef.current.push(event.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        onUpload([new File([blob], `voice-${Date.now()}.webm`, { type: 'audio/webm' })]);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setVoiceError('اجازه میکروفون داده نشد. دسترسی میکروفون را فعال کن و دوباره تلاش کن.');
    } finally {
      setAskingMic(false);
    }
  }

  return (
    <section className={inline ? 'voice-inline' : 'panel compact-panel'}>
      <h2>توضیحات صوتی <small className="optional-note">(اختیاری)</small></h2>
      <ul className="voice-tips">
        <li>با ویس می‌تونی قیمت، موجودی و توضیحات محصول را هم بگی.</li>
        <li>با شماره عکس محصول هم می‌تونی توضیح بدی؛ مثلا «عکس شماره ۲ قیمتش ۲۰۰ هزار تومنه».</li>
        <li>اسم و توضیح بهتر کمک می‌کند محصولت در ترب بهتر دیده شود.</li>
      </ul>
      <div className="voice-actions">
        <button className={`button mic-button ${recording ? 'danger' : 'secondary'}`} type="button" onClick={toggleRecording} disabled={disabled || askingMic}>
          <span className="mic-ai-icon">
            {askingMic ? <Loader2 className="spin" size={18} /> : recording ? <Pause size={18} /> : <Mic size={18} />}
            {!askingMic && !recording && <Sparkles className="mic-spark" size={10} />}
          </span>
          {askingMic ? 'در حال آماده‌سازی' : recording ? 'توقف ضبط' : 'ضبط صدا'}
        </button>
      </div>
      {voiceError && <span className="field-error" role="alert">{voiceError}</span>}
      <span className="muted">{audios.length ? 'صدا ضبط شد و آماده پردازش است.' : 'می‌توانی بدون صدا هم ادامه بدهی.'}</span>
    </section>
  );
}

function BasalamPanel({
  connection,
  connecting,
  onConnect,
}: {
  connection: PlatformConnection | null;
  connecting: boolean;
  onConnect: () => void;
}) {
  return (
    <section className="panel basalam-panel">
      <div className="basalam-title">
        <Store size={18} />
        <strong>غرفه باسلام</strong>
      </div>
      {connection ? (
        <div className="connection-state connected">
          <Check size={17} />
          <span>
            <strong>وصل به باسلام</strong>
            <small>{connection.external_shop_name}</small>
          </span>
        </div>
      ) : (
        <>
          <p>برای ثبت مستقیم محصول‌ها، غرفه‌ات را وصل کن.</p>
          <button className="button primary full" type="button" onClick={onConnect} disabled={connecting}>
            {connecting ? <Loader2 className="spin" size={17} /> : <Store size={17} />}
            اتصال غرفه
          </button>
        </>
      )}
    </section>
  );
}

function ShopInfoPanel({
  seller,
  saving,
  onSave,
}: {
  seller: Seller;
  saving: boolean;
  onSave: (payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) => void;
}) {
  const [form, setForm] = useState({
    name: seller.name === 'فروشنده' ? '' : seller.name,
    mobile: seller.mobile === '-' ? '' : seller.mobile,
    shop_name: seller.shop_name === 'فروشگاه' ? '' : seller.shop_name,
  });

  useEffect(() => {
    setForm({
      name: seller.name === 'فروشنده' ? '' : seller.name,
      mobile: seller.mobile === '-' ? '' : seller.mobile,
      shop_name: seller.shop_name === 'فروشگاه' ? '' : seller.shop_name,
    });
  }, [seller]);

  return (
    <details className="panel optional-panel">
      <summary>اطلاعات فروشگاه <small className="optional-note">(اختیاری)</small></summary>
      <label className="field">
        <span>نام شما</span>
        <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
      </label>
      <label className="field">
        <span>موبایل</span>
        <input value={toPersianDigits(form.mobile)} inputMode="tel" onChange={(event) => setForm({ ...form, mobile: normalizeDigits(event.target.value) })} />
      </label>
      <label className="field">
        <span>نام فروشگاه</span>
        <input value={form.shop_name} onChange={(event) => setForm({ ...form, shop_name: event.target.value })} />
      </label>
      <button className="button secondary full" type="button" onClick={() => onSave(form)} disabled={saving}>
        {saving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
        ذخیره اطلاعات
      </button>
    </details>
  );
}

function ProgressPanel({
  job,
  processing,
  canRetry,
  onRetry,
}: {
  job: Job | null;
  processing: boolean;
  canRetry: boolean;
  onRetry: () => void;
}) {
  const failed = job?.status === 'failed';
  return (
    <section className={`panel progress-panel ${failed ? 'failed' : ''}`}>
      <div>
        <h2>{job ? jobLabels[job.step] : 'در حال ساخت لیست'}</h2>
        <p>{failed ? 'عکس‌ها و صدا پاک نشده‌اند. می‌توانی دوباره تلاش کنی.' : 'این کار ممکن است کمی زمان ببرد.'}</p>
      </div>
      {processing ? <Loader2 className="spin" size={22} /> : failed ? <RotateCcw size={22} /> : <Check size={22} />}
      {job?.error && <div className="error inline">{job.error}</div>}
      {canRetry && (
        <button className="button secondary" type="button" onClick={onRetry}>
          <RotateCcw size={18} />
          دوباره تلاش کن
        </button>
      )}
    </section>
  );
}

function PreviewPanel({
  refNode,
  batch,
  items,
  drafts,
  saving,
  suggestingCategories,
  publishing,
  basalamConnected,
  publishJob,
  publishedProducts,
  splittingPhotoKey,
  onDraftChange,
  onApplyPreparationDays,
  onSelectBasalamCategory,
  onPublishBasalam,
  onSplitPhoto,
  onAskStartFresh,
}: {
  refNode: MutableRefObject<HTMLElement | null>;
  batch: Batch | null;
  items: ProductItem[];
  drafts: DraftMap;
  saving: boolean;
  suggestingCategories: boolean;
  publishing: boolean;
  basalamConnected: boolean;
  publishJob: PublishJob | null;
  publishedProducts: PublishedProduct[];
  splittingPhotoKey: string | null;
  onDraftChange: (itemId: number, patch: Partial<ProductDraft>) => void;
  onApplyPreparationDays: (days: number) => void;
  onSelectBasalamCategory: (itemId: number, category: BasalamCategory) => void;
  onPublishBasalam: () => void;
  onSplitPhoto: (itemId: number, assetId: number) => void;
  onAskStartFresh: () => void;
}) {
  if (items.length === 0 || !batch) return null;
  return (
    <section className="preview" ref={(node) => { refNode.current = node; }}>
      <div className="preview-head">
        <div>
          <h2>لیست آماده شد</h2>
          <p>چک کن، اصلاح کن، بعد محصول‌ها را در غرفه ثبت کن.</p>
        </div>
        <div className="actions">
          <button className="button secondary" type="button" onClick={onAskStartFresh}>
            <Upload size={18} />
            افزودن محصولات جدید
          </button>
        </div>
      </div>

      {publishJob && <PublishStatusPanel job={publishJob} products={publishedProducts} items={items} />}
      {suggestingCategories && (
        <div className="category-loading" role="status">
          <Loader2 className="spin" size={17} />
          در حال حدس دسته‌بندی باسلام
        </div>
      )}

      <BulkPreparationBox onApply={onApplyPreparationDays} />

      <div className="item-list">
        {items.map((item) => (
          <ProductCard
            key={item.id}
            item={item}
            draft={drafts[item.id] ?? toDraft(item)}
            splittingPhotoKey={splittingPhotoKey}
            onDraftChange={(patch) => onDraftChange(item.id, patch)}
            onSelectBasalamCategory={onSelectBasalamCategory}
            onSplitPhoto={onSplitPhoto}
          />
        ))}
      </div>

      <div className="save-dock">
        <button className="button primary save-list-button" type="button" onClick={onPublishBasalam} disabled={saving || publishing}>
          {publishing ? <Loader2 className="spin" size={18} /> : basalamConnected ? <Send size={18} /> : <Store size={18} />}
          {basalamConnected ? 'ثبت در غرفه باسلام' : 'اتصال غرفه باسلام'}
        </button>
      </div>
    </section>
  );
}

function BulkPreparationBox({ onApply }: { onApply: (days: number) => void }) {
  const [visible, setVisible] = useState(true);
  const [value, setValue] = useState('');
  if (!visible) return null;
  const days = parseNullableInt(value);
  return (
    <div className="bulk-prep-box">
      <button className="icon-dismiss" type="button" aria-label="بستن" onClick={() => setVisible(false)}>
        ×
      </button>
      <span>زمان آماده‌سازی همه محصولات</span>
      <div className="suffix-input compact">
        <input
          value={toPersianDigits(value)}
          inputMode="numeric"
          placeholder="مثلا ۲"
          aria-label="زمان آماده‌سازی همه محصولات"
          onChange={(event) => setValue(normalizeDigits(event.target.value).replace(/[^\d]/g, ''))}
        />
        <span>روز</span>
      </div>
      <button
        className="prep-apply"
        type="button"
        disabled={days === null}
        onClick={() => {
          if (days === null) return;
          onApply(days);
          setVisible(false);
        }}
      >
        اعمال برای همه
      </button>
    </div>
  );
}

function PublishStatusPanel({ job, products, items }: { job: PublishJob; products: PublishedProduct[]; items: ProductItem[] }) {
  const published = products.filter((product) => product.status === 'published').length;
  const failedProducts = products.filter((product) => product.status === 'failed');
  const hasFailedState = job.status === 'failed' || job.status === 'partial_failed';
  const isFailed = hasFailedState || failedProducts.length > 0;
  const failed = failedProducts.length || (hasFailedState ? Math.max(0, items.length - published) : 0);
  const isRunning = job.status === 'running' || job.status === 'queued';
  const itemTitleById = new Map(items.map((item) => [item.id, item.title]));
  const title = isRunning
    ? publishLabels[job.step]
    : isFailed
      ? published > 0
        ? 'بعضی محصول‌ها ثبت نشدند'
        : 'ثبت محصول‌ها انجام نشد'
      : 'محصول‌ها در باسلام ثبت شدند';
  const message = isRunning
    ? 'چند لحظه صبر کن.'
    : isFailed
      ? `${toPersianDigits(published)} محصول ثبت شد، ${toPersianDigits(failed)} محصول خطا دارد.`
      : `${toPersianDigits(published)} محصول با موفقیت ثبت شد.`;
  return (
    <section className={`publish-status ${isFailed ? 'failed' : ''}`} role="status">
      <div>
        <strong>{title}</strong>
        <span>{message}</span>
        {failedProducts.length > 0 && (
          <ul className="publish-errors">
            {failedProducts.slice(0, 3).map((product) => (
              <li key={product.id}>
                <b>{itemTitleById.get(product.batch_item_id) ?? 'محصول'}</b>
                <span>{humanizePublishError(product.error)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {isRunning ? <Loader2 className="spin" size={20} /> : isFailed ? <AlertTriangle size={20} /> : <Check size={20} />}
      {job.error && !failedProducts.length && <span className="field-error">{humanizePublishError(job.error)}</span>}
    </section>
  );
}

function ProductCard({
  item,
  draft,
  splittingPhotoKey,
  onDraftChange,
  onSelectBasalamCategory,
  onSplitPhoto,
}: {
  item: ProductItem;
  draft: ProductDraft;
  splittingPhotoKey: string | null;
  onDraftChange: (patch: Partial<ProductDraft>) => void;
  onSelectBasalamCategory: (itemId: number, category: BasalamCategory) => void;
  onSplitPhoto: (itemId: number, assetId: number) => void;
}) {
  const needsPhotoCheck = item.photos.length > 1 && item.confidence < PHOTO_GROUP_WARNING_THRESHOLD;
  const unitLabel = item.basalam_category?.unit_type_title || 'واحد';
  const [activePhotoIndex, setActivePhotoIndex] = useState(0);
  const touchStartX = useRef<number | null>(null);
  const activePhoto = item.photos[activePhotoIndex] ?? item.photos[0];
  const hasMultiplePhotos = item.photos.length > 1;

  useEffect(() => {
    if (activePhotoIndex > item.photos.length - 1) setActivePhotoIndex(0);
  }, [activePhotoIndex, item.photos.length]);

  function movePhoto(delta: number) {
    if (!hasMultiplePhotos) return;
    setActivePhotoIndex((current) => (current + delta + item.photos.length) % item.photos.length);
  }

  function handleTouchEnd(clientX: number) {
    if (touchStartX.current === null) return;
    const delta = clientX - touchStartX.current;
    touchStartX.current = null;
    if (Math.abs(delta) < 38) return;
    movePhoto(delta > 0 ? -1 : 1);
  }

  return (
    <article className="panel product-card">
      <div
        className="product-photos"
        onTouchStart={(event) => {
          touchStartX.current = event.changedTouches[0]?.clientX ?? null;
        }}
        onTouchEnd={(event) => handleTouchEnd(event.changedTouches[0]?.clientX ?? 0)}
      >
        {activePhoto && (
          <figure className="photo-tile result-photo">
            <div className="result-photo-frame">
              <img src={`${API_BASE}${activePhoto.url}`} alt={`عکس شماره ${toPersianDigits(activePhoto.upload_order)}`} />
              <figcaption>شماره {toPersianDigits(activePhoto.upload_order)}</figcaption>
              {hasMultiplePhotos && (
                <div className="gallery-controls">
                  <button type="button" aria-label="عکس قبلی" onClick={() => movePhoto(-1)}>
                    <ChevronRight size={17} />
                  </button>
                  <button type="button" aria-label="عکس بعدی" onClick={() => movePhoto(1)}>
                    <ChevronLeft size={17} />
                  </button>
                </div>
              )}
            </div>
          </figure>
        )}
        {hasMultiplePhotos && (
          <div className="gallery-dots" aria-label="عکس‌های محصول">
            {item.photos.map((photo, index) => (
              <button
                key={photo.asset_id}
                type="button"
                aria-label={`نمایش عکس شماره ${toPersianDigits(photo.upload_order)}`}
                className={index === activePhotoIndex ? 'active' : ''}
                onClick={() => setActivePhotoIndex(index)}
              />
            ))}
          </div>
        )}
        {needsPhotoCheck && activePhoto && (
          <div className="photo-actions">
            <button
              className="split-photo-button"
              type="button"
              onClick={() => onSplitPhoto(item.id, activePhoto.asset_id)}
              disabled={splittingPhotoKey === `${item.id}-${activePhoto.asset_id}`}
            >
              {splittingPhotoKey === `${item.id}-${activePhoto.asset_id}` ? <Loader2 className="spin" size={15} /> : <SplitSquareHorizontal size={15} />}
              این عکس محصول جداست
            </button>
          </div>
        )}
      </div>

      {needsPhotoCheck && (
        <div className="photo-check-warning" role="alert">
          <strong>عکس‌های این محصول را چک کن.</strong>
          <span>اگر یکی از عکس‌ها برای محصول دیگری است، همان عکس را جدا کن.</span>
        </div>
      )}

      <div className="product-fields">
        <label className="field product-title-field">
          <span>نام محصول</span>
          <input value={draft.title} onChange={(event) => onDraftChange({ title: event.target.value })} />
        </label>
        <label className="field product-desc-field">
          <span>توضیح کوتاه</span>
          <textarea value={draft.description} onChange={(event) => onDraftChange({ description: event.target.value })} />
        </label>
        <label className="field price-field product-price-field">
          <span>قیمت</span>
          <div className="price-input">
            <input
              value={formatPriceInput(draft.price_toman)}
              inputMode="numeric"
              onChange={(event) => onDraftChange({ price_toman: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
            />
            <span>تومان</span>
          </div>
        </label>
        <div className="product-extra-fields" aria-label="جزئیات ثبت در باسلام">
          <label className="field">
            <span>موجودی</span>
            <input
              value={formatIntegerInput(draft.stock)}
              inputMode="numeric"
              placeholder="مثلا ۵"
              onChange={(event) => onDraftChange({ stock: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
            />
          </label>
          <label className="field">
            <span>آماده‌سازی</span>
            <div className="suffix-input">
              <input
                value={formatIntegerInput(draft.preparation_days)}
                inputMode="numeric"
                placeholder="مثلا ۲"
                onChange={(event) => onDraftChange({ preparation_days: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
              />
              <span>روز</span>
            </div>
          </label>
          <label className="field">
            <span>وزن محصول</span>
            <div className="suffix-input">
              <input
                value={formatIntegerInput(draft.weight_grams)}
                inputMode="numeric"
                placeholder="مثلا ۳۰۰"
                onChange={(event) => onDraftChange({ weight_grams: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
              />
              <span>گرم</span>
            </div>
          </label>
          <label className="field">
            <span>وزن محصول با بسته‌بندی</span>
            <div className="suffix-input">
              <input
                value={formatIntegerInput(draft.package_weight_grams)}
                inputMode="numeric"
                placeholder="مثلا ۵۰۰"
                onChange={(event) => onDraftChange({ package_weight_grams: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
              />
              <span>گرم</span>
            </div>
          </label>
          <label className="field">
            <span>چندتایی می‌فروشی؟</span>
            <div className="suffix-input">
              <input
                value={formatIntegerInput(draft.unit_quantity)}
                inputMode="numeric"
                placeholder="مثلا ۱"
                onChange={(event) => onDraftChange({ unit_quantity: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
              />
              <span>{unitLabel}</span>
            </div>
          </label>
        </div>
        <BasalamCategoryPicker
          item={item}
          onSelect={(category) => onSelectBasalamCategory(item.id, category)}
        />
      </div>
    </article>
  );
}

function BasalamCategoryPicker({ item, onSelect }: { item: ProductItem; onSelect: (category: BasalamCategory) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BasalamCategory[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectingId, setSelectingId] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const category = item.basalam_category;
  const lowConfidence = category?.source === 'auto' && (category.confidence ?? 0) < BASALAM_AUTO_CATEGORY_THRESHOLD;
  const needsCategory = lowConfidence || !category?.category_id;
  const showSearch = needsCategory || editing;

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const nextResults = await api.searchBasalamCategories(trimmed);
        if (!cancelled) setResults(nextResults);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  async function selectCategory(category: BasalamCategory) {
    setSelectingId(category.id);
    try {
      await onSelect(category);
      setQuery('');
      setResults([]);
      setEditing(false);
    } finally {
      setSelectingId(null);
    }
  }

  return (
    <div className={`category-picker ${needsCategory ? 'needs-category' : ''}`}>
      <div className="category-current">
        <span>دسته‌بندی باسلام</span>
        {category?.category_id ? (
          <strong>{category.path || category.title}</strong>
        ) : (
          <strong>انتخاب نشده</strong>
        )}
        {!needsCategory && (
          <button className="category-edit-button" type="button" onClick={() => setEditing((value) => !value)}>
            {editing ? 'بستن' : 'تغییر'}
          </button>
        )}
      </div>
      {needsCategory && (
        <small>{lowConfidence ? 'اگر دسته درست نیست، اصلاحش کن.' : 'برای ثبت در باسلام، دسته را انتخاب کن.'}</small>
      )}
      {showSearch && (
        <>
          <div className="category-search">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="جستجوی دسته"
              aria-label="جستجوی دسته‌بندی باسلام"
            />
            {loading && <Loader2 className="spin" size={16} />}
          </div>
          {results.length > 0 && (
            <div className="category-results">
              {results.map((category) => (
                <button
                  key={category.id}
                  type="button"
                  onClick={() => selectCategory(category)}
                  disabled={selectingId === category.id}
                >
                  <span>{category.path}</span>
                  {selectingId === category.id && <Loader2 className="spin" size={14} />}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel?: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{title}</h2>
        <p>{body}</p>
        <div className="modal-actions">
          {cancelLabel && onCancel && (
            <button className="button secondary" type="button" onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
          <button className="button primary" type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="loading-panel">
      <Loader2 className="spin" size={22} />
      {label}
    </div>
  );
}

function readBasalamReturn(): { status: 'success' | 'failed'; sellerId: number | null } | null {
  const params = new URLSearchParams(window.location.search);
  const status = params.get('basalam_status');
  if (!status) return null;
  const rawSellerId = params.get('seller_id');
  const sellerId = rawSellerId ? Number(rawSellerId) : null;
  window.history.replaceState({}, '', window.location.pathname);
  return { status: status === 'success' ? 'success' : 'failed', sellerId: Number.isFinite(sellerId) ? sellerId : null };
}

function buildDrafts(items: ProductItem[]): DraftMap {
  return Object.fromEntries(items.map((item) => [item.id, toDraft(item)]));
}

function toDraft(item: ProductItem): ProductDraft {
  return {
    title: item.title,
    description: item.description,
    price_toman: item.price_toman?.toString() ?? '',
    stock: item.stock?.toString() ?? '',
    preparation_days: item.preparation_days?.toString() ?? '',
    weight_grams: item.weight_grams?.toString() ?? '',
    package_weight_grams: item.package_weight_grams?.toString() ?? '',
    unit_quantity: item.unit_quantity?.toString() ?? '',
  };
}

function parsePersianPrice(value: string): number | null {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  return normalized ? Number(normalized) : null;
}

function parseNullableInt(value: string): number | null {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  return normalized ? Number(normalized) : null;
}

function humanizePublishError(error: string | null): string {
  if (!error) return 'این محصول ثبت نشد. فیلدهای قیمت، عکس و دسته‌بندی را چک کن.';
  const normalized = error.toLowerCase();
  if (/product\(s\) failed|product failed/i.test(error)) {
    return 'ثبت این محصول ناموفق بود. فیلدهای لازم را چک کن و دوباره تلاش کن.';
  }
  if (normalized.includes('inactive') || (normalized.includes('vendor') && normalized.includes('active'))) {
    return 'غرفه باسلام فعال نیست یا اجازه ثبت محصول ندارد. وضعیت غرفه را در باسلام چک کن.';
  }
  if (normalized.includes('category') || error.includes('دسته‌بندی')) {
    return 'دسته‌بندی این محصول درست نیست یا انتخاب نشده. دسته‌بندی را اصلاح کن و دوباره ثبت کن.';
  }
  if (normalized.includes('stock') || normalized.includes('inventory')) {
    return 'موجودی محصول را چک کن و دوباره ثبت کن.';
  }
  if (normalized.includes('preparation') || error.includes('آماده')) {
    return 'زمان آماده‌سازی محصول برای این دسته قابل قبول نیست.';
  }
  if (normalized.includes('shipping')) {
    return 'تنظیمات ارسال غرفه یا روش ارسال برای ثبت محصول کامل نیست.';
  }
  if (normalized.includes('attribute')) {
    return 'این دسته‌بندی به ویژگی‌های بیشتری نیاز دارد. باید فیلدهای لازم دسته را اضافه کنیم یا دسته را عوض کنی.';
  }
  if (normalized.includes('basalam product create failed')) {
    return 'باسلام ثبت این محصول را قبول نکرد. فیلدهای محصول را چک کن و دوباره تلاش کن.';
  }
  return 'این محصول ثبت نشد. فیلدهای محصول را چک کن و دوباره تلاش کن.';
}

function formatPriceInput(value: string): string {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  if (!normalized) return '';
  return toPersianDigits(Number(normalized).toLocaleString('en-US')).replace(/,/g, '٬');
}

function formatIntegerInput(value: string): string {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  return normalized ? toPersianDigits(normalized) : '';
}

function normalizeDigits(value: string): string {
  const persian = '۰۱۲۳۴۵۶۷۸۹';
  const arabic = '٠١٢٣٤٥٦٧٨٩';
  return value.replace(/[۰-۹٠-٩]/g, (char) => {
    const persianIndex = persian.indexOf(char);
    if (persianIndex >= 0) return String(persianIndex);
    const arabicIndex = arabic.indexOf(char);
    return arabicIndex >= 0 ? String(arabicIndex) : char;
  });
}

function toPersianDigits(value: string | number): string {
  return String(value).replace(/\d/g, (digit) => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
}
