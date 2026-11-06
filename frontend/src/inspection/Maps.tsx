import { useCallback, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { Camera } from 'lucide-react';
import { dateLabel } from '../api';
import PhotoMapPanel from '../PhotoMapPanel';
import { escapeMapLabel, type MapFeature } from '../yandexMaps';
import type { InspectionMeta, InspectionPhoto } from './types';

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

export default function InspectionPhotoMap({base, filters, meta, revision, active, openPhoto, mapLink, listLink}: {
  base: string;
  filters: string;
  meta: InspectionMeta;
  revision: number;
  active: boolean;
  openPhoto: (id: number) => void;
  mapLink: string;
  listLink: string;
}) {
  const feature = useCallback((photo: InspectionPhoto) =>
    inspectionMapFeature(photo, mapLink + '&photo=' + photo.id), [mapLink]);

  function onClick(event: MouseEvent<HTMLDivElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = (event.target as Element).closest<HTMLAnchorElement>('.inspection-map-open');
    if (!link) return;
    const id = Number(link.dataset.photoId);
    if (Number.isSafeInteger(id) && id > 0) {
      event.preventDefault();
      openPhoto(id);
    }
  }

  return <PhotoMapPanel endpoint={base + '/photos/map'} filterQuery={filters} apiKey={meta.yandex_maps_api_key}
    revision={revision} active={active} feature={feature} onClick={onClick}
    listAction={<Link className="button" to={listLink}><Camera size={16}/>Списком</Link>}>
    <p className="hint">На карте доступны фотографии закрытых дней.</p>
  </PhotoMapPanel>;
}
