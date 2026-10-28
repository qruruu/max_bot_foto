/* First-party aggregate analytics. No IP lookup, full URLs, forms or external SDKs. */
(() => {
  if (navigator.doNotTrack === '1') return;
  let memoryVisitor = '', active = null, lastView = '', lastViewAt = 0;
  const memorySessions = {};
  const uuid = () => crypto.randomUUID();
  const read = (store, key) => {try {return store.getItem(key);} catch {return null;}};
  const write = (store, key, value) => {try {store.setItem(key, value);} catch { /* ephemeral IDs only */ }};
  function source() {
    const params = new URLSearchParams(location.search);
    const tagged = (params.get('from') || params.get('utm_source') || '').toLowerCase();
    const names = {max:'max', telegram:'telegram', tg:'telegram', vk:'vk', qr:'qr'};
    let host = '';
    try {host = new URL(document.referrer).hostname;} catch { /* no referrer */ }
    if (names[tagged]) return {source:names[tagged], host:'', tagged:true};
    if (!host || host === location.hostname) return {source:'direct', host:'', tagged:false};
    if (/(^|\.)max\.ru$/.test(host)) return {source:'max', host:'', tagged:false};
    if (/(^|\.)(t\.me|telegram\.org)$/.test(host)) return {source:'telegram', host:'', tagged:false};
    if (/(^|\.)vk\.(com|ru)$/.test(host)) return {source:'vk', host:'', tagged:false};
    if (/(^|\.)(yandex\.(ru|com)|ya\.ru|google\.[a-z.]+|bing\.com|duckduckgo\.com)$/.test(host)) return {source:'search', host, tagged:false};
    return {source:'referral', host, tagged:false};
  }
  function session(product) {
    let visitor;
    try {visitor = read(localStorage, 'metka-usage-visitor');} catch { /* storage unavailable */ }
    if (!visitor) {visitor = memoryVisitor || uuid(); memoryVisitor = visitor; try {write(localStorage, 'metka-usage-visitor', visitor);} catch {}}
    const entry = source();
    let current;
    try {current = JSON.parse(read(sessionStorage, 'metka-usage-' + product) || 'null');} catch {}
    current = current || memorySessions[product];
    if (!current || Date.now() - current.last > 30 * 60 * 1000 || entry.tagged && entry.source !== current.source) {
      current = {id:uuid(), source:entry.source, host:entry.host, last:Date.now()};
    }
    current.last = Date.now();
    memorySessions[product] = current;
    try {write(sessionStorage, 'metka-usage-' + product, JSON.stringify(current));} catch {}
    return {current, visitor};
  }
  function send(product, page, heartbeat = false) {
    if (document.hidden) return;
    const {current, visitor} = session(product);
    const ua = navigator.userAgent;
    const device = /iPad|Tablet/.test(ua) ? 'tablet' : /Mobile|iPhone|Android/.test(ua) ? 'phone' : 'desktop';
    const body = {visitor_id:visitor, session_id:current.id, event_id:uuid(), product, page,
      source:current.source, referrer_host:current.host, device, heartbeat};
    fetch('/api/public/metrics/visit', {method:'POST', credentials:'include', keepalive:true,
      headers:{'Content-Type':'application/json', 'X-Usage-Event':'page'}, body:JSON.stringify(body)}).catch(() => {});
  }
  window.MetkaUsage = {page(product, page, key = page) {
    const view = product + ':' + key;
    if (view === lastView && Date.now() - lastViewAt < 1000) return;
    lastView = view; lastViewAt = Date.now(); active = {product, page}; send(product, page);
  }, event(product, page) {send(product, page);}};
  setInterval(() => {if (active) send(active.product, active.page, true);}, 60000);
  document.addEventListener('DOMContentLoaded', () => {
    const page = document.body.dataset.usagePage;
    if (page) window.MetkaUsage.page('signal', page);
  });
})();
