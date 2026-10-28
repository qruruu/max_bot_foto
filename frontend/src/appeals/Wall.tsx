import { lazy, Suspense, useEffect, useState } from 'react';
import { CheckCircle2, ChevronLeft, ChevronRight, Inbox, RefreshCw, Search, X } from 'lucide-react';
import { publicRequest } from './requests';
import type { PublicOrganization } from './catalog';
import { citizenWorkOption } from './workTypes';
import RecipientChoice from './RecipientChoice';
import AppealPhotos from './AppealPhotos';

const TerritoryMap = lazy(() => import('./TerritoryMap'));

export const appealStatuses: Record<string, string> = {NEW: 'Новое', IN_REVIEW: 'На рассмотрении', ASSIGNED: 'Назначен исполнитель',
  IN_PROGRESS: 'В работе', COMPLETED: 'На проверке результата', REJECTED: 'Исполнитель отклонил', CANCELLED: 'Задача отменена', RESOLVED: 'Закрыто', DECLINED: 'Отказ', SPAM: 'Спам'};
type WallPhoto = {id: string; url: string; preview_url: string};
type WallAppeal = {id: number; number: string; organization_name: string; address: string; place: string; description: string;
  category: string; work_type_name?: string; status: string; created_at: string; photos: WallPhoto[];
  response: {comment: string; at: string; photos: WallPhoto[]} | null};
type WallPage = {items: WallAppeal[]; page: number; total: number; page_size: number};
const date = (value: string) => new Date(value).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'});

export default function Wall({city, organizations, revision, apiKey = ''}: {city: string; organizations: PublicOrganization[]; revision: number; apiKey?: string}) {
  const [organization, setOrganization] = useState(''), [sort, setSort] = useState('newest'), [page, setPage] = useState(1);
  const [data, setData] = useState<WallPage | null>(null), [error, setError] = useState(''), [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState(''), [query, setQuery] = useState('');
  useEffect(() => {
    const timer = window.setTimeout(() => {setQuery(search.trim()); setPage(1);}, 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {setOrganization(''); setPage(1); setData(null);}, [city]);
  const soleOrganization = organizations.length === 1 ? organizations[0].id : '';
  useEffect(() => {
    setOrganization(current => soleOrganization || (organizations.some(item => item.id === current) ? current : ''));
  }, [soleOrganization, organizations]);
  useEffect(() => {
    const changed = () => {if (!document.hidden) setRefresh(value => value + 1);};
    const timer = window.setInterval(changed, 30_000);
    window.addEventListener('focus', changed); window.addEventListener('online', changed);
    return () => {window.clearInterval(timer); window.removeEventListener('focus', changed); window.removeEventListener('online', changed);};
  }, []);
  useEffect(() => {
    if (!city) return;
    let active = true;
    const params = new URLSearchParams({city, page: String(page), sort});
    if (organization) params.set('organization_id', organization);
    if (query) params.set('q', query);
    publicRequest<WallPage>('/wall?' + params, {method: 'GET'}).then(value => {
      if (!active) return;
      const last = Math.max(1, Math.ceil(value.total / value.page_size));
      if (page > last) setPage(last); else setData(value);
      setError('');
    }).catch(reason => {if (active) setError(reason.message);});
    return () => {active = false;};
  }, [city, page, organization, sort, query, revision, refresh]);
  if (!city) return <div className="signal-empty"><Inbox size={36}/><h2>Выберите город</h2><p>Здесь появятся обращения его жителей.</p></div>;
  return <section className="signal-wall"><div className="signal-section-title"><div><span className="signal-eyebrow">ЧТО ПРОИСХОДИТ В ГОРОДЕ</span><h1>Обращения жителей</h1></div>
    <button className="signal-icon-button" aria-label="Обновить стену" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={19}/></button></div>
    <form className="signal-wall-search" role="search" onSubmit={event => {event.preventDefault(); setQuery(search.trim()); setPage(1);}}>
      <Search size={19} aria-hidden="true"/><input type="search" aria-label="Поиск обращений" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по тексту, адресу или дате"/>
      {search && <button type="button" aria-label="Очистить поиск" onClick={() => {setSearch(''); setQuery(''); setPage(1);}}><X size={18}/></button>}
    </form>
    <Suspense fallback={<p>Загружаем карту территорий…</p>}><TerritoryMap organizations={organizations} selected={organization} apiKey={apiKey} disabled={false}
      onChoose={id => {setOrganization(id); setPage(1); setData(null);}}/></Suspense>
    <div className="signal-wall-filters"><RecipientChoice label="Организация" name="wall_organization" placeholder="Все организации" value={organization} disabled={false}
      options={organizations.map(item => ({value: item.id, label: item.name}))} onChange={id => {setOrganization(id); setPage(1); setData(null);}}/>
      <label>Порядок<select value={sort} onChange={event => {setSort(event.target.value); setPage(1); setData(null);}}><option value="newest">Сначала новые</option><option value="oldest">Сначала старые</option><option value="organization">По организации</option></select></label></div>
    {error && <p className="citizen-error" role="alert">{error}</p>}
    {!data ? <p role="status">Загружаем обращения…</p> : !data.items.length ? <div className="signal-empty"><Inbox size={36}/><h2>{query ? 'Ничего не найдено' : 'Пока тихо'}</h2><p>{query ? 'Попробуйте другие слова или числа.' : 'Новое обращение появится здесь сразу после отправки.'}</p></div>
      : data.items.map(item => <article className="signal-wall-card" key={item.id}>
        <div className="signal-wall-meta"><span>{item.number} · {date(item.created_at)}</span><span className={'signal-status status-' + item.status}>{appealStatuses[item.status] || item.status}</span></div>
        <h2>{citizenWorkOption({code: item.category, name: item.work_type_name || 'Обращение'}).label}</h2>
        <p className="signal-wall-address">{item.address}{item.place ? ' · ' + item.place : ''}</p><p className="signal-wall-organization">{item.organization_name}</p>
        <p className="signal-wall-text">{item.description}</p><AppealPhotos photos={item.photos}/>
        {item.response && <div className="signal-public-response"><strong><CheckCircle2 size={17}/>Ответ организации</strong><p className="signal-wall-text">{item.response.comment}</p>
          <AppealPhotos photos={item.response.photos} label="Фотография ответа организации"/><small>{date(item.response.at)}</small></div>}
      </article>)}
    {data && data.total > data.page_size && <div className="signal-pagination"><button aria-label="Предыдущая страница" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft/></button><span>{page} / {Math.ceil(data.total / data.page_size)}</span><button aria-label="Следующая страница" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight/></button></div>}
  </section>;
}
