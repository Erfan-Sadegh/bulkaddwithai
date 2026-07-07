import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Mic,
  Pause,
  RotateCcw,
  Send,
  Sparkles,
  SplitSquareHorizontal,
  Store,
  Upload,
} from 'lucide-react';
import type { ChangeEvent, MutableRefObject } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE, api } from './lib/api';
import type {
  Asset,
  BasalamCategory,
  Batch,
  Job,
  PlatformConnection,
  ProductItem,
  PublishedProduct,
  PublishJob,
  Seller,
  TorobSubmission,
} from './lib/types';

type Platform = 'basalam' | 'torob';
type ProductDraft = Pick<ProductItem, 'title' | 'description'> & {
  price_toman: string;
  stock: string;
  preparation_days: string;
  weight_grams: string;
  package_weight_grams: string;
  unit_quantity: string;
};
type DraftMap = Record<number, ProductDraft>;
type RequiredField =
  | 'title'
  | 'price_toman'
  | 'stock'
  | 'preparation_days'
  | 'weight_grams'
  | 'package_weight_grams'
  | 'unit_quantity'
  | 'category';
type PublishValidationIssue = {
  itemId: number;
  title: string;
  fields: RequiredField[];
};
const BASALAM_AUTO_CATEGORY_THRESHOLD = 0.62;
const PHOTO_GROUP_WARNING_THRESHOLD = 0.65;
const REQUIRED_FIELD_LABELS: Record<RequiredField, string> = {
  title: 'نام محصول',
  price_toman: 'قیمت',
  stock: 'موجودی',
  preparation_days: 'زمان آماده‌سازی',
  weight_grams: 'وزن محصول',
  package_weight_grams: 'وزن با بسته‌بندی',
  unit_quantity: 'چندتایی می‌فروشی',
  category: 'دسته‌بندی باسلام',
};

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
  if (window.location.pathname.startsWith('/admin')) return <AdminApp />;
  return <MainApp />;
}

function MainApp() {
  const [seller, setSeller] = useState<Seller | null>(null);
  const [platform, setPlatform] = useState<Platform>('basalam');
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
  const [torobShopName, setTorobShopName] = useState('');
  const [torobContactMobile, setTorobContactMobile] = useState('');
  const [submittingTorob, setSubmittingTorob] = useState(false);
  const [torobInfoTouched, setTorobInfoTouched] = useState(false);
  const [torobSuccessMessage, setTorobSuccessMessage] = useState<string | null>(null);
  const [splittingPhotoKey, setSplittingPhotoKey] = useState<string | null>(null);
  const [freshConfirmOpen, setFreshConfirmOpen] = useState(false);
  const [showPublishValidation, setShowPublishValidation] = useState(false);
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
  const publishValidationIssues = useMemo(() => validateItemsForBasalam(items, drafts), [drafts, items]);
  const activeValidationIssues = platform === 'basalam' && showPublishValidation ? publishValidationIssues : [];

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
          await loadItemsForPlatform(batch.id, platform);
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
  }, [batch, job, platform]);

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
      setShowPublishValidation(false);
      setTorobSuccessMessage(null);
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
      setShowPublishValidation(false);
      setTorobSuccessMessage(null);
      showToast('صفحه برای محصولات جدید آماده شد.');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'شروع دوباره ناموفق بود.');
    }
  }

  async function upload(files: File[]) {
    if (!batch || files.length === 0) return;
    const hasImage = files.some((file) => file.type.startsWith('image/'));
    if (items.length > 0 && hasImage) {
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
        await loadItemsForPlatform(batch.id, platform);
        setShowPublishValidation(false);
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

  async function loadItemsForPlatform(batchId: number, targetPlatform: Platform) {
    if (targetPlatform === 'torob') {
      setSuggestingCategories(false);
      setItems(await api.listItems(batchId));
      return;
    }
    await loadItemsWithCategorySuggestions(batchId);
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
    setShowPublishValidation(true);
    setPublishJob(null);
    setPublishedProducts([]);
    if (publishValidationIssues.length > 0) {
      return;
    }
    setPublishingBasalam(true);
    setError(null);
    try {
      const saved = await persistDrafts();
      if (!saved) {
        setPublishingBasalam(false);
        return;
      }
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

  async function submitToTorob() {
    if (!batch) return;
    setTorobInfoTouched(true);
    setPublishJob(null);
    setPublishedProducts([]);
    const shopName = torobShopName.trim();
    const contactMobile = torobContactMobile.trim();
    if (!shopName || !contactMobile) {
      setError('برای ترب، اسم فروشگاه و شماره تماس را وارد کن.');
      document.querySelector('.torob-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    setSubmittingTorob(true);
    setError(null);
    try {
      const saved = await persistDrafts();
      if (!saved) {
        setSubmittingTorob(false);
        return;
      }
      const created = await api.createTorobSubmission(batch.id, {
        shop_name: shopName,
        contact_mobile: contactMobile,
      });
      setTorobSuccessMessage(created.message);
      showToast('درخواست ترب ثبت شد.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'درخواست ترب ثبت نشد. دوباره تلاش کن.');
    } finally {
      setSubmittingTorob(false);
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

  function selectPlatform(nextPlatform: Platform) {
    setPlatform(nextPlatform);
    setError(null);
    setShowPublishValidation(false);
    setPublishJob(null);
    setPublishedProducts([]);
  }

  function scrollToFirstIssue() {
    const firstIssue = publishValidationIssues[0];
    if (!firstIssue) return;
    document.querySelector(`[data-product-id="${firstIssue.itemId}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
          <PlatformChooser platform={platform} onChange={selectPlatform} />

          {seller && platform === 'basalam' && (
            <BasalamPanel
              connection={basalamConnection}
              connecting={connectingBasalam}
              onConnect={connectBasalam}
            />
          )}

          {platform === 'torob' && (
            <TorobPanel
              shopName={torobShopName}
              contactMobile={torobContactMobile}
              touched={torobInfoTouched}
              onShopNameChange={setTorobShopName}
              onContactMobileChange={setTorobContactMobile}
            />
          )}

          <UploadPanel
            images={imageAssets}
            audios={audioAssets}
            uploading={uploading}
            uploadDisabled={items.length > 0 || processing}
            voiceDisabled={items.length > 0 || uploading || processing}
            onUpload={upload}
          />

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
            platform={platform}
            saving={savingList}
            suggestingCategories={suggestingCategories}
            publishing={platform === 'basalam' ? publishingBasalam : submittingTorob}
            basalamConnected={Boolean(basalamConnection)}
            publishJob={publishJob}
            publishedProducts={publishedProducts}
            audios={audioAssets}
            processing={processing}
            splittingPhotoKey={splittingPhotoKey}
            onDraftChange={updateDraft}
            onUploadVoice={upload}
            onReprocessWithVoice={processBatch}
            onGoToFirstIssue={scrollToFirstIssue}
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
            onSubmitTorob={submitToTorob}
            onSplitPhoto={splitPhoto}
            onAskStartFresh={() => setFreshConfirmOpen(true)}
            validationIssues={activeValidationIssues}
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

      {torobSuccessMessage && (
        <ConfirmDialog
          title="درخواست ترب ثبت شد"
          body={torobSuccessMessage}
          confirmLabel="باشه"
          onConfirm={() => setTorobSuccessMessage(null)}
        />
      )}

    </main>
  );
}

function AdminApp() {
  const [password, setPassword] = useState(() => window.sessionStorage.getItem('bulkadd_admin_password') ?? '');
  const [loggedIn, setLoggedIn] = useState(() => Boolean(window.sessionStorage.getItem('bulkadd_admin_password')));
  const [submissions, setSubmissions] = useState<TorobSubmission[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (loggedIn) loadSubmissions();
  }, [loggedIn]);

  async function login() {
    setLoading(true);
    setError(null);
    try {
      await api.adminLogin(password);
      window.sessionStorage.setItem('bulkadd_admin_password', password);
      setLoggedIn(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ورود انجام نشد.');
    } finally {
      setLoading(false);
    }
  }

  async function loadSubmissions() {
    setLoading(true);
    setError(null);
    try {
      setSubmissions(await api.listTorobSubmissions(password));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'درخواست‌های ترب خوانده نشد.');
    } finally {
      setLoading(false);
    }
  }

  function updateSubmission(nextSubmission: TorobSubmission) {
    setSubmissions((current) => current.map((submission) => (submission.id === nextSubmission.id ? nextSubmission : submission)));
  }

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 1800);
  }

  if (!loggedIn) {
    return (
      <main className="app-shell admin-shell">
        <section className="panel admin-login">
          <h1>ادمین درخواست‌های ترب</h1>
          <label className="field">
            <span>رمز ورود</span>
            <input value={password} type="password" onChange={(event) => setPassword(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') login(); }} />
          </label>
          {error && <div className="error inline">{error}</div>}
          <button className="button primary full" type="button" onClick={login} disabled={loading || !password.trim()}>
            {loading ? <Loader2 className="spin" size={17} /> : <Store size={17} />}
            ورود
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell admin-shell">
      <header className="hero admin-hero">
        <div>
          <h1>درخواست‌های ترب</h1>
          <p>shop_id و شناسه محصول ترب را وارد کن، بعد ارسال کن.</p>
        </div>
        <button className="button secondary" type="button" onClick={loadSubmissions} disabled={loading}>
          {loading ? <Loader2 className="spin" size={17} /> : <RotateCcw size={17} />}
          به‌روزرسانی
        </button>
      </header>
      {error && (
        <div className="error" role="alert">
          <strong>مشکلی پیش آمد.</strong>
          <span>{error}</span>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
      {loading && submissions.length === 0 ? (
        <LoadingPanel label="در حال خواندن درخواست‌ها" />
      ) : (
        <section className="admin-list">
          {submissions.length === 0 && <div className="panel compact-panel">درخواستی برای ترب ثبت نشده است.</div>}
          {submissions.map((submission) => (
            <AdminTorobSubmissionCard
              key={submission.id}
              password={password}
              submission={submission}
              onUpdated={updateSubmission}
              onToast={showToast}
            />
          ))}
        </section>
      )}
    </main>
  );
}

function AdminTorobSubmissionCard({
  password,
  submission,
  onUpdated,
  onToast,
}: {
  password: string;
  submission: TorobSubmission;
  onUpdated: (submission: TorobSubmission) => void;
  onToast: (message: string) => void;
}) {
  const [shopId, setShopId] = useState(submission.shop_id?.toString() ?? '');
  const [note, setNote] = useState(submission.admin_note ?? '');
  const [itemDrafts, setItemDrafts] = useState(() => torobItemDrafts(submission));
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setShopId(submission.shop_id?.toString() ?? '');
    setNote(submission.admin_note ?? '');
    setItemDrafts(torobItemDrafts(submission));
  }, [submission]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.patchTorobSubmission(password, submission.id, {
        shop_id: parseNullableInt(shopId),
        admin_note: note,
        items: submission.items.map((item) => ({
          id: item.id,
          base_product_rk: itemDrafts[item.id]?.base_product_rk.trim() || null,
          price: parseNullableInt(itemDrafts[item.id]?.price ?? ''),
        })),
      });
      onUpdated(updated);
      onToast('درخواست ترب ذخیره شد.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'درخواست ذخیره نشد.');
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    const parsedShopId = parseNullableInt(shopId);
    const publishItems = submission.items
      .map((item) => {
        const draft = itemDrafts[item.id];
        const price = parsePositivePrice(draft?.price ?? '');
        const baseProductRk = draft?.base_product_rk.trim() ?? '';
        return price !== null && baseProductRk ? { id: item.id, base_product_rk: baseProductRk, price } : null;
      })
      .filter((item): item is { id: number; base_product_rk: string; price: number } => Boolean(item));
    if (!parsedShopId) {
      setError('shop_id را وارد کن.');
      return;
    }
    if (publishItems.length === 0) {
      setError('برای حداقل یک محصول، شناسه محصول ترب و قیمت را وارد کن.');
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      const updated = await api.publishTorobSubmission(password, submission.id, {
        shop_id: parsedShopId,
        items: publishItems,
      });
      onUpdated(updated);
      onToast('محصول‌ها به ترب ارسال شدند.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ارسال به ترب انجام نشد.');
    } finally {
      setPublishing(false);
    }
  }

  return (
    <article className={`panel admin-submission ${submission.status === 'failed' ? 'failed' : ''}`}>
      <header className="admin-submission-head">
        <div>
          <strong>{submission.shop_name}</strong>
          <span>{toPersianDigits(submission.contact_mobile)}</span>
        </div>
        <span className="status-pill">{torobStatusLabel(submission.status)}</span>
      </header>
      <div className="admin-submission-meta">
        <label className="field">
          <span>shop_id ترب</span>
          <input value={toPersianDigits(shopId)} inputMode="numeric" onChange={(event) => setShopId(normalizeDigits(event.target.value).replace(/[^\d]/g, ''))} />
        </label>
        <label className="field">
          <span>یادداشت</span>
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
      </div>
      <div className="admin-products">
        {submission.items.map((item) => {
          const draft = itemDrafts[item.id] ?? { base_product_rk: '', price: '' };
          return (
            <section className="admin-product" key={item.id}>
              <div className="admin-product-images">
                {item.image_urls.slice(0, 3).map((url, index) => (
                  <img key={`${url}-${index}`} src={`${API_BASE}${url}`} alt={`عکس شماره ${toPersianDigits(item.image_numbers[index] ?? index + 1)}`} />
                ))}
              </div>
              <div className="admin-product-body">
                <strong>{item.title}</strong>
                <p>{item.description}</p>
                <div className="admin-product-fields">
                  <label className="field">
                    <span>شناسه محصول ترب</span>
                    <input
                      dir="ltr"
                      value={draft.base_product_rk}
                      onChange={(event) =>
                        setItemDrafts((current) => ({
                          ...current,
                          [item.id]: { ...draft, base_product_rk: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className="field price-field">
                    <span>قیمت</span>
                    <div className="price-input">
                      <input
                        value={formatPriceInput(draft.price)}
                        inputMode="numeric"
                        onChange={(event) =>
                          setItemDrafts((current) => ({
                            ...current,
                            [item.id]: { ...draft, price: normalizeDigits(event.target.value).replace(/[^\d]/g, '') },
                          }))
                        }
                      />
                      <span>تومان</span>
                    </div>
                  </label>
                </div>
                {item.error && <small className="field-error">{item.error}</small>}
              </div>
            </section>
          );
        })}
      </div>
      {error && <div className="error inline">{error}</div>}
      {submission.error && <div className="error inline">{submission.error}</div>}
      <div className="admin-actions">
        <button className="button secondary" type="button" onClick={save} disabled={saving || publishing}>
          {saving ? <Loader2 className="spin" size={17} /> : <Check size={17} />}
          ذخیره
        </button>
        <button className="button primary" type="button" onClick={publish} disabled={saving || publishing}>
          {publishing ? <Loader2 className="spin" size={17} /> : <Send size={17} />}
          ارسال به ترب
        </button>
      </div>
    </article>
  );
}

function torobItemDrafts(submission: TorobSubmission): Record<number, { base_product_rk: string; price: string }> {
  return Object.fromEntries(
    submission.items.map((item) => [
      item.id,
      {
        base_product_rk: item.base_product_rk ?? '',
        price: item.price?.toString() ?? '',
      },
    ]),
  );
}

function torobStatusLabel(status: string): string {
  if (status === 'submitted') return 'ارسال شده';
  if (status === 'failed') return 'ناموفق';
  if (status === 'submitting') return 'در حال ارسال';
  return 'در انتظار بررسی';
}

function PlatformChooser({ platform, onChange }: { platform: Platform; onChange: (platform: Platform) => void }) {
  return (
    <section className="platform-chooser" aria-label="انتخاب مسیر فروشگاه">
      <button
        className={`platform-card ${platform === 'basalam' ? 'active' : ''}`}
        type="button"
        onClick={() => onChange('basalam')}
      >
        <span>باسلام</span>
        <strong>ثبت مستقیم در غرفه</strong>
      </button>
      <button
        className={`platform-card ${platform === 'torob' ? 'active' : ''}`}
        type="button"
        onClick={() => onChange('torob')}
      >
        <span>ترب</span>
        <strong>آماده‌سازی برای اضافه شدن</strong>
      </button>
    </section>
  );
}

function TorobPanel({
  shopName,
  contactMobile,
  touched,
  onShopNameChange,
  onContactMobileChange,
}: {
  shopName: string;
  contactMobile: string;
  touched: boolean;
  onShopNameChange: (value: string) => void;
  onContactMobileChange: (value: string) => void;
}) {
  return (
    <section className="panel torob-panel">
      <div className="torob-panel-head">
        <Store size={18} />
        <div>
          <strong>فروشگاه ترب</strong>
          <p>اسم فروشگاهت رو بگو تا درخواستت درست پیگیری شود.</p>
        </div>
      </div>
      <div className="torob-form">
        <label className={`field ${touched && !shopName.trim() ? 'missing' : ''}`}>
          <span>اسم فروشگاه</span>
          <input aria-label="اسم فروشگاه" value={shopName} onChange={(event) => onShopNameChange(event.target.value)} />
        </label>
        <label className={`field ${touched && !contactMobile.trim() ? 'missing' : ''}`}>
          <span>شماره تماس</span>
          <input
            aria-label="شماره تماس"
            value={toPersianDigits(contactMobile)}
            inputMode="tel"
            onChange={(event) => onContactMobileChange(normalizeDigits(event.target.value).replace(/[^\d+]/g, ''))}
          />
          <small>اگر مشکلی پیش آمد، با همین شماره هماهنگ می‌کنیم.</small>
        </label>
      </div>
    </section>
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
  platform,
  saving,
  suggestingCategories,
  publishing,
  basalamConnected,
  publishJob,
  publishedProducts,
  audios,
  processing,
  validationIssues,
  splittingPhotoKey,
  onDraftChange,
  onUploadVoice,
  onReprocessWithVoice,
  onGoToFirstIssue,
  onApplyPreparationDays,
  onSelectBasalamCategory,
  onPublishBasalam,
  onSubmitTorob,
  onSplitPhoto,
  onAskStartFresh,
}: {
  refNode: MutableRefObject<HTMLElement | null>;
  batch: Batch | null;
  items: ProductItem[];
  drafts: DraftMap;
  platform: Platform;
  saving: boolean;
  suggestingCategories: boolean;
  publishing: boolean;
  basalamConnected: boolean;
  publishJob: PublishJob | null;
  publishedProducts: PublishedProduct[];
  audios: Asset[];
  processing: boolean;
  validationIssues: PublishValidationIssue[];
  splittingPhotoKey: string | null;
  onDraftChange: (itemId: number, patch: Partial<ProductDraft>) => void;
  onUploadVoice: (files: File[]) => void | Promise<void>;
  onReprocessWithVoice: () => void;
  onGoToFirstIssue: () => void;
  onApplyPreparationDays: (days: number) => void;
  onSelectBasalamCategory: (itemId: number, category: BasalamCategory) => void;
  onPublishBasalam: () => void;
  onSubmitTorob: () => void;
  onSplitPhoto: (itemId: number, assetId: number) => void;
  onAskStartFresh: () => void;
}) {
  if (items.length === 0 || !batch) return null;
  const missingByItemId = missingFieldMap(validationIssues);
  const noMissingFields = new Set<RequiredField>();
  const hasValidationIssues = validationIssues.length > 0;
  const publishFailed = Boolean(
    publishJob && ['partial_failed', 'failed'].includes(publishJob.status),
  );
  return (
    <section className="preview" ref={(node) => { refNode.current = node; }}>
      <div className="preview-head">
        <div>
          <h2>لیست آماده شد</h2>
          <p>{platform === 'basalam' ? 'چک کن، اصلاح کن، بعد محصول‌ها را در غرفه ثبت کن.' : 'چک کن، اصلاح کن، بعد درخواست ترب را ثبت کن.'}</p>
        </div>
        <div className="actions">
          <button className="button secondary" type="button" onClick={onAskStartFresh}>
            <Upload size={18} />
            افزودن محصولات جدید
          </button>
        </div>
      </div>

      {platform === 'basalam' && publishJob && <PublishStatusPanel job={publishJob} products={publishedProducts} items={items} />}
      {platform === 'basalam' && suggestingCategories && (
        <div className="category-loading" role="status">
          <Loader2 className="spin" size={17} />
          در حال حدس دسته‌بندی باسلام
        </div>
      )}

      {platform === 'basalam' && <BulkPreparationBox onApply={onApplyPreparationDays} />}

      <div className="item-list">
        {items.map((item) => (
          <ProductCard
            key={item.id}
            item={item}
            draft={drafts[item.id] ?? toDraft(item)}
            platform={platform}
            missingFields={missingByItemId.get(item.id) ?? noMissingFields}
            splittingPhotoKey={splittingPhotoKey}
            onDraftChange={(patch) => onDraftChange(item.id, patch)}
            onSelectBasalamCategory={onSelectBasalamCategory}
            onSplitPhoto={onSplitPhoto}
          />
        ))}
      </div>

      <div className="save-dock">
        {validationIssues.length > 0 && (
          <PublishValidationPanel
            issues={validationIssues}
            audios={audios}
            processing={processing}
            onUploadVoice={onUploadVoice}
            onReprocessWithVoice={onReprocessWithVoice}
            onGoToFirstIssue={onGoToFirstIssue}
          />
        )}
        {validationIssues.length === 0 && publishFailed && (
          <DockPublishProblem job={publishJob} products={publishedProducts} />
        )}
        <button
          className="button primary save-list-button"
          type="button"
          onClick={platform === 'basalam' ? onPublishBasalam : onSubmitTorob}
          disabled={saving || publishing || processing || hasValidationIssues}
        >
          {publishing || processing ? (
            <Loader2 className="spin" size={18} />
          ) : hasValidationIssues ? (
            <AlertTriangle size={18} />
          ) : platform === 'torob' ? (
            <Send size={18} />
          ) : basalamConnected ? (
            <Send size={18} />
          ) : (
            <Store size={18} />
          )}
          {processing
            ? 'در حال بازبینی لیست'
            : hasValidationIssues
              ? 'اول اطلاعات لازم را کامل کن'
              : platform === 'torob'
                ? 'ثبت درخواست ترب'
                : basalamConnected
                  ? 'ثبت در غرفه باسلام'
                  : 'اتصال غرفه باسلام'}
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
      <button className="bulk-prep-close" type="button" aria-label="بستن" onClick={() => setVisible(false)}>
        ×
      </button>
      <label className="bulk-prep-field">
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
      </label>
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

function PublishValidationPanel({
  issues,
  audios,
  processing,
  onUploadVoice,
  onReprocessWithVoice,
  onGoToFirstIssue,
}: {
  issues: PublishValidationIssue[];
  audios: Asset[];
  processing: boolean;
  onUploadVoice: (files: File[]) => void | Promise<void>;
  onReprocessWithVoice: () => void;
  onGoToFirstIssue: () => void;
}) {
  const firstIssue = issues[0];
  const issueCount = issues.length;
  const firstFields = firstIssue ? firstIssue.fields.slice(0, 2).map((field) => REQUIRED_FIELD_LABELS[field]).join('، ') : '';
  return (
    <div className="dock-message needs-info" role="alert">
      <div>
        <strong>اطلاعات لازم کامل نیست.</strong>
        {firstIssue && (
          <span>
            {toPersianDigits(issueCount)} محصول نیاز به تکمیل دارد؛ اول {firstFields}
            {firstIssue.fields.length > 2 ? ' و چند مورد دیگر' : ''}.
          </span>
        )}
      </div>
      <div className="dock-message-actions">
        <button className="link-button" type="button" onClick={onGoToFirstIssue}>
          اولین مورد
        </button>
        <VoiceRefineControl
          hasAudio={audios.length > 0}
          processing={processing}
          onUpload={onUploadVoice}
          onReprocess={onReprocessWithVoice}
        />
      </div>
    </div>
  );
}

function DockPublishProblem({ job, products }: { job: PublishJob | null; products: PublishedProduct[] }) {
  const failedProducts = products.filter((product) => product.status === 'failed');
  const failedCount = failedProducts.length || (job?.status === 'partial_failed' || job?.status === 'failed' ? 1 : 0);
  if (!job || failedCount === 0) return null;
  return (
    <div className="dock-message failed" role="alert">
      <div>
        <strong>ثبت کامل انجام نشد.</strong>
        <span>
          {toPersianDigits(failedCount)} محصول ثبت نشد. اطلاعات محصول‌ها یا وضعیت غرفه را چک کن.
        </span>
      </div>
    </div>
  );
}

function VoiceRefineControl({
  hasAudio,
  processing,
  onUpload,
  onReprocess,
}: {
  hasAudio: boolean;
  processing: boolean;
  onUpload: (files: File[]) => void | Promise<void>;
  onReprocess: () => void;
}) {
  const [recording, setRecording] = useState(false);
  const [askingMic, setAskingMic] = useState(false);
  const [localAudioReady, setLocalAudioReady] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const canReprocess = hasAudio || localAudioReady;

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    setVoiceError(null);
    setAskingMic(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => chunksRef.current.push(event.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        await onUpload([new File([blob], `voice-${Date.now()}.webm`, { type: 'audio/webm' })]);
        setLocalAudioReady(true);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setVoiceError('اجازه میکروفون داده نشد.');
    } finally {
      setAskingMic(false);
    }
  }

  return (
    <div className="voice-refine">
      <button className="link-button" type="button" onClick={toggleRecording} disabled={askingMic || processing}>
        {askingMic ? <Loader2 className="spin" size={15} /> : recording ? <Pause size={15} /> : <Mic size={15} />}
        {recording ? 'توقف ضبط' : 'ضبط صدا'}
      </button>
      <button className="link-button primary-link" type="button" onClick={onReprocess} disabled={!canReprocess || processing || recording}>
        {processing ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}
        بازبینی
      </button>
      {voiceError && <span>{voiceError}</span>}
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
  const visibleFailedProducts = failedProducts.slice(0, 6);
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
      ? published > 0
        ? `${toPersianDigits(published)} محصول ثبت شد، ${toPersianDigits(failed)} محصول ثبت نشد.`
        : `${toPersianDigits(failed)} محصول ثبت نشد.`
      : `${toPersianDigits(published)} محصول با موفقیت ثبت شد.`;
  return (
    <section className={`publish-status ${isFailed ? 'failed' : ''}`} role="status">
      <div>
        <strong>{title}</strong>
        <span>{message}</span>
        {failedProducts.length > 0 && (
          <ul className="publish-errors">
            {visibleFailedProducts.map((product) => (
              <li key={product.id}>
                <b>{itemTitleById.get(product.batch_item_id) ?? 'محصول'}</b>
                <span>{humanizePublishError(product.error)}</span>
              </li>
            ))}
            {failedProducts.length > visibleFailedProducts.length && (
              <li>
                <b>{toPersianDigits(failedProducts.length - visibleFailedProducts.length)} محصول دیگر</b>
                <span>برای دیدن همه، فیلدهای محصولات ناقص را از روی کارت‌ها کامل کن و دوباره ثبت کن.</span>
              </li>
            )}
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
  platform,
  missingFields,
  splittingPhotoKey,
  onDraftChange,
  onSelectBasalamCategory,
  onSplitPhoto,
}: {
  item: ProductItem;
  draft: ProductDraft;
  platform: Platform;
  missingFields: Set<RequiredField>;
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
    <article className={`panel product-card ${platform === 'torob' ? 'torob-card' : ''} ${missingFields.size > 0 ? 'needs-info' : ''}`} data-product-id={item.id}>
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
        <label className={`field product-title-field ${missingFields.has('title') ? 'missing' : ''}`}>
          <span>نام محصول</span>
          <input value={draft.title} onChange={(event) => onDraftChange({ title: event.target.value })} />
        </label>
        <label className="field product-desc-field">
          <span>توضیحات</span>
          <textarea value={draft.description} onChange={(event) => onDraftChange({ description: event.target.value })} />
        </label>
        <label className={`field price-field product-price-field ${missingFields.has('price_toman') ? 'missing' : ''}`}>
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
        {platform === 'basalam' && (
          <>
            <div className="product-extra-fields" aria-label="جزئیات ثبت در باسلام">
              <label className={`field ${missingFields.has('stock') ? 'missing' : ''}`}>
                <span>موجودی</span>
                <input
                  value={formatIntegerInput(draft.stock)}
                  inputMode="numeric"
                  placeholder="مثلا ۵"
                  onChange={(event) => onDraftChange({ stock: normalizeDigits(event.target.value).replace(/[^\d]/g, '') })}
                />
              </label>
              <label className={`field ${missingFields.has('preparation_days') ? 'missing' : ''}`}>
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
              <label className={`field ${missingFields.has('weight_grams') ? 'missing' : ''}`}>
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
              <label className={`field ${missingFields.has('package_weight_grams') ? 'missing' : ''}`}>
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
              <label className={`field ${missingFields.has('unit_quantity') ? 'missing' : ''}`}>
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
              hasValidationError={missingFields.has('category')}
              onSelect={(category) => onSelectBasalamCategory(item.id, category)}
            />
          </>
        )}
      </div>
    </article>
  );
}

function BasalamCategoryPicker({
  item,
  hasValidationError,
  onSelect,
}: {
  item: ProductItem;
  hasValidationError: boolean;
  onSelect: (category: BasalamCategory) => void;
}) {
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
    <div className={`category-picker ${needsCategory ? 'needs-category' : ''} ${hasValidationError ? 'missing' : ''}`}>
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

function missingFieldMap(issues: PublishValidationIssue[]): Map<number, Set<RequiredField>> {
  const map = new Map<number, Set<RequiredField>>();
  for (const issue of issues) {
    map.set(issue.itemId, new Set(issue.fields));
  }
  return map;
}

function validateItemsForBasalam(items: ProductItem[], drafts: DraftMap): PublishValidationIssue[] {
  return items
    .map((item) => {
      const draft = drafts[item.id] ?? toDraft(item);
      const fields: RequiredField[] = [];
      if (!draft.title.trim()) fields.push('title');
      if (parsePositivePrice(draft.price_toman) === null) fields.push('price_toman');
      if (parseStockValue(draft.stock) === null) fields.push('stock');
      const preparationDays = parsePositiveInt(draft.preparation_days);
      if (preparationDays === null) fields.push('preparation_days');
      if (parsePositiveInt(draft.weight_grams) === null) fields.push('weight_grams');
      if (parsePositiveInt(draft.package_weight_grams) === null) fields.push('package_weight_grams');
      if (parsePositiveInt(draft.unit_quantity) === null) fields.push('unit_quantity');
      const category = item.basalam_category;
      const categoryIsReady = Boolean(
        category?.category_id &&
        (category.source === 'user' || (category.confidence ?? 0) >= BASALAM_AUTO_CATEGORY_THRESHOLD),
      );
      if (!categoryIsReady) fields.push('category');
      if (
        preparationDays !== null &&
        category?.max_preparation_days &&
        preparationDays > category.max_preparation_days &&
        !fields.includes('preparation_days')
      ) {
        fields.push('preparation_days');
      }
      return fields.length > 0
        ? {
            itemId: item.id,
            title: draft.title.trim() || item.title || 'محصول',
            fields,
          }
        : null;
    })
    .filter((issue): issue is PublishValidationIssue => Boolean(issue));
}

function parsePersianPrice(value: string): number | null {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  return normalized ? Number(normalized) : null;
}

function parseNullableInt(value: string): number | null {
  const normalized = normalizeDigits(value).replace(/[^\d]/g, '');
  return normalized ? Number(normalized) : null;
}

function parsePositivePrice(value: string): number | null {
  const parsed = parsePersianPrice(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function parsePositiveInt(value: string): number | null {
  const parsed = parseNullableInt(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function parseStockValue(value: string): number | null {
  const parsed = parseNullableInt(value);
  return parsed !== null && parsed >= 0 ? parsed : null;
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
