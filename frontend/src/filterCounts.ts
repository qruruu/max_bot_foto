import type { FilterFacet } from './types';

export function filterOptionLabel(label: string, facet?: FilterFacet, value?: string): string {
  if (!facet) return label;
  const count = value === undefined ? facet.total : facet.values[value] ?? 0;
  return `${label} (${count.toLocaleString('ru-RU')})`;
}
