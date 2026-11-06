import { useEffect, useState } from 'react';
import { Share2, X } from 'lucide-react';

const maxMessages = 20;

export function useChatSelection(chat: string) {
  const [selection, setSelection] = useState<{chat: string; ids: number[]}>({chat, ids: []});
  const ids = selection.chat === chat ? selection.ids : [];
  const clear = () => setSelection(current => current.chat === chat ? {chat, ids: []} : current);
  useEffect(() => {
    setSelection(current => current.chat === chat ? current : {chat, ids: []});
  }, [chat]);
  return {ids, clear, toggle: (id: number) => {
    const next = ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id];
    if (next.length <= maxMessages) setSelection({chat, ids: next});
  }};
}

export function ChatSelectionBar({count, cancel, forward}: {count: number; cancel: () => void; forward: () => void}) {
  return <div className="chat-selection-bar" aria-label="Выбор сообщений">
    <button type="button" title="Отменить выбор" aria-label="Отменить выбор" onClick={cancel}><X size={18}/></button>
    <span role="status">Выбрано {count}{count === maxMessages && ' · достигнут предел'}</span>
    <button type="button" className="primary" onClick={forward}><Share2 size={16}/>Переслать</button>
  </div>;
}
