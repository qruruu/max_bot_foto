import { describe, expect, it } from 'vitest';
import { mergeMessages, messageDay, messageTime } from './operatorChatData';
import type { OperatorMessage } from './operatorChatData';

const message = (id: number, read_at: string | null = null): OperatorMessage => ({
  id, sender_id: 1, recipient_id: 2, client_id: String(id), body: 'Текст',
  created_at: '2026-10-16T22:00:00Z', read_at,
});

describe('operator conversations', () => {
  it('merges polling, a send response and older pages without duplicating or reordering messages', () => {
    const sent = mergeMessages([message(3)], [message(5)]);
    const polled = mergeMessages(sent, [message(4), message(5)]);
    const result = mergeMessages(polled, [message(1), message(2)]);
    expect(result.map(item => item.id)).toEqual([1, 2, 3, 4, 5]);
  });
  it('accepts an updated read receipt when the same message is returned again', () => {
    const result = mergeMessages([message(1)], [message(1, '2026-10-17T01:00:00Z')]);
    expect(result).toHaveLength(1);
    expect(result[0].read_at).toBe('2026-10-17T01:00:00Z');
  });
  it('displays message days and times in the service timezone across midnight', () => {
    expect(messageTime(message(1).created_at, 'Asia/Yekaterinburg')).toBe('03:00');
    expect(messageDay(message(1).created_at, 'Asia/Yekaterinburg')).toContain('17 октября');
  });
});
