// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import PhotoMap from './PhotoMap';

const {useApp} = vi.hoisted(() => ({useApp: vi.fn()}));
vi.mock('./App', () => ({useApp, useFilters: () => ({filters: {}, change: vi.fn()})}));
vi.mock('./FilterBar', () => ({default: () => null}));
vi.mock('./PhotoMapPanel', () => ({
  default: ({previewMarkers}: {previewMarkers: boolean}) => <output>{String(previewMarkers)}</output>,
}));

it.each([true, false])('only toggles the preview marker mode for the owner (%s)', async owner => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  useApp.mockReturnValue({user: {is_platform_owner: owner}, meta: {yandex_maps_api_key: '', timezone: 'Asia/Yekaterinburg'}});
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {value: scroll, configurable: true});
  sessionStorage.clear();
  const toggle = (target: EventTarget = window) => target.dispatchEvent(new KeyboardEvent('keydown', {code: 'KeyZ', ctrlKey: true, bubbles: true}));
  try {
    await act(async () => root.render(<MemoryRouter><PhotoMap/></MemoryRouter>));
    expect(container.querySelector('output')?.textContent).toBe('false');
    const input = document.createElement('input');
    container.append(input);
    await act(async () => {toggle(input);});
    expect(container.querySelector('output')?.textContent).toBe('false');
    await act(async () => {toggle();});
    expect(container.querySelector('output')?.textContent).toBe(String(owner));
    await act(async () => {toggle();});
    expect(container.querySelector('output')?.textContent).toBe('false');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    sessionStorage.clear();
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
    vi.unstubAllGlobals();
  }
});
