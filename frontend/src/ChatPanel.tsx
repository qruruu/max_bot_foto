import { Fragment, useState } from 'react';
import type { FormEvent, KeyboardEvent, ReactNode, RefObject } from 'react';
import { ArrowLeft, Bot, Check, CheckCheck, MessageCircle, Search, Send, Share2 } from 'lucide-react';
import { ErrorBox } from './App';
import Avatar from './Avatar';
import { messageDay, messageTime } from './operatorChatData';
import './operator-chats.css';

export type ChatContact = {
  key: string; name: string; subtitle: string; avatar_url: string | null; active: boolean;
  assistant?: boolean; unread: number; preview: string | null; preview_at?: string | null; organization?: string | null;
};
export type ChatMessage = {
  id: number; body: string; outgoing: boolean; created_at: string; read: boolean; attachment?: ReactNode; forwarded?: boolean; canForward?: boolean;
};
type Props = {
  contacts: ChatContact[]; selected: string; select: (key: string) => void;
  contactLoading: boolean; contactError: string; messages: ChatMessage[]; historyError: string;
  loading: boolean; hasOlder: boolean; loadingOlder: boolean; older: () => void;
  listRef: RefObject<HTMLDivElement | null>; draft: string; changeDraft: (value: string) => void;
  send: (event?: FormEvent) => void; keyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  sending: boolean; sendError: string; timezone: string;
  forward?: (id: number) => void;
  assistantPrompt?: { example: string; maxLength: number };
  labels?: {contacts: string; search: string; loading: string; none: string; empty: string; back: string; message: string};
};
const operatorLabels = {
  contacts: 'Операторы для переписки', search: 'Найти оператора', loading: 'Загружаем операторов…',
  none: 'Операторов не найдено.', empty: 'Другие операторы пока не добавлены.', back: 'К списку операторов', message: 'Сообщение оператору',
};

function ContactAvatar({contact}: {contact?: ChatContact}) {
  return contact?.assistant
    ? <span className="avatar operator-assistant-avatar" aria-hidden="true"><Bot size={21}/></span>
    : <Avatar name={contact?.name || 'Собеседник'} src={contact?.avatar_url || null}/>;
}

/** Shared conversation layout for operator and inspector accounts. Authorization stays in their APIs. */
export default function ChatPanel(props: Props) {
  const {contacts, selected, select, messages, listRef, timezone, labels = operatorLabels} = props;
  const [search, setSearch] = useState('');
  const peer = contacts.find(contact => contact.key === selected);
  const assistantPrompt = peer?.assistant ? props.assistantPrompt : undefined;
  const filtered = contacts.filter(contact => [contact.name, contact.organization].filter(Boolean).join(' ').toLocaleLowerCase('ru-RU').includes(search.toLocaleLowerCase('ru-RU')));
  return <section className={`panel operator-chats ${selected ? 'conversation-open' : ''}`}>
    <aside className="operator-chat-contacts" aria-label={labels.contacts}>
      <label className="operator-chat-search"><Search size={16} aria-hidden="true"/><input aria-label={labels.search} placeholder={labels.search + '…'} value={search} onChange={event => setSearch(event.target.value)}/></label>
      <ErrorBox error={props.contactError}/>
      <div className="operator-chat-contact-list">
        {props.contactLoading && <p className="operator-chat-note">{labels.loading}</p>}
        {!props.contactLoading && !filtered.length && <p className="operator-chat-note">{search ? labels.none : labels.empty}</p>}
        {filtered.map(contact => <button type="button" key={contact.key} className={`operator-chat-contact ${selected === contact.key ? 'selected' : ''}`} onClick={() => select(contact.key)} aria-pressed={selected === contact.key}>
          <ContactAvatar contact={contact}/>
          <span className="operator-chat-contact-copy"><strong>{contact.name}</strong>{contact.organization && <span>{contact.organization}</span>}<span>{contact.preview ?? (contact.active ? 'Начать переписку' : 'Аккаунт отключён')}</span></span>
          <span className="operator-chat-contact-meta">{contact.preview_at && <time dateTime={contact.preview_at}>{messageTime(contact.preview_at, timezone)}</time>}{contact.unread > 0 && <span className="operator-chat-unread" aria-label={`Непрочитанных: ${contact.unread}`}>{contact.unread > 99 ? '99+' : contact.unread}</span>}</span>
        </button>)}
      </div>
    </aside>
    <div className="operator-conversation">
      {!selected ? <div className="operator-chat-empty"><MessageCircle size={44}/><h2>Выберите собеседника</h2><p>Откройте диалог из списка, чтобы начать переписку.</p></div> : <>
        <div className="operator-conversation-header"><button type="button" className="operator-chat-back" aria-label={labels.back} onClick={() => select('')}><ArrowLeft size={18}/></button><ContactAvatar contact={peer}/><div><strong>{peer?.name || 'Переписка'}</strong><span>{peer?.subtitle || 'Загружаем…'}</span></div></div>
        <ErrorBox error={props.historyError}/>
        <div className="operator-message-list" ref={listRef}>
          {props.hasOlder && <button type="button" className="operator-chat-older" onClick={props.older} disabled={props.loadingOlder}>{props.loadingOlder ? 'Загружаем…' : 'Более ранние сообщения'}</button>}
          {props.loading && <p className="operator-chat-note">Загружаем переписку…</p>}
          {!props.loading && !messages.length && !props.historyError && <div className="operator-chat-empty">
            {assistantPrompt ? <><Bot size={36}/><h2>Фото и задачи</h2><p>Спросите, сколько фото поступило за нужный день, или попросите подготовить задачу.</p></> :
              <><MessageCircle size={36}/><p>Сообщений пока нет. Напишите собеседнику первым.</p></>}
          </div>}
          <ol role="log" aria-label="Сообщения" aria-live="polite" aria-relevant="additions">
            {messages.map((message, index) => {
              const day = messageDay(message.created_at, timezone);
              return <Fragment key={message.id}>
                {(index === 0 || messageDay(messages[index - 1].created_at, timezone) !== day) && <li className="operator-message-day">{day}</li>}
                <li className={`operator-message ${message.outgoing ? 'own' : ''}`}><div className="operator-message-bubble">{message.forwarded && <span className="operator-message-forwarded"><Share2 size={12}/>Пересланное сообщение</span>}{message.attachment}{message.body && <p>{message.body}</p>}<div className="operator-message-meta"><time dateTime={message.created_at}>{messageTime(message.created_at, timezone)}</time>{props.forward && <button type="button" className="operator-message-forward" aria-label={'Переслать сообщение №'+message.id} title="Переслать сообщение" disabled={message.canForward===false} onClick={()=>props.forward?.(message.id)}><Share2 size={13}/></button>}{message.outgoing && <span className={message.read ? 'message-read' : ''} aria-label={message.read ? 'Прочитано' : 'Отправлено'} title={message.read ? 'Прочитано' : 'Отправлено'}>{message.read ? <CheckCheck size={14} aria-hidden="true"/> : <Check size={14} aria-hidden="true"/>}</span>}</div></div></li>
              </Fragment>;
            })}
          </ol>
        </div>
        <form className="operator-chat-compose" onSubmit={props.send}>
          <ErrorBox error={props.sendError}/>
          <div><textarea aria-label={assistantPrompt ? 'Вопрос помощнику' : labels.message} placeholder={peer && !peer.active ? 'Аккаунт отключён' : assistantPrompt?.example || 'Напишите сообщение…'} maxLength={assistantPrompt?.maxLength ?? 4000} rows={2} value={props.draft} disabled={!peer?.active || props.loading || props.sending} onChange={event => props.changeDraft(event.target.value)} onKeyDown={props.keyDown}/><button className="primary" aria-label="Отправить сообщение" disabled={!peer?.active || !props.draft.trim() || props.loading || props.sending}><Send size={19}/></button></div>
          <p className="hint" role="status">{props.sending ? (assistantPrompt ? 'Даня ИИ отвечает…' : 'Отправляем…') : 'Enter — отправить, Shift + Enter — новая строка.'}</p>
        </form>
      </>}
    </div>
  </section>;
}
