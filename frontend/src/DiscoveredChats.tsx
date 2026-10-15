import { useEffect, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { api } from './api';
import { ErrorBox, useApp } from './App';
import type { Chat, DiscoveredChat } from './types';

export default function DiscoveredChats({ chats, onAdd }: {
  chats: Chat[];
  onAdd: (chatId: string) => void;
}) {
  const { meta } = useApp();
  const [items, setItems] = useState<DiscoveredChat[] | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    async function load() {
      if (loading) return;
      loading = true;
      try {
        const result = await api<DiscoveredChat[]>('/chats/discovered', 'GET', undefined, controller.signal);
        if (!controller.signal.aborted) {
          setItems(result);
          setError('');
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 10000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [revision]);

  const known = new Set(chats.map(chat => String(chat.max_chat_id)));
  const visible = items?.filter(chat => !known.has(chat.max_chat_id));

  return <section className="panel" aria-labelledby="discovered-chats-title">
    <div className="section-title">
      <h2 id="discovered-chats-title">Обнаруженные чаты</h2>
      <button onClick={() => setRevision(value => value + 1)} aria-label="Обновить обнаруженные чаты">
        <RefreshCw size={16}/>Обновить
      </button>
    </div>
    <p className="hint">Добавьте нашего бота в новый чат, назначьте администратором и отправьте любое сообщение. Чат появится здесь автоматически; список обновляется каждые 10 секунд.</p>
    <ErrorBox error={error}/>
    {items === null && !error && <p className="loading">Ищем новые чаты…</p>}
    {visible?.length === 0 && <p className="hint">Новых чатов пока нет. После установки обновления отправьте в нужный чат новое сообщение.</p>}
    {!!visible?.length && <div className="table-scroll"><table>
      <thead><tr><th>MAX chat ID</th><th>Последнее сообщение</th><th>Дата и время</th><th/></tr></thead>
      <tbody>{visible.map(chat => <tr key={chat.max_chat_id}>
        <td className="mono">{chat.max_chat_id}</td>
        <td>{chat.message_preview || 'Сообщение без текста'}</td>
        <td>{new Date(chat.last_message_at).toLocaleString('ru-RU', { timeZone: meta.timezone })}</td>
        <td><button onClick={() => onAdd(chat.max_chat_id)}><Plus size={15}/>Добавить чат</button></td>
      </tr>)}</tbody>
    </table></div>}
    {items?.length === 100 && <p className="hint">Показаны 100 последних обнаруженных чатов.</p>}
    <p className="hint">Укажите название и сохраните чат, чтобы включить приём фотографий. Фото, отправленные до добавления чата, нужно отправить заново.</p>
  </section>;
}
