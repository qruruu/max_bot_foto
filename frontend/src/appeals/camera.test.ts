import { describe, expect, it } from 'vitest';
import { captureMetadata, encodeFrame, frameDimensions, serverNow, stampLines, sufficientResolution, validPosition } from './camera';
import type { CaptureSession } from './camera';

const clientTime = Date.parse('2026-10-23T03:29:00Z');
function position(changes: Partial<GeolocationCoordinates> = {}, timestamp = clientTime): GeolocationPosition {
  return {timestamp, coords: {latitude: 61.1025, longitude: 72.5794, accuracy: 8, altitude: null, altitudeAccuracy: null, heading: null, speed: null, ...changes}} as GeolocationPosition;
}

describe('camera-only capture metadata', () => {
  it('formats the reference stamp and keeps hemispheres', () => {
    const capture = captureMetadata(position(), clientTime, clientTime);
    expect(stampLines(capture, 'Asia/Yekaterinburg')).toEqual(['23.10.2026 08:29', '61,1025N 72,5794E']);
    expect(stampLines({...capture, latitude: -61.1025, longitude: -72.5794}, 'UTC')[1]).toBe('61,1025S 72,5794W');
  });
  it('rejects stale, inaccurate, missing and invalid geolocation', () => {
    expect(validPosition(null, clientTime)).toBe(false);
    expect(validPosition(position({accuracy: 500}), clientTime)).toBe(false);
    expect(validPosition(position({}, clientTime - 16_000), clientTime)).toBe(false);
    expect(validPosition(position({}, clientTime + 2_000), clientTime)).toBe(false);
    expect(validPosition(position({latitude: NaN}), clientTime)).toBe(false);
    expect(() => captureMetadata(position({accuracy: 500}), clientTime, clientTime)).toThrow();
  });
  it('uses server time even when the phone clock is wrong and retains position age', () => {
    const session = {server_time: '2026-10-23T03:29:00Z', receivedAt: 1000} as CaptureSession;
    const time = serverNow(session, 4000);
    expect(time).toBe(clientTime + 3000);
    const wrongPhoneTime = clientTime + 3600_000;
    const capture = captureMetadata(position({}, wrongPhoneTime - 2000), time, wrongPhoneTime);
    expect(Date.parse(capture.captured_at) - Date.parse(capture.position_at)).toBe(2000);
  });
  it('accepts both orientations and never accepts a small frame stretched by the interface', () => {
    expect(sufficientResolution(1920, 1080)).toBe(true);
    expect(sufficientResolution(1080, 1920)).toBe(true);
    expect(sufficientResolution(640, 480)).toBe(false);
    expect(sufficientResolution(2560, 360)).toBe(false);
    expect(sufficientResolution(8000, 6000)).toBe(false);
  });
  it('limits large sensor frames without cropping or upscaling', () => {
    expect(frameDimensions(4032, 3024)).toEqual({width: 2560, height: 1920});
    expect(frameDimensions(3024, 4032)).toEqual({width: 1920, height: 2560});
    expect(frameDimensions(640, 480)).toEqual({width: 640, height: 480});
  });
  it('reduces JPEG size for a mobile connection while retaining the frame dimensions', async () => {
    const canvas = {width: 1920, height: 1080, toBlob(callback: BlobCallback, type: string, quality: number) {
      callback(new Blob([new Uint8Array(quality > 0.86 ? 2_000_000 : 900_000)], {type}));
    }} as unknown as HTMLCanvasElement;
    const blob = await encodeFrame(canvas);
    expect(blob.size).toBeLessThanOrEqual(1500 * 1024);
    expect(canvas.width).toBe(1920); expect(canvas.height).toBe(1080);
  });
});
