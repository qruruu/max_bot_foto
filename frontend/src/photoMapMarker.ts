import type { MapFeature, YMaps } from './yandexMaps';

const template = `<div class="map-photo-marker" role="img">
  <div class="map-photo-marker-frame">
    <svg class="map-photo-marker-fallback" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/>
      <circle cx="12" cy="13" r="3"/>
    </svg>
  </div>
  <span class="map-photo-marker-count" aria-hidden="true"></span>
</div>`;

export function createPhotoMarkerLayout(sdk: Pick<YMaps, 'templateLayoutFactory'>) {
  const Layout = sdk.templateLayoutFactory.createClass(template, {
    build() {
      Layout.superclass.build.call(this);
      const marker = this.getParentElement().querySelector<HTMLElement>('.map-photo-marker');
      if (!marker) return;
      const properties = this.getData().properties;
      const getProperty = (name: string): unknown => typeof properties.get === 'function'
        ? properties.get(name) : (properties as Record<string, unknown>)[name];
      const members = getProperty('geoObjects') as MapFeature[] | undefined;
      const count = members?.length || 0;
      marker.classList.toggle('map-photo-marker-cluster', count > 1);
      marker.setAttribute('aria-label', count > 1 ? `Фотографий рядом: ${count}` : String(getProperty('photoLabel') || 'Фотография'));
      const badge = marker.querySelector<HTMLElement>('.map-photo-marker-count')!;
      badge.textContent = count > 1 ? String(count) : '';

      // ObjectManager clusters contain the original JSON features. Show one available preview per cluster.
      const preview = members?.find(photo => photo.properties.photoPreviewUrl)?.properties.photoPreviewUrl
        || getProperty('photoPreviewUrl');
      if (typeof preview !== 'string' || !preview) return;
      const image = document.createElement('img');
      image.className = 'map-photo-marker-image';
      image.alt = '';
      image.draggable = false;
      image.loading = 'lazy';
      image.decoding = 'async';
      // Keep the camera placeholder if a local preview was removed or cannot be loaded.
      image.addEventListener('error', () => image.remove(), {once: true});
      image.src = preview;
      marker.querySelector('.map-photo-marker-frame')!.appendChild(image);
    },
  });
  return Layout;
}
