import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { ChatMessage } from './ChatPanel';

export const assistantKey = 'danya';
export const assistantName = 'Даня ИИ';
export const assistantQuestionLimit = 500;
export const assistantExample = 'Сколько фото поступило сегодня?';

export default function useLocalAssistantChat() {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  function changeDraft(value: string) {
    setDraft(value);
    setError('');
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const question = draft.trim();
    if (!question || sending) return;

    const sentAt = new Date().toISOString();
    setSending(true);
    setError('');
    try {
      const { answer } = await api<{ answer: string }>('/local-assistant/question', 'POST', { question });
      const answeredAt = new Date().toISOString();
      setMessages(previous => [
        ...previous,
        { id: previous.length + 1, body: question, outgoing: true, created_at: sentAt, read: true },
        { id: previous.length + 2, body: answer, outgoing: false, created_at: answeredAt, read: false },
      ]);
      setDraft('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить ответ.');
    } finally {
      setSending(false);
    }
  }

  return { draft, messages, sending, error, changeDraft, send };
}
