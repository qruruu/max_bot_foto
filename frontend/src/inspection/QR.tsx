import { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import jsQR from 'jsqr';
import { Camera, RefreshCw, X } from 'lucide-react';
import { api } from '../api';

export function invitationToken(value: string): string {
  const input = value.trim();
  if (/^[A-Za-z0-9_-]{40,100}$/.test(input)) return input;
  const url = new URL(input);
  if (url.origin !== window.location.origin || url.pathname !== '/inspection') throw new Error('Это не QR организации в Метке.');
  const token = new URLSearchParams(url.hash.slice(1)).get('invite') || '';
  if (!/^[A-Za-z0-9_-]{40,100}$/.test(token)) throw new Error('В QR нет приглашения организации.');
  return token;
}

export function OrganizationQR({endpoint}: {endpoint: string}) {
  const [image,setImage] = useState(''), [url,setUrl] = useState(''), [expires,setExpires] = useState('');
  const [busy,setBusy] = useState(false), [error,setError] = useState('');
  async function create() {
    setBusy(true); setError(''); setImage(''); setUrl('');
    try {
      const result = await api<{url: string; expires_at: string}>(endpoint, 'POST');
      setImage(await QRCode.toDataURL(result.url, {width: 320, margin: 3, errorCorrectionLevel:'M'}));
      setUrl(result.url); setExpires(result.expires_at);
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  useEffect(() => {setImage(''); setUrl(''); setError('');}, [endpoint]);
  return <section className="panel inspection-qr"><h2>Доступ проверяющего</h2>
    <p>Каждый QR выдаёт доступ одному аккаунту. Он действует 15 минут и погашается после первого использования. Новый QR заменяет предыдущий неиспользованный.</p>
    <button disabled={busy} onClick={() => void create()}><RefreshCw size={17}/>{busy ? 'Создаём…' : image ? 'Создать новый QR' : 'Создать QR организации'}</button>
    {error && <p className="error" role="alert">{error}</p>}
    {image && <><img className="inspection-qr-image" src={image} alt="Одноразовый QR организации для проверяющего"/>
      <p>Действует до {new Date(expires).toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'})}</p>
      <a className="button" download="organization-qr.png" href={image}>Скачать QR</a>
      <button onClick={async () => {try {await navigator.clipboard.writeText(url);} catch {setError('Не удалось скопировать ссылку. Скачайте QR.');}}}>Копировать ссылку</button></>}
  </section>;
}

export function QRScanner({onScan,onClose}: {onScan: (value: string) => void; onClose: () => void}) {
  const video = useRef<HTMLVideoElement>(null);
  const [error,setError] = useState(''), [manual,setManual] = useState(''), [starting,setStarting] = useState(false);
  const stream = useRef<MediaStream | null>(null), timer = useRef<number | undefined>(undefined), delivered = useRef(false);
  function stop() {window.clearTimeout(timer.current); stream.current?.getTracks().forEach(track => track.stop()); stream.current=null;}
  useEffect(() => () => stop(), []);
  useEffect(() => {const hidden=()=>{if(document.hidden)stop();};document.addEventListener('visibilitychange',hidden);return()=>document.removeEventListener('visibilitychange',hidden);},[]);
  function found(value: string) {
    try {const token=invitationToken(value); if (delivered.current) return; delivered.current=true; stop(); onScan(token);}
    catch(e) {setError((e as Error).message);}
  }
  function scanFrame() {
    if (!video.current || !stream.current || delivered.current) return;
    if (video.current.readyState >= 2) {
      const canvas=document.createElement('canvas'), scale=Math.min(1, 900 / video.current.videoWidth);
      canvas.width=Math.round(video.current.videoWidth * scale); canvas.height=Math.round(video.current.videoHeight * scale);
      const ctx=canvas.getContext('2d', {willReadFrequently:true});
      if (ctx && canvas.width && canvas.height) {ctx.drawImage(video.current,0,0,canvas.width,canvas.height);
        const pixels=ctx.getImageData(0,0,canvas.width,canvas.height), result=jsQR(pixels.data,pixels.width,pixels.height);
        if (result) found(result.data);}
    }
    if (!delivered.current) timer.current=window.setTimeout(scanFrame,250);
  }
  async function start() {
    setError(''); setStarting(true); stop();
    try {const media=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
      if (!video.current) {media.getTracks().forEach(t=>t.stop()); return;}
      stream.current=media; video.current.srcObject=media; await video.current.play(); scanFrame();
    } catch {setError('Камера недоступна. Разрешите доступ к камере или выберите изображение QR.');} finally {setStarting(false);}
  }
  async function fileSelected(file?: File) {
    if (!file) return;
    setError('');
    if (file.size > 15 * 1024 * 1024) {setError('Изображение должно быть не больше 15 МБ.'); return;}
    const source=URL.createObjectURL(file);
    try {const image=new Image(); image.src=source; await image.decode(); const scale=Math.min(1,1600/Math.max(image.width,image.height));
      const canvas=document.createElement('canvas'); canvas.width=Math.round(image.width*scale); canvas.height=Math.round(image.height*scale);
      const ctx=canvas.getContext('2d')!; ctx.drawImage(image,0,0,canvas.width,canvas.height);
      const pixels=ctx.getImageData(0,0,canvas.width,canvas.height), result=jsQR(pixels.data,pixels.width,pixels.height);
      if (!result) throw new Error('QR не найден на изображении.'); found(result.data);
    } catch(e) {setError((e as Error).message || 'Не удалось прочитать изображение.');} finally {URL.revokeObjectURL(source);}
  }
  return <section className="panel inspection-scanner"><div className="section-title"><h2>Сканировать QR организации</h2><button aria-label="Закрыть сканер" onClick={onClose}><X size={18}/></button></div>
    <p>Получите новый QR у администратора организации. Доступ закрепится только за вашим аккаунтом.</p>
    <video ref={video} muted playsInline aria-label="Камера сканирования QR"/>
    <button disabled={starting} onClick={() => void start()}><Camera size={17}/>Включить камеру</button>
    <label>Или выберите изображение QR<input type="file" accept="image/*" onChange={e => void fileSelected(e.target.files?.[0])}/></label>
    <form onSubmit={e=>{e.preventDefault();found(manual);}}><label>Ссылка из QR<input required value={manual} onChange={e=>setManual(e.target.value)} placeholder="Вставьте ссылку приглашения"/></label><button>Открыть доступ</button></form>
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
