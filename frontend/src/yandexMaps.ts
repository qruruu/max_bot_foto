import type { MultiPolygon, Polygon, Position } from 'geojson';

export type Coordinates = number[][][];
export interface YPolygon {
  geometry: { getCoordinates(): Coordinates; getBounds(): number[][] | null };
  editor: { startDrawing(): void; stopDrawing(): void; startEditing(): void; stopEditing(): void };
  events: { add(name: string, callback: () => void): void };
}
export interface YMap {
  geoObjects: { add(object: YPolygon): void; remove(object: YPolygon): void; getBounds(): number[][] | null };
  setBounds(bounds: number[][], options?: Record<string, unknown>): void;
  destroy(): void;
}
export interface YMaps {
  ready(callback: () => void): void;
  Map: new (container: HTMLElement, state: Record<string, unknown>, options?: Record<string, unknown>) => YMap;
  Polygon: new (coordinates: Coordinates, properties?: Record<string, unknown>, options?: Record<string, unknown>) => YPolygon;
}
declare global { interface Window { ymaps?: YMaps } }
let loading: Promise<YMaps> | null = null;
export function loadYandexMaps(key: string): Promise<YMaps> {
  if (!key) return Promise.reject(new Error('Для карты укажите YANDEX_MAPS_API_KEY в настройках сервера.'));
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    const timer = window.setTimeout(() => { loading = null; script.remove(); reject(new Error('Не удалось загрузить Яндекс.Карты. Проверьте ключ и подключение.')); }, 25000);
    // longlat deliberately matches GeoJSON/PostGIS; no hidden coordinate reversal.
    script.src = 'https://api-maps.yandex.ru/2.1.79/?' + new URLSearchParams({ apikey: key, lang: 'ru_RU', coordorder: 'longlat', csp: 'true' });
    script.async = true;
    script.onload = () => { if (window.ymaps) window.ymaps.ready(() => { window.clearTimeout(timer); resolve(window.ymaps!); }); };
    script.onerror = () => { window.clearTimeout(timer); script.remove(); loading = null; reject(new Error('Не удалось подключить Яндекс.Карты.')); };
    document.head.appendChild(script);
  });
  return loading;
}
export function polygonsOf(geometry: Polygon | MultiPolygon): Position[][][] {
  return geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
}
export function closedPolygon(coordinates: Coordinates): Coordinates {
  return coordinates.map(ring => {
    const copy = ring.map(point => point.slice(0,2));
    if (copy.length < 3) throw new Error('В каждой границе должно быть минимум три вершины.');
    const first=copy[0], last=copy[copy.length-1];
    if (first[0]!==last[0] || first[1]!==last[1]) copy.push([...first]);
    return copy;
  });
}
export function escapeMapLabel(text: string): string {
  return text.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!));
}
