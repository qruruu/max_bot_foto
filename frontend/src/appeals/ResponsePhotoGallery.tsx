import { useCallback, useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import PhotoContextMenu from '../PhotoContextMenu';
import { apiUrl } from '../workspace';
import type { ResultPhoto } from './AppealActions';
import '../operator-chats.css';

type Menu = {id: string; x: number; y: number; row: HTMLAnchorElement};

export default function ResponsePhotoGallery({photos = [], path, selected, setSelected}: {
  photos?: ResultPhoto[]; path: string; selected: string[]; setSelected: (ids: string[]) => void;
}) {
  const [menu, setMenu] = useState<Menu | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const transfer = useRef<AbortController | null>(null);
  const close = useCallback(() => setMenu(null), []);
  useEffect(() => () => transfer.current?.abort(), []);

  const picked = photos.filter(photo => selected.includes(photo.id)).map(photo => photo.id);
  const selecting = picked.length > 0;
  const ids = selecting ? picked : menu ? [menu.id] : [];

  async function download() {
    if (!ids.length || transfer.current) return;
    const controller = new AbortController();
    transfer.current = controller;
    setDownloading(true);
    setError('');
    try {
      const query = new URLSearchParams(ids.map(id => ['photo_id', id]));
      const response = await fetch(apiUrl(path + '/response-photos/download?' + query), {
        credentials: 'same-origin', signal: controller.signal,
      });
      if (!response.ok) throw new Error();
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]
        || (ids.length === 1 ? 'photo.jpg' : 'photos.zip');
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      if (!controller.signal.aborted) setError('Не удалось скачать фотографии ответа. Попробуйте ещё раз.');
    } finally {
      transfer.current = null;
      if (!controller.signal.aborted) setDownloading(false);
    }
  }

  if (!photos.length) return null;
  return <>
    <div className="appeal-evidence">{photos.map((photo, index) => {
      const marked = picked.includes(photo.id);
      return <a key={photo.id} className="appeal-response-photo" data-selected={marked}
        href={photo.url} target="_blank" rel="noreferrer" aria-haspopup="menu"
        aria-label={`Фотография ответа ${index + 1}${marked ? ', выбрана' : ''}`}
        onClick={event => {
          if (!selecting) return;
          event.preventDefault();
          close();
          setSelected(marked ? picked.filter(id => id !== photo.id) : [...picked, photo.id]);
        }}
        onContextMenu={event => {
          event.preventDefault();
          setMenu({id: photo.id, x: event.clientX, y: event.clientY, row: event.currentTarget});
        }}
        onKeyDown={event => {
          if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return;
          event.preventDefault();
          const {left, bottom} = event.currentTarget.getBoundingClientRect();
          setMenu({id: photo.id, x: left, y: bottom, row: event.currentTarget});
        }}>
        <img src={photo.preview_url} alt=""/>
        {marked && <span className="appeal-response-photo-check" aria-hidden="true"><Check size={14}/></span>}
      </a>;
    })}</div>
    {error && <p className="error" role="alert">{error}</p>}
    {menu && photos.some(photo => photo.id === menu.id) && <PhotoContextMenu target={menu} count={ids.length}
      canSelect={!selecting} selecting={selecting} downloading={downloading} close={close}
      downloadLabel={picked.length === 1 ? 'Скачать выбранную фотографию' : undefined}
      select={() => setSelected([menu.id])}
      cancel={() => setSelected([])} download={() => void download()}/>}
  </>;
}
