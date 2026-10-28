import { useEffect, useRef, useState } from 'react';
import { MapPin, RefreshCw } from 'lucide-react';
import { escapeMapLabel, loadYandexMaps, polygonsOf } from '../yandexMaps';
import type { YMap, YMapEvent, YMarker } from '../yandexMaps';
import type { PublicOrganization } from './catalog';
import { coversPoint } from './geometry';

export default function ProblemMap({organization, organizations, districtId, apiKey, point, disabled, onPoint}: {
  organization: PublicOrganization; districtId: number; apiKey: string;
  organizations?: PublicOrganization[];
  point: [number, number] | null; disabled: boolean; onPoint: (point: [number, number]) => void;
}) {
  const element = useRef<HTMLDivElement>(null), map = useRef<YMap | null>(null), marker = useRef<YMarker | null>(null);
  const pick = useRef(onPoint), locked = useRef(disabled), currentPoint = useRef(point);
  pick.current = onPoint; locked.current = disabled; currentPoint.current = point;
  const [error, setError] = useState(''), [ready, setReady] = useState(false), [retry, setRetry] = useState(0);
  const [pointError, setPointError] = useState('');
  useEffect(() => {
    let active = true;
    setError(''); setReady(false);
    loadYandexMaps(apiKey).then(api => {
      if (!active || !element.current) return;
      const layer = new api.Map(element.current, {center: [72.6, 61.1], zoom: 12, controls: ['zoomControl', 'fullscreenControl']}, {suppressMapOpenBlock: true});
      map.current = layer;
      const click = (event: YMapEvent) => {
        const coordinates = event.get('coords');
        if (locked.current || !Array.isArray(coordinates) || coordinates.length !== 2 || !coordinates.every(Number.isFinite)) return;
        const area = organization.territories.find(item => item.id === districtId), point = coordinates as [number, number];
        if (!area || !coversPoint(area.geometry, point)) {setPointError('Выберите место внутри выделенной территории этого адреса.'); return;}
        setPointError(''); pick.current(point);
      };
      layer.events?.add('click', click);
      for (const owner of organizations || [organization]) for (const area of owner.territories) for (const coordinates of polygonsOf(area.geometry)) {
        const selected = owner.id === organization.id && area.id === districtId;
        const shape = new api.Polygon(coordinates, {hintContent: escapeMapLabel(owner.name + ' · ' + area.name)}, {
          fillColor: owner.color, fillOpacity: selected ? .24 : .06,
          strokeColor: owner.color, strokeWidth: selected ? 3 : 1, openBalloonOnClick: false,
        });
        shape.events.add('click', click); layer.geoObjects.add(shape);
      }
      const selected = organization.territories.find(area => area.id === districtId);
      if (selected) {
        const positions = polygonsOf(selected.geometry).flat(2);
        const bounds = [[Math.min(...positions.map(p => p[0])), Math.min(...positions.map(p => p[1]))],
          [Math.max(...positions.map(p => p[0])), Math.max(...positions.map(p => p[1]))]];
        layer.setBounds(bounds, {checkZoomRange: true, zoomMargin: 35});
      }
      if (api.Placemark) {
        const initial = currentPoint.current || [72.6, 61.1];
        marker.current = new api.Placemark(initial, {iconCaption: 'Место проблемы'}, {preset: 'islands#redDotIcon'});
        if (currentPoint.current) layer.geoObjects.add(marker.current);
      }
      setReady(true);
    }).catch(reason => {if (active) setError(reason.message);});
    return () => {active = false; map.current?.destroy(); map.current = null; marker.current = null;};
  }, [organization, organizations, districtId, apiKey, retry]);
  useEffect(() => {
    if (!ready || !marker.current || !map.current) return;
    map.current.geoObjects.remove(marker.current);
    if (point) {marker.current.geometry.setCoordinates(point); map.current.geoObjects.add(marker.current);}
  }, [point?.[0], point?.[1], ready]);
  return <section className="signal-location"><div className="signal-section-title"><MapPin size={19}/><h2>Где находится проблема?</h2></div>
    <p>Нажмите на нужное место в выделенной территории.</p>
    <div className="signal-map" ref={element} aria-label="Выберите место проблемы на карте" hidden={!!error}/>
    {!ready && !error && <p role="status">Загружаем карту…</p>}
    {error && <div className="citizen-error" role="alert"><p>Не удалось загрузить карту. Для обращения нужно выбрать место.</p><button type="button" onClick={() => setRetry(value => value + 1)}><RefreshCw size={16}/>Попробовать снова</button></div>}
    {pointError && <p className="citizen-error" role="alert">{pointError}</p>}
    <div className={'signal-point ' + (point ? 'ready' : '')}><MapPin size={17}/>{point ? 'Место отмечено. Можно описать проблему.' : 'Сначала отметьте место на карте'}</div>
    {organizations && organizations.length > 1 && <div className="signal-map-colors">{organizations.filter(item => item.territories.length).map(item => <span key={item.id}><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><circle cx="5" cy="5" r="5" fill={item.color}/></svg>{item.name}</span>)}</div>}
  </section>;
}
