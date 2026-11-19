import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { Camera, Check, LocateFixed } from 'lucide-react';
import { dateLabel } from './api';
import { loadPhotoMap, mapPreviewUrl, previewMarkerProperties, viewportBounds, type MapPage, type MapPhoto } from './photoMapData';
import { createPhotoMarkerLayout } from './photoMapMarker';
import { loadYandexMaps, type MapFeature, type YMap, type YMapEvent, type YObjectManager } from './yandexMaps';
import type { PhotoBatchActions } from './PhotoBatchActions';
import './photo-map.css';

const city = [72.603, 61.099];
const cityZoom = 12;
const maxZoom = 19;
const pinPreset = 'islands#circleDotIcon';
const pinColor = '#1e98ff';
const selectedPinColor = '#000';

type Props = {
  endpoint: string;
  filterQuery: string;
  apiKey: string;
  revision: number;
  timezone: string;
  photoHref: (id: number) => string;
  openPhoto?: (id: number) => void;
  listAction: ReactNode;
  children?: ReactNode;
  active?: boolean;
  previewMarkers?: boolean;
  batch?: PhotoBatchActions;
};

function feature(photo: MapPhoto): MapFeature {
  return {type: 'Feature', id: photo.id, geometry: {type: 'Point', coordinates: [photo.longitude, photo.latitude]}, properties: {}};
}

export default function PhotoMapPanel({
  endpoint, filterQuery, apiKey, revision, timezone, photoHref, openPhoto, listAction, children, active = true, previewMarkers = false, batch,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const cards = useRef<HTMLDivElement>(null);
  const camera = useRef({center: city, zoom: cityZoom});
  const usePreviewPins = previewMarkers && !batch?.selecting;
  const previewPhotoHref = usePreviewPins ? photoHref : null;
  const [view, setView] = useState<{map: YMap; points: YObjectManager; showHighlight: (photo: MapPhoto) => (() => void) | undefined} | null>(null);
  const [bounds, setBounds] = useState('');
  const [cursor, setCursor] = useState({scope: '', offsets: [0]});
  const scope = [endpoint, filterQuery, bounds, revision].join('|');
  const offsets = cursor.scope === scope ? cursor.offsets : [0];
  const after = offsets.at(-1) ?? 0;
  const request = scope + '|' + after;
  const [data, setData] = useState<{request: string; page: MapPage}>();
  const [error, setError] = useState<{request: string; message: string}>();
  const [mapError, setMapError] = useState('');
  const [retry, setRetry] = useState(0);
  const selectionScope = [endpoint, filterQuery, revision, after].join('|');
  const [selected, setSelected] = useState<{scope: string; id: number; fromMap: boolean}>();
  const page = data?.request === request ? data.page : undefined;
  const photos = page?.items;
  const selection = selected?.scope === selectionScope ? photos?.find(photo => photo.id === selected.id) : undefined;
  const selectionHandler = useRef<(id: number) => void>(() => {});
  selectionHandler.current = id => {
    if (batch?.selecting) {
      const photo = photos?.find(item => item.id === id);
      if (photo) batch.toggle(photo);
    } else setSelected({scope: selectionScope, id, fromMap: true});
  };
  const markerMenuHandler = useRef<(id: number, event: YMapEvent) => void>(() => {});
  markerMenuHandler.current = (id, event) => {
    const photo = photos?.find(item => item.id === id);
    const canvas = container.current;
    if (!batch || !photo || !canvas) return;
    const domEvent = event.get('domEvent') as {get(name: string): unknown; callMethod?(name: string): void} | undefined;
    const position = domEvent?.get('position');
    const bounds = canvas.getBoundingClientRect();
    const [x, y] = Array.isArray(position) ? [position[0] - window.scrollX, position[1] - window.scrollY]
      : [bounds.left + 12, bounds.top + 12];
    domEvent?.callMethod?.('preventDefault');
    batch.setMenu({photo, x, y, row: canvas});
  };
  const highlighted = batch?.selecting ? photos?.filter(photo => batch.ids.has(photo.id)) : undefined;
  const highlightedKey = highlighted?.map(photo => photo.id).join(',');

  useLayoutEffect(() => {
    if (!selection || !selected?.fromMap) return;
    cards.current?.querySelector<HTMLElement>('[data-map-photo="' + selection.id + '"]')
      ?.scrollIntoView?.({block: 'nearest', inline: 'nearest'});
  }, [selection, selected]);

  useEffect(() => {
    if (!active || !view || !bounds || data?.request === request) return;
    const controller = new AbortController();
    setError(undefined);
    loadPhotoMap(endpoint, filterQuery, bounds, after, controller.signal)
      .then(page => setData({request, page}))
      .catch(error => {if (!controller.signal.aborted) setError({request, message: error.message});});
    return () => controller.abort();
  }, [active, view, bounds, endpoint, filterQuery, after, request, retry, data?.request]);

  useEffect(() => {
    let cancelled = false;
    let map: YMap | undefined;
    let timer: number | undefined;
    setView(null); setBounds(''); setMapError('');
    if (!apiKey) return;
    loadYandexMaps(apiKey).then(sdk => {
      if (cancelled || !container.current) return;
      const instance = new sdk.Map(container.current, {
        ...camera.current, behaviors: ['default', 'scrollZoom'], controls: ['zoomControl', 'typeSelector', 'fullscreenControl'],
      }, {suppressMapOpenBlock: true, maxZoom});
      map = instance;
      const iconLayout = usePreviewPins ? createPhotoMarkerLayout(sdk) : null;
      const points = new sdk.ObjectManager(iconLayout ? {
        clusterize: true, gridSize: 80, geoObjectIconLayout: iconLayout, clusterIconLayout: iconLayout,
        geoObjectIconShape: {type: 'Rectangle', coordinates: [[-28, -64], [28, 0]]},
        clusterIconShape: {type: 'Rectangle', coordinates: [[-28, -73], [37, 0]]},
        geoObjectBalloonPanelMaxMapArea: 0, clusterBalloonPanelMaxMapArea: 0, geoObjectHideIconOnBalloonOpen: false,
        clusterBalloonContentLayout: 'cluster#balloonCarousel',
      } : {
        clusterize: true, gridSize: 56, geoObjectOpenBalloonOnClick: false, clusterOpenBalloonOnClick: false,
        clusterDisableClickZoom: true, geoObjectPreset: pinPreset, geoObjectIconColor: pinColor,
      });
      const selectedPreviewLayout = usePreviewPins
        ? sdk.templateLayoutFactory.createClass('<div class="photo-map-selected-preview"></div>')
        : null;
      const showHighlight = (photo: MapPhoto) => {
        if (!usePreviewPins && !points.getObjectState?.(photo.id).isClustered && points.objects.setObjectOptions) {
          points.objects.setObjectOptions(photo.id, {iconColor: selectedPinColor});
          return () => {if (!cancelled) points.objects.setObjectOptions?.(photo.id, {iconColor: pinColor});};
        }
        if (!sdk.Placemark) return;
        // A clustered photo has no visible individual pin to recolor.
        const marker = new sdk.Placemark([photo.longitude, photo.latitude], {}, {
          ...(selectedPreviewLayout ? {iconLayout: selectedPreviewLayout} : {preset: pinPreset, iconColor: selectedPinColor}),
          zIndex: 10000,
          interactiveZIndex: false,
          interactivityModel: 'default#silent',
        });
        instance.geoObjects.add(marker);
        return () => {if (!cancelled) instance.geoObjects.remove(marker);};
      };
      instance.geoObjects.add(points);
      const select = (id: unknown) => {
        const photoId = Number(id);
        if (Number.isSafeInteger(photoId) && photoId > 0) selectionHandler.current(photoId);
      };
      points.objects?.events?.add('click', event => select(event.get('objectId')));
      points.objects?.events?.add('contextmenu', event => markerMenuHandler.current(Number(event.get('objectId')), event));
      if (!usePreviewPins) {
        points.clusters?.events?.add('click', event => {
          const members = points.clusters.getById?.(Number(event.get('objectId')))?.properties.geoObjects;
          if (!members?.length) return;
          const lng = members.map(item => item.geometry.coordinates[0]);
          const lat = members.map(item => item.geometry.coordinates[1]);
          const groupBounds = [[Math.min(...lng), Math.min(...lat)], [Math.max(...lng), Math.max(...lat)]];
          if ((instance.getZoom?.() ?? 0) >= maxZoom ||
              (groupBounds[0][0] === groupBounds[1][0] && groupBounds[0][1] === groupBounds[1][1])) {
            select(members[0].id);
          } else {
            instance.setBounds(groupBounds, {checkZoomRange: true, zoomMargin: 40});
          }
        });
      }
      const readBounds = () => {
        const next = viewportBounds(instance.getBounds?.());
        if (next) setBounds(next);
      };
      instance.events?.add('boundschange', () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(readBounds, 300);
      });
      setView({map: instance, points, showHighlight});
      readBounds();
    }).catch(error => {if (!cancelled) setMapError(error.message);});
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (map) {
        camera.current = {center: map.getCenter?.() ?? city, zoom: map.getZoom?.() ?? cityZoom};
        map.destroy();
      }
    };
  }, [apiKey, usePreviewPins]);

  useLayoutEffect(() => {
    if (active) view?.map.container?.fitToViewport();
  }, [active, view]);

  useLayoutEffect(() => {
    if (!view) return;
    view.points.removeAll();
    if (photos?.length) view.points.add({type: 'FeatureCollection', features: photos.map(photo => {
      const point = feature(photo);
      if (previewPhotoHref) point.properties = previewMarkerProperties(photo,
        photo.preview_url ? mapPreviewUrl(endpoint, photo.id) : '', previewPhotoHref(photo.id), timezone);
      return point;
    })});
    cards.current?.scrollTo?.({top: 0});
  }, [view, photos, endpoint, previewPhotoHref, timezone]);

  useLayoutEffect(() => {
    if (!view) return;
    const chosen = highlighted ?? (selection ? [selection] : []);
    const cleanup = chosen.map(view.showHighlight);
    return () => cleanup.forEach(remove => remove?.());
  }, [view, selection, photos, highlightedKey]);

  function followPhoto(event: MouseEvent<HTMLAnchorElement>, id: number) {
    if (!openPhoto || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openPhoto(id);
  }

  const message = error?.request === request ? error.message : '';
  const unavailable = mapError || (!apiKey ? 'Для карты укажите YANDEX_MAPS_API_KEY в настройках сервера.' : '');
  const status = message ? <p role="alert">{message} <button type="button" onClick={() => setRetry(value => value + 1)}>Повторить</button></p>
    : !page ? <p className="hint" role="status">Загружаем фотографии…</p>
    : !photos?.length ? <p className="hint" role="status">В этой области нет фотографий за выбранный период.</p> : null;
  const paging = (offsets.length > 1 || page?.next_after_id != null) && <div className="photo-map-paging">
    {page?.next_after_id != null && <p className="hint">Здесь есть ещё снимки. Приблизьте карту или откройте следующую часть.</p>}
    <button type="button" disabled={offsets.length < 2} onClick={() => setCursor({scope, offsets: offsets.slice(0, -1)})}>Назад</button>
    <button type="button" disabled={page?.next_after_id == null} onClick={() => {
      if (page?.next_after_id != null) setCursor({scope, offsets: [...offsets, page.next_after_id]});
    }}>Далее</button>
  </div>;
  return <section className="panel photo-map-panel">
    <div className="photo-map-toolbar">
      <strong aria-live="polite">{page ? 'На карте: ' + page.items.length : 'Фотографии на карте'}</strong>
      <div className="photo-map-actions">
        <button type="button" onClick={() => view?.map.setCenter?.(city, cityZoom)} disabled={!view}><LocateFixed size={16}/>К городу</button>
        {listAction}
      </div>
    </div>
    {unavailable && <p className="error" role="alert">{unavailable}</p>}
    {batch?.dialogs}
    {previewMarkers && !batch?.selecting && !unavailable && status}
    <div className={'photo-map-layout' + (previewMarkers && !batch?.selecting ? ' is-preview-map' : '')} hidden={!!unavailable}>
      {(!previewMarkers || batch?.selecting) && <aside className="photo-map-sidebar" aria-label="Фото в видимой области">
        <h3>Фото в видимой области</h3>
        {status}
        <div className="photo-map-cards" ref={cards}>
          {photos?.map(photo => <article key={photo.id} data-map-photo={photo.id} className={(batch?.selecting ? batch.ids.has(photo.id) : selection?.id === photo.id) ? 'is-selected' : undefined}
            onContextMenu={batch ? event => {
              event.preventDefault();
              batch.setMenu({photo, x: event.clientX, y: event.clientY, row: event.currentTarget.querySelector('button')!});
            } : undefined}>
            <button className="photo-map-card-button" type="button" aria-haspopup={batch ? 'menu' : undefined}
              onKeyDown={batch ? event => {
                if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return;
                event.preventDefault();
                const bounds = event.currentTarget.getBoundingClientRect();
                batch.setMenu({photo, x: bounds.left + 12, y: bounds.top + 12, row: event.currentTarget});
              } : undefined} aria-pressed={batch?.selecting ? batch.ids.has(photo.id) : selection?.id === photo.id}
              disabled={batch?.selecting && !batch.canToggle(photo)}
              onClick={() => batch?.selecting ? batch.toggle(photo) : setSelected({scope: selectionScope, id: photo.id, fromMap: false})}>
              <span className="photo-map-card-image">
                <Camera size={22} aria-hidden="true"/>
                {photo.preview_url && <img src={mapPreviewUrl(endpoint, photo.id)} alt="" loading="lazy" decoding="async" onError={event => {event.currentTarget.hidden = true;}}/>}
              </span>
              {(batch?.selecting ? batch.ids.has(photo.id) : selection?.id === photo.id) && <span className="photo-map-selected-label"><Check size={14} aria-hidden="true"/> Выбрано</span>}
              <strong>Фото №{photo.id}</strong>
              <small>{photo.photo_date ? dateLabel(photo.photo_date) : new Date(photo.received_at).toLocaleDateString('ru-RU', {timeZone: timezone})}</small>
              <span>{photo.work_type_name || photo.district_name || photo.chat_name || 'Вид работы не указан'}</span>
            </button>
            {!batch?.selecting && selection?.id === photo.id && <a href={photoHref(photo.id)} onClick={event => followPhoto(event, photo.id)}>Открыть фото</a>}
          </article>)}
        </div>
        {paging}
      </aside>}
      <div className="photo-map-canvas" ref={container} tabIndex={batch ? -1 : undefined} aria-label="Карта мест съёмки фотографий"/>
    </div>
    {previewMarkers && !batch?.selecting && !unavailable && paging}
    {children}
  </section>;
}
