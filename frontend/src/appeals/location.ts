import { validPosition } from './camera';

type LocationState = {position: GeolocationPosition | null; error: string};

export function locationErrorMessage(code: number) {
  return code === 1 ? 'Разрешите доступ к геолокации в настройках браузера и телефона, затем повторите попытку.'
    : code === 3 ? 'Местоположение определяется дольше обычного. Выйдите на открытое место — поиск продолжается.'
    : 'Не удалось определить местоположение. Проверьте геолокацию телефона — поиск продолжается.';
}

/** Keep requesting a fresh fix even when watchPosition reports no movement. */
export function monitorLocation(geolocation: Geolocation, changed: (state: LocationState) => void) {
  let active = true, pending = false, denied = false;
  let latest: GeolocationPosition | null = null, lastError = '';
  const emit = () => {if (active) changed({position: latest, error: validPosition(latest) ? '' : lastError});};
  const success: PositionCallback = result => {
    if (!active || denied) return;
    latest = result; lastError = ''; emit();
  };
  const failure: PositionErrorCallback = error => {
    if (!active) return;
    lastError = locationErrorMessage(error.code);
    if (error.code === 1) {latest = null; denied = true;}
    emit();
  };
  const options: PositionOptions = {enableHighAccuracy: true, maximumAge: 0, timeout: 20_000};
  const watcher = geolocation.watchPosition(success, failure, options);
  const refresh = () => {
    if (!active || pending || denied) return;
    pending = true;
    geolocation.getCurrentPosition(result => {pending = false; success(result);}, error => {pending = false; failure(error);}, options);
  };
  const refreshTimer = setInterval(refresh, 10_000), statusTimer = setInterval(emit, 1000);
  return {refresh, stop() {
    active = false;
    clearInterval(refreshTimer); clearInterval(statusTimer);
    geolocation.clearWatch(watcher);
  }};
}
