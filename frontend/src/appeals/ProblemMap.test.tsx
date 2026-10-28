// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ProblemMap from './ProblemMap';
import { coversPoint } from './geometry';
import { loadYandexMaps } from '../yandexMaps';
import type { YMapEvent, YMaps } from '../yandexMaps';
import type { PublicOrganization } from './catalog';

vi.mock('../yandexMaps', async () => ({...await vi.importActual('../yandexMaps'), loadYandexMaps: vi.fn()}));
const organization: PublicOrganization = {id: 'one', name: 'Организация', city: 'Сургут', color: '#2563eb', work_types: [],
  territories: [{id: 1, name: 'Территория', geometry: {type: 'Polygon', coordinates: [
    [[72, 61], [73, 61], [73, 62], [72, 62], [72, 61]],
    [[72.7, 61.7], [72.8, 61.7], [72.8, 61.8], [72.7, 61.8], [72.7, 61.7]],
  ]}}]};
let root: Root, element: HTMLDivElement, mapClick: (event: YMapEvent) => void, polygonClick: (event: YMapEvent) => void;
const destroy = vi.fn(), setCoordinates = vi.fn(), choose = vi.fn();
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
class FakeMap {
  events = {add: (_name: string, handler: typeof mapClick) => {mapClick = handler;}};
  geoObjects = {add: vi.fn(), remove: vi.fn(), getBounds: vi.fn()};
  setBounds = vi.fn(); destroy = destroy;
}
class FakePolygon {events = {add: (_name: string, handler: typeof polygonClick) => {polygonClick = handler;}};}
class FakeMarker {geometry = {setCoordinates};}
beforeEach(() => {
  vi.clearAllMocks(); (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
  vi.mocked(loadYandexMaps).mockResolvedValue({Map: FakeMap, Polygon: FakePolygon, Placemark: FakeMarker} as unknown as YMaps);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});
async function render(disabled = false, point: [number, number] | null = null) {
  await act(async () => {root.render(<ProblemMap organization={organization} districtId={1} apiKey="key" disabled={disabled} point={point} onPoint={choose}/>); await tick();});
}
const event = (coords: number[]) => ({get: () => coords});

it('accepts a tap on the map or polygon, keeps longitude/latitude order and rejects territory holes', async () => {
  await render();
  await act(async () => mapClick(event([72.6, 61.1])));
  expect(choose).toHaveBeenCalledWith([72.6, 61.1]);
  choose.mockClear();
  await act(async () => polygonClick(event([72.75, 61.75])));
  expect(choose).not.toHaveBeenCalled(); expect(element.textContent).toContain('внутри выделенной территории');
  await act(async () => mapClick(event([70, 50]))); expect(choose).not.toHaveBeenCalled();
  await render(true); await act(async () => mapClick(event([72.6, 61.1]))); expect(choose).not.toHaveBeenCalled();
});

it('updates the selected marker without rebuilding the map', async () => {
  await render(); await render(false, [72.6, 61.1]);
  expect(setCoordinates).toHaveBeenCalledWith([72.6, 61.1]); expect(destroy).not.toHaveBeenCalled();
});

it('shows retry when maps fail and retains the requirement to choose a place', async () => {
  vi.mocked(loadYandexMaps).mockRejectedValueOnce(new Error('offline'));
  await render(); expect(element.textContent).toContain('Для обращения нужно выбрать место');
  await act(async () => {element.querySelector<HTMLButtonElement>('button')!.click(); await tick();});
  expect(element.querySelector('[role=alert]')).toBeNull(); expect(loadYandexMaps).toHaveBeenCalledTimes(2);
});

it('matches coverage rules for polygon edges, holes and disconnected areas', () => {
  const geometry = organization.territories[0].geometry;
  expect(coversPoint(geometry, [72, 61])).toBe(true);
  expect(coversPoint(geometry, [72.7, 61.75])).toBe(true);
  expect(coversPoint(geometry, [72.75, 61.75])).toBe(false);
  expect(coversPoint(geometry, [72.6, NaN])).toBe(false);
  expect(coversPoint({type: 'MultiPolygon', coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[72, 61], [73, 61], [73, 62], [72, 61]]]]}, [72.9, 61.1])).toBe(true);
});
