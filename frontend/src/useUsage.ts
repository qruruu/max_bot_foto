import { useEffect } from 'react';
export type UsagePage = 'home' | 'login' | 'photos' | 'photo_map' | 'days' | 'review' | 'reports' | 'messages' | 'appeals' | 'appeal_form' | 'appeal_sent' | 'settings' | 'news' | 'other';
declare global {interface Window {MetkaUsage?: {page(product: 'metka' | 'signal', page: UsagePage, key?: string): void; event(product: 'metka' | 'signal', page: UsagePage): void}}}
export function useUsage(product: 'metka' | 'signal', page: UsagePage, key: string = page, enabled = true) {
  useEffect(() => {if (enabled) window.MetkaUsage?.page(product, page, key);}, [product, page, key, enabled]);
}
export function metkaPage(path: string): UsagePage {
  const first = path.split('/').filter(Boolean)[0] || 'home';
  return ({home:'home', photos:'photos', 'photo-map':'photo_map', days:'days', review:'review',
    'daily-reports':'reports', messages:'messages', appeals:'appeals', settings:'settings', news:'news'} as Record<string, UsagePage>)[first] || 'other';
}
