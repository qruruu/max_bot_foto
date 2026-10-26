import { ChevronRight } from 'lucide-react';
import { dateLabel } from '../api';
import WorkTypeHint from '../WorkTypeHint';
import type { InspectionPhoto } from './types';

export default function InspectionPhotoTable({photos, openPhoto, workTypes = []}: {
  photos: InspectionPhoto[]; openPhoto: (id: number) => void; workTypes?: {code: string; description?: string}[];
}) {
  return <div className="table-scroll"><table className="photos-table inspection-photo-table" aria-label="Фотографии закрытых дней">
    <thead><tr><th scope="col">Фотография</th><th scope="col">Дата / время</th><th scope="col">Микрорайон</th>
      <th scope="col">Координаты</th><th scope="col">Вид работы</th><th scope="col" className="defect-column">Неисправность</th>
      <th scope="col">Статус</th><th scope="col"><span className="inspection-sr-only">Просмотр</span></th></tr></thead>
    <tbody>{photos.map(photo => <tr key={photo.id} id={'inspection-photo-row-' + photo.id}>
      <td><button id={'inspection-photo-' + photo.id} className="photo-thumb" onClick={() => openPhoto(photo.id)}>
        <img src={photo.preview_url} loading="lazy" alt={'Фото №' + photo.id}/><small>#{photo.id}</small>
      </button></td>
      <td>{dateLabel(photo.photo_date)}<small>{photo.photo_time || 'Время не указано'}</small>
        {photo.received_at && <small>Получено {new Date(photo.received_at).toLocaleString('ru-RU')}</small>}</td>
      <td>{photo.district_name || <span className="muted">Микрорайон не определён</span>}</td>
      <td className="mono">{photo.latitude?.toFixed(5) ?? '—'}<small>{photo.longitude?.toFixed(5) ?? '—'}</small></td>
      <td className="photo-work-cell"><span className="photo-work-name">{photo.work_type_name || <span className="muted">Не определён</span>}</span><WorkTypeHint name={photo.work_type_name||'Не определён'} description={workTypes.find(w=>w.code===photo.work_type)?.description}/></td>
      <td className="defect-column"><input className="inspection-defect-readonly" type="checkbox" checked={photo.is_defect} disabled
        aria-label={'Неисправность на фото №' + photo.id}/></td>
      <td><span className="badge status-ACCEPTED">Принято</span></td>
      <td><button className="text-button" onClick={() => openPhoto(photo.id)} aria-label={'Открыть фото №' + photo.id}>Открыть<ChevronRight size={14}/></button></td>
    </tr>)}</tbody>
  </table></div>;
}
