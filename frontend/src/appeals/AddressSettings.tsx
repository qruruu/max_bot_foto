import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { api } from '../api';

type Settings = {addresses: {id: string; label: string; district_id: number}[]; territories: {id: number; name: string}[]};
export default function AddressSettings() {
  const [data, setData] = useState<Settings | null>(null), [label, setLabel] = useState(''), [district, setDistrict] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    api<Settings>('/appeals/workflow/settings', 'GET', undefined, abort.signal).then(value => {setData(value); if (value.territories.length === 1) setDistrict(String(value.territories[0].id));})
      .catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [revision]);
  async function change(path: string, method: string, body?: object) {
    setBusy(true); setError('');
    try {await api('/appeals/workflow/addresses' + path, method, body); setLabel(''); setRevision(value => value + 1);}
    catch (reason) {setError((reason as Error).message);} finally {setBusy(false);}
  }
  return <section className="panel appeal-address-settings"><h2>Адреса для «Сигнала»</h2><p className="hint">Жители смогут выбрать только эти адреса. Для каждого адреса выберите обслуживаемую территорию: точка проблемы должна находиться внутри неё.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!data ? <p>Загружаем…</p> : <><ul>{data.addresses.map(address => <li key={address.id}><span><strong>{address.label}</strong><small>{data.territories.find(area => area.id === address.district_id)?.name || 'Территория недоступна — добавьте адрес с действующей территорией'}</small></span>
      <button aria-label={'Убрать адрес ' + address.label} disabled={busy} onClick={() => void change('/' + address.id, 'DELETE')}><Trash2 size={16}/></button></li>)}</ul>
      {!data.territories.length ? <p className="hint">Сначала добавьте активные территории на карте микрорайонов.</p> : <form onSubmit={event => {event.preventDefault(); void change('', 'POST', {label, district_id: Number(district)});}}>
        <label>Улица и адрес<input required minLength={2} maxLength={300} value={label} disabled={busy} placeholder="Например, улица Ленина, дом 10" onChange={event => setLabel(event.target.value)}/></label>
        <label>Территория<select required value={district} disabled={busy} onChange={event => setDistrict(event.target.value)}><option value="">Выберите территорию</option>{data.territories.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
        <button className="primary" disabled={busy || !label.trim() || !district}><Plus size={16}/>Добавить адрес</button></form>}
    </>}
  </section>;
}
