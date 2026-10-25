import { afterEach, describe, expect, it, vi } from 'vitest';
import { monitorLocation } from './location';
import { validPosition } from './camera';

function fix(time = Date.now(), accuracy = 8) {
  return {timestamp: time, coords: {latitude: 61.1, longitude: 72.5, accuracy}} as GeolocationPosition;
}
function geolocation() {
  let success: PositionCallback = () => {}, error: PositionErrorCallback = () => {};
  const api = {watchPosition: vi.fn((ok: PositionCallback, failed: PositionErrorCallback) => {success = ok; error = failed; return 7;}),
    clearWatch: vi.fn(), getCurrentPosition: vi.fn((ok: PositionCallback) => ok(fix()))};
  return {api: api as unknown as Geolocation, mocks: api, fix: () => success(fix()),
    error: (code: number) => error({code} as GeolocationPositionError)};
}
afterEach(() => vi.useRealTimers());

describe('mobile geolocation', () => {
  it('keeps a stationary user able to shoot after the first GPS fix grows old', () => {
    vi.useFakeTimers();
    const source = geolocation(), changes = vi.fn();
    const monitor = monitorLocation(source.api, changes);
    source.fix(); vi.advanceTimersByTime(65_000);
    expect(source.mocks.getCurrentPosition.mock.calls.length).toBeGreaterThanOrEqual(6);
    expect(validPosition(changes.mock.lastCall![0].position)).toBe(true);
    monitor.stop(); expect(source.mocks.clearWatch).toHaveBeenCalledWith(7);
    const count = changes.mock.calls.length;
    vi.advanceTimersByTime(30_000); source.fix();
    expect(changes).toHaveBeenCalledTimes(count);
  });
  it('retains a recent good fix through a temporary error and expires it safely', () => {
    vi.useFakeTimers(); const source = geolocation(), changes = vi.fn();
    source.mocks.getCurrentPosition.mockImplementation(() => {});
    const monitor = monitorLocation(source.api, changes);
    source.fix(); source.error(2);
    expect(validPosition(changes.mock.lastCall![0].position)).toBe(true);
    vi.advanceTimersByTime(16_000);
    expect(validPosition(changes.mock.lastCall![0].position)).toBe(false);
    expect(changes.mock.lastCall![0].error).not.toBe(''); monitor.stop();
  });
  it('stops polling after permission denial and never reuses an older fix', () => {
    vi.useFakeTimers(); const source = geolocation(), changes = vi.fn();
    const monitor = monitorLocation(source.api, changes); source.fix(); source.error(1);
    source.fix();
    vi.advanceTimersByTime(60_000);
    expect(changes.mock.lastCall![0].position).toBeNull();
    expect(source.mocks.getCurrentPosition).not.toHaveBeenCalled(); monitor.stop();
  });
  it('does not accumulate location requests while the sensor has not answered', () => {
    vi.useFakeTimers(); const source = geolocation(); source.mocks.getCurrentPosition.mockImplementation(() => {});
    const monitor = monitorLocation(source.api, vi.fn()); vi.advanceTimersByTime(60_000);
    expect(source.mocks.getCurrentPosition).toHaveBeenCalledTimes(1); monitor.stop();
  });
});
