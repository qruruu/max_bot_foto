import { useEffect, useRef, useState } from 'react';
import type { Geometry, MultiPolygon, Polygon } from 'geojson';
import { Camera, Check, Download, LocateFixed, Pencil, Plus, RefreshCw, Route, Save, Trash2, Undo2, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api, query } from '../api';
import { ErrorBox, useApp } from '../App';
import { loadYandexMaps, polygonsOf, type YMap, type YMaps, type YMarker, type YPolygon, type YPolyline } from '../yandexMaps';
import { useTheme } from '../theme';
import './photo-routes.css';

type XY = [number, number];
type Building = Polygon | MultiPolygon;
type Plan = {district_id: number; version: number; enabled: boolean; chat_ids: number[]; paths: XY[][]; buildings: Building[]; buildings_source: string; snap_m: number; max_gap_minutes: number};
type Catalogue = {territories: Territory[]; plans: Plan[]; chats: {id: number; name: string}[]};
type Territory = {type: 'Feature'; geometry: Building; properties: {id: number; name: string; active: boolean}};
type Coverage = {version: number; total_m: number; covered_m: number; remaining_m: number; remaining_percent: number | null; covered: Geometry; remaining: Geometry; matched_photos: number; photo_count: number; unknown_time: number; diagnostics: Record<string, number>; photos: {id: number; longitude: number; latitude: number; taken_at: string; chat_name: string}[]};
type Mode = 'route' | 'building' | '';
const emptyPlan = (district_id: number): Plan => ({district_id, version: 0, enabled: false, chat_ids: [], paths: [], buildings: [], buildings_source: 'manual', snap_m: 25, max_gap_minutes: 45});
const distance = (value: number) => value >= 1000 ? (value / 1000).toLocaleString('ru-RU', {maximumFractionDigits: 2}) + ' км' : Math.round(value).toLocaleString('ru-RU') + ' м';

function lines(geometry: Geometry): number[][][] {
  if (geometry.type === 'LineString') return [geometry.coordinates];
  if (geometry.type === 'MultiLineString') return geometry.coordinates;
  if (geometry.type === 'GeometryCollection') return geometry.geometries.flatMap(lines);
  return [];
}

export default function PhotoRoutes() {
  const {user, meta, notify} = useApp();
  const {theme} = useTheme();
  const admin = user.role === 'ADMIN_OPERATOR';
  const [catalogue, setCatalogue] = useState<Catalogue>({plans: [], chats: [], territories: []});
  const [territories, setTerritories] = useState<Territory[]>([]);
  const [district, setDistrict] = useState(0), [chat, setChat] = useState('');
  const [from, setFrom] = useState(meta.today), [to, setTo] = useState(meta.today), [period, setPeriod] = useState(false);
  const [revision, setRevision] = useState(0), [coverage, setCoverage] = useState<Coverage | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [mapError, setMapError] = useState('');
  const [draft, setDraft] = useState<Plan | null>(null), [mode, setMode] = useState<Mode>('');
  const [points, setPoints] = useState<XY[]>([]), [checked, setChecked] = useState(false);
  const container = useRef<HTMLDivElement>(null), map = useRef<YMap | null>(null), sdk = useRef<YMaps | null>(null);
  const click = useRef<(xy: XY) => void>(() => {});
  const [ready, setReady] = useState(false);
  const plan = catalogue.plans.find(p => p.district_id === district);
  const territory = territories.find(t => t.properties.id === district);
  const eligible = catalogue.chats.filter(c => plan?.enabled && plan.chat_ids.includes(c.id));
  const displayed = draft || plan;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api<Catalogue>('/photo-routes', 'GET', undefined, controller.signal)
      .then(data => {
        setCatalogue(data); setTerritories(data.territories);
        setDistrict(value => value || data.plans.find(p => p.enabled)?.district_id || (admin ? data.territories.find(f => f.properties.active)?.properties.id : 0) || 0);
      }).catch(e => {if (!controller.signal.aborted) setError(e.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [revision, admin]);

  useEffect(() => {
    const controller = new AbortController();
    setCoverage(null);
    if (!plan?.enabled || !eligible.length || draft) {setLoading(false); return;}
    setLoading(true); setError('');
    api<Coverage>(`/photo-routes/${district}/coverage?` + query({date_from: from, date_to: period ? to : from, chat_id: chat}), 'GET', undefined, controller.signal)
      .then(setCoverage).catch(e => {if (!controller.signal.aborted) setError(e.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [district, plan, chat, from, to, period, draft, revision]);

  useEffect(() => {
    let cancelled = false;
    setReady(false); setMapError('');
    loadYandexMaps(meta.yandex_maps_api_key).then(value => {
      if (cancelled || !container.current) return;
      sdk.current = value;
      map.current = new value.Map(container.current, {center: [72.603, 61.099], zoom: 13, controls: ['zoomControl', 'typeSelector', 'fullscreenControl']}, {suppressMapOpenBlock: true});
      map.current.events?.add('click', event => {const xy = event.get('coords'); if (Array.isArray(xy)) click.current(xy as XY);});
      setReady(true);
    }).catch(e => {if (!cancelled) setMapError(e.message);});
    return () => {cancelled = true; map.current?.destroy(); map.current = null;};
  }, [meta.yandex_maps_api_key, theme]);

  click.current = xy => {if (draft && mode) {setPoints(value => [...value, xy]); setChecked(false);}};

  function fit() {
    if (!territory) return;
    const coords = polygonsOf(territory.geometry).flat(2);
    map.current?.setBounds([[Math.min(...coords.map(p => p[0])), Math.min(...coords.map(p => p[1]))],
      [Math.max(...coords.map(p => p[0])), Math.max(...coords.map(p => p[1]))]], {checkZoomRange: true, zoomMargin: 35});
  }
  useEffect(() => {if (ready) fit();}, [ready, district, territories]);

  useEffect(() => {
    const value = sdk.current, canvas = map.current;
    if (!ready || !value || !canvas) return;
    const objects: (YMarker | YPolygon | YPolyline)[] = [];
    const add = (object: YMarker | YPolygon | YPolyline) => {canvas.geoObjects.add(object); objects.push(object);};
    const line = (coords: number[][], color: string, width = 5) => {
      if (value.Polyline) add(new value.Polyline(coords, {}, {strokeColor: color, strokeWidth: width, strokeOpacity: .9, interactivityModel: 'default#transparent'}));
    };
    if (territory) for (const polygon of polygonsOf(territory.geometry)) add(new value.Polygon(polygon, {}, {fillColor: '#4d71d411', strokeColor: '#5673cf', strokeWidth: 2, interactivityModel: 'default#transparent'}));
    for (const building of displayed?.buildings || []) for (const polygon of polygonsOf(building)) add(new value.Polygon(polygon, {}, {fillColor: '#8f96a66a', strokeColor: '#6f7685', strokeWidth: 1, interactivityModel: 'default#transparent'}));
    if (draft || !coverage) for (const path of displayed?.paths || []) line(path, '#4361d9');
    if (!draft && coverage) {
      lines(coverage.remaining).forEach(path => line(path, '#e59437', 6));
      lines(coverage.covered).forEach(path => line(path, '#1d9a70', 7));
      for (const photo of coverage.photos) if (value.Placemark) add(new value.Placemark([photo.longitude, photo.latitude],
        {hintContent: `Фото №${photo.id}`, balloonContent: `Фото №${photo.id}`}, {preset: 'islands#blueCircleDotIcon'}));
    }
    if (points.length >= 2) line(points, mode === 'building' ? '#a14e52' : '#7154d8', 4);
    if (points.length && value.Placemark) for (const point of points) add(new value.Placemark(point, {}, {preset: 'islands#violetCircleDotIcon'}));
    return () => {for (const object of objects) canvas.geoObjects.remove(object);};
  }, [ready, territory, displayed, coverage, points, mode]);

  function begin() {setDraft(structuredClone(plan || emptyPlan(district))); setChecked(false); setPoints([]); setMode(''); setError('');}
  function cancel() {setDraft(null); setMode(''); setPoints([]); setChecked(false); setError('');}
  function finish() {
    if (!draft) return;
    if (mode === 'route' && points.length >= 2) setDraft({...draft, paths: [...draft.paths, points]});
    else if (mode === 'building' && points.length >= 3) setDraft({...draft, buildings: [...draft.buildings, {type: 'Polygon', coordinates: [[...points, points[0]]]}], buildings_source: draft.buildings_source + (draft.buildings_source.includes('manual') ? '' : ' + manual')});
    else return;
    setPoints([]); setMode(''); setChecked(false);
  }
  async function save() {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      const result = await api<Plan>(`/photo-routes/${district}`, 'PUT', {...draft, buildings_checked: checked, district_id: undefined});
      setCatalogue(value => ({...value, plans: [...value.plans.filter(p => p.district_id !== district), result]}));
      cancel(); setChat(''); notify('Маршрут и выбранные чаты сохранены');
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function buildings() {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      const result = await api<{buildings: Building[]; source: string}>(`/photo-routes/${district}/buildings`);
      setDraft({...draft, buildings: [...draft.buildings, ...result.buildings], buildings_source: result.source + ' + manual'});
      setChecked(false); notify(`Загружено контуров домов: ${result.buildings.length}. Проверьте их на карте`);
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }

  const choices = territories.filter(t => admin || catalogue.plans.some(p => p.district_id === t.properties.id && p.enabled));
  return <>
    <header className="page-header"><div><span className="eyebrow">КОНТРОЛЬ ОБХОДА</span><h1>Маршруты по фото</h1><p>Прогресс по отмеченному маршруту внутри выбранной территории.</p></div><button disabled={busy || !!draft} onClick={() => setRevision(v => v + 1)} aria-label="Обновить маршруты"><RefreshCw size={18}/></button></header>
    <div className="route-photo-filters panel">
      <label>Территория<select disabled={!!draft || busy} value={district} onChange={e => {setDistrict(Number(e.target.value)); setChat('');}}>{!choices.length && <option value={0}>Нет доступных маршрутов</option>}{choices.map(t => <option key={t.properties.id} value={t.properties.id}>{t.properties.name}</option>)}</select></label>
      {!draft && <><label>Чат<select value={chat} onChange={e => setChat(e.target.value)}><option value="">Все выбранные чаты</option>{eligible.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label>Период<select value={period ? 'period' : 'day'} onChange={e => setPeriod(e.target.value === 'period')}><option value="day">За день</option><option value="period">За период</option></select></label>
        <label>{period ? 'С' : 'Дата'}<input type="date" value={from} onChange={e => setFrom(e.target.value)}/></label>{period && <label>По<input type="date" value={to} min={from} onChange={e => setTo(e.target.value)}/></label>}
      {admin && !!district && <button onClick={begin}><Pencil size={16}/>{plan ? 'Настроить маршрут' : 'Отметить маршрут'}</button>}</>}
    </div>
    <ErrorBox error={error}/>
    {!draft && !loading && !eligible.length && <section className="panel"><h2>Маршрут ещё не включён</h2><p>{admin ? 'Отметьте путь на карте, проверьте контуры зданий и выберите чаты, фотографии которых будут учитываться.' : 'Для доступных вам чатов пока нет включённых маршрутов.'}</p>{admin && !territories.length && <><p>В этой локальной базе пока нет границ территорий.</p><Link className="button" to="/districts">Добавить территорию</Link></>}</section>}
    {!draft && coverage && <section className="route-photo-stats" aria-live="polite">
      <div className="panel route-photo-progress"><span>Осталось пройти</span><strong>{coverage.remaining_percent === null ? '—' : coverage.remaining_percent.toLocaleString('ru-RU') + '%'}</strong><progress max={100} value={100 - (coverage.remaining_percent ?? 100)} aria-label="Пройденная доля маршрута"/><small>Оценка по фотографиям</small></div>
      <div className="panel"><span>Осталось</span><strong>{distance(coverage.remaining_m)}</strong><small>Из {distance(coverage.total_m)} маршрута</small></div>
      <div className="panel"><span>Пройдено по фото</span><strong>{distance(coverage.covered_m)}</strong><small>Повторные проходы учтены один раз</small></div>
      <div className="panel"><span>Подходящие снимки</span><strong>{coverage.matched_photos}</strong><small>Из {coverage.photo_count} принятых за период</small></div>
    </section>}
    {!draft && loading && <p role="status">Загружаем маршрут и фотографии…</p>}
    <div className={'route-photo-layout ' + (draft ? 'editing' : '')}>
      {draft && <section className="panel route-photo-editor"><h2>Настройка маршрута</h2><p>Рисуйте по дорогам и проходам. Каждая линия должна целиком оставаться в этой территории и обходить дома.</p>
        <fieldset disabled={busy}><legend>Чаты для этого маршрута</legend>{catalogue.chats.map(c => <label className="route-photo-check" key={c.id}><input type="checkbox" checked={draft.chat_ids.includes(c.id)} onChange={e => setDraft({...draft, chat_ids: e.target.checked ? [...draft.chat_ids, c.id] : draft.chat_ids.filter(id => id !== c.id)})}/>{c.name}</label>)}{!catalogue.chats.length && <p>Сначала добавьте чаты в разделе «Чаты MAX».</p>}</fieldset>
        <fieldset disabled={busy}><legend>1. Здания</legend><button onClick={buildings}><Download size={15}/>Загрузить контуры домов</button><button disabled={!!mode} onClick={() => {setMode('building'); setPoints([]);}}><Plus size={15}/>Обвести дом вручную</button>
          <p className="hint">Контуров: {draft.buildings.length}. Карта может содержать не все здания — дополните недостающие.</p>
          {draft.buildings.length > 0 && <button onClick={() => {setDraft({...draft, buildings: draft.buildings.slice(0, -1)}); setChecked(false);}}><Undo2 size={15}/>Убрать последний контур</button>}</fieldset>
        <fieldset disabled={busy}><legend>2. Обязательный маршрут</legend><button disabled={!!mode} onClick={() => {setMode('route'); setPoints([]);}}><Route size={15}/>Добавить участок</button>
          {draft.paths.map((path, index) => <div className="route-photo-section" key={index}><span>Участок {index + 1} · {path.length} точек</span><button aria-label={'Удалить участок ' + (index + 1)} onClick={() => setDraft({...draft, paths: draft.paths.filter((_, i) => i !== index)})}><Trash2 size={15}/></button></div>)}</fieldset>
        {mode && <div className="route-photo-drawing"><strong>{mode === 'route' ? 'Отмечайте путь точками на карте' : 'Обведите дом точками на карте'}</strong><p>Точек: {points.length}</p><button disabled={points.length < (mode === 'route' ? 2 : 3)} onClick={finish}><Check size={15}/>Завершить</button><button disabled={!points.length} onClick={() => setPoints(p => p.slice(0, -1))}><Undo2 size={15}/>Шаг назад</button><button onClick={() => {setMode(''); setPoints([]);}}><X size={15}/>Отменить рисование</button></div>}
        <fieldset disabled={busy}><legend>3. Правила расчёта</legend><label>Допуск координат фото, м<input type="number" min={1} max={50} value={draft.snap_m} onChange={e => setDraft({...draft, snap_m: Number(e.target.value)})}/></label><label>Перерыв между фото, не более минут<input type="number" min={1} max={120} value={draft.max_gap_minutes} onChange={e => setDraft({...draft, max_gap_minutes: Number(e.target.value)})}/></label>
        <label className="route-photo-check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>Контуры домов и путь проверены на карте</label><label className="route-photo-check"><input type="checkbox" checked={draft.enabled} onChange={e => setDraft({...draft, enabled: e.target.checked})}/>Включить расчёт для выбранных чатов</label></fieldset>
        <div className="route-photo-actions"><button className="primary" disabled={busy || !!mode || (draft.enabled && (!checked || !draft.paths.length || !draft.chat_ids.length))} onClick={save}><Save size={16}/>{busy ? 'Сохранение…' : 'Сохранить'}</button><button disabled={busy} onClick={cancel}>Отмена</button></div>
      </section>}
      <section className="panel route-photo-map"><div className="route-photo-toolbar"><span><i className="route-photo-key remaining"/>Осталось</span><span><i className="route-photo-key covered"/>Пройдено по фото</span><span><i className="route-photo-key building"/>Здания</span><button onClick={fit} disabled={!ready || !territory}><LocateFixed size={16}/>Территория</button></div><ErrorBox error={mapError}/><div ref={container} className="route-photo-canvas" aria-label="Карта маршрута по фотографиям" hidden={!!mapError}/>{!ready && !mapError && <p>Подключаем карту…</p>}
        <p className="hint">Путь между фотографиями восстановлен по отмеченному маршруту и может отличаться от фактического. Снимки разных авторов, чатов и дней не соединяются. Здания и участки вне территории не входят в длину маршрута.</p>
        {displayed?.buildings_source.includes('OpenStreetMap') && <p className="hint">Контуры зданий: <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>. Полнота проверяется при настройке маршрута.</p>}
      </section>
    </div>
    {!draft && coverage && <section className="panel"><h2>Фотографии маршрута</h2><p className="hint">Учитываются принятые фотографии с координатами, известными автором, датой и временем съёмки. Одиночный снимок не подтверждает проход всего участка. Без времени съёмки: {coverage.unknown_time}.</p>
      {!!Object.keys(coverage.diagnostics).length && <p className="hint">Вне территории: {coverage.diagnostics.outside || 0} · Вдали от маршрута: {coverage.diagnostics.off_route || 0} · Без координат: {coverage.diagnostics.no_coordinates || 0} · В здании: {coverage.diagnostics.inside_building || 0} · Без времени или автора: {coverage.diagnostics.unknown_time_or_sender || 0}. Групп с неизвестным порядком съёмки: {coverage.diagnostics.uncertain_order || 0} — они не соединяются.</p>}
      <div className="route-photo-links">{coverage.photos.map(p => <Link key={p.id} to={`/photos/${p.id}`}><Camera size={15}/><span>№{p.id}<small>{p.taken_at} · {p.chat_name}</small></span></Link>)}</div>{!coverage.photos.length && <p>За выбранный период внутри территории нет подходящих фотографий.</p>}
    </section>}
  </>;
}
