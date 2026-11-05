import type { ClipboardEvent } from 'react';

export function pastedImages(event: ClipboardEvent<HTMLTextAreaElement>) {
  const images = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
  if (images.length) event.preventDefault();
  return images;
}

export default function TaskImageInput({disabled, files, onChange, allowPaste = true}: {
  disabled: boolean;
  allowPaste?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
}) {
  return <div>
    <label>Фото и скриншоты <small>До 3 файлов по 25 МБ.{allowPaste && ' Скриншот можно вставить в поле текста.'}</small>
      <input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.png,.webp,.heic,.heif"
        multiple disabled={disabled} onChange={event => {
          onChange([...files, ...Array.from(event.target.files || [])]);
          event.target.value = '';
        }}/>
    </label>
    {files.length > 0 && <span className="hint">Выбрано: {files.length}</span>}
    {files.map((file, index) => <div className="appeal-file-row" key={index}>
      <span>{file.name}</span>
      <button type="button" disabled={disabled} aria-label={'Удалить ' + file.name}
        onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}>Удалить</button>
    </div>)}
  </div>;
}
