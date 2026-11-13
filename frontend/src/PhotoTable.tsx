import { Camera, ChevronRight } from 'lucide-react';
import { StatusBadge, useApp } from './App';
import { dateLabel } from './api';
import DefectCheckbox from './DefectCheckbox';
import { canEditPhoto } from './photoWork';
import type { PhotoMenuTarget } from './PhotoContextMenu';
import type { Photo } from './types';
import WorkTypeHint from './WorkTypeHint';
import { MAX_DOWNLOAD_PHOTOS } from './photoLimits';

export default function PhotoTable({photos, openPhoto, focusId, defectBusy = null, onDefect, selection, onPhotoMenu}: {
  photos: Photo[];
  onPhotoMenu?: (target: PhotoMenuTarget) => void;
  selection?: {ids: Set<number>; toggle: (photo: Photo) => void; limit?: number};
  openPhoto: (id: number) => void;
  focusId?: number | null;
  defectBusy?: number | null;
  onDefect: (photo: Photo, checked: boolean) => Promise<void>;
}) {
  const {meta, user} = useApp();
  return <div className="table-scroll"><table className="photos-table">
    <thead><tr>{selection && <th scope="col">Выбор</th>}<th>Фотография</th><th>Дата / время</th><th>Чат / микрорайон</th><th>Координаты</th><th>Вид работы</th><th className="defect-column" scope="col">Неисправность</th><th>Статус</th><th>Нейросеть</th><th>Оператор</th><th/></tr></thead>
    <tbody>{photos.map(photo => <tr key={photo.id} id={'photo-row-' + photo.id} className={photo.id === focusId ? 'photo-return-row' : undefined}
      data-photo-selected={selection?.ids.has(photo.id) || undefined} data-photo-selectable={!!selection || undefined} tabIndex={onPhotoMenu ? 0 : undefined}
      aria-haspopup={onPhotoMenu ? 'menu' : undefined} aria-keyshortcuts={onPhotoMenu ? 'Shift+F10 ContextMenu' : undefined}
      onContextMenu={onPhotoMenu ? event => {
        event.preventDefault();
        onPhotoMenu({photo, x: event.clientX, y: event.clientY, row: event.currentTarget});
      } : undefined}
      onKeyDown={onPhotoMenu ? event => {
        if (event.target !== event.currentTarget || !(event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10'))) return;
        event.preventDefault();
        const bounds = event.currentTarget.getBoundingClientRect();
        onPhotoMenu({photo, x: bounds.left + 12, y: bounds.top + 12, row: event.currentTarget});
      } : undefined}>
      {selection && <td className="photo-cell-select"><label><input type="checkbox" aria-label={'Выбрать фото №' + photo.id} checked={selection.ids.has(photo.id)}
        disabled={!photo.preview_url || (selection.ids.size >= (selection.limit ?? MAX_DOWNLOAD_PHOTOS) && !selection.ids.has(photo.id))} onChange={() => selection.toggle(photo)}/><span className="photo-mobile-field" aria-hidden="true">Выбрать</span></label></td>}
      <td className="photo-cell-preview"><button className="photo-thumb" aria-label={'Открыть фото №' + photo.id} onClick={() => openPhoto(photo.id)}>{photo.preview_url ? <img src={photo.preview_url} loading="lazy" alt={'Фото №' + photo.id}/> : <Camera size={22}/>}<small>#{photo.id}</small></button></td>
      <td className="photo-cell-date"><span className="photo-capture"><span>{dateLabel(photo.photo_date)}</span><small>{photo.photo_time || 'Время не указано'}</small></span><small className="photo-received-at">Получено {new Date(photo.received_at).toLocaleString('ru-RU')}</small></td>
      <td className="photo-cell-location"><span>{photo.chat_name}</span><small>{photo.district_name || 'Микрорайон не определён'}</small></td>
      <td className="mono photo-cell-technical photo-cell-coordinates"><span className="photo-mobile-field">Координаты</span><span className="photo-coordinate">{photo.latitude?.toFixed(5) ?? '—'}</span><small className="photo-coordinate">{photo.longitude?.toFixed(5) ?? '—'}</small></td>
      <td className="photo-work-cell"><span className="photo-work-name">{photo.work_type_name || <span className="muted">Не определён</span>}</span><WorkTypeHint name={photo.work_type_name || 'Не определён'} description={meta.work_types.find(work => work.code === photo.work_type)?.description}/></td>
      <td className="defect-column"><span className="photo-mobile-field" aria-hidden="true">Неисправность</span><DefectCheckbox hideLabel photoId={photo.id} workTypeName={meta.work_types.find(work => work.code === photo.work_type)?.name || 'Не определён'} checked={!!photo.is_defect} disabled={defectBusy !== null || photo.is_spam || !canEditPhoto(user, photo)} inputLabel={'Неисправность на фото №' + photo.id} saveImmediately onConfirm={checked => onDefect(photo, checked)}/></td>
      <td className="photo-cell-status"><span className="photo-mobile-number">#{photo.id}</span><StatusBadge value={photo.status}/>{photo.storage_status === 'ERROR' && <small className="danger-text">Ошибка хранения</small>}</td>
      <td className="photo-cell-technical photo-cell-ai"><span className="photo-mobile-field">ИИ</span>{photo.ai_confidence === null ? '—' : Math.round(photo.ai_confidence * 100) + '%'}</td>
      <td className="photo-cell-technical photo-cell-operator"><span className="photo-mobile-field">Оператор</span><span>{photo.operator_name || '—'}</span></td>
      <td className="photo-cell-open"><button className="text-button" onClick={() => openPhoto(photo.id)}>Открыть<ChevronRight size={14}/></button></td>
    </tr>)}</tbody>
  </table></div>;
}
