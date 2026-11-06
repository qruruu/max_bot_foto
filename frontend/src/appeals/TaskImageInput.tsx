import type { ClipboardEvent } from 'react';

export const MAX_PHOTOS = 10;

export function pastedImages(event: ClipboardEvent<HTMLTextAreaElement>) {
  const images = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
  if (images.length) event.preventDefault();
  return images;
}

export default function TaskImageInput({disabled, files, onChange}: {
  disabled: boolean;
  files: File[];
  onChange: (files: File[]) => void;
}) {
  return <div>
    <label>Фото и скриншоты <small>До {MAX_PHOTOS} файлов по 25 МБ. Скриншот можно вставить в поле текста.</small>
      <input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.png,.webp,.heic,.heif"
        multiple disabled={disabled} onChange={event => {
          onChange([...files, ...Array.from(event.target.files || [])]);
          event.target.value = '';
        }}/>
    </label>
    {files.length > 0 && <span className="hint">Выбрано: {files.length} из {MAX_PHOTOS}</span>}
    {files.map((file, index) => <div className="appeal-file-row" key={index}>
      <span>{file.name}</span>
      <button type="button" disabled={disabled} aria-label={'Удалить ' + file.name}
        onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}>Удалить</button>
    </div>)}
  </div>;
}
