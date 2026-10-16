import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createNotificationSound } from './notificationSound';

let contexts: FakeAudio[];
class FakeAudio {
  state = 'suspended';
  currentTime = 5;
  destination = {};
  resume = vi.fn(async () => { this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; });
  createOscillator = vi.fn(() => ({
    type: '', frequency: {value: 0}, connect: vi.fn(), disconnect: vi.fn(),
    onended: null, start: vi.fn(), stop: vi.fn(),
  }));
  createGain = vi.fn(() => ({
    gain: {setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn()},
    connect: vi.fn(), disconnect: vi.fn(),
  }));
  constructor() { contexts.push(this); }
}
beforeEach(() => { contexts = []; vi.stubGlobal('window', {AudioContext: FakeAudio}); });
afterEach(() => vi.unstubAllGlobals());

describe('local notification sound', () => {
  it('starts only after activation, reuses one context and plays a short two-note chime', async () => {
    const sound = createNotificationSound();
    expect(sound.play()).toBe(false);
    expect(contexts).toHaveLength(0);
    expect(await sound.unlock()).toBe(true);
    expect(await sound.unlock()).toBe(true);
    expect(contexts).toHaveLength(1);
    expect(sound.play()).toBe(true);
    const context = contexts[0];
    expect(context.createOscillator).toHaveBeenCalledTimes(2);
    const [first, second] = context.createOscillator.mock.results.map(result => result.value);
    expect(first.frequency.value).toBe(660);
    expect(second.frequency.value).toBe(880);
    expect(first.stop).toHaveBeenCalledWith(5.22);
    expect(second.stop).toHaveBeenCalledWith(5.37);
    sound.dispose();
    expect(context.close).toHaveBeenCalledTimes(1);
    expect(sound.play()).toBe(false);
    expect(await sound.unlock()).toBe(false);
  });

  it('handles unsupported browsers and blocked audio without throwing', async () => {
    vi.stubGlobal('window', {});
    let sound = createNotificationSound();
    expect(await sound.unlock()).toBe(false);
    expect(sound.play()).toBe(false);
    vi.stubGlobal('window', {AudioContext: FakeAudio});
    sound = createNotificationSound();
    const activation = sound.unlock();
    await activation;
    contexts[0].state = 'suspended';
    contexts[0].resume.mockRejectedValue(new Error('Blocked'));
    expect(await sound.unlock()).toBe(false);
    expect(sound.play()).toBe(false);
    sound.dispose();
  });
});
