import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { LocateFixed } from 'lucide-react';
import { loadPhotoMap, type MapSummary } from './photoMapData';
import { createPhotoMarkerLayout } from './photoMapMarker';
import { loadYandexMaps, type MapFeature, type YMap, type YObjectManager } from './yandexMaps';
import { useTheme } from './theme';
import './photo-map.css';

type Props<Photo> = {
  endpoint: string;
  filterQuery: string;
  apiKey: string;
  revision: number;
  feature: (photo: Photo) => MapFeature;
  listAction: ReactNode;
  children?: ReactNode;
  active?: boolean;
  onClick?: (event: MouseEvent<HTMLDivElement>) => void;
};

export default function PhotoMapPanel<Photo>({
  endpoint, filterQuery, apiKey, revision, feature, listAction, children, active = true, onClick,
}: Props<Photo>) {
  const {theme} = useTheme();
  const container = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<{map: YMap; manager: YObjectManager} | null>(null);
  const [data, setData] = useState<{photos: Photo[]; summary: MapSummary} | null>(null);
  const [error, setError] = useState(''), [mapError, setMapError] = useState('');
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(''); setLoading(true); setLoaded(0);
    loadPhotoMap<Photo>(endpoint, filterQuery, controller.signal, setLoaded)
      .then(setData)
      .catch(e => {if (!controller.signal.aborted) setError(e.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [endpoint, filterQuery, revision]);

  useEffect(() => {
    let cancelled = false;
    let map: YMap | undefined;
    setView(null); setMapError('');
    loadYandexMaps(apiKey).then(sdk => {
      if (cancelled || !container.current) return;
      map = new sdk.Map(container.current, {
        center: [72.603, 61.099], zoom: 12, controls: ['zoomControl', 'typeSelector', 'fullscreenControl'],
      }, {suppressMapOpenBlock: true});
      const iconLayout = createPhotoMarkerLayout(sdk);
      const manager = new sdk.ObjectManager({
        clusterize: true, gridSize: 80,
        geoObjectIconLayout: iconLayout,
        geoObjectIconShape: {type: 'Rectangle', coordinates: [[-28, -64], [28, 0]]},
        geoObjectBalloonPanelMaxMapArea: 0,
        clusterIconLayout: iconLayout,
        clusterIconShape: {type: 'Rectangle', coordinates: [[-28, -73], [37, 0]]},
        clusterBalloonContentLayout: 'cluster#balloonCarousel', clusterBalloonPanelMaxMapArea: 0,
      });
      map.geoObjects.add(manager);
      setView({map, manager});
    }).catch(e => {if (!cancelled) setMapError(e.message);});
    return () => {cancelled = true; map?.destroy();};
  }, [apiKey, theme, revision]);

  useLayoutEffect(() => {
    if (active) view?.map.container?.fitToViewport();
  }, [active, view]);

  useLayoutEffect(() => {
    if (!view) return;
    view.manager.removeAll();
    if (!data) return;
    view.manager.add({type: 'FeatureCollection', features: data.photos.map(feature)});
    fitPhotoBounds(view);
  }, [view, data, feature]);

  return <section className="panel photo-map-panel">
    <div className="photo-map-toolbar">
      <div aria-live="polite">{loading ? `Загружаем точки… ${loaded || ''}` : data && <>
        <strong>На карте: {data.photos.length.toLocaleString('ru-RU')}</strong>
        <span>Всего: {data.summary.total.toLocaleString('ru-RU')} · Без координат: {data.summary.without_coordinates.toLocaleString('ru-RU')}</span>
      </>}</div>
      <div className="photo-map-actions"><button onClick={() => view && fitPhotoBounds(view)} disabled={!view || !data?.photos.length}><LocateFixed size={16}/>Все точки</button>
        {listAction}</div>
    </div>
    {(error || mapError) && <p className="error" role="alert">{error || mapError}</p>}
    {!loading && data && data.photos.length === 0 && <p className="photo-map-empty" role="status">{data.summary.total ? 'В этой выборке нет фотографий с координатами. Их можно открыть списком.' : 'За выбранный период и с этими фильтрами фотографий нет.'}</p>}
    <div className="photo-map-canvas" ref={container} aria-label="Карта мест съёмки фотографий" hidden={!!mapError} onClickCapture={onClick}/>
    {!mapError && !view && <p className="hint">Подключаем Яндекс.Карты…</p>}
    <p className="hint">На карте показаны миниатюры снимков. Нажмите на миниатюру, чтобы открыть фотографию. Число в углу — количество фотографий рядом; увеличьте карту или откройте группу. Снимки без координат на карту не наносятся.</p>
    {children}
  </section>;
}

function fitPhotoBounds({map, manager}: {map: YMap; manager: YObjectManager}) {
  const bounds = manager.getBounds();
  if (bounds) map.setBounds(bounds, {checkZoomRange: true, zoomMargin: 45, maxZoom: 17});
}
