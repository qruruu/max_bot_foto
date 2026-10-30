import { useState } from 'react';
import { Check, Copy, ExternalLink } from 'lucide-react';
import './appeal-share.css';

export function appealShareLinks(url: string, attribution = false) {
  const shared = (source: string) => {const link = new URL(url, window.location.origin); if (attribution) link.searchParams.set('from', source); return link.href;};
  return [
    {name: 'MAX', href: 'https://max.ru/:share?' + new URLSearchParams({text: shared('max')})},
    {name: 'Telegram', href: 'https://t.me/share/url?' + new URLSearchParams({url: shared('telegram')})},
    {name: 'ВКонтакте', href: 'https://vk.com/share.php?' + new URLSearchParams({url: shared('vk')})},
  ];
}

export default function AppealShare({id, url}: {id: number; url?: string}) {
  const link = url || new URL('/a/' + id, window.location.origin).href;
  return <ShareControls link={link} compact/>;
}

export function SignalShare({url}: {url: string}) {
  return <ShareControls link={new URL(url, window.location.origin).href} social/>;
}

function ShareControls({link, social = false, compact = false}: {link: string; social?: boolean; compact?: boolean}) {
  const [copied, setCopied] = useState(false), [manual, setManual] = useState(false);
  async function copy() {
    try {await navigator.clipboard.writeText(link); setCopied(true); setManual(false);}
    catch {setManual(true); setCopied(false);}
  }
  const copyLabel = copied ? 'Ссылка скопирована' : 'Скопировать ссылку';
  return <div className={'appeal-share' + (compact ? ' appeal-share-compact' : '')}>
    {!compact && <div className="appeal-share-heading"><span>{social ? 'Поделиться страницей для жителей' : 'Ссылка на обращение'}</span><a href={link} aria-label={social ? 'Открыть страницу для жителей' : 'Открыть обращение по отдельной ссылке'}><ExternalLink size={15}/></a></div>}
    <div className="appeal-share-actions">
      {social && appealShareLinks(link, true).map(item => <a key={item.name} href={item.href} target="_blank" rel="noopener noreferrer nofollow" aria-label={'Поделиться в ' + item.name}>{item.name}</a>)}
      <button type="button" onClick={() => void copy()} aria-label={copyLabel} title={copyLabel}>{copied ? <Check size={compact ? 20 : 17}/> : <Copy size={compact ? 20 : 17}/>}<span className={compact ? 'appeal-share-label-hidden' : undefined}>{copied ? 'Скопировано' : 'Копировать ссылку'}</span></button>
    </div>
    {copied && <small className={compact ? 'appeal-share-label-hidden' : undefined} role="status">Ссылка скопирована</small>}
    {manual && <label className="appeal-share-manual">Скопируйте ссылку<input readOnly value={link} onFocus={event => event.currentTarget.select()} aria-label="Ссылка на обращение"/></label>}
  </div>;
}
