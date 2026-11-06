import { Share2 } from 'lucide-react';
import type { ChatContent } from './chatContent';

export function ChatMessageContent({message, jump}: {message: ChatContent; jump?: (id: number) => void}) {
  const reply = message.reply;
  return <>
    {message.forwarded && <span className="operator-message-forwarded"><Share2 size={13}/>
      {message.forwarded_name ? 'Переслано от: ' + message.forwarded_name : 'Пересланное сообщение'}</span>}
    {reply && (jump ? <button type="button" className="chat-quote" title="Перейти к сообщению" onClick={() => jump(reply.id)}>
      <strong>{reply.author}</strong><span>{reply.body}</span></button> : <div className="chat-quote"><strong>{reply.author}</strong><span>{reply.body}</span></div>)}
    {!!message.screenshots?.length && <div className="chat-message-images">{message.screenshots.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer" title="Открыть скриншот">
      <img src={url} loading="lazy" alt={'Скриншот ' + (index + 1)}/></a>)}</div>}
  </>;
}

export function revealMessage(log: HTMLElement | null, id: number) {
  const message = log?.querySelector<HTMLElement>(`[data-message-id="${id}"]`);
  message?.scrollIntoView({block: 'nearest'});
  message?.focus({preventScroll: true});
}
