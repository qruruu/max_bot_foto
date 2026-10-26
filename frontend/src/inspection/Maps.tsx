import { useEffect, useRef, useState } from 'react';
import { Camera, LocateFixed } from 'lucide-react';
import { api, dateLabel } from '../api';
import { createPhotoMarkerLayout } from '../photoMapMarker';
import { escapeMapLabel, loadYandexMaps } from '../yandexMaps';
import type { MapFeature, YMap, YObjectManager } from '../yandexMaps';
import { useTheme } from '../theme';
import type { InspectionMeta, InspectionPhoto } from './types';
import '../photo-map.css';

type Summary = {total: number; located: number; without_coordinates: number};
type Batch = {items: InspectionPhoto[]; summary: Summary | null; snapshot_id: number; next_after_id: number | null};

export async function loadInspectionMap(base: string, filters: string, signal: AbortSignal, progress: (n: number) => void) {
  const items: InspectionPhoto[] = [];
  let after = 0, snapshot: number | undefined, summary: Summary | null = null;
  do {
    const params = new URLSearchParams(filters); params.set('after_id', String(after));
    if (snapshot !== undefined) params.set('snapshot_id', String(snapshot));
    const batch = await api<Batch>(base + '/photos/map?' + params, 'GET', undefined, signal);
    signal.throwIfAborted(); summary ??= batch.summary; snapshot = batch.snapshot_id;
    items.push(...batch.items); progress(items.length);
    if (batch.next_after_id === null) break;
    if (batch.next_after_id <= after) throw new Error('Не удалось загрузить следующую часть карты. Обновите карту.');
    after = batch.next_after_id;
  } while (!signal.aborted);
  if (!summary) throw new Error('Не удалось загрузить сводку карты.');
  return {items, summary};
}

export function inspectionMapFeature(photo: InspectionPhoto, href: string): MapFeature {
  const escape = escapeMapLabel;
  return {type:'Feature', id:photo.id, geometry:{type:'Point', coordinates:[photo.longitude!,photo.latitude!]}, properties:{
    photoLabel:`Фото №${photo.id}`, photoPreviewUrl:photo.preview_url,
    hintContent:escape(`Фото №${photo.id} · ${photo.district_name || 'Микрорайон не определён'}`),
    clusterCaption:escape(`Фото №${photo.id} · ${dateLabel(photo.photo_date)}`),
    balloonContentHeader:escape(`Фото №${photo.id}`),
    balloonContentBody:`<div class="map-photo-balloon"><img class="map-photo-preview" src="${escape(photo.preview_url)}" alt="Фото №${photo.id}"/><strong>${escape(photo.work_type_name || 'Не определён')}</strong><div>${escape(photo.district_name || 'Микрорайон не определён')}</div><div>${escape(dateLabel(photo.photo_date))} ${escape(photo.photo_time || '')}</div><a class="inspection-map-open" data-photo-id="${photo.id}" href="${escape(href)}">Открыть фотографию →</a></div>`,
  }};
}

export default function InspectionPhotoMap({base, filters, meta, revision, openPhoto, photoLink, showList}: {
  base: string; filters: string; meta: InspectionMeta; revision: number; openPhoto: (id: number) => void;
  photoLink: (id: number) => string; showList: () => void;
}) {
  const {theme} = useTheme();
  const container = useRef<HTMLDivElement>(null), map = useRef<YMap | null>(null), manager = useRef<YObjectManager | null>(null);
  const [data,setData] = useState<{items:InspectionPhoto[]; summary:Summary}|null>(null);
  const [ready,setReady] = useState(false),[error,setError] = useState(''),[mapError,setMapError] = useState(''),[loaded,setLoaded] = useState(0);
  const opener=useRef(openPhoto);opener.current=openPhoto;
  useEffect(() => {
    const controller=new AbortController();setData(null);setError('');setLoaded(0);
    loadInspectionMap(base,filters,controller.signal,setLoaded).then(setData).catch(e=>{if(!controller.signal.aborted)setError(e.message);});
    return()=>controller.abort();
  },[base,filters,revision]);
  useEffect(() => {
    let cancelled=false;setReady(false);setMapError('');
    loadYandexMaps(meta.yandex_maps_api_key).then(sdk=>{
      if(cancelled||!container.current)return;
      map.current=new sdk.Map(container.current,{center:[72.603,61.099],zoom:12,controls:['zoomControl','typeSelector','fullscreenControl']},{suppressMapOpenBlock:true});
      const layout=createPhotoMarkerLayout(sdk);
      manager.current=new sdk.ObjectManager({clusterize:true,gridSize:80,geoObjectIconLayout:layout,
        geoObjectIconShape:{type:'Rectangle',coordinates:[[-28,-64],[28,0]]},geoObjectBalloonPanelMaxMapArea:0,
        clusterIconLayout:layout,clusterIconShape:{type:'Rectangle',coordinates:[[-28,-73],[37,0]]},
        clusterBalloonContentLayout:'cluster#balloonCarousel',clusterBalloonPanelMaxMapArea:0});
      map.current.geoObjects.add(manager.current);setReady(true);
    }).catch(e=>{if(!cancelled)setMapError(e.message);});
    return()=>{cancelled=true;map.current?.destroy();map.current=null;manager.current=null;};
  },[meta.yandex_maps_api_key,theme,revision]);
  function fit(){const bounds=manager.current?.getBounds();if(bounds)map.current?.setBounds(bounds,{checkZoomRange:true,zoomMargin:45,maxZoom:17});}
  useEffect(()=>{
    if(!ready||!manager.current)return;manager.current.removeAll();if(!data)return;
    manager.current.add({type:'FeatureCollection',features:data.items.map(p=>inspectionMapFeature(p,photoLink(p.id)))});fit();
  },[ready,data,filters]);
  useEffect(()=>{
    const click=(event:MouseEvent)=>{const link=(event.target as Element)?.closest<HTMLAnchorElement>('.inspection-map-open');
      if(!link)return;const id=Number(link.dataset.photoId);if(Number.isSafeInteger(id)&&id>0){event.preventDefault();opener.current(id);}};
    const node=container.current;node?.addEventListener('click',click);return()=>node?.removeEventListener('click',click);
  },[]);
  return <section className="panel photo-map-panel"><div className="photo-map-toolbar"><div aria-live="polite">
    {!data&&!error?`Загружаем точки… ${loaded||''}`:data&&<><strong>На карте: {data.items.length}</strong><span>Всего: {data.summary.total} · Без координат: {data.summary.without_coordinates}</span></>}</div>
    <div className="photo-map-actions"><button onClick={fit} disabled={!ready||!data?.items.length}><LocateFixed size={16}/>Все точки</button><button onClick={showList}><Camera size={16}/>Списком</button></div></div>
    {(error||mapError)&&<p className="error" role="alert">{error||mapError}</p>}
    <div ref={container} className="photo-map-canvas" aria-label="Карта мест съёмки фотографий" hidden={!!mapError}/>
    {!mapError&&!ready&&<p className="hint">Подключаем Яндекс.Карты…</p>}
    {data&&!data.items.length&&<p className="photo-map-empty">В этой выборке нет фотографий с координатами.</p>}
    <p className="hint">Нажмите на миниатюру, чтобы посмотреть фотографию. Число в углу показывает количество соседних снимков. На карте доступны только фотографии закрытых дней.</p>
  </section>;
}
