import { expect, it } from 'vitest';
import { draftIsFresh, EMPTY_FORM, hasDraftContent } from './drafts';

it('expires local personal data after a day and rejects a corrupt timestamp', () => {
  const now = Date.now(); expect(draftIsFresh(now - 1000, now)).toBe(true);
  expect(draftIsFresh(now - 24 * 3600_000, now)).toBe(false);
  expect(draftIsFresh(NaN, now)).toBe(false); expect(draftIsFresh(now + 3600_000, now)).toBe(false);
});
it('preserves an unfinished form or pending send and clears an empty form', () => {
  expect(hasDraftContent(EMPTY_FORM, [], false)).toBe(false);
  expect(hasDraftContent({...EMPTY_FORM, address: 'Ленина, 10'}, [], false)).toBe(true);
  expect(hasDraftContent(EMPTY_FORM, [], true)).toBe(true);
});
