import { useEffect, useRef, useState } from 'react';
import { Camera, ChevronDown, ChevronUp } from 'lucide-react';
import { api } from '../api';
import './appeal-photos.css';

export type AppealPhoto = {id: string; url: string; preview_url: string; original_url?: string};

export default function AppealPhotos({photos, endpoint, count, label = 'Фотография обращения'}: {
  photos?: AppealPhoto[]; endpoint?: string; count?: number; label?: string;
}) {
  const [open, setOpen] = useState(false), [loaded, setLoaded] = useState<AppealPhoto[] | undefined>(photos);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  if (!(count ?? photos?.length ?? 0)) return null;
  async function toggle() {
    setOpen(!open);
    if (open || loaded || !endpoint || busy) return;
    controller.current = new AbortController(); setBusy(true); setError('');
    try {setLoaded((await api<{photos: AppealPhoto[]}>(endpoint, 'GET', undefined, controller.current.signal)).photos);}
    catch (reason) {if (!controller.current.signal.aborted) setError((reason as Error).message);}
    finally {if (!controller.current.signal.aborted) setBusy(false);}
  }
  return <div className="appeal-photos">
    <button type="button" className="appeal-photo-toggle" aria-expanded={open} disabled={busy} onClick={() => void toggle()}>
      <Camera size={17}/>{open ? 'Скрыть фото' : 'Показать фото'}{!open && <span>({count ?? photos?.length})</span>}{open ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}
    </button>
    {open && <>{busy && <p role="status">Загружаем фотографии…</p>}{error && <p className="error" role="alert">{error}</p>}
      <div className="appeal-photo-previews">{(photos ?? loaded)?.map((photo, index) => <a key={photo.id} href={photo.original_url || photo.url} target="_blank" rel="noreferrer" aria-label={`Открыть фото ${index + 1} полностью`}>
        <img src={photo.preview_url} alt={`${label}, снимок ${index + 1}`} loading="lazy"/>
      </a>)}</div></>}
  </div>;
}
