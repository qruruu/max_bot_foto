// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealLocation from './AppealLocation';
import { loadYandexMaps } from '../yandexMaps';
import type { YMaps } from '../yandexMaps';

vi.mock('../yandexMaps', () => ({loadYandexMaps: vi.fn()}));
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});

it('shows the saved point in longitude-latitude order and destroys the map on unmount', async () => {
  const destroy = vi.fn(), add = vi.fn(), points: number[][] = [], states: Record<string, unknown>[] = [];
  vi.mocked(loadYandexMaps).mockResolvedValue({
    Map: class {
      geoObjects = {add}; destroy = destroy;
      constructor(_target: HTMLElement, state: Record<string, unknown>) {states.push(state);}
    },
    Placemark: class {constructor(point: number[]) {points.push(point);}},
  } as unknown as YMaps);
  await act(async () => {root.render(<AppealLocation longitude={72.6} latitude={61.1} apiKey="public-map-key"/>); await tick();});
  expect(states[0]).toMatchObject({center: [72.6, 61.1], zoom: 17});
  expect(points).toEqual([[72.6, 61.1]]); expect(add).toHaveBeenCalledTimes(1);
  const link = element.querySelector<HTMLAnchorElement>('a')!;
  expect(new URL(link.href).searchParams.get('pt')).toBe('72.6,61.1');
  expect(element.textContent).not.toContain('Загружаем карту');
  await act(async () => {root.render(<span/>);});
  expect(destroy).toHaveBeenCalledTimes(1);
});

it('does not invent a map point when coordinates are missing', async () => {
  await act(async () => {root.render(<AppealLocation apiKey="public-map-key"/>);});
  expect(loadYandexMaps).not.toHaveBeenCalled();
  expect(element.textContent).toContain('Место на карте не указано'); expect(element.querySelector('a')).toBeNull();
});
