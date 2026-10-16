/** A short local chime; no downloads, external services or audio permissions prompt. */
export function createNotificationSound() {
  let context: AudioContext | null = null;
  let disposed = false;

  async function unlock(): Promise<boolean> {
    if (disposed) return false;
    try {
      const Audio = window.AudioContext || (window as Window & {webkitAudioContext?: typeof AudioContext}).webkitAudioContext;
      if (!Audio) return false;
      context ??= new Audio();
      if (context.state === 'suspended') await context.resume();
      return !disposed && context.state === 'running';
    } catch { return false; }
  }

  function play(): boolean {
    if (disposed || !context || context.state !== 'running') return false;
    try {
      const start = context.currentTime;
      for (const [offset, frequency] of [[0, 660], [0.15, 880]]) {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = frequency;
        gain.gain.setValueAtTime(0, start + offset);
        gain.gain.linearRampToValueAtTime(0.12, start + offset + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.001, start + offset + 0.2);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
        oscillator.start(start + offset);
        oscillator.stop(start + offset + 0.22);
      }
      return true;
    } catch { return false; }
  }

  function dispose() {
    disposed = true;
    if (context && context.state !== 'closed') void context.close().catch(() => {});
    context = null;
  }

  return {unlock, play, dispose};
}
