import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Paperclip, Send, X } from 'lucide-react';
import { MAX_PHOTOS, pastedImages } from './appeals/TaskImageInput';
import type { ChatExtras } from './chatContent';

export default function ChatComposer({label, draft, changeDraft, extras, changeExtras, send, disabled, sending, error, pending}: {
  label: string; draft: string; changeDraft: (text: string) => void; extras: ChatExtras;
  changeExtras: (extras: Partial<ChatExtras>) => void; send: (event?: FormEvent) => void;
  disabled?: boolean; sending?: boolean; error?: string; pending?: boolean;
}) {
  const {files, reply} = extras;
  const input = useRef<HTMLInputElement>(null), field = useRef<HTMLTextAreaElement>(null);
  const [previews, setPreviews] = useState<string[]>([]), [attachmentError, setAttachmentError] = useState('');
  useEffect(() => {
    const urls = files.map(file => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach(url => URL.revokeObjectURL(url));
  }, [files]);
  useEffect(() => {if (reply) field.current?.focus();}, [reply]);
  function add(added: File[]) {
    if (!added.length) return;
    if (files.length + added.length > MAX_PHOTOS || added.some(file => file.size > 25 * 1024 * 1024)) {
      setAttachmentError(`Можно приложить до ${MAX_PHOTOS} изображений по 25 МБ.`);
      return;
    }
    setAttachmentError('');
    changeExtras({files: [...files, ...added]});
  }
  const canSend = !disabled && !sending && (!!draft.trim() || !!files.length);
  return <form className="chat-composer" onSubmit={event => {event.preventDefault(); if (canSend) send();}}>
    {(error || attachmentError) && <p className="error" role="alert">{error || attachmentError}</p>}
    {reply && <div className="chat-compose-reply"><div className="chat-quote"><strong>{reply.author}</strong><span>{reply.body}</span></div>
      <button type="button" aria-label="Отменить ответ" disabled={disabled || sending || pending} onClick={() => changeExtras({reply: null})}><X size={16}/></button></div>}
    {!!files.length && <div className="chat-compose-images">{files.map((file, index) => <div key={index}><img src={previews[index]} alt={file.name}/>
      <button type="button" aria-label={'Удалить скриншот ' + (index + 1)} disabled={disabled || sending || pending} onClick={() => {
        setAttachmentError(''); changeExtras({files: files.filter((_, item) => item !== index)});
      }}><X size={14}/></button></div>)}</div>}
    <div className="chat-compose-row">
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple hidden onChange={event => {
        add(Array.from(event.target.files || [])); event.target.value = '';
      }}/>
      <button type="button" title="Прикрепить скриншот" aria-label="Прикрепить скриншот" disabled={disabled || sending || pending || files.length >= MAX_PHOTOS}
        onClick={() => input.current?.click()}><Paperclip size={19}/></button>
      <textarea ref={field} aria-label={label} placeholder="Напишите сообщение…" maxLength={4000} rows={2} value={draft}
        disabled={disabled || sending || pending} onChange={event => changeDraft(event.target.value)} onPaste={event => add(pastedImages(event))}
        onKeyDown={event => {
          if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
          event.preventDefault();
          if (canSend) send();
        }}/>
      <button type="submit" className="primary" title={pending ? 'Повторить отправку' : 'Отправить сообщение'} aria-label={pending ? 'Повторить отправку' : 'Отправить сообщение'}
        disabled={!canSend}><Send size={18}/></button>
    </div>
  </form>;
}
