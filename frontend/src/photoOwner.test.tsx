import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import PhotoNumberSearch, { findPhotoByNumber, photoNumber } from './PhotoNumberSearch';
import PhotoProductionControl from './PhotoProductionControl';
import { photoListBackLink } from './photoNavigation';
import type { Photo } from './types';

afterEach(() => vi.unstubAllGlobals());

describe('photo number search', () => {
  it('accepts displayed numbers, ignores whitespace and rejects invalid identifiers', () => {
    for (const value of ['195', '#195', ' № 195 ', '00195']) expect(photoNumber(value)).toBe(195);
    for (const value of ['', '0', '-1', '1.5', '1e3', '195 фото', '2147483648', '<script>']) expect(photoNumber(value)).toBeNull();
  });
  it('opens exactly one photo in the current organization, without date or list filters', async () => {
    vi.stubGlobal('window', {location: {pathname: '/org/11111111-1111-4111-8111-111111111111/photos'}});
    vi.stubGlobal('document', {cookie: ''});
    const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({id: 195})});
    vi.stubGlobal('fetch', fetch);
    expect(await findPhotoByNumber('#195')).toBe(195);
    expect(fetch.mock.calls[0][0]).toBe('/org/11111111-1111-4111-8111-111111111111/api/photos/195');
    expect(fetch.mock.calls[0][1].method).toBe('GET');
    await expect(findPhotoByNumber('1e3')).rejects.toThrow('Введите номер');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('explains the owner scope and preserves a useful return to the all-dates list', () => {
    expect(renderToStaticMarkup(<PhotoNumberSearch owner open={() => {}}/>)).toContain('рабочих и тестовых');
    expect(renderToStaticMarkup(<PhotoNumberSearch owner={false} open={() => {}}/>)).toContain('доступных вам фото текущего режима');
    const link = photoListBackLink(195, new URLSearchParams('by_number=1&all_dates=1'));
    expect(link).toBe('/photos?all_dates=1&anchor_id=195');
  });
});

const testPhoto = {id: 195, version: 2, cohort: 'test', analyzed_at: '2026-10-16T12:00:00Z', status: 'ACCEPTED'} as Photo;
const callbacks = {disabled: false, onBusy: () => {}, onPromoted: async () => {}, openExisting: () => {}};

describe('owner-only production control', () => {
  it('never offers a promotion to a company administrator or operator without the owner flag', () => {
    expect(renderToStaticMarkup(<PhotoProductionControl {...callbacks} owner={false} photo={testPhoto}/>)).toBe('');
    expect(renderToStaticMarkup(<PhotoProductionControl {...callbacks} owner photo={{...testPhoto, cohort: 'production'}}/>)).toBe('');
    expect(renderToStaticMarkup(<PhotoProductionControl {...callbacks} owner photo={testPhoto}/>)).toContain('Сделать рабочим');
  });
  it('offers the existing working photo instead of creating a duplicate', () => {
    const markup = renderToStaticMarkup(<PhotoProductionControl {...callbacks} owner photo={{...testPhoto, production_duplicate_id: 706}}/>);
    expect(markup).toContain('Открыть рабочее фото №706');
    expect(markup).not.toContain('Сделать рабочим');
  });
  it('requires the initial image processing to have completed', () => {
    const markup = renderToStaticMarkup(<PhotoProductionControl {...callbacks} owner photo={{...testPhoto, analyzed_at: null}}/>);
    expect(markup).toContain('disabled=""');
    expect(markup).toContain('после первичной обработки');
  });
});
