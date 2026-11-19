import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import usePhotoBatchActions, { type PhotoBatchActions } from '../PhotoBatchActions';
import { isPhotoRowClick } from '../photoRowClick';
import { dateLabel } from '../api';
import WorkTypeHint from '../WorkTypeHint';
import type { InspectionPhoto } from './types';

type Props = {
  photos: InspectionPhoto[]; openPhoto: (id: number) => void; focusId?: number | null; workTypes?: {code: string; description?: string}[];
};

export function SelectableInspectionPhotoTable({organization, filterQuery, pagination, ...props}: Props & {organization: string; filterQuery: string; pagination: ReactNode}) {
  const batch = usePhotoBatchActions(organization + '?' + filterQuery, organization, filterQuery);
  return <>{batch.toolbar(props.photos.length > 0)}{pagination}<InspectionPhotoTable {...props} batch={batch}/>{batch.dialogs}</>;
}

export default function InspectionPhotoTable({photos, openPhoto, focusId, workTypes = [], batch}: Props & {batch?: PhotoBatchActions}) {
  return <div className="table-scroll"><table className="photos-table inspection-photo-table" aria-label="Фотографии закрытых дней">
    <thead><tr>{batch?.selecting && <th scope="col">Выбор</th>}<th scope="col">Фотография</th><th scope="col">Дата / время</th><th scope="col">Микрорайон</th>
      <th scope="col">Координаты</th><th scope="col">Вид работы</th><th scope="col" className="defect-column">Неисправность</th>
      <th scope="col">Статус</th><th scope="col"><span className="inspection-sr-only">Просмотр</span></th></tr></thead>
    <tbody>{photos.map(photo => <tr key={photo.id} id={'photo-row-' + photo.id} className={photo.id === focusId ? 'photo-return-row' : undefined}
      data-photo-selected={batch?.ids.has(photo.id) || undefined} data-photo-selectable={batch?.selecting || undefined}
      tabIndex={batch ? 0 : undefined} aria-haspopup={batch ? 'menu' : undefined}
      onContextMenu={batch ? event => {
        event.preventDefault();
        batch.setMenu({photo, x: event.clientX, y: event.clientY, row: event.currentTarget});
      } : undefined}
      onKeyDown={batch ? event => {
        if (event.target !== event.currentTarget || !(event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10'))) return;
        event.preventDefault();
        const bounds = event.currentTarget.getBoundingClientRect();
        batch.setMenu({photo, x: bounds.left + 12, y: bounds.top + 12, row: event.currentTarget});
      } : undefined}
      onClick={batch?.selecting ? event => {if (isPhotoRowClick(event)) batch.toggle(photo);} : undefined}>
      {batch?.selecting && <td className="photo-cell-select"><input type="checkbox" aria-label={'Выбрать фото №' + photo.id}
        checked={batch.ids.has(photo.id)} disabled={!batch.canToggle(photo)} onChange={() => batch.toggle(photo)}/></td>}
      <td className="photo-cell-preview"><button id={'inspection-photo-' + photo.id} className="photo-thumb" disabled={batch?.selecting && !batch.canToggle(photo)} onClick={() => batch?.selecting ? batch.toggle(photo) : openPhoto(photo.id)}>
        <img src={photo.preview_url} loading="lazy" alt={'Фото №' + photo.id}/><small>#{photo.id}</small>
      </button></td>
      <td className="photo-cell-date">{dateLabel(photo.photo_date)}<small>{photo.photo_time || 'Время не указано'}</small>
        {photo.received_at && <small className="photo-received-at">Получено {new Date(photo.received_at).toLocaleString('ru-RU')}</small>}</td>
      <td className="photo-cell-location">{photo.district_name || <span className="muted">Микрорайон не определён</span>}</td>
      <td className="mono photo-cell-technical">{photo.latitude?.toFixed(5) ?? '—'}<small>{photo.longitude?.toFixed(5) ?? '—'}</small></td>
      <td className="photo-work-cell"><span className="photo-work-name">{photo.work_type_name || <span className="muted">Не определён</span>}</span><WorkTypeHint name={photo.work_type_name||'Не определён'} description={workTypes.find(w=>w.code===photo.work_type)?.description}/></td>
      <td className="defect-column"><input className="inspection-defect-readonly" type="checkbox" checked={photo.is_defect} disabled
        aria-label={'Неисправность на фото №' + photo.id}/></td>
      <td className="photo-cell-status"><span className="badge status-ACCEPTED">Принято</span></td>
      <td className="photo-cell-open"><button className="text-button" onClick={() => openPhoto(photo.id)} aria-label={'Открыть фото №' + photo.id}>Открыть<ChevronRight size={14}/></button></td>
    </tr>)}</tbody>
  </table></div>;
}
