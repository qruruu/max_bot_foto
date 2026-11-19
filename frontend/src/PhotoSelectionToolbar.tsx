import { MAX_PHOTOS } from './appeals/TaskImageInput';

export default function PhotoSelectionToolbar({count, selectingAll = false, canSelectAll, downloading, selectAll, download, cancel}: {
  count: number; selectingAll?: boolean; canSelectAll: boolean; downloading: boolean;
  selectAll: () => void; download: () => void; cancel: () => void;
}) {
  return <>
    <section className="day-dialog-actions" aria-label="Выбор и скачивание фотографий">
      <button type="button" disabled={!canSelectAll || selectingAll || downloading} onClick={selectAll}>Выбрать все</button>
      <span role="status">{selectingAll ? 'Выбираем фотографии…' : `Выбрано фотографий: ${count}`}</span>
      <button type="button" disabled={!count || selectingAll || downloading} onClick={download}>Скачать</button>
      <button type="button" onClick={cancel}>Отменить выбор</button>
    </section>
    {count > MAX_PHOTOS && <p className="hint">Пересылка доступна при выборе не более 10 фотографий</p>}
  </>;
}
