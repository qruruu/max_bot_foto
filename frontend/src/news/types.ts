export type NewsScreenshot = {src: string; alt: string; caption: string; width?: number; height?: number};
export type NewsNode = {type: string; text?: string; attrs?: Record<string, unknown>; marks?: {type: string; attrs?: {href: string}}[]; content?: NewsNode[]};
export type NewsSnapshot = {title: string; summary: string; category: string; document: NewsNode; cover_id: string | null};
export type NewsPost = NewsSnapshot & {slug: string; publishedAt: string; cover_src?: string | null};
export type NewsSummary = Omit<NewsPost, 'document'>;
export type NewsArticle = {id: string; slug: string; version: number; draft: NewsSnapshot; published: NewsSnapshot | null; published_at: string | null; deleted_at: string | null; updated_at: string; author_name: string; has_changes: boolean};
export type NewsListItem = Omit<NewsArticle, 'draft' | 'published'> & {draft: Omit<NewsSnapshot, 'document'>; published: boolean};
export type NewsRevision = {id: string; version: number; action: string; author_name: string; created_at: string; snapshot: NewsSnapshot};
export type NewsAsset = {id: string; src: string; width: number; height: number};
export function newsDate(value: string): string {
  return new Date(value.slice(0,10) + 'T12:00:00Z').toLocaleDateString('ru-RU', {day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
}
export function newsAssetIds(document: NewsNode): string[] {
  return [...new Set([...(document.type === 'image' ? [String(document.attrs?.asset_id)] : []), ...(document.content || []).flatMap(newsAssetIds)])];
}
export function editorAssetUrl(id: string) { return '/api/platform/news/assets/' + encodeURIComponent(id); }
