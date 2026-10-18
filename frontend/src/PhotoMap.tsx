import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera, LocateFixed, RefreshCw } from 'lucide-react';
import { ErrorBox, useApp, useFilters } from './App';
import FilterBar from './FilterBar';
import { query } from './api';
import { loadMapPhotos, mapPhotoFeature, type MapPhoto, type MapSummary } from './photoMapData';
import { createPhotoMarkerLayout } from './photoMapMarker';
import { loadYandexMaps, type YMap, type YObjectManager } from './yandexMaps';
import { useTheme } from './theme';
import './photo-map.css';

export default function PhotoMap() {
  const {meta} = useApp();
  const {theme} = useTheme();
  const {filters, change} = useFilters(false, false, true);
  const key = query(filters);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<YMap | null>(null);
  const manager = useRef<YObjectManager | null>(null);
  const [data, setData] = useState<{photos: MapPhoto[]; summary: MapSummary} | null>(null);
  const [error, setError] = useState(''), [mapError, setMapError] = useState('');
  const [ready, setReady] = useState(false), [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(0), [revision, setRevision] = useState(0);
  const listQuery = query({...filters, ...(!filters.date_from && !filters.date_to ? {all_dates: '1'} : {})});

  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(''); setLoading(true); setLoaded(0);
    loadMapPhotos(Object.fromEntries(new URLSearchParams(key)), controller.signal, setLoaded)
      .then(setData)
      .catch(e => {if (!controller.signal.aborted) setError(e.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [key, revision]);

  useEffect(() => {
    let cancelled = false;
    setReady(false); setMapError('');
    loadYandexMaps(meta.yandex_maps_api_key).then(sdk => {
      if (cancelled || !container.current) return;
      map.current = new sdk.Map(container.current, {
        center: [72.603, 61.099], zoom: 12, controls: ['zoomControl', 'typeSelector', 'fullscreenControl'],
      }, {suppressMapOpenBlock: true});
      const iconLayout = createPhotoMarkerLayout(sdk);
      manager.current = new sdk.ObjectManager({
        clusterize: true, gridSize: 80,
        geoObjectIconLayout: iconLayout,
        geoObjectIconShape: {type: 'Rectangle', coordinates: [[-28, -64], [28, 0]]},
        geoObjectBalloonPanelMaxMapArea: 0,
        clusterIconLayout: iconLayout,
        clusterIconShape: {type: 'Rectangle', coordinates: [[-28, -73], [37, 0]]},
        clusterBalloonContentLayout: 'cluster#balloonCarousel', clusterBalloonPanelMaxMapArea: 0,
      });
      map.current.geoObjects.add(manager.current);
      setReady(true);
    }).catch(e => {if (!cancelled) setMapError(e.message);});
    return () => {cancelled = true; map.current?.destroy(); map.current = null; manager.current = null;};
  }, [meta.yandex_maps_api_key, theme, revision]);

  function fit() {
    const bounds = manager.current?.getBounds();
    if (bounds) map.current?.setBounds(bounds, {checkZoomRange: true, zoomMargin: 45, maxZoom: 17});
  }
  useEffect(() => {
    if (!ready || !manager.current) return;
    manager.current.removeAll();
    if (!data) return;
    manager.current.add({type: 'FeatureCollection', features: data.photos.map(photo =>
      mapPhotoFeature(photo, Object.fromEntries(new URLSearchParams(key)), meta.timezone))});
    fit();
  }, [ready, data, key, meta.timezone]);

  return <>
    <header className="page-header"><div><span className="eyebrow">ГЕОГРАФИЯ СНИМКОВ</span><h1>Карта фотографий</h1><p>Выберите период и чат, чтобы увидеть, где сделаны фотографии.</p></div>
      <button onClick={() => setRevision(value => value + 1)} aria-label="Обновить карту"><RefreshCw size={18}/></button>
    </header>
    <FilterBar filters={filters} change={change} refreshKey={revision}/>
    <section className="panel photo-map-panel">
      <div className="photo-map-toolbar">
        <div aria-live="polite">{loading ? `Загружаем точки… ${loaded || ''}` : data && <>
          <strong>На карте: {data.photos.length.toLocaleString('ru-RU')}</strong>
          <span>Всего: {data.summary.total.toLocaleString('ru-RU')} · Без координат: {data.summary.without_coordinates.toLocaleString('ru-RU')}</span>
        </>}</div>
        <div className="photo-map-actions"><button onClick={fit} disabled={!ready || !data?.photos.length}><LocateFixed size={16}/>Все точки</button>
          <Link className="button" to={(filters.status === 'SPAM' ? '/spam?' : '/photos?') + listQuery}><Camera size={16}/>Списком</Link></div>
      </div>
      <ErrorBox error={error || mapError}/>
      {!loading && data && data.photos.length === 0 && <p className="photo-map-empty" role="status">{data.summary.total ? 'В этой выборке нет фотографий с координатами. Их можно открыть списком.' : 'За выбранный период и с этими фильтрами фотографий нет.'}</p>}
      <div className="photo-map-canvas" ref={container} aria-label="Карта мест съёмки фотографий" hidden={!!mapError}/>
      {!mapError && !ready && <p className="hint">Подключаем Яндекс.Карты…</p>}
      <p className="hint">На карте показаны миниатюры снимков. Нажмите на миниатюру, чтобы открыть фотографию. Число в углу — количество фотографий рядом; увеличьте карту или откройте группу. Снимки без координат на карту не наносятся.</p>
      <p className="hint">Если дата снимка не определена, фильтр по дате фотографии использует дату получения. Часовой пояс: {meta.timezone}.</p>
    </section>
  </>;
}
