import { describe, expect, it } from 'vitest';
import { closedPolygon, escapeMapLabel, loadYandexMaps, polygonsOf } from './yandexMaps';

describe('Yandex map geometry', () => {
  it('preserves longitude/latitude, multiple parts and holes', () => {
    const outer = [[72,61],[73,61],[73,62],[72,61]];
    const hole = [[72.1,61.1],[72.2,61.1],[72.2,61.2],[72.1,61.1]];
    const part = [outer,hole];
    expect(polygonsOf({type:'MultiPolygon',coordinates:[part,[outer]]})).toEqual([part,[outer]]);
    expect(polygonsOf({type:'Polygon',coordinates:part})).toEqual([part]);
    expect(closedPolygon(part)).toEqual(part);
  });
  it('closes drawn rings without mutating source coordinates', () => {
    const input=[[[72,61],[73,61],[73,62]]];
    expect(closedPolygon(input)[0]).toEqual([[72,61],[73,61],[73,62],[72,61]]);
    expect(input[0]).toHaveLength(3);
    expect(()=>closedPolygon([[[72,61],[73,61]]])).toThrow();
  });
  it('escapes district titles passed to map HTML hints', () => {
    expect(escapeMapLabel('<img src=x onerror="x">&')).toBe('&lt;img src=x onerror=&quot;x&quot;&gt;&amp;');
  });
  it('reports a missing map key before requesting any external script', async () => {
    await expect(loadYandexMaps('')).rejects.toThrow('YANDEX_MAPS_API_KEY');
  });
});
