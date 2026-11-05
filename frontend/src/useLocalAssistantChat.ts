import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { ChatMessage } from './ChatPanel';
import type { AdminTaskDraft } from './appeals/adminTaskData';
import useAssistantTask from './useAssistantTask';

type DateContext = 'ago' | 'last';
type AssistantResponse = { answer: string; date_context?: DateContext | null; task?: AdminTaskDraft };

export const assistantKey = 'danya';
export const assistantName = 'Даня ИИ';
export const assistantQuestionLimit = 500;
export const assistantExample = 'Сколько фото поступило сегодня?';

export default function useLocalAssistantChat(today: string) {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [dateContext, setDateContext] = useState<DateContext>();

  function append(reply: string, question?: string, sentAt = new Date().toISOString()) {
    const answeredAt = new Date().toISOString();
    setMessages(previous => {
      const id = previous.length + 1;
      const answer = {body: reply, outgoing: false, created_at: answeredAt, read: false};
      return question ? [
        ...previous,
        {id, body: question, outgoing: true, created_at: sentAt, read: true},
        {id: id + 1, ...answer},
      ] : [...previous, {id, ...answer}];
    });
  }
  const task = useAssistantTask(today, append);

  function changeDraft(value: string) {
    setDraft(value);
    setError('');
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const question = draft.trim();
    if (!question || sending) return;

    if (task.step) {
      if (task.reply(question)) setDraft('');
      return;
    }

    const sentAt = new Date().toISOString();
    setSending(true);
    setError('');
    try {
      const response = await api<AssistantResponse>('/local-assistant/question', 'POST', {
        question,
        ...(messages.length && {history: messages.slice(-8).map(message => ({
          role: message.outgoing ? 'user' : 'assistant', content: message.body.slice(0, 4000),
        }))}),
        ...(dateContext && {date_context: dateContext}),
      });
      setDateContext(response.date_context ?? undefined);
      if (response.task) await task.begin(response.task, question);
      else append(response.answer, question, sentAt);
      setDraft('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить ответ.');
    } finally {
      setSending(false);
    }
  }

  return {draft, messages, sending, error: task.error || error, task, changeDraft, send};
}
