export const defaultSidebarOrder = [
  '/', '/news', '/photos', '/photo-map', '/review', '/days', '/spam', '/districts', '/appeals', '/messages',
  '/chats', '/work-types', '/users', '/audit', '/jobs', '/exchange', '/learning', '/daily-reports', '/inspectors',
] as const;

// Missing (new) sections are appended; invalid or repeated legacy entries are ignored.
export function normalizeSidebarOrder(value: unknown): string[] {
  const known = new Set<string>(defaultSidebarOrder);
  const saved = Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string' && known.has(id)) : [];
  return [...new Set([...saved, ...defaultSidebarOrder])];
}

export function sortSidebarLinks<T extends {to: string}>(links: T[], order: unknown): T[] {
  const positions = new Map(normalizeSidebarOrder(order).map((id, index) => [id, index]));
  // Only reorder the links already allowed by the application's permission checks.
  return [...links].sort((a, b) => (positions.get(a.to) ?? positions.size) - (positions.get(b.to) ?? positions.size));
}

export function moveSidebarItem(order: unknown, source: string, target: string, side: 'before' | 'after'): string[] {
  const result = normalizeSidebarOrder(order);
  if (source === target || !result.includes(source) || !result.includes(target)) return result;
  result.splice(result.indexOf(source), 1);
  result.splice(result.indexOf(target) + (side === 'after' ? 1 : 0), 0, source);
  return result;
}
