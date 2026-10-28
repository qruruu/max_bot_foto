import { useState } from 'react';
import { Check, Copy, ExternalLink } from 'lucide-react';
import './appeal-share.css';

export function appealShareLinks(url: string) {
  return [
    {name: 'MAX', href: 'https://max.ru/:share?' + new URLSearchParams({text: url})},
    {name: 'Telegram', href: 'https://t.me/share/url?' + new URLSearchParams({url})},
    {name: 'ВКонтакте', href: 'https://vk.com/share.php?' + new URLSearchParams({url})},
  ];
}

export default function AppealShare({id, url}: {id: number; url?: string}) {
  const link = url || new URL('/a/' + id, window.location.origin).href;
  const [copied, setCopied] = useState(false), [manual, setManual] = useState(false);
  async function copy() {
    try {await navigator.clipboard.writeText(link); setCopied(true); setManual(false);}
    catch {setManual(true); setCopied(false);}
  }
  return <div className="appeal-share">
    <div className="appeal-share-heading"><span>Поделиться обращением</span><a href={link} aria-label="Открыть обращение по отдельной ссылке"><ExternalLink size={15}/></a></div>
    <div className="appeal-share-actions">
      {appealShareLinks(link).map(item => <a key={item.name} href={item.href} target="_blank" rel="noopener noreferrer nofollow" aria-label={'Поделиться в ' + item.name}>{item.name}</a>)}
      <button type="button" onClick={() => void copy()} aria-label={copied ? 'Ссылка скопирована' : 'Скопировать ссылку'} title="Скопировать ссылку">{copied ? <Check size={17}/> : <Copy size={17}/>}</button>
    </div>
    {copied && <small role="status">Ссылка скопирована</small>}
    {manual && <label className="appeal-share-manual">Скопируйте ссылку<input readOnly value={link} onFocus={event => event.currentTarget.select()} aria-label="Ссылка на обращение"/></label>}
  </div>;
}
