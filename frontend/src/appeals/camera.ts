export const MAX_PHOTOS = 3;
export const MAX_PHOTO_BYTES = 6 * 1024 * 1024;
export const MAX_POSITION_AGE_MS = 15_000;
export const MAX_POSITION_ACCURACY = 100;
export const CAMERA_CONSTRAINTS: MediaStreamConstraints = {
  audio: false,
  video: {facingMode: {ideal: 'environment'}, width: {ideal: 2560}, height: {ideal: 1920}},
};

export type CaptureMetadata = {
  captured_at: string; position_at: string; latitude: number; longitude: number; accuracy: number;
};
export type CameraPhoto = {id: string; blob: Blob; preview: Blob; url: string; capture: CaptureMetadata};
export type CaptureSession = {
  token: string; server_time: string; expires_at: string; timezone: string; receivedAt: number;
};

export function serverNow(session: CaptureSession, elapsed = performance.now()): number {
  return Date.parse(session.server_time) + elapsed - session.receivedAt;
}

export function validPosition(position: GeolocationPosition | null, clientNow = Date.now()): boolean {
  if (!position) return false;
  const {latitude, longitude, accuracy} = position.coords;
  return Number.isFinite(latitude) && Math.abs(latitude) <= 90 && Number.isFinite(longitude) && Math.abs(longitude) <= 180
    && Number.isFinite(accuracy) && accuracy > 0 && accuracy <= MAX_POSITION_ACCURACY
    && position.timestamp <= clientNow + 1000 && clientNow - position.timestamp <= MAX_POSITION_AGE_MS;
}

export function captureMetadata(position: GeolocationPosition, at: number, clientNow = Date.now()): CaptureMetadata {
  if (!validPosition(position, clientNow)) throw new Error('Дождитесь точного местоположения перед съёмкой.');
  return {captured_at: new Date(at).toISOString(), position_at: new Date(at + position.timestamp - clientNow).toISOString(),
    latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy: position.coords.accuracy};
}

export function sufficientResolution(width: number, height: number): boolean {
  return Math.max(width, height) >= 1280 && Math.min(width, height) >= 720 && width * height <= 16_000_000;
}

export function stampLines(capture: CaptureMetadata, timezone: string): [string, string] {
  const parts = new Intl.DateTimeFormat('ru-RU', {timeZone: timezone, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(new Date(capture.captured_at));
  const part = (type: string) => parts.find(item => item.type === type)?.value || '';
  const coordinate = (value: number, positive: string, negative: string) => Math.abs(value).toFixed(4).replace('.', ',') + (value >= 0 ? positive : negative);
  return [`${part('day')}.${part('month')}.${part('year')} ${part('hour')}:${part('minute')}`,
    `${coordinate(capture.latitude, 'N', 'S')} ${coordinate(capture.longitude, 'E', 'W')}`];
}

export function drawStamp(context: CanvasRenderingContext2D, width: number, height: number, lines: [string, string]) {
  const fontSize = Math.max(28, Math.round(width * 0.038));
  const padding = Math.max(10, Math.round(width * 0.012)), lineHeight = Math.round(fontSize * 1.35);
  context.font = `700 ${fontSize}px Arial, sans-serif`;
  const panelWidth = Math.max(...lines.map(line => context.measureText(line).width)) + padding * 2;
  const panelHeight = lineHeight * 2 + padding * 2;
  context.fillStyle = '#000'; context.fillRect(width - panelWidth, height - panelHeight, panelWidth, panelHeight);
  context.fillStyle = '#fff'; context.textAlign = 'right'; context.textBaseline = 'top';
  lines.forEach((line, index) => context.fillText(line, width - padding, height - panelHeight + padding + index * lineHeight));
}

export function frameDimensions(width: number, height: number, maximum = 2560) {
  const ratio = Math.min(1, maximum / Math.max(width, height));
  return {width: Math.round(width * ratio), height: Math.round(height * ratio)};
}

export async function encodeFrame(canvas: HTMLCanvasElement, targetBytes = 1500 * 1024): Promise<Blob> {
  let blob: Blob | null = null;
  for (const quality of [0.92, 0.86, 0.80, 0.74]) {
    blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (!blob || blob.type !== 'image/jpeg') throw new Error('Не удалось сохранить кадр камеры. Попробуйте ещё раз.');
    if (blob.size <= targetBytes) break;
  }
  if (!blob || blob.size > MAX_PHOTO_BYTES) throw new Error('Снимок получился слишком большим. Попробуйте сделать его ещё раз.');
  return blob;
}
