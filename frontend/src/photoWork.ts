import { api } from './api';
import { hasPermission } from './permissions';
import type { Photo, PhotoEditResult, User } from './types';

export function workTypeLabel(name: string, isDefect: boolean): string {
  return isDefect ? `${name} · НЕИСПРАВНОСТЬ` : name;
}

export function canEditPhoto(user: User, photo: Pick<Photo, 'analyzed_at' | 'status'>): boolean {
  return hasPermission(user, 'photos_edit') && !!photo.analyzed_at && !['REJECTED', 'DUPLICATE', 'FORWARDED'].includes(photo.status);
}

export function updatePhotoDefect(photo: Pick<Photo, 'id' | 'version'>, checked: boolean): Promise<PhotoEditResult> {
  return api<PhotoEditResult>(`/photos/${photo.id}`, 'PATCH', {version: photo.version, is_defect: checked});
}
