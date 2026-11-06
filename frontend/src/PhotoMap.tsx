import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera, RefreshCw } from 'lucide-react';
import { useApp, useFilters } from './App';
import FilterBar from './FilterBar';
import { query } from './api';
import { mapPhotoFeature, type MapPhoto } from './photoMapData';
import PhotoMapPanel from './PhotoMapPanel';

export default function PhotoMap() {
  const {meta} = useApp();
  const {filters, change} = useFilters(false, false, true, true);
  const filterQuery = query(filters);
  const [revision, setRevision] = useState(0);
  const listQuery = query({...filters, ...(!filters.date_from && !filters.date_to ? {all_dates: '1'} : {})});
  const feature = useCallback((photo: MapPhoto) =>
    mapPhotoFeature(photo, Object.fromEntries(new URLSearchParams(filterQuery)), meta.timezone),
  [filterQuery, meta.timezone]);

  return <>
    <header className="page-header"><div><span className="eyebrow">ГЕОГРАФИЯ СНИМКОВ</span><h1>Карта фотографий</h1><p>Выберите период и чат, чтобы увидеть, где сделаны фотографии.</p></div>
      <button onClick={() => setRevision(value => value + 1)} aria-label="Обновить карту"><RefreshCw size={18}/></button>
    </header>
    <FilterBar filters={filters} change={change} refreshKey={revision}/>
    <PhotoMapPanel endpoint="/photos/map" filterQuery={filterQuery} apiKey={meta.yandex_maps_api_key}
      revision={revision} feature={feature}
      listAction={<Link className="button" to={(filters.status === 'SPAM' ? '/spam?' : '/photos?') + listQuery}><Camera size={16}/>Списком</Link>}>
      <p className="hint">Если дата снимка не определена, фильтр по дате фотографии использует дату получения. Часовой пояс: {meta.timezone}.</p>
    </PhotoMapPanel>
  </>;
}
