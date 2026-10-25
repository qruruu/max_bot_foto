import { useEffect, useRef, useState } from 'react';
import { Camera, Copy, LocateFixed, RefreshCw, X } from 'lucide-react';
import { CAMERA_CONSTRAINTS, captureMetadata, drawStamp, encodeFrame, frameDimensions, serverNow, stampLines, sufficientResolution, validPosition } from './camera';
import type { CameraPhoto, CaptureSession } from './camera';
import { monitorLocation } from './location';
import useModal from './useModal';

export default function LiveCamera({session, onCapture, onClose, onResume}: {
  session: CaptureSession; onCapture: (photo: CameraPhoto) => void; onClose: () => void;
  onResume?: () => Promise<CaptureSession | null>;
}) {
  const video = useRef<HTMLVideoElement>(null), stream = useRef<MediaStream | null>(null);
  const root = useRef<HTMLDivElement>(null), activeCapture = useRef(false);
  const position = useRef<GeolocationPosition | null>(null), mounted = useRef(true);
  const clock = useRef(session), restarting = useRef(false);
  useEffect(() => {clock.current = session;}, [session]);
  useModal(root);
  const [error, setError] = useState(''), [locationError, setLocationError] = useState('');
  const [ready, setReady] = useState(false), [positionReady, setPositionReady] = useState(false);
  const [accuracy, setAccuracy] = useState<number | null>(null), [busy, setBusy] = useState(false);
  const [paused, setPaused] = useState(false), [restart, setRestart] = useState(0), [copied, setCopied] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);

  useEffect(() => {
    let active = true, stopped = false, media: MediaStream | null = null;
    let location: ReturnType<typeof monitorLocation> | undefined;
    setReady(false); setPositionReady(false); setAccuracy(null); setError(''); setLocationError(''); setPaused(false);
    position.current = null;
    function stop() {
      stopped = true; location?.stop(); location = undefined;
      const ending = media; media = null; ending?.getTracks().forEach(track => track.stop());
      stream.current = null;
      if (video.current) video.current.srcObject = null;
    }
    function pause() {
      if (!active || stopped) return;
      stop(); setReady(false); setPositionReady(false); setPaused(true);
    }
    const visibility = () => {if (document.hidden) pause();};
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', pause);
    // StrictMode's discarded first effect must never open another permission prompt.
    queueMicrotask(async () => {
      if (!active || stopped) return;
      if (document.hidden) {pause(); return;}
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setError('Для съёмки нужна защищённая ссылка HTTPS и браузер с доступом к камере.'); return;
      }
      try {
        const result = await navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS);
        if (!active || stopped) {result.getTracks().forEach(track => track.stop()); return;}
        media = result; stream.current = result;
        const track = result.getVideoTracks()[0];
        track.addEventListener('ended', () => {if (active && !stopped) {pause(); setError('Камера отключилась. Включите её снова.');}});
        track.addEventListener('mute', () => {if (active && !stopped) {setReady(false); setPaused(true);}});
        track.addEventListener('unmute', () => {if (active && !stopped && video.current) void video.current.play().then(frameReady).catch(() => setPaused(true));});
        if (video.current) {video.current.srcObject = result; await video.current.play();}
        if (!active || stopped) return;
        if (!navigator.geolocation) setLocationError('Этот браузер не предоставляет геолокацию. Откройте ссылку в обычном браузере телефона.');
        else location = monitorLocation(navigator.geolocation, state => {
          if (!active || stopped) return;
          position.current = state.position;
          setPositionReady(validPosition(state.position)); setAccuracy(state.position?.coords.accuracy ?? null); setLocationError(state.error);
        });
      } catch (failure) {
        if (!active || stopped) return;
        stop();
        const name = (failure as DOMException).name;
        setError(name === 'NotAllowedError' ? 'Разрешите доступ к камере в настройках браузера и телефона, затем повторите попытку.'
          : name === 'NotFoundError' ? 'Камера не найдена. Откройте ссылку на телефоне с камерой.'
          : 'Не удалось включить камеру. Закройте другие приложения с камерой и повторите попытку.');
      }
    });
    return () => {
      active = false; stop(); document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pagehide', pause);
    };
  }, [restart]);

  function frameReady() {
    const player = video.current, track = stream.current?.getVideoTracks()[0];
    const available = !!player && player.readyState >= 2 && player.videoWidth > 0 && track?.readyState === 'live' && !track.muted;
    setReady(available); if (available) setPaused(false);
  }
  async function shoot() {
    const player = video.current, fix = position.current, track = stream.current?.getVideoTracks()[0];
    if (activeCapture.current || !player || !track || track.muted || track.readyState !== 'live' || document.hidden || player.readyState < 2) return;
    if (!fix || !validPosition(fix)) {setPositionReady(false); return;}
    activeCapture.current = true; setBusy(true); setError('');
    const canvas = document.createElement('canvas'), previewCanvas = document.createElement('canvas');
    try {
      if (serverNow(clock.current) >= Date.parse(clock.current.expires_at)) throw new Error('Время съёмки истекло. Закройте камеру и сделайте новые снимки; анкета сохранится.');
      const size = frameDimensions(player.videoWidth, player.videoHeight);
      if (!sufficientResolution(size.width, size.height)) throw new Error('Камера передаёт слишком маленькое изображение. Откройте ссылку в Safari, Chrome или Яндекс.Браузере.');
      const capture = captureMetadata(fix, serverNow(clock.current));
      canvas.width = size.width; canvas.height = size.height;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Не удалось получить изображение камеры.');
      context.drawImage(player, 0, 0, canvas.width, canvas.height);
      const blob = await encodeFrame(canvas);
      const previewSize = frameDimensions(size.width, size.height, 1280);
      previewCanvas.width = previewSize.width; previewCanvas.height = previewSize.height;
      const previewContext = previewCanvas.getContext('2d');
      if (!previewContext) throw new Error('Не удалось подготовить просмотр снимка.');
      previewContext.drawImage(canvas, 0, 0, previewCanvas.width, previewCanvas.height);
      drawStamp(previewContext, previewCanvas.width, previewCanvas.height, stampLines(capture, clock.current.timezone));
      const preview = await encodeFrame(previewCanvas, 350 * 1024);
      if (mounted.current) onCapture({id: crypto.randomUUID(), blob, preview, url: URL.createObjectURL(preview), capture});
    } catch (failure) {if (mounted.current) setError((failure as Error).message);}
    finally {canvas.width = 0; canvas.height = 0; previewCanvas.width = 0; previewCanvas.height = 0;
      activeCapture.current = false; if (mounted.current) setBusy(false);}
  }

  async function copyLink() {
    try {await navigator.clipboard.writeText(window.location.href); setCopied(true);}
    catch {setLocationError('Скопируйте адрес из адресной строки и откройте его в браузере телефона.');}
  }
  async function restartCamera() {
    if (restarting.current) return;
    restarting.current = true; setReconnecting(true);
    try {
      const fresh = onResume ? await onResume() : clock.current;
      if (mounted.current && fresh) {clock.current = fresh; setRestart(value => value + 1);}
    } catch (failure) {if (mounted.current) setError((failure as Error).message);}
    finally {restarting.current = false; if (mounted.current) setReconnecting(false);}
  }
  const failed = !!error || !!locationError;
  return <div ref={root} className="citizen-camera" role="dialog" aria-modal="true" aria-labelledby="camera-title">
    <header><div><span className="citizen-kicker">СЪЁМКА НА МЕСТЕ</span><h2 id="camera-title">Сфотографируйте проблему</h2></div>
      <button data-modal-close type="button" className="citizen-icon" onClick={onClose} disabled={busy} aria-label="Закрыть камеру"><X/></button></header>
    <div className="citizen-viewfinder"><video ref={video} autoPlay playsInline muted onLoadedData={frameReady} onPlaying={frameReady} onResize={frameReady}/>
      {paused ? <div className="citizen-camera-paused"><Camera size={32}/><p>Камера приостановлена</p><button type="button" disabled={reconnecting} onClick={() => void restartCamera()}>{reconnecting ? 'Подключаемся…' : 'Включить снова'}</button></div>
        : !ready && !error && <p>Включаем камеру…</p>}</div>
    <div className="citizen-camera-footer">
      <div className="citizen-camera-messages">
      <p className={'citizen-location ' + (positionReady ? 'ready' : '')} role="status"><LocateFixed size={18}/>{locationError || (positionReady
        ? `Местоположение определено · точность ±${Math.ceil(accuracy || 0)} м`
        : accuracy !== null ? `Уточняем местоположение · сейчас ±${Math.ceil(accuracy)} м` : 'Определяем местоположение…')}</p>
      <p className="citizen-camera-hint">Держите телефон ровно. Покажите проблему и немного территории вокруг. Дата и координаты добавятся автоматически.</p>
      {error && <p className="citizen-error" role="alert">{error}</p>}
      {failed && <div className="citizen-camera-recovery"><button type="button" disabled={busy || reconnecting} onClick={() => void restartCamera()}><RefreshCw size={16}/>Повторить</button>
        <button type="button" onClick={() => void copyLink()}><Copy size={16}/>{copied ? 'Ссылка скопирована' : 'Скопировать ссылку'}</button>
        <p>Если страница открыта внутри MAX, откройте меню приложения и выберите открытие в браузере. Черновик останется в текущем браузере.</p></div>}
      </div>
      <button type="button" className="citizen-shutter" onClick={() => void shoot()} disabled={!ready || !positionReady || busy || paused}>
        <Camera size={24}/>{busy ? 'Сохраняем снимок…' : 'Сделать снимок'}</button>
    </div>
  </div>;
}
