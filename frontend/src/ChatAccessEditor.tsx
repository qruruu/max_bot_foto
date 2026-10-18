import type { Chat } from './types';

export default function ChatAccessEditor({chats, value, onChange, administrator}: {
  chats: Chat[];
  value: number[] | null;
  onChange: (value: number[] | null) => void;
  administrator: boolean;
}) {
  return <section className="chat-access-editor" aria-labelledby="chat-access-title">
    <h3 id="chat-access-title">Доступ к чатам MAX</h3>
    {administrator ? <p className="hint">Администратору доступны все чаты.</p> : <>
      <p className="hint">Оператор увидит фотографии, карту и отчёты только из разрешённых чатов. Выбранные выше функции действуют в пределах этого доступа.</p>
      <div className="chat-access-modes">
        <label className="checkbox"><input type="radio" name="chat-access" checked={value === null} onChange={() => onChange(null)}/>Все чаты, включая новые</label>
        <label className="checkbox"><input type="radio" name="chat-access" checked={value !== null} onChange={() => onChange([])}/>Только выбранные чаты</label>
      </div>
      {value !== null && <>
        <div className="chat-access-list">{chats.map(chat => <label className="checkbox" key={chat.id}>
          <input type="checkbox" checked={value.includes(chat.id)} onChange={e => onChange(e.target.checked ? [...value, chat.id] : value.filter(id => id !== chat.id))}/>
          <span>{chat.name}{!chat.active && <small>Приём новых фото отключён</small>}</span>
        </label>)}{!chats.length && <p className="hint">Чаты MAX пока не добавлены.</p>}</div>
        <p className="hint">{value.length ? `Выбрано чатов: ${value.length}. Новые чаты нужно разрешать отдельно.` : 'Чаты не выбраны — фотографии и отчёты будут пустыми.'}</p>
        <p className="hint">Обмен с АРМ и обучение нейросети требуют доступа ко всем чатам.</p>
      </>}
      <p className="hint">После изменения доступа оператору нужно войти снова.</p>
    </>}
  </section>;
}
