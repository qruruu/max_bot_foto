// No third-party scripts. Choosing a recipient and sending stay inside the selected app.
const button = document.getElementById('copy-link');
button?.addEventListener('click', async () => {
  const status = document.getElementById('copy-status');
  const manual = document.getElementById('copy-manual');
  try {
    await navigator.clipboard.writeText(button.dataset.url);
    status.textContent = 'Ссылка скопирована';
    manual.hidden = true;
  } catch {
    status.textContent = '';
    manual.hidden = false;
    const input = manual.querySelector('input');
    input.focus();
    input.select();
  }
});
