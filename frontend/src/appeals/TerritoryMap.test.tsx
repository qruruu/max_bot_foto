// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import TerritoryMap from './TerritoryMap';
import { loadYandexMaps } from '../yandexMaps';
import type { YMaps } from '../yandexMaps';
import type { PublicOrganization } from './catalog';

vi.mock('../yandexMaps', async () => ({...await vi.importActual('../yandexMaps'), loadYandexMaps: vi.fn()}));
let root: Root, element: HTMLDivElement, shapes: FakePolygon[];
const ring = [[72, 61], [73, 61], [73, 62], [72, 61]];
const organizations: PublicOrganization[] = [
  {id: 'one', name: '<Первая>', city: 'Сургут', color: '#2563eb', work_types: [], territories: [{id: 1, name: 'Сквер', geometry: {type: 'MultiPolygon', coordinates: [[ring]]}}]},
  {id: 'two', name: 'Вторая', city: 'Сургут', color: '#d97706', work_types: [], territories: [{id: 1, name: 'Двор', geometry: {type: 'MultiPolygon', coordinates: [[ring]]}}]},
];
class FakePolygon {
  click = () => {};
  events = {add: (_name: string, callback: () => void) => {this.click = callback;}};
  constructor(public coordinates: number[][][], public properties: Record<string, string>, public options: Record<string, unknown>) {shapes.push(this);}
}
const destroy = vi.fn(), remove = vi.fn(), bounds = vi.fn();
class FakeMap {
  constructor(container: HTMLElement) {if (container.hidden) throw new Error('Map container is hidden');}
  geoObjects = {add: vi.fn(), remove, getBounds: () => [[72, 61], [73, 62]]};
  setBounds = bounds;
  destroy = destroy;
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
beforeEach(() => {
  vi.clearAllMocks(); shapes = [];
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
  vi.mocked(loadYandexMaps).mockResolvedValue({Map: FakeMap, Polygon: FakePolygon} as unknown as YMaps);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});

it('draws different organization colors and selects the recipient by tapping its territory', async () => {
  const choose = vi.fn();
  await act(async () => {root.render(<TerritoryMap organizations={organizations} selected="one" apiKey="public-key" disabled={false} onChoose={choose}/>); await tick();});
  expect(shapes.map(shape => shape.options.fillColor)).toEqual(['#2563eb', '#d97706']);
  expect(shapes[0].options.strokeWidth).toBe(4); expect(shapes[0].coordinates).toEqual([ring]);
  expect(shapes[0].properties.hintContent).toContain('&lt;Первая&gt;');
  expect(bounds).toHaveBeenCalled();
  shapes[1].click(); expect(choose).toHaveBeenCalledWith('two');
  await act(async () => root.render(<TerritoryMap organizations={organizations} selected="one" apiKey="public-key" disabled onChoose={choose}/>));
  choose.mockClear(); shapes.at(-1)!.click(); expect(choose).not.toHaveBeenCalled();
});

it('keeps a selectable legend when maps cannot load and never requires a manual point', async () => {
  vi.mocked(loadYandexMaps).mockRejectedValue(new Error('Карта недоступна'));
  const choose = vi.fn();
  await act(async () => {root.render(<TerritoryMap organizations={organizations} selected="" apiKey="" disabled={false} onChoose={choose}/>); await tick();});
  expect(element.textContent).toContain('Организацию можно выбрать');
  await act(async () => element.querySelectorAll<HTMLButtonElement>('.citizen-map-legend button')[1].click());
  expect(choose).toHaveBeenCalledWith('two');
  expect(element.querySelector('input')).toBeNull();
});

it('shows the map container before retrying with an already loaded SDK', async () => {
  vi.mocked(loadYandexMaps).mockRejectedValueOnce(new Error('Сеть недоступна'))
    .mockResolvedValue({Map: FakeMap, Polygon: FakePolygon} as unknown as YMaps);
  await act(async () => {root.render(<TerritoryMap organizations={organizations} selected="" apiKey="public-key" disabled={false} onChoose={() => {}}/>); await tick();});
  expect(element.querySelector<HTMLElement>('.citizen-territory-map')!.hidden).toBe(true);
  await act(async () => {element.querySelector<HTMLButtonElement>('.citizen-map-error button')!.click(); await tick();});
  expect(element.querySelector<HTMLElement>('.citizen-territory-map')!.hidden).toBe(false);
  expect(element.querySelector('.citizen-map-error')).toBeNull(); expect(shapes).toHaveLength(2);
});
