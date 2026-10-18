import type { PermissionDefinition, User } from './types';

export function hasPermission(user: User, code: string): boolean {
  if (user.role !== 'ADMIN_OPERATOR' && user.allowed_chat_ids != null && ['exchange_manage', 'learning_manage'].includes(code)) return false;
  return user.role === 'ADMIN_OPERATOR' || !!user.permissions?.includes(code);
}

export function changePermission(selected: string[], code: string, enabled: boolean, catalog: PermissionDefinition[]): string[] {
  const definitions = new Map(catalog.map(item => [item.code, item]));
  const next = new Set(selected.filter(value => definitions.has(value)));
  function add(value: string) {
    if (next.has(value) || !definitions.has(value)) return;
    next.add(value);
    for (const prerequisite of definitions.get(value)!.requires) add(prerequisite);
  }
  if (enabled) add(code);
  else {
    next.delete(code);
    let changed = true;
    while (changed) {
      changed = false;
      for (const item of catalog) {
        if (next.has(item.code) && item.requires.some(required => !next.has(required))) {
          next.delete(item.code);
          changed = true;
        }
      }
    }
  }
  return catalog.filter(item => next.has(item.code)).map(item => item.code);
}
