// Observe first-page readiness from navigation start, including Cloud's wrapper.
(() => {
  if (window.top !== window) return;
  let stableAt = null;
  const timer = setInterval(() => {
    let doc = document;
    const frame = document.querySelector('iframe[title="streamlitApp"]');
    if (frame) {
      try { doc = frame.contentDocument; } catch { return; }
    }
    if (!doc) return;
    const heading = [...doc.querySelectorAll('h1')].some(node => node.textContent.trim() === 'Complaint change monitor');
    const footer = [...doc.querySelectorAll('p')].some(node => node.textContent.includes('View prepared in'));
    const idle = doc.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning';
    const table = doc.querySelector('.screening-table tbody tr');
    const ready = heading && footer && idle && table;
    if (ready) {
      stableAt ??= performance.now();
      if (performance.now()-stableAt >= 150) {
        window.ewsInitialLoad = {
          seconds: performance.now()/1000,
          scope: 'Fresh browser first navigation through full leaderboard readiness; includes Cloud wrapper, network, assets, app session and 150ms stability window',
          measured_at: new Date().toISOString(),
        };
        clearInterval(timer);
      }
    } else stableAt = null;
  }, 20);
  setTimeout(() => clearInterval(timer), 60000);
})();
