import { afterEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { api } from './api';
import { apiUrl, workspacePrefix, workspaceStorageKey, workspaceUrl } from './workspace';
import { OrganizationCard } from './Organizations';
import { mapPhotoFeature } from './photoMapData';
import Login, { signInDestination } from './Login';
import ConnectDisk from './ConnectDisk';
import type { User } from './types';

const id = '11111111-1111-4111-8111-111111111111';
const prefix = '/org/' + id;
afterEach(() => vi.unstubAllGlobals());

it('keeps all direct URLs and browser preferences in the selected company', () => {
  vi.stubGlobal('window', {location: {pathname: prefix + '/photos'}});
  expect(workspacePrefix()).toBe(prefix);
  expect(apiUrl('/export.xlsx')).toBe(prefix + '/api/export.xlsx');
  expect(workspaceUrl('/photos/1')).toBe(prefix + '/photos/1');
  expect(workspaceStorageKey('notifications:1')).toBe('notifications:1:' + id);
  expect(workspacePrefix('/photos/1')).toBe('');
  expect(workspacePrefix('/org/../../api')).toBe('');
});

it('uses only the company CSRF cookie for operators even if a global cookie remains', async () => {
  vi.stubGlobal('window', {location: {pathname: prefix + '/photos'}});
  vi.stubGlobal('document', {cookie: 'platform_csrf=unrelated; workspace_csrf=local%2Btoken'});
  const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({is_platform_owner: false})});
  vi.stubGlobal('fetch', fetch);
  await api('/auth/me');
  await api('/photos/1', 'PATCH', {version: 1});
  expect(fetch.mock.calls[1][0]).toBe(prefix + '/api/photos/1');
  expect(fetch.mock.calls[1][1].headers['X-CSRF-Token']).toBe('local+token');
});

it('uses the global CSRF token for the owner while retaining the selected company URL', async () => {
  vi.stubGlobal('window', {location: {pathname: prefix + '/photos'}});
  vi.stubGlobal('document', {cookie: 'platform_csrf=owner-token; workspace_csrf=operator-token'});
  const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({is_platform_owner: true, organization: {id}})});
  vi.stubGlobal('fetch', fetch);
  await api('/auth/me');
  await api('/work-types', 'POST', {name: 'Урны'});
  expect(fetch.mock.calls[1][0]).toBe(prefix + '/api/work-types');
  expect(fetch.mock.calls[1][1].headers['X-CSRF-Token']).toBe('owner-token');
});

it('builds scoped map links without trusting an arbitrary preview URL', () => {
  vi.stubGlobal('window', {location: {pathname: prefix + '/photo-map'}});
  const feature = mapPhotoFeature({id: 1, latitude: 61, longitude: 72, photo_date: null, photo_time: null,
    received_at: '2026-10-16T12:00:00Z', chat_name: 'Alpha', status: 'ACCEPTED', work_type_name: null,
    preview_url: 'https://other.invalid/private'}, {}, 'Asia/Yekaterinburg');
  expect(feature.properties.photoPreviewUrl).toBe(prefix + '/api/photos/1/preview');
  expect(feature.properties.balloonContentBody).toContain(prefix + '/photos/1?');
  expect(feature.properties.balloonContentBody).not.toContain('other.invalid');
});

it('shows the independent model and workspace link on an organization card', () => {
  const markup = renderToStaticMarkup(<OrganizationCard item={{id, name: 'Компания Alpha', slug: 'alpha',
    status: 'ACTIVE', url: prefix + '/', legacy: false, last_error: null,
    stats: {photos: 23, operators: 2, chats: 1, work_types: 0, model_ready: false}}} edit={() => {}} retry={() => {}}/>);
  expect(markup).toContain('Компания Alpha');
  expect(markup).toContain('Модель видов работ ещё не обучена');
  expect(markup).toContain('href="' + prefix + '/"');
  expect(markup).toContain('23');
  expect(markup).toContain('Тестовый режим');
});

it('shows production mode from the organization own settings', () => {
  const markup = renderToStaticMarkup(<OrganizationCard item={{id, name: 'Alpha', slug: 'alpha', status:'ACTIVE',
    url: prefix + '/', legacy:false, last_error:null, stats: {photos:0, operators:0, chats:0, work_types:0,
      model_ready:false, intake_cohort:'production'}}} edit={() => {}} retry={() => {}}/>);
  expect(markup).toContain('Рабочий режим');
  expect(markup).not.toContain('Тестовый режим');
});

it('offers one common sign-in and routes each role to its own home', () => {
  const markup = renderToStaticMarkup(<Login unified onLogin={() => {}}/>);
  expect(markup).toContain('ЕДИНЫЙ ВХОД');
  expect(markup).not.toContain('Кабинет владельца');
  expect(signInDestination({is_platform_owner:true} as User)).toBe('/');
  expect(signInDestination({organization:{id}} as User)).toBe(prefix + '/');
});

it('keeps connection credentials masked and explains shared company storage', () => {
  const markup = renderToStaticMarkup(<ConnectDisk onClose={() => {}} onConnected={() => {}}/>);
  expect(markup).toContain('type="password"');
  expect(markup).toContain('отдельных папках');
  expect(markup).toContain('нескольких организаций');
});
