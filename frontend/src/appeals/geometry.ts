import type { MultiPolygon, Polygon, Position } from 'geojson';
import { polygonsOf } from '../yandexMaps';

function ringPosition(point: Position, ring: Position[]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[j], b = ring[i];
    const cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0]);
    if (Math.abs(cross) < 1e-12 && point[0] >= Math.min(a[0], b[0]) && point[0] <= Math.max(a[0], b[0])
      && point[1] >= Math.min(a[1], b[1]) && point[1] <= Math.max(a[1], b[1])) return 0;
    if ((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside ? 1 : -1;
}

/** Match ST_Covers: include boundaries, exclude the interior of holes. */
export function coversPoint(geometry: Polygon | MultiPolygon, point: [number, number]) {
  return point.every(Number.isFinite) && polygonsOf(geometry).some(polygon => polygon.length > 0
    && ringPosition(point, polygon[0]) >= 0 && !polygon.slice(1).some(hole => ringPosition(point, hole) > 0));
}
