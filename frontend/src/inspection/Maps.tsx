import { Link } from 'react-router-dom';
import { Camera } from 'lucide-react';
import usePhotoBatchActions from '../PhotoBatchActions';
import PhotoMapPanel from '../PhotoMapPanel';
import type { InspectionMeta } from './types';

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
  const batch = usePhotoBatchActions(base + '?' + filters, base.split('/').at(-1));
  return <PhotoMapPanel batch={batch} endpoint={base + '/photos/map'} filterQuery={filters} apiKey={meta.yandex_maps_api_key}
    revision={revision} active={active} timezone={meta.timezone} photoHref={id => mapLink + '&photo=' + id} openPhoto={openPhoto}
    listAction={<Link className="button" to={listLink}><Camera size={16}/>Списком</Link>}>
    <p className="hint">На карте доступны фотографии закрытых дней.</p>
  </PhotoMapPanel>;
}
