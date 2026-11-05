import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';

export default function LocalAssistantChat() {
  const [draft, setDraft] = useState('');
  const [exchange, setExchange] = useState<{ question: string; answer: string }>();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  async function ask(event: FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || sending) return;
    setSending(true);
    setError('');
    try {
      const { answer } = await api<{ answer: string }>('/local-assistant/question', 'POST', { question });
      setExchange({ question, answer });
      setDraft('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить ответ.');
    } finally {
      setSending(false);
    }
  }

  return <section className="panel operator-conversation" aria-label="Даня ИИ">
    <div className="operator-conversation-header"><strong>Даня ИИ</strong></div>
    <div className="operator-message-list" aria-live="polite">
      {exchange && <ol>
        <li className="operator-message own"><div className="operator-message-bubble"><p>{exchange.question}</p></div></li>
        <li className="operator-message"><div className="operator-message-bubble"><p>{exchange.answer}</p></div></li>
      </ol>}
      {sending && <p>Помощник отвечает…</p>}
    </div>
    <form className="operator-chat-compose" onSubmit={ask}>
      <div>
        <textarea aria-label="Вопрос помощнику" placeholder="Сколько фото поступило сегодня?" rows={2}
          maxLength={500} value={draft} disabled={sending} onChange={event => setDraft(event.target.value)}/>
        <button type="submit" aria-label="Отправить вопрос" disabled={sending || !draft.trim()}>↵</button>
      </div>
      {error && <p role="alert">{error}</p>}
    </form>
  </section>;
}
