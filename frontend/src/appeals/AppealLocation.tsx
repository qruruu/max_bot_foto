import { useEffect, useRef, useState } from 'react';
import { ExternalLink, MapPin, RefreshCw } from 'lucide-react';
import { loadYandexMaps } from '../yandexMaps';
import type { YMap } from '../yandexMaps';

export default function AppealLocation({longitude, latitude, apiKey}: {longitude?: number; latitude?: number; apiKey: string}) {
  const target = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(''), [retry, setRetry] = useState(0), [ready, setReady] = useState(false);
  const located = longitude != null && latitude != null && Number.isFinite(longitude) && Number.isFinite(latitude);
  useEffect(() => {
    if (!located || !apiKey) return;
    let cancelled = false, map: YMap | undefined, observer: ResizeObserver | undefined;
    setError(''); setReady(false);
    loadYandexMaps(apiKey).then(sdk => {
      if (cancelled || !target.current) return;
      map = new sdk.Map(target.current, {center: [longitude, latitude], zoom: 17, controls: ['zoomControl', 'fullscreenControl']}, {suppressMapOpenBlock: true});
      if (sdk.Placemark) map.geoObjects.add(new sdk.Placemark([longitude!, latitude!], {iconCaption: 'Место проблемы'}, {preset: 'islands#redDotIcon'}));
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(() => {
          const box = target.current?.getBoundingClientRect();
          if (box?.width && box.height) map?.container?.fitToViewport();
        });
        observer.observe(target.current);
      }
      setReady(true);
    }).catch(reason => {if (!cancelled) setError(reason.message);});
    return () => {cancelled = true; observer?.disconnect(); map?.destroy();};
  }, [located, longitude, latitude, apiKey, retry]);
  const link = located ? 'https://yandex.ru/maps/?' + new URLSearchParams({pt: longitude + ',' + latitude, z: '18', l: 'map'}) : '';
  return <section className="panel appeal-location-panel" aria-label="Место проблемы на карте">
    <header><h3>Место проблемы на карте</h3>{located && <a href={link} target="_blank" rel="noreferrer" aria-label="Открыть место проблемы в Яндекс.Картах"><ExternalLink size={15}/></a>}</header>
    {located ? <div className="appeal-location-view"><div ref={target} className="appeal-location-map" hidden={!!error || !apiKey}/>
      {(!ready || error || !apiKey) && <div className="appeal-location-placeholder"><MapPin size={26}/><p>{error ? 'Не удалось загрузить карту.' : apiKey ? 'Загружаем карту…' : 'Точка обращения сохранена.'}</p>
        {error ? <button type="button" onClick={() => setRetry(value => value + 1)}><RefreshCw size={14}/>Повторить</button> : !apiKey && <a href={link} target="_blank" rel="noreferrer">Открыть место на карте</a>}</div>}
    </div> : <p className="appeal-location-empty"><MapPin size={22}/>Место на карте не указано</p>}
  </section>;
}
