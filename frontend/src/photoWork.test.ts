import { afterEach, describe, expect, it, vi } from 'vitest';
import { canEditPhoto, updatePhotoDefect, workTypeLabel } from './photoWork';
import type { User } from './types';

afterEach(() => vi.unstubAllGlobals());

describe('photo defect marker', () => {
  it('decorates any work label without replacing its category', () => {
    for (const name of ['УРНЫ', 'ГАЗОН', 'ПЛОЩАДКИ']) {
      expect(workTypeLabel(name, true)).toBe(name + ' · НЕИСПРАВНОСТЬ');
      expect(workTypeLabel(name, false)).toBe(name);
    }
  });

  it.each([true, false])('saves only the marker and concurrency version: %s', async checked => {
    vi.stubGlobal('document', {cookie: ''});
    const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({id: 7, is_defect: checked, version: 4})});
    vi.stubGlobal('fetch', fetch);
    expect(await updatePhotoDefect({id: 7, version: 3}, checked)).toMatchObject({is_defect: checked, version: 4});
    const [url, request] = fetch.mock.calls[0];
    expect(url).toBe('/api/photos/7');
    expect(request.method).toBe('PATCH');
    expect(JSON.parse(request.body)).toEqual({version: 3, is_defect: checked});
  });

  it('limits editing to processed photos and users with edit permission', () => {
    const reader = {role: 'OPERATOR', permissions: ['photos_view']} as User;
    const editor = {...reader, permissions: ['photos_view', 'photos_edit']};
    const accepted = {analyzed_at: '2026-10-18T12:00:00Z', status: 'ACCEPTED'};
    expect(canEditPhoto(reader, accepted)).toBe(false);
    expect(canEditPhoto(editor, accepted)).toBe(true);
    expect(canEditPhoto(editor, {...accepted, analyzed_at: null})).toBe(false);
    for (const status of ['REJECTED', 'DUPLICATE', 'FORWARDED']) expect(canEditPhoto(editor, {...accepted, status})).toBe(false);
  });
});
