import { describe, expect, it } from 'vitest';
import { mergeMessages, messageDay, messagePreview, messageTime, operatorPhotoLink } from './operatorChatData';
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


describe('forwarded photos', () => {
  it('shows the photo and the question in conversation previews, including photo-only messages', () => {
    const photo = {id: 48, available: true, preview_url: '/api/photos/48/preview'};
    expect(messagePreview({...message(1), body: 'Какой вид работ выбрать?', photo})).toBe('Фото #48 · Какой вид работ выбрать?');
    expect(messagePreview({...message(1), body: '', photo})).toBe('Фото #48');
    expect(messagePreview(message(1))).toBe('Текст');
  });
  it('links to the photo with the peer needed to return and answer', () => {
    expect(operatorPhotoLink(48, 2)).toBe('/photos/48?operator_chat=2');
  });
  it('preserves attachments and their availability when merging polling with pagination', () => {
    const current = {...message(1), photo: {id: 48, available: true, preview_url: '/api/photos/48/preview'}};
    const updated = {...current, photo: {...current.photo, available: false, preview_url: null}};
    expect(mergeMessages([current], [updated, message(2)])[0].photo).toEqual(updated.photo);
  });
});
