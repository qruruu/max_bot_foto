import { useEffect, useRef, useState } from 'react';
import { MapPin, RefreshCw } from 'lucide-react';
import { escapeMapLabel, loadYandexMaps, polygonsOf } from '../yandexMaps';
import type { YMap, YMaps, YPolygon } from '../yandexMaps';
import type { PublicOrganization } from './catalog';

export default function TerritoryMap({organizations, selected, apiKey, disabled, onChoose}: {
  organizations: PublicOrganization[]; selected: string; apiKey: string; disabled: boolean; onChoose: (id: string) => void;
}) {
  const element = useRef<HTMLDivElement>(null), map = useRef<YMap | null>(null), sdk = useRef<YMaps | null>(null);
  const choose = useRef(onChoose), locked = useRef(disabled);
  choose.current = onChoose; locked.current = disabled;
  const [ready, setReady] = useState(false), [retry, setRetry] = useState(0);
  const [failure, setFailure] = useState<{key: string; attempt: number; message: string} | null>(null);
  const error = failure?.key === apiKey && failure.attempt === retry ? failure.message : '';
  const hasAreas = organizations.some(item => item.territories.length);
  const multiple = organizations.length > 1;
  useEffect(() => {
    let active = true;
    setReady(false); setFailure(null);
    if (!hasAreas) return;
    loadYandexMaps(apiKey).then(api => {
      if (!active || !element.current) return;
      sdk.current = api;
      map.current = new api.Map(element.current, {center: [72.6, 61.1], zoom: 11, controls: ['zoomControl', 'fullscreenControl']}, {suppressMapOpenBlock: true});
      setReady(true);
    }).catch(reason => {if (active) setFailure({key: apiKey, attempt: retry, message: reason.message});});
    return () => {active = false; map.current?.destroy(); map.current = null; sdk.current = null;};
  }, [apiKey, retry, hasAreas]);
  useEffect(() => {
    if (!ready || !sdk.current || !map.current) return;
    const layer = map.current, api = sdk.current, shapes: YPolygon[] = [];
    for (const organization of organizations) for (const territory of organization.territories) {
      for (const coordinates of polygonsOf(territory.geometry)) {
        const shape = new api.Polygon(coordinates, {hintContent: escapeMapLabel(organization.name + ' · ' + territory.name)}, {
          fillColor: organization.color, fillOpacity: !selected || selected === organization.id ? .3 : .1,
          strokeColor: organization.color, strokeWidth: selected === organization.id ? 4 : 2,
          openBalloonOnClick: false, cursor: disabled || !multiple ? 'default' : 'pointer',
        });
        shape.events.add('click', () => {if (!locked.current && multiple) choose.current(organization.id);});
        shapes.push(shape); layer.geoObjects.add(shape);
      }
    }
    return () => {shapes.forEach(shape => layer.geoObjects.remove(shape));};
  }, [organizations, selected, ready, disabled]);
  useEffect(() => {
    if (!ready || !map.current) return;
    const bounds = map.current.geoObjects.getBounds();
    if (bounds) map.current.setBounds(bounds, {checkZoomRange: true, zoomMargin: 32});
  }, [organizations, ready]);
  return <section className="citizen-territories" aria-label="Территории организаций">
    <div className="citizen-map-heading"><MapPin size={18}/><strong>Кто отвечает за территорию</strong></div>
    <p className="citizen-help">{multiple ? 'У каждой организации свой цвет. Нажмите на территорию или название, чтобы выбрать получателя обращения.' : 'На карте показана территория обслуживающей организации.'}</p>
    {hasAreas && <div className="citizen-territory-map" ref={element} hidden={!!error} aria-label="Карта территорий организаций"/>}
    {hasAreas && !ready && !error && <p role="status" className="citizen-help">Загружаем карту…</p>}
    {hasAreas && error && <div className="citizen-map-error" role="status"><p>{multiple ? 'Карта временно недоступна. Организацию можно выбрать из списка ниже.' : 'Карта временно недоступна. Получатель обращения уже выбран.'}</p>
      <button type="button" disabled={disabled} onClick={() => setRetry(value => value + 1)}><RefreshCw size={16}/>Повторить загрузку</button></div>}
    <div className="citizen-map-legend">{organizations.map(item => multiple ? <button key={item.id} type="button" disabled={disabled}
      aria-pressed={selected === item.id} onClick={() => onChoose(item.id)}>
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill={item.color}/></svg>
      <span><strong>{item.name}</strong>{item.territories.length > 0 && <small>{item.territories.map(area => area.name).join(' · ')}</small>}</span></button>
      : <div key={item.id} className="citizen-map-fixed"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill={item.color}/></svg>
        <span><strong>{item.name}</strong><small>{item.territories.map(area => area.name).join(' · ')}</small></span></div>)}</div>
  </section>;
}
