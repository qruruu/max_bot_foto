import { Fragment, useState } from 'react';
import type { FormEvent, ReactNode, RefObject } from 'react';
import { ArrowLeft, Check, CheckCheck, MessageCircle, Search, X } from 'lucide-react';
import { ErrorBox } from './App';
import Avatar from './Avatar';
import UserPresence from './UserPresence';
import ChatComposer from './ChatComposer';
import LinkedText from './LinkedText';
import { ChatMessageContent, revealMessage } from './ChatMessageContent';
import ChatMessageMenu from './ChatMessageMenu';
import { ChatSelectionBar, useChatSelection } from './ChatSelection';
import type { ChatContent, ChatExtras, MessageQuote } from './chatContent';
import { messageDay, messageTime } from './operatorChatData';
import './operator-chats.css';

export type ChatContact = {
  key: string; name: string; subtitle: string; avatar_url: string | null; active: boolean;
  unread: number; last_seen_at?: string | null; preview: string | null; preview_at?: string | null; organization?: string | null;
};
export type ChatMessage = ChatContent & {
  id: number; body: string; outgoing: boolean; created_at: string; read: boolean; attachment?: ReactNode; canForward?: boolean; author: string;
};
type Props = {
  contacts: ChatContact[]; selected: string; select: (key: string) => void;
  contactLoading: boolean; contactError: string; messages: ChatMessage[]; historyError: string;
  loading: boolean; hasOlder: boolean; loadingOlder: boolean; older: () => void;
  listRef: RefObject<HTMLDivElement | null>; draft: string; changeDraft: (value: string) => void;
  send: (event?: FormEvent) => void;
  extras: ChatExtras; changeExtras: (value: Partial<ChatExtras>) => void;
  reply: (value: MessageQuote) => void;
  sending: boolean; sendError: string; timezone: string;
  forward?: (ids: number[], sent: () => void) => void;
  forwardedTo?: {key: string; name: string} | null;
  dismissForwarded?: () => void;
  labels?: {contacts: string; search: string; loading: string; none: string; empty: string; back: string; message: string};
};
const operatorLabels = {
  contacts: 'Собеседники', search: 'Найти собеседника', loading: 'Загружаем собеседников…',
  none: 'Собеседников не найдено.', empty: 'Доступных собеседников пока нет.', back: 'К списку чатов', message: 'Сообщение',
};

/** Shared conversation layout for operator and inspector accounts. Authorization stays in their APIs. */
export default function ChatPanel(props: Props) {
  const {contacts, selected, select, messages, listRef, timezone, labels = operatorLabels} = props;
  const [search, setSearch] = useState('');
  const selection = useChatSelection(selected);
  const visibleMessageIds = new Set(messages.map(message => message.id));
  const peer = contacts.find(contact => contact.key === selected);
  const filtered = contacts.filter(contact => [contact.name, contact.subtitle, contact.organization].filter(Boolean).join(' ').toLocaleLowerCase('ru-RU').includes(search.toLocaleLowerCase('ru-RU')));
  return <section className={`panel operator-chats ${selected ? 'conversation-open' : ''}`}>
    <aside className="operator-chat-contacts" aria-label={labels.contacts}>
      <label className="operator-chat-search"><Search size={16} aria-hidden="true"/><input aria-label={labels.search} placeholder={labels.search + '…'} value={search} onChange={event => setSearch(event.target.value)}/></label>
      <ErrorBox error={props.contactError}/>
      <div className="operator-chat-contact-list">
        {props.contactLoading && <p className="operator-chat-note">{labels.loading}</p>}
        {!props.contactLoading && !filtered.length && <p className="operator-chat-note">{search ? labels.none : labels.empty}</p>}
        {filtered.map(contact => <button type="button" key={contact.key} className={`operator-chat-contact ${selected === contact.key ? 'selected' : ''}`} onClick={() => select(contact.key)} aria-pressed={selected === contact.key}>
          <Avatar name={contact.name} src={contact.avatar_url}/>
          <span className="operator-chat-contact-copy"><strong>{contact.name}</strong><span>{contact.preview ?? [contact.subtitle, contact.organization].filter(Boolean).join(' · ')}</span><UserPresence lastSeen={contact.last_seen_at} active={contact.active} timezone={timezone}/></span>
          <span className="operator-chat-contact-meta">{contact.preview_at && <time dateTime={contact.preview_at}>{messageTime(contact.preview_at, timezone)}</time>}{contact.unread > 0 && <span className="operator-chat-unread" aria-label={`Непрочитанных: ${contact.unread}`}>{contact.unread > 99 ? '99+' : contact.unread}</span>}</span>
        </button>)}
      </div>
    </aside>
    <div className="operator-conversation">
      {!selected ? <div className="operator-chat-empty"><MessageCircle size={44}/><h2>Выберите собеседника</h2><p>Откройте диалог из списка, чтобы начать переписку.</p></div> : <>
        <div className="operator-conversation-header"><button type="button" className="operator-chat-back" aria-label={labels.back} onClick={() => select('')}><ArrowLeft size={18}/></button><Avatar name={peer?.name || 'Собеседник'} src={peer?.avatar_url || null}/><div><strong>{peer?.name || 'Переписка'}</strong><span>{peer?.subtitle || 'Загружаем…'}</span>{peer && <UserPresence lastSeen={peer.last_seen_at} active={peer.active} timezone={timezone}/>}</div></div>
        {props.forwardedTo && <div className="chat-forwarded-notice">
          <span role="status">Переслано · {props.forwardedTo.name}</span>
          {props.forwardedTo.key !== selected && <button type="button" className="text-button" onClick={() => select(props.forwardedTo!.key)}>Открыть чат</button>}
          <button type="button" className="chat-forwarded-close" aria-label="Скрыть подтверждение" onClick={props.dismissForwarded}><X size={15}/></button>
        </div>}
        <ErrorBox error={props.historyError}/>
        <div className="operator-message-list" ref={listRef}>
          {props.hasOlder && <button type="button" className="operator-chat-older" onClick={props.older} disabled={props.loadingOlder}>{props.loadingOlder ? 'Загружаем…' : 'Более ранние сообщения'}</button>}
          {props.loading && <p className="operator-chat-note">Загружаем переписку…</p>}
          {!props.loading && !messages.length && !props.historyError && <div className="operator-chat-empty"><MessageCircle size={36}/><p>Сообщений пока нет. Напишите собеседнику первым.</p></div>}
          <ol role="log" aria-label="Сообщения" aria-live="polite" aria-relevant="additions">
            {messages.map((message, index) => {
              const day = messageDay(message.created_at, timezone);
              return <Fragment key={message.id}>
                {(index === 0 || messageDay(messages[index - 1].created_at, timezone) !== day) && <li className="operator-message-day">{day}</li>}
                <ChatMessageMenu as="li" id={message.id} className={`operator-message ${message.outgoing ? 'own' : ''}`}
                  reply={peer?.active && !props.sending ? () => props.reply({id: message.id, author: message.author,
                    body: message.body.slice(0, 180) || 'Вложение'}) : undefined}
                  forward={message.canForward !== false && props.forward ? () => props.forward?.([message.id], selection.clear) : undefined}
                  select={message.canForward !== false && props.forward ? () => selection.toggle(message.id) : undefined}
                  selected={selection.ids.length ? selection.ids.includes(message.id) : undefined}>
                  <div className={'operator-message-bubble' + (message.screenshots?.length && !message.body && !message.attachment ? ' media-only' : '')}>
                    <ChatMessageContent message={message} jump={message.reply && visibleMessageIds.has(message.reply.id) ? id => revealMessage(listRef.current, id) : undefined}/>
                    {message.attachment}{message.body && <p><LinkedText>{message.body}</LinkedText></p>}
                    <div className="operator-message-meta">
                      <time dateTime={message.created_at}>{messageTime(message.created_at, timezone)}</time>
                      {message.outgoing && <span className={message.read ? 'message-read' : ''} aria-label={message.read ? 'Прочитано' : 'Отправлено'}>
                        {message.read ? <CheckCheck size={14} aria-hidden="true"/> : <Check size={14} aria-hidden="true"/>}</span>}
                    </div>
                  </div>
                </ChatMessageMenu>
              </Fragment>;
            })}
          </ol>
        </div>
        {selection.ids.length > 0 && <ChatSelectionBar count={selection.ids.length} cancel={selection.clear}
          forward={() => props.forward?.(selection.ids, selection.clear)}/>}
        <div hidden={selection.ids.length > 0}><ChatComposer key={selected} label={labels.message} draft={props.draft} changeDraft={props.changeDraft}
          extras={props.extras} changeExtras={props.changeExtras} send={props.send} sending={props.sending}
          disabled={!peer?.active || props.loading} error={props.sendError}/></div>
      </>}
    </div>
  </section>;
}
