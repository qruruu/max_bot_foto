import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { CalendarCheck, Camera, CheckCheck, ChevronLeft, ChevronRight, ClipboardCheck, Clock3, RefreshCw } from 'lucide-react';
import { ErrorBox, useApp } from './App';
import { api, dateLabel, query, shiftDate } from './api';
import { dayNeedsReviewLink, dayPhotoFilters, dayPhotoLink, dayReviewDate } from './dayReviewData';
import type { DaySummary } from './dayReviewData';
import type { Photo, PhotoPage } from './types';
import { photoListPage } from './photoNavigation';
import PhotoTable from './PhotoTable';
import { canEditPhoto, updatePhotoDefect } from './photoWork';
import './day-reviews.css';

export default function DayReviews() {
  const {meta, notify, user} = useApp();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const day = dayReviewDate(params.get('day'), shiftDate(meta.today, -1));
  const work = params.get('work') || '';
  const page = photoListPage(params.get('page'));
  const filters = dayPhotoFilters(day, work, page);
  const key = query(filters);
  const [data, setData] = useState<{summary: DaySummary; photos: PhotoPage} | null>(null);
  const [error, setError] = useState(''), [revision, setRevision] = useState(0), [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const closing = useRef(false);
  const [defectBusy, setDefectBusy] = useState<number | null>(null);
  const defectSaving = useRef(false);
  const loadRevision = useRef(0);
  function change(values: Record<string, string>) {
    setParams({...Object.fromEntries(params), day, page: '1', ...values});
  }
  useEffect(() => {
    const revision = ++loadRevision.current;
    const controller = new AbortController();
    setData(null); setError('');
    Promise.all([
      api<DaySummary>('/day-reviews/' + day, 'GET', undefined, controller.signal),
      api<PhotoPage>('/photos?' + key, 'GET', undefined, controller.signal),
    ]).then(([summary, photos]) => {if (!controller.signal.aborted && revision === loadRevision.current) setData({summary, photos});})
      .catch(e => {if (!controller.signal.aborted && revision === loadRevision.current) setError(e.message);});
    return () => controller.abort();
  }, [day, key, revision]);
  async function markDefect(photo: Photo, checked: boolean) {
    if (defectSaving.current || closing.current || !canEditPhoto(user, photo) || photo.is_spam) return;
    defectSaving.current = true; setDefectBusy(photo.id); setError('');
    const requestRevision = ++loadRevision.current;
    try {
      await updatePhotoDefect(photo, checked);
      const [summary, photos] = await Promise.all([
        api<DaySummary>('/day-reviews/' + day), api<PhotoPage>('/photos?' + key),
      ]);
      if (requestRevision === loadRevision.current) setData({summary, photos});
      notify(checked ? 'Неисправность отмечена' : 'Отметка о неисправности снята');
    } catch (e) {
      if (requestRevision === loadRevision.current) {setData(null); setError((e as Error).message);}
      throw e;
    } finally {defectSaving.current = false; setDefectBusy(null);}
  }
  async function closeDay() {
    if (!data || closing.current || defectSaving.current) return;
    closing.current = true; setBusy(true); setError('');
    try {
      const result = await api<{confirmed: number}>('/day-reviews/' + day + '/close', 'POST', {snapshot: data.summary.snapshot});
      dialog.current?.close();
      notify(`За ${dateLabel(day)} подтверждено фотографий: ${result.confirmed}.`);
      change({work: ''}); setRevision(value => value + 1);
    } catch (e) {
      dialog.current?.close(); setError((e as Error).message);
    } finally {closing.current = false; setBusy(false);}
  }
  const summary = data?.summary;
  const added = summary?.closed_before;
  return <>
    <header className="page-header"><div><span className="eyebrow">КОНТРОЛЬ ОПЕРАТОРА</span><h1>Проверка дней</h1>
      <p>Проверьте виды работ, выбранные нейросетью, и закройте день по всем доступным вам чатам.</p></div>
      <button aria-label="Обновить проверку дня" disabled={busy} onClick={() => setRevision(value => value + 1)}><RefreshCw size={18}/></button>
    </header>
    <section className="panel day-toolbar">
      <div className="day-date-controls"><button aria-label="Предыдущий день" disabled={busy} onClick={() => change({day: shiftDate(day, -1), work: ''})}><ChevronLeft size={18}/></button>
        <label>Дата фотографий<input type="date" value={day} disabled={busy} onChange={e => {if (e.target.value) change({day: e.target.value, work: ''});}}/></label>
        <button aria-label="Следующий день" disabled={busy} onClick={() => change({day: shiftDate(day, 1), work: ''})}><ChevronRight size={18}/></button>
      </div>
      <div className="day-report-actions">
        <button className="primary" disabled={busy || defectBusy !== null || !summary?.can_close} onClick={() => dialog.current?.showModal()}><CheckCheck size={18}/>{added ? 'Добавить в день' : 'Закрыть день'}</button></div>
    </section>
    <ErrorBox error={error}/>
    {summary && data && <>
      <div className="day-stats">
        <section className="panel"><Camera size={20}/><span>Всего за {dateLabel(day)}</span><strong>{summary.total}</strong></section>
        <section className="panel"><CalendarCheck size={20}/><span>Проверено и включено в день</span><strong>{summary.confirmed}</strong></section>
        <section className={'panel ' + (summary.ai_pending ? 'day-pending' : '')}><Clock3 size={20}/><span>Проверить за нейросетью</span><strong>{summary.ai_pending}</strong></section>
        <Link className={'panel day-review-stat ' + (summary.needs_review ? 'day-pending' : '')} to={dayNeedsReviewLink(day)}>
          <ClipboardCheck size={20}/><span>Требуют проверки</span><strong>{summary.needs_review}</strong><small>Открыть фотографии за {dateLabel(day)}<ChevronRight size={14}/></small>
        </Link>
      </div>
      <p className="hint">Всего — все {summary.cohort === 'test' ? 'тестовые' : 'рабочие'} фотографии за дату снимка. «Проверить за нейросетью» — её решения, ещё не включённые в проверенный день. «Требуют проверки» — фотографии, по которым система ждёт решения оператора. Одно фото может быть в обеих очередях.</p>
      <section className={'panel day-state ' + (!summary.pending && summary.confirmed ? 'day-complete' : '')}>
        <h2>{!summary.total ? 'За эту дату фотографий пока нет' : !summary.pending ? 'День закрыт — все фотографии проверены' : added ? 'В закрытом дне есть дополнения' : 'День ожидает проверки'}</h2>
        <p>{summary.pending ? `На проверку за нейросетью: ${summary.ai_pending}.${summary.manual_pending ? ` Уже распределены оператором или настройкой чата: ${summary.manual_pending} — они войдут в день при подтверждении без повторной проверки.` : ''}${summary.changed ? ` Изменены после закрытия: ${summary.changed}.` : ''}` : summary.confirmed ? 'Новые поступления за эту дату появятся отдельно. Повторно проходить проверенные фотографии не потребуется.' : 'Дата берётся с самой фотографии. Снимки без распознанной даты сначала нужно разобрать в разделе «Требуют проверки».'}</p>
        {!!summary.blocked && <p className="warning-text">Сначала нужно разобрать фотографии с вопросами или ошибками: {summary.blocked}. Закрытие станет доступно после исправления. <Link className="text-button" to={'/review?' + query({review_day: day, all_dates: '1'})}>Перейти в «Требуют проверки»</Link></p>}
        {summary.last_confirmation_at && <small>Последнее подтверждение: {new Date(summary.last_confirmation_at).toLocaleString('ru-RU')}</small>}
      </section>
      <section className="panel photo-panel">
        <label className="day-work-filter">Вид работы<select value={work} onChange={e => change({work: e.target.value})}><option value="">Все виды работ</option>{summary.work_types.filter(w => w.pending).map(w => <option key={w.code} value={w.code}>{w.name} ({w.pending})</option>)}</select></label>
        <div className="section-title"><h2>Проверка за нейросетью</h2>
          {!!data.photos.items.length && <button onClick={() => navigate(dayPhotoLink(data.photos.items[0].id, day, filters))}>Просмотреть подряд<ChevronRight size={16}/></button>}</div>
        {!data.photos.items.length ? <p className="muted">{work ? 'В этом виде работ фотографий нейросети для проверки нет.' : 'Фотографий нейросети для проверки нет. Ручные решения повторно проверять не требуется.'}</p> : <PhotoTable photos={data.photos.items} openPhoto={id => navigate(dayPhotoLink(id, day, filters))} defectBusy={defectBusy} onDefect={markDefect}/>}
        <div className="pagination"><span>Страница {data.photos.page} из {Math.max(1, Math.ceil(data.photos.total / data.photos.page_size))}</span><button disabled={data.photos.page <= 1} onClick={() => change({page: String(data.photos.page - 1)})}>Назад</button><button disabled={data.photos.page * data.photos.page_size >= data.photos.total} onClick={() => change({page: String(data.photos.page + 1)})}>Далее</button></div>
      </section>
    </>}
    {!data && !error && <p className="loading">Собираем фотографии дня…</p>}
    <p className="hint">Дубли, пересланные фотографии и спам в проверку дня не входят. Подтверждение охватывает все доступные чаты и виды работ за дату снимка, включая фотографии за эту дату, полученные позже.</p>
    <dialog ref={dialog} className="day-close-dialog" onCancel={e => {if (busy) e.preventDefault();}}>
      <h2>{added ? 'Подтвердить дополнения?' : 'Закрыть день?'}</h2>
      <p>Подтверждаю проверку {summary?.ai_pending || 0} решений нейросети за {dateLabel(day)} по доступным мне чатам и видам работ.</p>
      <p>В день будет включено фотографий: {summary?.pending || 0}. Уже распределённые оператором фотографии включаются вместе с ними.</p>
      <p className="hint">Видимый фильтр по виду работы не ограничивает подтверждение. Поздние поступления останутся на отдельной проверке.</p>
      <div className="day-dialog-actions"><button disabled={busy} onClick={() => dialog.current?.close()}>Отмена</button><button className="primary" disabled={busy || defectBusy !== null || !summary?.can_close} onClick={closeDay}>{busy ? 'Подтверждаем…' : 'Подтвердить проверку'}</button></div>
    </dialog>
  </>;
}
