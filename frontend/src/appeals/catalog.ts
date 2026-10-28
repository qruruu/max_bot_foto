import type { MultiPolygon, Polygon } from 'geojson';
import type { AppealForm } from './drafts';

export type PublicOrganization = {id: string; name: string; city: string; color: string;
  work_types: {code: string; name: string}[];
  addresses?: {id: string; label: string; district_id: number}[];
  territories: {id: number; name: string; geometry: MultiPolygon | Polygon}[]};
export type AppealCatalog = {organizations: PublicOrganization[]; yandex_maps_api_key: string};

export function recipientFor(form: AppealForm, catalog: AppealCatalog | null) {
  return catalog?.organizations.find(item => item.id === form.organization_id && item.city === form.city) || null;
}
export function validRecipient(form: AppealForm, catalog: AppealCatalog | null) {
  return form.category !== 'DRAIN_CLEANING' && !!recipientFor(form, catalog)?.work_types.some(work => work.code === form.category);
}

/** Keep valid choices, fill sole options, and discard recipients no longer in the catalog. */
export function availableRecipient(form: AppealForm, catalog: AppealCatalog): AppealForm {
  const cities = [...new Set(catalog.organizations.map(item => item.city))];
  const city = cities.includes(form.city) ? form.city : cities.length === 1 ? cities[0] : '';
  const organizations = catalog.organizations.filter(item => item.city === city);
  const organization = organizations.find(item => item.id === form.organization_id)
    || (organizations.length === 1 ? organizations[0] : undefined);
  const works = organization?.work_types.filter(work => work.code !== 'DRAIN_CLEANING') || [];
  const sameRecipient = city === form.city && organization?.id === form.organization_id;
  const category = sameRecipient && works.some(item => item.code === form.category) ? form.category
    : works.length === 1 ? works[0].code : '';
  const organization_id = organization?.id || '';
  const addresses = organization?.addresses || [];
  const address = sameRecipient && addresses.find(item => item.id === form.address_id)
    || (addresses.length === 1 ? addresses[0] : undefined);
  const address_id = address?.id || '', addressLabel = address?.label || '';
  const sameAddress = sameRecipient && address_id === form.address_id;
  return city === form.city && organization_id === form.organization_id && category === form.category
    && address_id === form.address_id && addressLabel === form.address ? form
    : {...form, city, organization_id, category, address_id, address: addressLabel,
      latitude: sameAddress ? form.latitude : null, longitude: sameAddress ? form.longitude : null};
}
