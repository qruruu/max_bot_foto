import { useEffect, useState } from 'react';
import AttachmentButton from '../AttachmentButton';
import type { ReactNode } from 'react';
import { api } from '../api';
import type { ClosePhoto } from './ResponsePhotoDraft';

type PhotoSource = 'chat' | 'result';

export default function ClosePhotoPicker({endpoint, chooseGeneral, selected, change, remaining, disabled, openFiles, resultPhotos, answerField}: {
  endpoint: string; chooseGeneral?: () => void; selected: ClosePhoto[]; change: (photos: ClosePhoto[]) => void;
  remaining: number; disabled: boolean; openFiles: () => void; resultPhotos?: ReactNode; answerField: ReactNode;
}) {
  const [source, setSource] = useState<PhotoSource | null>(null), [page, setPage] = useState(1);
  const [result, setResult] = useState<{items: ClosePhoto[]; more: boolean} | null>(null), [error, setError] = useState('');

  useEffect(() => {
    if (!source || source === 'result') return;
    const controller = new AbortController();
    setResult(null); setError('');
    api<{items: {id: string; url: string}[]; has_more: boolean}>(endpoint + '/close-chat-photos?page=' + page, 'GET', undefined, controller.signal)
      .then(value => {
        if (!controller.signal.aborted) setResult({items: value.items.map(item => ({...item, source})), more: value.has_more});
      }).catch(reason => {if (!controller.signal.aborted) setError(reason.message);});
    return () => controller.abort();
  }, [endpoint, source, page]);

  function show(next: PhotoSource) {
    setSource(next);
    setPage(1);
  }
  const matches = (a: ClosePhoto, b: ClosePhoto) => a.id === b.id && a.source === b.source;
  return <section className="appeal-close-photo-picker">
    <div className="chat-compose-row">
      <AttachmentButton label="Прикрепить фото" disabled={disabled} options={[
        {label: 'С устройства', action: openFiles, disabled: remaining <= 0},
        {label: 'Фото из переписки', action: () => show('chat')},
        ...(chooseGeneral ? [{label: 'Общие фотографии', action: chooseGeneral}] : []),
        ...(resultPhotos ? [{label: 'Фото исполнителя', action: () => show('result')}] : []),
      ]}/>
      {answerField}
    </div>
    <p className="hint">До 10 фото по 25 МБ. Скриншот можно вставить в поле ответа.</p>
    {source && <section className="appeal-close-source">
      <div className="section-title"><h3>{{chat: 'Фото из переписки', result: 'Фото исполнителя'}[source]}</h3>
        <button type="button" onClick={() => setSource(null)}>Свернуть</button>
      </div>
      {source === 'result' ? resultPhotos : <>
      {error ? <p className="error" role="alert">{error}</p> : !result ? <p role="status">Загружаем фотографии…</p> :
        result.items.length ? <div className="appeal-result-selection">{result.items.map(item => {
          const checked = selected.some(photo => matches(photo, item));
          return <label key={item.id}>
            <input type="checkbox" aria-label={'Выбрать фотографию ' + 'из переписки ' + (result.items.indexOf(item) + 1)}
              checked={checked} disabled={disabled || (!checked && remaining <= 0)}
              onChange={() => change(checked ? selected.filter(photo => !matches(photo, item)) : [...selected, item])}/>
            <img src={item.url} loading="lazy" alt=""/>
          </label>;
        })}</div> : <p className="hint">На этой странице нет фотографий с превью.</p>}
      {result && (page > 1 || result.more) && <div className="pagination">
        <button type="button" disabled={disabled || page === 1} onClick={() => setPage(page - 1)}>Назад</button>
        <button type="button" disabled={disabled || !result.more} onClick={() => setPage(page + 1)}>Далее</button>
      </div>}
      </>}
    </section>}
    {!!selected.length && <div className="appeal-close-picked" aria-label="Фотографии, выбранные для ответа">
      {selected.map((item, index) => <button type="button" key={item.source + item.id} disabled={disabled}
        aria-label={'Убрать фото из ответа ' + (index + 1)} onClick={() => change(selected.filter(photo => !matches(photo, item)))}>
        <img src={item.url} alt=""/> ×
      </button>)}
    </div>}
  </section>;
}
