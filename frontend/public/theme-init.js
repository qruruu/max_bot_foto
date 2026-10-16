// Run before the app and stylesheet so a saved dark theme does not flash light.
(() => {
  let theme = 'light';
  try {
    if (localStorage.getItem('max-photo-theme') === 'dark') theme = 'dark';
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();
