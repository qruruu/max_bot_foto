export type NewsScreenshot = {src: string; alt: string; caption: string; width: number; height: number};
export type NewsSection = {
  title: string;
  paragraphs: string[];
  steps: string[];
  screenshots: NewsScreenshot[];
};
export type NewsPost = {
  slug: string;
  publishedAt: string;
  category: string;
  title: string;
  summary: string;
  sections: NewsSection[];
};
export type NewsSummary = Omit<NewsPost, 'sections'>;

export function newsDate(value: string): string {
  return new Date(value + 'T12:00:00Z').toLocaleDateString('ru-RU', {day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
}
