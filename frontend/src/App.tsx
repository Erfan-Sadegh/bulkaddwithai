import {
  Check,
  Download,
  FileJson,
  Loader2,
  Mic,
  Pause,
  RotateCcw,
  Save,
  Sparkles,
  SplitSquareHorizontal,
  Upload,
} from 'lucide-react';
import type { ChangeEvent, MutableRefObject } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE, api } from './lib/api';
import type { Asset, Batch, Job, ProductItem, Seller } from './lib/types';

type ProductDraft = Pick<ProductItem, 'title' | 'description'> & { price_toman: string };
type DraftMap = Record<number, ProductDraft>;

const jobLabels: Record<Job['step'], string> = {
  upload_ready: 'آماده شروع',
  transcribing: 'در حال خواندن ویس',
  vision_extracting: 'در حال بررسی عکس‌ها',
  matching: 'در حال ساخت لیست محصولات',
  ready: 'لیست آماده است',
  failed: 'ساخت لیست ناموفق بود',
};

export function App() {
  const [seller, setSeller] = useState<Seller | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [items, setItems] = useState<ProductItem[]>([]);
  const [drafts, setDrafts] = useState<DraftMap>({});
  const [job, setJob] = useState<Job | null>(null);
  const [booting, setBooting] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [savingList, setSavingList] = useState(false);
  const [savingShop, setSavingShop] = useState(false);
  const [splittingPhotoKey, setSplittingPhotoKey] = useState<string | null>(null);
  const [freshConfirmOpen, setFreshConfirmOpen] = useState(false);
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);

  const imageAssets = useMemo(
    () => assets.filter((asset) => asset.type === 'image').sort((a, b) => a.upload_order - b.upload_order),
    [assets],
  );
  const audioAssets = useMemo(() => assets.filter((asset) => asset.type === 'audio'), [assets]);

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
          const readyItems = await api.listItems(batch.id);
          setItems(readyItems);
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
    if (items.length === 0) return;
    setDrafts(buildDrafts(items));
    window.setTimeout(() => {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
  }, [items]);

  async function bootstrapWorkspace() {
    setBooting(true);
    setError(null);
    try {
      const sellers = await api.listSellers();
      const currentSeller = sellers[0] ?? (await api.createSeller({}));
      const currentBatch = await api.createBatch(currentSeller.id);
      setSeller(currentSeller);
      setBatch(currentBatch);
      setAssets([]);
      setItems([]);
      setDrafts({});
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
      setJob(null);
      showToast('صفحه برای محصولات جدید آماده شد.');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'شروع دوباره ناموفق بود.');
    }
  }

  async function upload(files: File[]) {
    if (!batch || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      const uploaded = await api.uploadAssets(batch.id, files);
      setAssets((current) => [...current, ...uploaded].sort((a, b) => a.type.localeCompare(b.type) || a.upload_order - b.upload_order));
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
    try {
      const result = await api.processBatch(batch.id);
      const firstJob = await api.getJob(result.job_id);
      setJob(firstJob);
      if (firstJob.status === 'succeeded') {
        const readyItems = await api.listItems(batch.id);
        setItems(readyItems);
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

  async function saveWholeList() {
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
          });
        }),
      );
      setItems(savedItems);
      setSaveSuccessOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'لیست ذخیره نشد. دوباره تلاش کن.');
    } finally {
      setSavingList(false);
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
          <h1>محصولاتت رو با عکس و ویس به فروشگاهت اضافه کن</h1>
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
            voiceDisabled={uploading || processing}
            onUpload={upload}
          />

          {seller && (
            <aside className="side-rail">
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
            splittingPhotoKey={splittingPhotoKey}
            onDraftChange={updateDraft}
            onSaveList={saveWholeList}
            onSplitPhoto={splitPhoto}
            onAskStartFresh={() => setFreshConfirmOpen(true)}
          />
        </section>
      )}

      {freshConfirmOpen && (
        <ConfirmDialog
          title="محصولات جدید اضافه می‌کنی؟"
          body="اگر ادامه بدهی، صفحه برای عکس‌های جدید خالی می‌شود. لیست آماده‌شده از بین نمی‌رود و در خروجی همین نوبت قبلی باقی می‌ماند."
          confirmLabel="بله، صفحه را خالی کن"
          cancelLabel="نه، برگرد"
          onConfirm={startFreshList}
          onCancel={() => setFreshConfirmOpen(false)}
        />
      )}

      {saveSuccessOpen && (
        <ConfirmDialog
          title="لیست محصولات ذخیره شد"
          body="تغییراتت ثبت شد. حالا می‌توانی خروجی CSV یا JSON بگیری."
          confirmLabel="باشه"
          onConfirm={() => setSaveSuccessOpen(false)}
        />
      )}
    </main>
  );
}

function UploadPanel({
  images,
  audios,
  uploading,
  voiceDisabled,
  onUpload,
}: {
  images: Asset[];
  audios: Asset[];
  uploading: boolean;
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
          <label className="button primary file-button">
            {uploading ? <Loader2 className="spin" size={18} /> : <Upload size={18} />}
            افزودن عکس
            <input type="file" accept="image/*" multiple disabled={uploading} onChange={handleFileInput} />
          </label>
        )}
      </div>

      {images.length === 0 ? (
        <label className={`drop-zone ${uploading ? 'disabled' : ''}`}>
          <input type="file" accept="image/*" multiple disabled={uploading} onChange={handleFileInput} />
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
        <li>با ویس می‌تونی قیمت و توضیحات محصول را هم بگی.</li>
        <li>با شماره عکس محصول هم می‌تونی توضیح بدی؛ مثلا «عکس شماره ۲ قیمتش ۲۰۰ هزار تومنه».</li>
        <li>اسم و توضیح بهتر کمک می‌کند محصولت در ترب بهتر دیده شود.</li>
      </ul>
      <div className="voice-actions">
        <button className={`button mic-button ${recording ? 'danger' : 'secondary'}`} type="button" onClick={toggleRecording} disabled={disabled || askingMic}>
          <span className="mic-ai-icon">
            {askingMic ? <Loader2 className="spin" size={18} /> : recording ? <Pause size={18} /> : <Mic size={18} />}
            {!askingMic && !recording && <Sparkles className="mic-spark" size={10} />}
          </span>
          {askingMic ? 'در حال آماده‌سازی' : recording ? 'توقف ضبط' : 'ضبط ویس'}
        </button>
      </div>
      {voiceError && <span className="field-error" role="alert">{voiceError}</span>}
      <span className="muted">{audios.length ? `${toPersianDigits(audios.length)} ویس آماده است` : 'می‌توانی بدون ویس هم ادامه بدهی.'}</span>
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
        <p>{failed ? 'عکس‌ها و ویس پاک نشده‌اند. می‌توانی دوباره تلاش کنی.' : 'این کار ممکن است کمی زمان ببرد.'}</p>
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
  splittingPhotoKey,
  onDraftChange,
  onSaveList,
  onSplitPhoto,
  onAskStartFresh,
}: {
  refNode: MutableRefObject<HTMLElement | null>;
  batch: Batch | null;
  items: ProductItem[];
  drafts: DraftMap;
  saving: boolean;
  splittingPhotoKey: string | null;
  onDraftChange: (itemId: number, patch: Partial<ProductDraft>) => void;
  onSaveList: () => void;
  onSplitPhoto: (itemId: number, assetId: number) => void;
  onAskStartFresh: () => void;
}) {
  if (items.length === 0 || !batch) return null;
  return (
    <section className="preview" ref={(node) => { refNode.current = node; }}>
      <div className="preview-head">
        <div>
          <h2>لیست آماده شد</h2>
          <p>چک کن، اصلاح کن، بعد کل لیست را ذخیره کن.</p>
        </div>
        <div className="actions">
          <a className="button secondary" href={`${API_BASE}/batches/${batch.id}/export.csv`}>
            <Download size={18} />
            CSV
          </a>
          <a className="button secondary" href={`${API_BASE}/batches/${batch.id}/export.json`}>
            <FileJson size={18} />
            JSON
          </a>
          <button className="button secondary" type="button" onClick={onAskStartFresh}>
            <Upload size={18} />
            افزودن محصولات جدید
          </button>
        </div>
      </div>

      <div className="item-list">
        {items.map((item) => (
          <ProductCard
            key={item.id}
            item={item}
            draft={drafts[item.id] ?? toDraft(item)}
            splittingPhotoKey={splittingPhotoKey}
            onDraftChange={(patch) => onDraftChange(item.id, patch)}
            onSplitPhoto={onSplitPhoto}
          />
        ))}
      </div>

      <div className="save-dock">
        <button className="button primary save-list-button" type="button" onClick={onSaveList} disabled={saving}>
          {saving ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
          ذخیره لیست
        </button>
      </div>
    </section>
  );
}

function ProductCard({
  item,
  draft,
  splittingPhotoKey,
  onDraftChange,
  onSplitPhoto,
}: {
  item: ProductItem;
  draft: ProductDraft;
  splittingPhotoKey: string | null;
  onDraftChange: (patch: Partial<ProductDraft>) => void;
  onSplitPhoto: (itemId: number, assetId: number) => void;
}) {
  const needsPhotoCheck = item.photos.length > 1 && item.confidence < 0.8;
  return (
    <article className="panel product-card">
      <div className="product-photos">
        {item.photos.map((photo) => {
          const splitKey = `${item.id}-${photo.asset_id}`;
          return (
            <figure className="photo-tile result-photo" key={photo.asset_id}>
              <div className="result-photo-frame">
                <img src={`${API_BASE}${photo.url}`} alt={`عکس شماره ${toPersianDigits(photo.upload_order)}`} />
                <figcaption>شماره {toPersianDigits(photo.upload_order)}</figcaption>
              </div>
              {needsPhotoCheck && (
                <div className="photo-actions">
                  <button className="split-photo-button" type="button" onClick={() => onSplitPhoto(item.id, photo.asset_id)} disabled={splittingPhotoKey === splitKey}>
                    {splittingPhotoKey === splitKey ? <Loader2 className="spin" size={15} /> : <SplitSquareHorizontal size={15} />}
                    این یک محصول جداست
                  </button>
                </div>
              )}
            </figure>
          );
        })}
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
      </div>
    </article>
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

function buildDrafts(items: ProductItem[]): DraftMap {
  return Object.fromEntries(items.map((item) => [item.id, toDraft(item)]));
}

function toDraft(item: ProductItem): ProductDraft {
  return {
    title: item.title,
    description: item.description,
    price_toman: item.price_toman?.toString() ?? '',
  };
}

function parsePersianPrice(value: string): number | null {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  return normalized ? Number(normalized) : null;
}

function formatPriceInput(value: string): string {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  if (!normalized) return '';
  return toPersianDigits(Number(normalized).toLocaleString('en-US')).replace(/,/g, '٬');
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
