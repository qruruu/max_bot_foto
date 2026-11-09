import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Camera, RefreshCw } from 'lucide-react';
import { useApp, useFilters } from './App';
import FilterBar from './FilterBar';
import { photoLink, query } from './api';
import { workspaceStorageKey, workspaceUrl } from './workspace';
import PhotoMapPanel from './PhotoMapPanel';

export default function PhotoMap() {
  const navigate = useNavigate();
  const {meta, user} = useApp();
  const owner = !!user.is_platform_owner;
  const previewPreference = workspaceStorageKey('photo-map-preview-markers');
  const [previewMarkers, setPreviewMarkers] = useState(() => owner && sessionStorage.getItem(previewPreference) === '1');
  useEffect(() => {
    if (!owner) return;
    function toggle(event: KeyboardEvent) {
      if (event.code !== 'KeyZ' || !event.ctrlKey || event.altKey || event.shiftKey || event.metaKey || event.repeat ||
          (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'))) return;
      event.preventDefault();
      const enabled = sessionStorage.getItem(previewPreference) !== '1';
      sessionStorage.setItem(previewPreference, enabled ? '1' : '0');
      setPreviewMarkers(enabled);
    }
    window.addEventListener('keydown', toggle, true);
    return () => window.removeEventListener('keydown', toggle, true);
  }, [owner, previewPreference]);
  const {filters, change} = useFilters(false, false, true, true);
  const filterQuery = query(filters);
  const [revision, setRevision] = useState(0);
  const mapStart = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    mapStart.current?.scrollIntoView({block: 'start', behavior: 'instant'});
  }, []);
  const listQuery = query({...filters, ...(!filters.date_from && !filters.date_to ? {all_dates: '1'} : {})});
  const photoPath = useCallback((id: number) => {
    const selection = Object.fromEntries(new URLSearchParams(filterQuery));
    return photoLink(id, {...selection, from_map: '1'}, false, selection.status === 'SPAM');
  }, [filterQuery]);
  const photoHref = useCallback((id: number) => workspaceUrl(photoPath(id)), [photoPath]);

  return <>
    <header className="page-header"><div><span className="eyebrow">ГЕОГРАФИЯ СНИМКОВ</span><h1>Карта фотографий</h1><p>Выберите период и чат, чтобы увидеть, где сделаны фотографии.</p></div>
      <button onClick={() => setRevision(value => value + 1)} aria-label="Обновить карту"><RefreshCw size={18}/></button>
    </header>
    <FilterBar filters={filters} change={change} refreshKey={revision} mapView/>
    <div ref={mapStart} className="photo-map-entry">
      <PhotoMapPanel endpoint="/photos/map" filterQuery={filterQuery} apiKey={meta.yandex_maps_api_key}
        revision={revision} timezone={meta.timezone} photoHref={photoHref}
        openPhoto={id => navigate(photoPath(id))} previewMarkers={owner && previewMarkers}
        listAction={<Link className="button" to={(filters.status === 'SPAM' ? '/spam?' : '/photos?') + listQuery}><Camera size={16}/>Списком</Link>}>
        <p className="hint">Если дата снимка не определена, фильтр по дате фотографии использует дату получения. Часовой пояс: {meta.timezone}.</p>
      </PhotoMapPanel>
    </div>
  </>;
}
