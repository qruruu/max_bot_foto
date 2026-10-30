// Browser-only integration. All application UI and state are implemented in Dart.
(() => {
  'use strict';
  const databaseName = 'citizen-appeal-drafts', store = 'drafts', draftKey = 'current';
  let dirty = false, latestDraft = null, mapsPromise = null, nextMap = 0, nextListener = 0;
  let writes = Promise.resolve();
  const maps = new Map(), pendingMaps = new WeakMap(), listeners = new Map();

  function database() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => {if (!request.result.objectStoreNames.contains(store)) request.result.createObjectStore(store);};
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('Хранилище черновиков недоступно'));
    });
  }
  async function transaction(mode, action) {
    const db = await database();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(store, mode), request = action(tx.objectStore(store));
        tx.oncomplete = () => resolve(request.result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error || new Error('Не удалось сохранить черновик'));
      });
    } finally {db.close();}
  }
  function base64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }
  function blob64(data, type) {
    const binary = atob(data), bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], {type});
  }
  async function writeDraft(json) {
    const draft = JSON.parse(json);
    draft.photos = draft.photos.map(photo => ({id: photo.id, name: photo.name,
      blob: blob64(photo.data, photo.mime), preview: blob64(photo.preview, photo.mime),
      ...(photo.capture ? {capture: photo.capture} : {})}));
    await transaction('readwrite', values => values.put(draft, draftKey));
  }
  function queueDraft(json) {
    writes = writes.catch(() => {}).then(() => writeDraft(json));
    return writes;
  }
  async function loadDraft() {
    const draft = await transaction('readonly', values => values.get(draftKey));
    if (!draft) return null;
    const age = Date.now() - draft.savedAt;
    if (!Number.isFinite(age) || age < -60000 || age >= 86400000) {
      await transaction('readwrite', values => values.delete(draftKey)); return null;
    }
    draft.photos = await Promise.all((draft.photos || []).map(async photo => ({
      id: photo.id, name: photo.name || 'photo.jpg', mime: photo.blob.type || 'image/jpeg',
      data: await base64(photo.blob), preview: await base64(photo.preview || photo.blob),
      ...(photo.capture ? {capture: photo.capture} : {}),
    })));
    return JSON.stringify(draft);
  }
  async function preparePhoto(file) {
    if (!/\.(jpe?g|png|webp|hei[cf])$/i.test(file.name) && !/^image\/(jpeg|png|webp|hei[cf])$/.test(file.type)) {
      throw new Error('Выберите фотографию JPG, PNG, WebP или HEIC');
    }
    if (file.size > 25 * 1024 * 1024) throw new Error('Одна фотография должна занимать не больше 25 МБ');
    let result = file;
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      await new Promise((resolve, reject) => {image.onload = resolve; image.onerror = reject; image.src = url;});
      const ratio = Math.min(1, 2560 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(image.naturalWidth * ratio); canvas.height = Math.round(image.naturalHeight * ratio);
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Не удалось подготовить фотографию');
      context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      result = await new Promise((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('Не удалось подготовить фотографию')), 'image/jpeg', .86));
    } catch (_) { /* Keep HEIC and other phone originals for the server's decoder. */ }
    finally {URL.revokeObjectURL(url);}
    const encoded = await base64(result);
    return {id: crypto.randomUUID(), name: file.name, mime: result.type || 'image/jpeg', data: encoded, preview: encoded};
  }
  async function pickPhotos(remaining) {
    const input = document.createElement('input');
    input.type = 'file'; input.multiple = true;
    input.accept = 'image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif';
    input.style.display = 'none'; document.body.append(input);
    try {
      const files = await new Promise(resolve => {
        input.onchange = () => resolve([...input.files]);
        input.oncancel = () => resolve([]);
        input.click();
      });
      if (files.length > remaining) throw new Error('Можно приложить до трёх фотографий');
      return JSON.stringify(await Promise.all(files.map(preparePhoto)));
    } finally {input.remove();}
  }
  let nextDropTarget = 0;
  const dropTargets = new Map();
  function registerDropTarget(bounds, started, photos, error) {
    const id = String(++nextDropTarget);
    dropTargets.set(id, {bounds, started, photos, error, busy: false});
    return id;
  }
  function unregisterDropTarget(id) {dropTargets.delete(id);}
  function dropTargetAt(event) {
    for (const target of [...dropTargets.values()].reverse()) {
      const bounds = JSON.parse(target.bounds());
      if (bounds && event.clientX >= bounds.left && event.clientX <= bounds.right &&
          event.clientY >= bounds.top && event.clientY <= bounds.bottom) return {target, bounds};
    }
    return null;
  }
  document.addEventListener('dragover', event => {
    if ([...(event.dataTransfer?.types || [])].includes('Files') && dropTargetAt(event)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
    }
  }, true);
  document.addEventListener('drop', async event => {
    const files = [...(event.dataTransfer?.files || [])], hit = dropTargetAt(event);
    if (!files.length || !hit) return;
    event.preventDefault(); event.stopPropagation();
    const {target, bounds} = hit;
    if (target.busy) return;
    target.busy = true; target.started();
    try {
      if (files.length > bounds.remaining) throw new Error('Можно приложить до трёх фотографий');
      const photos = await Promise.all(files.map(preparePhoto));
      await target.photos(JSON.stringify(photos));
    } catch (error) {
      target.error(error.message || 'Не удалось добавить фотографии. Выберите файлы ещё раз.');
    } finally {target.busy = false;}
  }, true);
  function loadMaps(key) {
    if (!key) return Promise.reject(new Error('Не указан ключ карты'));
    if (mapsPromise) return mapsPromise;
    mapsPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const fail = () => {clearTimeout(timer); script.remove(); mapsPromise = null; reject(new Error('Карта недоступна'));};
      const timer = setTimeout(fail, 25000);
      script.src = 'https://api-maps.yandex.ru/2.1.79/?' + new URLSearchParams({apikey: key, lang: 'ru_RU', coordorder: 'longlat', csp: 'true'});
      script.async = true; script.onerror = fail;
      script.onload = () => window.ymaps?.ready(() => {clearTimeout(timer); resolve(window.ymaps);});
      document.head.append(script);
    });
    return mapsPromise;
  }
  const polygons = geometry => geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  const escaped = value => String(value).replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const hasMapSize = element => {
    if (!element.isConnected) return false;
    const {width, height} = element.getBoundingClientRect();
    return width > 0 && height > 0;
  };
  const mapCancelled = () => new DOMException('Карта закрыта', 'AbortError');

  function waitForMapContainer(element, signal) {
    if (signal.aborted) return Promise.reject(mapCancelled());
    if (hasMapSize(element)) return Promise.resolve();
    // Flutter calls onElementCreated before attaching the element to the DOM.
    // One animation frame is not enough when a sliver returns during scrolling.
    return new Promise((resolve, reject) => {
      const observer = new ResizeObserver(check);
      function cleanup() {observer.disconnect(); signal.removeEventListener('abort', cancel);}
      function cancel() {cleanup(); reject(mapCancelled());}
      function check() {if (hasMapSize(element)) {cleanup(); resolve();}}
      signal.addEventListener('abort', cancel, {once: true});
      observer.observe(element);
      check();
    });
  }
  function cancelMap(element) {
    pendingMaps.get(element)?.abort();
    pendingMaps.delete(element);
  }
  function observeMapSize(element, record) {
    record.resize = new ResizeObserver(() => {
      if (!hasMapSize(element) || record.frame != null) return;
      record.frame = requestAnimationFrame(() => {
        record.frame = null;
        if (hasMapSize(element)) record.layer.container.fitToViewport();
      });
    });
    record.resize.observe(element);
  }
  async function createMap(element, configuration, point, organization) {
    cancelMap(element);
    const pending = new AbortController();
    pendingMaps.set(element, pending);
    let id;
    try {
      const cfg = JSON.parse(configuration), api = await loadMaps(cfg.apiKey);
      await waitForMapContainer(element, pending.signal);
      if (pending.signal.aborted) throw mapCancelled();
      const layer = new api.Map(element, {center: [72.6, 61.1], zoom: 11, controls: cfg.preview ? [] : ['zoomControl', 'fullscreenControl']}, {suppressMapOpenBlock: true});
      id = String(++nextMap);
      const record = {layer, marker: null, resize: null, frame: null};
      maps.set(id, record);
      const selectedPositions = [];
      const choosePoint = event => {
        const coordinates = event.get('coords');
        if (cfg.picking && Array.isArray(coordinates) && coordinates.length === 2 && coordinates.every(Number.isFinite)) point(coordinates[0], coordinates[1]);
      };
      layer.events.add('click', choosePoint);
      for (const owner of cfg.organizations) for (const territory of owner.territories) for (const shape of polygons(territory.geometry)) {
        const selected = owner.id === cfg.organizationId && (!cfg.districtId || territory.id === cfg.districtId);
        const color = cfg.overview && selected ? '#438aff' : owner.color;
        const polygon = new api.Polygon(shape, {hintContent: escaped(owner.name + ' · ' + territory.name)}, {
          fillColor: color, fillOpacity: selected ? .24 : .08, strokeColor: color,
          strokeWidth: selected ? 3 : 1, openBalloonOnClick: false,
        });
        polygon.events.add('click', event => cfg.picking ? choosePoint(event) : organization(owner.id));
        layer.geoObjects.add(polygon);
        if (selected) selectedPositions.push(...shape.flat());
      }
      const bounds = selectedPositions.length ? [
        [Math.min(...selectedPositions.map(p => p[0])), Math.min(...selectedPositions.map(p => p[1]))],
        [Math.max(...selectedPositions.map(p => p[0])), Math.max(...selectedPositions.map(p => p[1]))],
      ] : layer.geoObjects.getBounds();
      if (bounds) {
        if (cfg.preview) {
          layer.setCenter([(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2], 12);
        } else {
          layer.setBounds(bounds, {checkZoomRange: true, zoomMargin: 30});
        }
      }
      if (cfg.point) setMapPoint(id, ...cfg.point);
      observeMapSize(element, record);
      return id;
    } catch (error) {
      if (id) destroyMap(id);
      throw error;
    } finally {
      if (pendingMaps.get(element) === pending) pendingMaps.delete(element);
    }
  }
  function setMapPoint(id, longitude, latitude) {
    const record = maps.get(id);
    if (!record) return;
    if (record.marker) record.layer.geoObjects.remove(record.marker);
    record.marker = new window.ymaps.Placemark([longitude, latitude], {iconCaption: 'Место проблемы'}, {preset: 'islands#greenDotIcon'});
    record.layer.geoObjects.add(record.marker);
  }
  function destroyMap(id) {
    const record = maps.get(id);
    if (!record) return;
    record.resize?.disconnect();
    if (record.frame != null) cancelAnimationFrame(record.frame);
    record.layer.destroy();
    maps.delete(id);
  }
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
  document.addEventListener('visibilitychange', () => {if (document.hidden && latestDraft) void queueDraft(latestDraft).catch(() => {});});
  window.addEventListener('pagehide', () => {if (latestDraft) void queueDraft(latestDraft).catch(() => {});});
  window.signalBrowser = {
    loadDraft, saveDraft: async json => {latestDraft = json; await queueDraft(json);}, pickPhotos,
    setDirty: value => {dirty = value;}, registerDropTarget, unregisterDropTarget, createMap, cancelMap, destroyMap, setMapPoint,
    listen: (connectivity, activity) => {
      const id = String(++nextListener), online = () => connectivity(navigator.onLine), focus = () => {if (!document.hidden) activity();};
      window.addEventListener('online', online); window.addEventListener('offline', online);
      window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus);
      listeners.set(id, {online, focus}); return id;
    },
    unlisten: id => {
      const listener = listeners.get(id); if (!listener) return;
      window.removeEventListener('online', listener.online); window.removeEventListener('offline', listener.online);
      window.removeEventListener('focus', listener.focus); document.removeEventListener('visibilitychange', listener.focus);
      listeners.delete(id);
    },
  };
})();
