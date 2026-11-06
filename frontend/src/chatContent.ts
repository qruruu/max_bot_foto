import { useState } from 'react';
import { galleryPhoto } from './appeals/gallery';

export type MessageQuote = {id: number; author: string; body: string};
export type ChatContent = {
  reply?: MessageQuote | null;
  forwarded?: boolean;
  forwarded_name?: string | null;
  screenshots?: string[];
};
export type ChatExtras = {files: File[]; reply: MessageQuote | null};
const empty: ChatExtras = {files: [], reply: null};

export function useChatExtras(key: string) {
  const [drafts, setDrafts] = useState<Record<string, ChatExtras>>({});
  const extras = drafts[key] || empty;
  const update = (values: Partial<ChatExtras>) => setDrafts(current => ({
    ...current, [key]: {...(current[key] || empty), ...values},
  }));
  function clearSent(sent: ChatExtras) {
    setDrafts(current => current[key] === sent ? {...current, [key]: empty} : current);
  }
  return {extras, update, clearSent};
}

export async function encodeScreenshots(files: File[], maxEncodedSize = 2_000_000): Promise<string[]> {
  return Promise.all(files.map(async file => {
    const {blob} = await galleryPhoto(file);
    if (Math.ceil(blob.size / 3) * 4 > maxEncodedSize) throw new Error('Скриншот слишком большой. Уменьшите его и попробуйте ещё раз.');
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = () => reject(new Error('Не удалось прочитать скриншот'));
      reader.readAsDataURL(blob);
    });
  }));
}
