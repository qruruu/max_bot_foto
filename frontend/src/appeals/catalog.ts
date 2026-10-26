import type { MultiPolygon, Polygon } from 'geojson';
import type { AppealForm } from './drafts';

export type PublicOrganization = {id: string; name: string; city: string; color: string;
  work_types: {code: string; name: string}[];
  territories: {id: number; name: string; geometry: MultiPolygon | Polygon}[]};
export type AppealCatalog = {organizations: PublicOrganization[]; yandex_maps_api_key: string};

export function recipientFor(form: AppealForm, catalog: AppealCatalog | null) {
  return catalog?.organizations.find(item => item.id === form.organization_id && item.city === form.city) || null;
}
export function validRecipient(form: AppealForm, catalog: AppealCatalog | null) {
  return !!recipientFor(form, catalog)?.work_types.some(work => work.code === form.category);
}
