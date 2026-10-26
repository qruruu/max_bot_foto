import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowUpRight, Camera, ChevronLeft, ChevronRight, Inbox, RefreshCw } from 'lucide-react';
import { api } from '../api';
import './owner-appeals.css';

type Status = 'NEW' | 'IN_REVIEW' | 'RESOLVED' | 'SPAM';
type Appeal = {id: number; number: string; city: string; address: string; place: string; category: string; description: string;
  organization_id: string | null; organization_name: string; work_type_name: string;
  organization_hint: string; contact: string; photo_count: number; status: Status; owner_note: string; version: number;
  created_at: string; updated_at: string; preview_url: string};
type Photo = {id: string; url: string; preview_url: string; original_url: string; captured_at: string; latitude: number; longitude: number; accuracy: number};
type Detail = Appeal & {photos: Photo[]};
type Page = {items: Appeal[]; total: number; page: number; page_size: number; categories: Record<string, string>; public_url: string};
const statuses: Record<Status, string> = {NEW: 'Новое', IN_REVIEW: 'На рассмотрении', RESOLVED: 'Решено', SPAM: 'Спам'};
const moment = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});

export default function OwnerAppeals({organization = false, endpoint: customEndpoint, readOnly = false, refreshKey = 0}: {
  organization?: boolean; endpoint?: string; readOnly?: boolean; refreshKey?: number;
}) {
  const endpoint = customEndpoint || (organization ? '/appeals' : '/platform/appeals');
  const [data, setData] = useState<Page | null>(null), [status, setStatus] = useState(''), [page, setPage] = useState(1);
  const [detail, setDetail] = useState<Detail | null>(null), [selected, setSelected] = useState<number | null>(null);
  const [nextStatus, setNextStatus] = useState<Status>('NEW'), [note, setNote] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const active = useRef(true);
  useEffect(() => {active.current = true; return () => {active.current = false;};}, []);
  useEffect(() => {
    const controller = new AbortController(); setError(''); setData(null);
    api<Page>(`${endpoint}?page=${page}${status ? '&status=' + status : ''}`, 'GET', undefined, controller.signal)
      .then(result => {
        const lastPage = Math.max(1, Math.ceil(result.total / result.page_size));
        if (page > lastPage) setPage(lastPage);
        else setData(result);
      }).catch(error => {if (error.name !== 'AbortError') setError(error.message);});
    return () => controller.abort();
  }, [page, status, revision, endpoint, refreshKey]);
  useEffect(() => {setSelected(null); setPage(1);}, [endpoint]);
  useEffect(() => {
    const refresh = () => {setSelected(null); setStatus(''); setPage(1); setRevision(value => value + 1);};
    window.addEventListener('refresh-appeals', refresh);
    return () => window.removeEventListener('refresh-appeals', refresh);
  }, []);
  useEffect(() => {
    if (selected === null) {setDetail(null); return;}
    const controller = new AbortController(); setError(''); setDetail(null);
    api<Detail>(endpoint + '/' + selected, 'GET', undefined, controller.signal).then(item => {
      setDetail(item); setNextStatus(item.status); setNote(item.owner_note);
    }).catch(error => {if (error.name !== 'AbortError') setError(error.message);});
    return () => controller.abort();
  }, [selected, revision, endpoint, refreshKey]);

  async function save() {
    if (!detail || readOnly) return;
    setBusy(true); setError('');
    try {
      await api(endpoint + '/' + detail.id, 'PATCH', {status: nextStatus, owner_note: note, expected_version: detail.version});
      window.dispatchEvent(new Event('appeals-changed'));
      if (active.current) setRevision(value => value + 1);
    } catch (error) {if (active.current) setError((error as Error).message);}
    finally {if (active.current) setBusy(false);}
  }
  return <section className="owner-appeals">
    <header className="page-header"><div><span className="eyebrow">{organization ? 'ОБРАЩЕНИЯ В ВАШУ ОРГАНИЗАЦИЮ' : 'ОБРАЩЕНИЯ ВСЕХ ОРГАНИЗАЦИЙ'}</span><h1>Обращения граждан</h1>
      <p>Нарушения, о которых сообщили жители: описание, фотографии и состояние рассмотрения.</p></div>
      <button disabled={busy} aria-label="Обновить обращения" onClick={() => setRevision(value => value + 1)}><RefreshCw size={18}/></button></header>
    {error && <p className="error" role="alert">{error}</p>}
    {selected !== null ? <>
      <button className="owner-appeal-back" disabled={busy} onClick={() => setSelected(null)}><ArrowLeft size={16}/>Все обращения</button>
      {!detail ? !error && <p className="loading">Открываем обращение…</p> : <div className="owner-appeal-detail">
        <article className="panel"><div className="section-title"><h2>{detail.number}</h2><span className={'badge appeal-status-' + detail.status}>{statuses[detail.status]}</span></div>
          <p className="hint">Получено {moment(detail.created_at)}</p><h3>{detail.work_type_name || data?.categories[detail.category] || detail.category}</h3>
          <dl><dt>Адрес</dt><dd>{detail.city}, {detail.address}</dd><dt>Место</dt><dd>{detail.place}</dd>
            <dt>Описание</dt><dd className="owner-appeal-text">{detail.description}</dd>
            <dt>Организация</dt><dd>{detail.organization_name || detail.organization_hint || 'Не назначена — обращение из прежней формы'}</dd>
            {!readOnly && <><dt>Контакт</dt><dd>{detail.contact || 'Не оставлен'}</dd></>}</dl>
          {!readOnly && <div className="owner-appeal-edit"><label>Состояние<select disabled={busy} value={nextStatus} onChange={event => setNextStatus(event.target.value as Status)}>
            {Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>Внутренняя заметка<textarea disabled={busy} rows={4} maxLength={4000} placeholder="Что проверено и что нужно сделать…" value={note} onChange={event => setNote(event.target.value)}/></label>
            <p className="hint">Заметка видна администраторам этой организации и владельцу сервиса.</p>
            <button className="primary" disabled={busy || (nextStatus === detail.status && note === detail.owner_note)} onClick={() => void save()}>{busy ? 'Сохраняем…' : 'Сохранить'}</button></div>}
        </article>
        <div className="owner-appeal-photos">{detail.photos.map((photo, index) => <article className="panel" key={photo.id}>
          <a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={`Фотография обращения ${detail.number}, снимок ${index + 1}`}/></a>
          <div><strong>Снято {moment(photo.captured_at)}</strong><p className="hint">{photo.latitude.toFixed(6)}, {photo.longitude.toFixed(6)} · точность ±{Math.ceil(photo.accuracy)} м</p>
            <a className="button" href={photo.original_url} target="_blank" rel="noreferrer"><ArrowDownToLine size={15}/>Исходный кадр без плашки</a></div>
        </article>)}</div>
      </div>}
    </> : <>
      {data && !readOnly && <div className="panel owner-appeal-public"><div><strong>Страница для жителей</strong><p className="hint">Передайте ссылку или разместите её в объявлениях.</p></div>
        <a className="button" href={data.public_url} target="_blank" rel="noreferrer">Открыть форму<ArrowUpRight size={16}/></a></div>}
      <div className="owner-appeal-toolbar"><label>Состояние<select value={status} onChange={event => {setStatus(event.target.value); setPage(1);}}><option value="">Все обращения</option>
        {Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><span className="hint">{data ? `${data.total} обращений` : 'Загружаем…'}</span></div>
      {!data ? !error && <p className="loading">Загружаем обращения…</p> : !data.items.length ? <div className="panel empty"><Inbox size={32}/><h3>Обращений пока нет</h3><p>Новые анкеты жителей появятся здесь.</p></div> : <div className="owner-appeal-list">{data.items.map(item => <button className="panel owner-appeal-card" key={item.id} onClick={() => setSelected(item.id)}>
        <img src={item.preview_url} alt="" loading="lazy"/><div><div className="owner-appeal-card-top"><strong>{item.number}</strong><span className={'badge appeal-status-' + item.status}>{statuses[item.status]}</span></div>
          <h3>{item.work_type_name || data.categories?.[item.category] || item.category}</h3>{(!organization || readOnly) && <p>{item.organization_name || 'Без назначенной организации'}</p>}<p>{item.city}, {item.address}</p><p className="owner-appeal-excerpt">{item.description}</p>
          <small>{moment(item.created_at)}<span><Camera size={13}/>{item.photo_count}</span></small></div></button>)}</div>}
      {data && data.total > data.page_size && <div className="owner-appeal-pagination"><button disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={17}/></button>
        <span>{page} / {Math.ceil(data.total / data.page_size)}</span><button disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight size={17}/></button></div>}
    </>}
  </section>;
}
