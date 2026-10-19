import type { FilterFacet } from './types';

export function filterOptionLabel(label: string, facet?: FilterFacet, value?: string): string {
  if (!facet) return label;
  const count = value === undefined ? facet.total : facet.values[value] ?? 0;
  return `${label} (${count.toLocaleString('ru-RU')})`;
}

export function senderFilterOptions(facet?: FilterFacet, selected = '') {
  const options = (facet?.options || []).map(sender => ({
    value: sender.value,
    name: sender.name ? `${sender.name} · ID ${sender.value}` : `ID ${sender.value}`,
  }));
  // Keep the active selection visible while loading or when other filters leave it with zero photos.
  if (selected && selected !== '0' && !options.some(option => option.value === selected)) {
    options.push({value: selected, name: `ID ${selected}`});
  }
  return options;
}
