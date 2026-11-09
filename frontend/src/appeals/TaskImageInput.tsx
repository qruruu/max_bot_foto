import { useEffect, useRef, useState } from 'react';
import type { ClipboardEvent, ReactNode } from 'react';
import { Image as ImageIcon } from 'lucide-react';

export const MAX_PHOTOS = 10;

export function pastedImages(event: ClipboardEvent<HTMLTextAreaElement>) {
  const images = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
  if (images.length) event.preventDefault();
  return images;
}

export default function TaskImageInput({disabled, files, onChange, picker}: {
  disabled: boolean;
  files: File[];
  onChange: (files: File[]) => void;
  picker?: (openFiles: () => void) => ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [previews, setPreviews] = useState<string[]>([]);
  useEffect(() => {
    if (typeof URL.createObjectURL !== 'function') return;
    const urls = files.map(file => {
      try {return URL.createObjectURL(file);}
      catch {return '';}
    });
    setPreviews(urls);
    return () => urls.filter(Boolean).forEach(url => URL.revokeObjectURL(url));
  }, [files]);
  const field = <input ref={input} type="file" hidden={!!picker}
    accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.png,.webp,.heic,.heif"
    multiple disabled={disabled} onChange={event => {
      onChange([...files, ...Array.from(event.target.files || [])]);
      event.target.value = '';
    }}/>;
  return <div>
    {picker ? <>{field}{picker(() => input.current?.click())}</> :
      <label>Фото и скриншоты <small>До {MAX_PHOTOS} файлов по 25 МБ. Скриншот можно вставить в поле текста.</small>{field}</label>}
    {files.length > 0 && <span className="hint">Выбрано: {files.length} из {MAX_PHOTOS}</span>}
    {files.map((file, index) => <div className="appeal-file-row" key={index}>
      {previews[index] ? <img className="appeal-file-preview" src={previews[index]} alt="" onError={event => {
        const failed = event.currentTarget.src;
        setPreviews(current => current.map(url => url === failed ? '' : url));
      }}/> : <ImageIcon size={20} aria-hidden="true"/>}
      <span>{file.name}</span>
      <button type="button" disabled={disabled} aria-label={'Удалить ' + file.name}
        onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}>Удалить</button>
    </div>)}
  </div>;
}
