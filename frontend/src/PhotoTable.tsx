import { Camera, ChevronRight } from 'lucide-react';
import { StatusBadge, useApp } from './App';
import { dateLabel } from './api';
import DefectCheckbox from './DefectCheckbox';
import { canEditPhoto } from './photoWork';
import type { Photo } from './types';
import WorkTypeHint from './WorkTypeHint';

export default function PhotoTable({photos, openPhoto, focusId, defectBusy = null, onDefect}: {
  photos: Photo[];
  openPhoto: (id: number) => void;
  focusId?: number | null;
  defectBusy?: number | null;
  onDefect: (photo: Photo, checked: boolean) => Promise<void>;
}) {
  const {meta, user} = useApp();
  return <div className="table-scroll"><table className="photos-table">
    <thead><tr><th>Фотография</th><th>Дата / время</th><th>Чат / микрорайон</th><th>Координаты</th><th>Вид работы</th><th className="defect-column" scope="col">Неисправность</th><th>Статус</th><th>Нейросеть</th><th>Оператор</th><th/></tr></thead>
    <tbody>{photos.map(photo => <tr key={photo.id} id={'photo-row-' + photo.id} className={photo.id === focusId ? 'photo-return-row' : undefined}>
      <td><button className="photo-thumb" onClick={() => openPhoto(photo.id)}>{photo.preview_url ? <img src={photo.preview_url} loading="lazy" alt={'Фото №' + photo.id}/> : <Camera size={22}/>}<small>#{photo.id}</small></button></td>
      <td>{dateLabel(photo.photo_date)}<small>{photo.photo_time || 'Время не указано'}</small><small>Получено {new Date(photo.received_at).toLocaleString('ru-RU')}</small></td>
      <td>{photo.chat_name}<small>{photo.district_name || 'Микрорайон не определён'}</small></td>
      <td className="mono">{photo.latitude?.toFixed(5) ?? '—'}<small>{photo.longitude?.toFixed(5) ?? '—'}</small></td>
      <td className="photo-work-cell"><span className="photo-work-name">{photo.work_type_name || <span className="muted">Не определён</span>}</span><WorkTypeHint name={photo.work_type_name || 'Не определён'} description={meta.work_types.find(work => work.code === photo.work_type)?.description}/></td>
      <td className="defect-column"><DefectCheckbox hideLabel photoId={photo.id} workTypeName={meta.work_types.find(work => work.code === photo.work_type)?.name || 'Не определён'} checked={!!photo.is_defect} disabled={defectBusy !== null || photo.is_spam || !canEditPhoto(user, photo)} inputLabel={'Неисправность на фото №' + photo.id} saveImmediately onConfirm={checked => onDefect(photo, checked)}/></td>
      <td><StatusBadge value={photo.status}/>{photo.storage_status === 'ERROR' && <small className="danger-text">Ошибка хранения</small>}</td>
      <td>{photo.ai_confidence === null ? '—' : Math.round(photo.ai_confidence * 100) + '%'}</td>
      <td>{photo.operator_name || '—'}</td>
      <td><button className="text-button" onClick={() => openPhoto(photo.id)}>Открыть<ChevronRight size={14}/></button></td>
    </tr>)}</tbody>
  </table></div>;
}
