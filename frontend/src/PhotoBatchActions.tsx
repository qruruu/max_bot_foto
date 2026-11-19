import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { apiUrl } from './workspace';
import { useApp } from './App';
import TaskPhotoSend from './appeals/TaskPhotoSend';
import { MAX_PHOTOS } from './appeals/TaskImageInput';
import ForwardPhotos from './inspection/Forward';
import PhotoSelectionToolbar from './PhotoSelectionToolbar';
import PhotoContextMenu, { type PhotoMenuTarget } from './PhotoContextMenu';
import { downloadPhotos } from './photoDownload';
import { MAX_DOWNLOAD_PHOTOS } from './photoLimits';
import type { SelectedPhoto } from './photoSelection';

export default function usePhotoBatchActions(scope: string, inspectionOrg?: string, listFilters?: string) {
  const {user, meta, notify} = useApp();
  const [photos, setPhotos] = useState<SelectedPhoto[]>([]);
  const [selecting, setSelecting] = useState(false);
  const [menu, setMenu] = useState<PhotoMenuTarget | null>(null);
  const [destination, setDestination] = useState<{kind: 'chat' | 'task'; photos: SelectedPhoto[]} | null>(null);
  const [error, setError] = useState('');
  const selectionRequest = useRef<AbortController | null>(null);
  const [selectingAll, setSelectingAll] = useState(false);
  const [loading, setLoading] = useState(false);
  const ids = new Set(photos.map(photo => photo.id));
  const base = inspectionOrg ? '/inspection/organizations/' + inspectionOrg : undefined;
  const canSendToTask = !!(base || meta.organization);
  const admin = !base && user.role === 'ADMIN_OPERATOR' && !!meta.organization;

  function clear() {selectionRequest.current?.abort(); selectionRequest.current = null; setSelectingAll(false); setPhotos([]); setSelecting(false); setMenu(null);}
  useEffect(() => {clear(); setDestination(null); setError(''); return () => selectionRequest.current?.abort();}, [scope]);

  function toggle(photo: SelectedPhoto) {
    if (!photo.preview_url || selectingAll) return;
    setPhotos(current => current.some(item => item.id === photo.id)
      ? current.filter(item => item.id !== photo.id)
      : current.length < MAX_DOWNLOAD_PHOTOS ? [...current, photo] : current);
  }
  async function selectAll() {
    if (!base || selectionRequest.current) return;
    const request = new AbortController();
    selectionRequest.current = request;
    setSelectingAll(true);
    setError('');
    try {
      const result = await api<{ids: number[]}>(base + '/photos/selection?' + listFilters, 'GET', undefined, request.signal);
      if (!request.signal.aborted) {
        setSelecting(true);
        setPhotos(result.ids.slice(0, MAX_DOWNLOAD_PHOTOS).map(id => ({
          id, preview_url: apiUrl(base + '/photos/' + id + '/preview'),
        })));
      }
    } catch (error) {if (!request.signal.aborted) setError((error as Error).message);}
    finally {
      if (selectionRequest.current === request) {
        selectionRequest.current = null;
        setSelectingAll(false);
      }
    }
  }
  function canToggle(photo: SelectedPhoto) {
    return !selectingAll && !!photo.preview_url && (ids.has(photo.id) || ids.size < MAX_DOWNLOAD_PHOTOS);
  }
  function forward(kind: 'chat' | 'task', batch = photos) {
    if (!selectingAll && batch.length && batch.length <= MAX_PHOTOS) setDestination({kind, photos: batch});
  }
  async function download(batch = photos) {
    if (!batch.length || loading || selectingAll) return;
    setLoading(true); setError('');
    try {
      await downloadPhotos({ids: batch.map(photo => photo.id)}, setError, state => {
        if (state === 'queued') notify('Подготавливаем скачивание…');
        if (state === 'finished') notify('Скачивание завершено');
      }, base ? base + '/photos/downloads' : undefined);
    } catch (error) {setError((error as Error).message);}
    finally {setLoading(false);}
  }
  function sent() {clear(); setDestination(null); notify('Фотографии отправлены');}

  const menuPhotos = photos.length ? photos : menu?.photo.preview_url ? [menu.photo] : [];
  const dialogs = <>
    {error && <p className="error" role="alert">{error}</p>}
    {menu && <PhotoContextMenu target={menu} count={menuPhotos.length} selecting={selecting}
      canSelect={canToggle(menu.photo)} canSendToTask={canSendToTask} downloading={loading || selectingAll}
      close={() => setMenu(null)} cancel={clear} select={() => {
        setSelecting(true);
        if (!ids.has(menu.photo.id)) toggle(menu.photo);
      }} forward={kind => forward(kind, menuPhotos)} download={() => void download(menuPhotos)}/>}
    {destination?.kind === 'task' && <TaskPhotoSend ids={destination.photos.map(photo => photo.id)}
      inspectionBase={base} close={() => setDestination(null)} sent={sent}/>}
    {destination?.kind === 'chat' && <ForwardPhotos photos={destination.photos.map(photo => ({
      ...photo, organization_id: inspectionOrg || (admin ? meta.organization?.id : undefined),
    }))} base={admin ? '/inspection-admin' : undefined} unified={admin} onClose={() => setDestination(null)} onSent={sent}/>}
  </>;
  function toolbar(canSelectAll: boolean) {
    if (!selecting) return null;
    return <PhotoSelectionToolbar count={ids.size} selectingAll={selectingAll}
      canSelectAll={canSelectAll} downloading={loading}
      selectAll={() => void selectAll()} download={() => void download()} cancel={clear}/>;
  }
  return {ids, selecting, toggle, canToggle, setMenu, dialogs, toolbar};
}

export type PhotoBatchActions = ReturnType<typeof usePhotoBatchActions>;
