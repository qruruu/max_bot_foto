// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LiveCamera from './LiveCamera';
import type { CameraPhoto, CaptureSession } from './camera';

class Track extends EventTarget {
  readyState = 'live'; muted = false;
  stop = vi.fn(() => {this.readyState = 'ended';});
}
let element: HTMLDivElement, root: Root, tracks: Track[], hidden: boolean;
let getUserMedia: ReturnType<typeof vi.fn>;
const onCapture = vi.fn<(photo: CameraPhoto) => void>();
const session = () => ({token: 'camera-session', server_time: new Date().toISOString(),
  expires_at: new Date(Date.now() + 1800_000).toISOString(), timezone: 'Asia/Yekaterinburg', receivedAt: performance.now()}) as CaptureSession;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function button(label: string) {return [...element.querySelectorAll('button')].find(item => item.textContent?.includes(label))!;}
async function mount(onResume?: () => Promise<CaptureSession | null>) {
  await act(async () => {root.render(<StrictMode><LiveCamera session={session()} onCapture={onCapture} onClose={vi.fn()} onResume={onResume}/></StrictMode>); await tick();});
  await act(async () => {element.querySelector('video')?.dispatchEvent(new Event('loadeddata')); await tick();});
}
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element); tracks = []; hidden = false; onCapture.mockReset();
  vi.stubGlobal('isSecureContext', true);
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(2);
  vi.spyOn(HTMLVideoElement.prototype, 'videoWidth', 'get').mockReturnValue(1920);
  vi.spyOn(HTMLVideoElement.prototype, 'videoHeight', 'get').mockReturnValue(1080);
  const context = {drawImage: vi.fn(), fillRect: vi.fn(), fillText: vi.fn(), measureText: () => ({width: 500})};
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as never);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback, type) => callback(new Blob(['a-camera-frame'], {type})));
  Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:camera-frame')});
  getUserMedia = vi.fn(async () => {
    const track = new Track(); tracks.push(track);
    return {getTracks: () => [track], getVideoTracks: () => [track]} as unknown as MediaStream;
  });
  vi.stubGlobal('navigator', {mediaDevices: {getUserMedia}, geolocation: {
    watchPosition(ok: PositionCallback) {queueMicrotask(() => ok({timestamp: Date.now(), coords: {latitude: 61.1, longitude: 72.5, accuracy: 8}} as GeolocationPosition)); return 1;},
    clearWatch: vi.fn(), getCurrentPosition: vi.fn(),
  }});
});
afterEach(async () => {
  await act(async () => {root.unmount(); await tick();}); element.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('mobile camera lifecycle', () => {
  it('opens only one stream under StrictMode and stops it on close', async () => {
    await mount(); expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(button('Сделать снимок').disabled).toBe(false);
    await act(async () => {root.unmount(); await tick();});
    expect(tracks[0].stop).toHaveBeenCalled(); root = createRoot(element);
  });
  it('stops the camera in the background and resumes without losing the form', async () => {
    await mount();
    await act(async () => {hidden = true; document.dispatchEvent(new Event('visibilitychange'));});
    expect(tracks[0].readyState).toBe('ended'); expect(button('Сделать снимок').disabled).toBe(true);
    expect(element.textContent).toContain('Камера приостановлена');
    await act(async () => {hidden = false; button('Включить снова').click(); await tick();});
    await act(async () => {element.querySelector('video')!.dispatchEvent(new Event('loadeddata')); await tick();});
    expect(getUserMedia).toHaveBeenCalledTimes(2); expect(button('Сделать снимок').disabled).toBe(false);
  });
  it('never captures a muted camera and accepts one photo after rapid double tapping', async () => {
    await mount();
    await act(async () => {tracks[0].muted = true; tracks[0].dispatchEvent(new Event('mute'));});
    expect(button('Сделать снимок').disabled).toBe(true);
    await act(async () => {tracks[0].muted = false; tracks[0].dispatchEvent(new Event('unmute')); await tick();});
    await act(async () => {button('Сделать снимок').click(); button('Сделать снимок').click(); await tick();});
    expect(onCapture).toHaveBeenCalledTimes(1);
    expect(onCapture.mock.calls[0][0].capture.latitude).toBe(61.1);
    expect(onCapture.mock.calls[0][0].blob.type).toBe('image/jpeg');
  });
  it('resynchronizes server time before capturing after the phone wakes', async () => {
    const fresh = {...session(), server_time: new Date(Date.now() + 600_000).toISOString()};
    const onResume = vi.fn(async () => fresh);
    await mount(onResume);
    await act(async () => {hidden = true; document.dispatchEvent(new Event('visibilitychange'));});
    await act(async () => {hidden = false; button('Включить снова').click(); await tick();});
    await act(async () => {element.querySelector('video')!.dispatchEvent(new Event('loadeddata')); await tick();});
    await act(async () => {button('Сделать снимок').click(); await tick();});
    expect(onResume).toHaveBeenCalledTimes(1);
    expect(Date.parse(onCapture.mock.calls[0][0].capture.captured_at)).toBeGreaterThan(Date.now() + 540_000);
  });
  it('offers retry after denied permissions and closes a late permission result', async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException('Denied', 'NotAllowedError'));
    await mount(); expect(element.textContent).toContain('Разрешите доступ к камере');
    expect(button('Повторить')).toBeTruthy(); expect(element.querySelector('input[type=file]')).toBeNull();
    let finish!: (stream: MediaStream) => void;
    getUserMedia.mockImplementation(() => new Promise(resolve => {finish = resolve;}));
    await act(async () => {button('Повторить').click(); await tick();});
    await act(async () => {root.unmount(); await tick();});
    const late = new Track(); finish({getTracks: () => [late]} as unknown as MediaStream); await tick();
    expect(late.stop).toHaveBeenCalled(); root = createRoot(element);
  });
});
