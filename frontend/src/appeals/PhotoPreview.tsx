import { useRef } from 'react';
import { Camera, X } from 'lucide-react';
import type { CameraPhoto } from './camera';
import useModal from './useModal';

export default function PhotoPreview({photo, onClose, onRetake}: {
  photo: CameraPhoto; onClose: () => void; onRetake: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  useModal(root);
  return <div ref={root} className="citizen-photo-dialog" role="dialog" aria-modal="true" aria-labelledby="photo-preview-title">
    <header><h2 id="photo-preview-title">Проверьте снимок</h2><button data-modal-close type="button" className="citizen-icon" onClick={onClose} aria-label="Закрыть просмотр"><X/></button></header>
    <img src={photo.url} alt="Снимок проблемы с датой и координатами"/>
    <p>Проблема и окружающее место должны быть хорошо видны.</p>
    <div><button type="button" className="citizen-shutter" onClick={onRetake}><Camera size={20}/>Переснять</button>
      <button type="button" className="citizen-primary" onClick={onClose}>Оставить снимок</button></div>
  </div>;
}
