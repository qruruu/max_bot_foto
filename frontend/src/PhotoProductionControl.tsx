import { useState } from 'react';
import { ArrowRight, CheckCheck, X } from 'lucide-react';
import { api, ApiError } from './api';
import type { Photo } from './types';

type PromotionPhoto = Pick<Photo, 'id' | 'version' | 'cohort' | 'status' | 'analyzed_at' | 'production_duplicate_id'>;

export default function PhotoProductionControl({photo, owner, disabled, onBusy, onPromoted, openExisting}: {
  photo: PromotionPhoto; owner: boolean; disabled: boolean; onBusy: (busy: boolean) => void;
  onPromoted: () => Promise<void>; openExisting: (id: number) => void;
}) {
  const [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [conflict, setConflict] = useState<number | null>(null);
  if (!owner || photo.cohort !== 'test') return null;
  const duplicate = photo.production_duplicate_id ?? conflict;
  const eligible = !!photo.analyzed_at && !['REJECTED', 'DUPLICATE', 'FORWARDED'].includes(photo.status);
  async function promote() {
    if (busy) return;
    setBusy(true); onBusy(true); setError('');
    try {
      await api('/photos/' + photo.id + '/promote', 'POST', {version: photo.version});
      setConfirm(false);
      await onPromoted();
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === 'object' && 'code' in e.detail
        && e.detail.code === 'PRODUCTION_DUPLICATE' && 'photo_id' in e.detail && typeof e.detail.photo_id === 'number') {
        setConflict(e.detail.photo_id); setConfirm(false);
      } else setError((e as Error).message);
    } finally { setBusy(false); onBusy(false); }
  }
  return <section className="photo-production-control" aria-label="Рабочий режим фотографии">
    <h3>Перевод в рабочий режим</h3>
    {duplicate ? <><p>Такое изображение уже есть в рабочих фото под номером <strong>#{duplicate}</strong>. Оно учитывается один раз.</p>
      <button type="button" disabled={disabled} onClick={() => openExisting(duplicate)}>Открыть рабочее фото №{duplicate}<ArrowRight size={16}/></button></>
      : <><p>Фото появится в рабочих списках и обзорах за дату снимка. Файл будет храниться в рабочей папке.</p>
        <button type="button" className="primary" disabled={disabled || !eligible} onClick={() => setConfirm(true)}><CheckCheck size={17}/>Сделать рабочим</button>
        {!eligible && <p className="hint">Доступно после первичной обработки фотографии.</p>}</>}
    {!confirm && error && <div className="error" role="alert">{error}</div>}
    {confirm && <div className="modal-backdrop"><section className="modal photo-production-confirmation" role="dialog" aria-modal="true" aria-labelledby="photo-production-title">
      <div className="section-title"><h2 id="photo-production-title">Сделать фото №{photo.id} рабочим?</h2>
        <button type="button" aria-label="Закрыть" disabled={busy} onClick={() => setConfirm(false)}><X size={18}/></button></div>
      <p>Фотография перейдёт из тестового режима в рабочий. Дата, вид работы и остальные данные сохранятся.</p>
      <p>В рабочем дне её потребуется проверить отдельно. Режим приёма новых фотографий останется прежним.</p>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="photo-production-actions"><button type="button" disabled={busy} onClick={() => setConfirm(false)}>Отмена</button>
        <button type="button" className="primary" disabled={busy} onClick={promote}>{busy ? 'Переводим…' : 'Подтвердить перевод'}</button></div>
    </section></div>}
  </section>;
}
