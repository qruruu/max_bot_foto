import { lazy, Suspense, useEffect, useState } from 'react';
import { Building2, Camera, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Inbox, MapPin, RefreshCw, Search, X } from 'lucide-react';
import { publicRequest } from './requests';
import type { PublicOrganization } from './catalog';
import RecipientChoice from './RecipientChoice';
import { appealStatuses } from './statuses';
export { appealStatuses } from './statuses';
import AppealPhotos from './AppealPhotos';
import AppealShare from './AppealShare';

const TerritoryMap = lazy(() => import('./TerritoryMap'));

type WallPhoto = {id: string; url: string; preview_url: string};
type WallAppeal = {id: number; number: string; organization_name: string; address: string; place: string; subject?: string; description: string;
  status: string; created_at: string; photos: WallPhoto[]; share_url?: string;
  response: {comment: string; at: string; photos: WallPhoto[]} | null};
type WallPage = {items: WallAppeal[]; page: number; total: number; page_size: number};
const date = (value: string) => new Date(value).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'});

export default function Wall({city, organizations, revision, apiKey = ''}: {city: string; organizations: PublicOrganization[]; revision: number; apiKey?: string}) {
  const [organization, setOrganization] = useState(''), [sort, setSort] = useState('newest'), [page, setPage] = useState(1);
  const [data, setData] = useState<WallPage | null>(null), [error, setError] = useState(''), [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState(''), [query, setQuery] = useState('');
  const [mapOpen, setMapOpen] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {setQuery(search.trim()); setPage(1);}, 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {setOrganization(''); setPage(1); setData(null); setMapOpen(false);}, [city]);
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
  return <section className="signal-wall"><div className="signal-section-title"><div><h1>Обращения жителей</h1></div>
    <button className="signal-icon-button" aria-label="Обновить стену" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={19}/></button></div>
    {organizations.some(item => item.territories.length) && <div className="signal-wall-territories"><button type="button" className="signal-territories-toggle" aria-expanded={mapOpen} aria-controls="wall-territories" onClick={() => setMapOpen(value => !value)}>
      <MapPin size={17}/><span>Кто отвечает за территорию</span><ChevronDown size={17} className={mapOpen ? 'is-open' : ''}/></button>
      {mapOpen && <div id="wall-territories"><Suspense fallback={<p>Загружаем карту территорий…</p>}><TerritoryMap organizations={organizations} selected={organization} apiKey={apiKey} disabled={false}
        onChoose={id => {setOrganization(id); setPage(1); setData(null);}}/></Suspense></div>}</div>}
    <div className="signal-wall-filters"><RecipientChoice label="Организация" name="wall_organization" placeholder="Все организации" value={organization} disabled={false}
      options={organizations.map(item => ({value: item.id, label: item.name}))} onChange={id => {setOrganization(id); setPage(1); setData(null);}}/>
      <label>Порядок<select value={sort} onChange={event => {setSort(event.target.value); setPage(1); setData(null);}}><option value="newest">Сначала новые</option><option value="oldest">Сначала старые</option><option value="organization">По организации</option></select></label></div>
    <form className="signal-wall-search" role="search" onSubmit={event => {event.preventDefault(); setQuery(search.trim()); setPage(1);}}>
      <Search size={19} aria-hidden="true"/><input type="search" aria-label="Поиск обращений" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по тексту, адресу или дате"/>
      {search && <button type="button" aria-label="Очистить поиск" onClick={() => {setSearch(''); setQuery(''); setPage(1);}}><X size={18}/></button>}
    </form>
    {error && <p className="citizen-error" role="alert">{error}</p>}
    {!data ? <p role="status">Загружаем обращения…</p> : !data.items.length ? <div className="signal-empty"><Inbox size={36}/><h2>{query ? 'Ничего не найдено' : 'Пока тихо'}</h2><p>{query ? 'Попробуйте другие слова или числа.' : 'Новое обращение появится здесь сразу после отправки.'}</p></div>
      : data.items.map(item => <WallCard item={item} key={item.id}/>)}
    {data && data.total > data.page_size && <div className="signal-pagination"><button aria-label="Предыдущая страница" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft/></button><span>{page} / {Math.ceil(data.total / data.page_size)}</span><button aria-label="Следующая страница" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight/></button></div>}
  </section>;
}

function WallCard({item}: {item: WallAppeal}) {
  const [expanded, setExpanded] = useState(false), [photosOpen, setPhotosOpen] = useState(false);
  const long = item.description.length > 220;
  const description = long && !expanded ? item.description.slice(0, 220).trimEnd() + '…' : item.description;
  return <article className="signal-wall-card">
    <div className="signal-wall-meta"><span>{item.number} · {date(item.created_at)}</span><AppealShare id={item.id} url={item.share_url}/></div>
    <div className="signal-wall-summary"><div className="signal-wall-complaint">
      <h2 className="signal-wall-title">{item.subject || description}</h2>
      {item.subject && <p className="signal-wall-text">{description}</p>}
      {long && <button type="button" className="signal-read-more" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? 'Свернуть' : 'Читать полностью'}</button>}
    </div>{item.photos.length > 0 && <button type="button" className="signal-wall-thumbnail" aria-label={photosOpen ? 'Скрыть фотографии обращения' : 'Показать фотографии обращения'} aria-expanded={photosOpen} aria-controls={`wall-photos-${item.id}`} onClick={() => setPhotosOpen(value => !value)}>
      <img src={item.photos[0].preview_url} alt="" loading="lazy"/><span><Camera size={14}/>{item.photos.length} фото</span>
    </button>}</div>
    <p className={'signal-status status-' + item.status}>{appealStatuses[item.status] || item.status}</p>
    <div className="signal-wall-location"><p className="signal-wall-address"><MapPin size={16}/><span>{item.address}{item.place ? ' · ' + item.place : ''}</span></p>
      <p className="signal-wall-organization"><Building2 size={16}/><span>{item.organization_name}</span></p></div>
    {photosOpen && <div className="signal-wall-photos" id={`wall-photos-${item.id}`}>{item.photos.map((photo, index) => <a key={photo.id} href={photo.url} target="_blank" rel="noreferrer" aria-label={`Открыть фото ${index + 1} полностью`}>
      <img src={photo.preview_url} alt={`Фотография обращения, снимок ${index + 1}`} loading="lazy"/></a>)}</div>}
    {item.response && <div className="signal-public-response"><div className="signal-response-heading"><strong><Building2 size={16}/>Ответ организации<CheckCircle2 size={16}/></strong><small>{date(item.response.at)}</small></div>
      <p className="signal-response-organization">{item.organization_name}</p><p className="signal-wall-text">{item.response.comment}</p>
      <AppealPhotos photos={item.response.photos} label="Фотография ответа организации"/></div>}
  </article>;
}
