(async () => {
  const views = ['Risk leaderboard','Company detail','Enforcement timeline','Backtest results','Limitations'];
  const minimumCharts = {'Risk leaderboard':0,'Company detail':3,'Enforcement timeline':3,'Backtest results':3,'Limitations':0};
  const results = {};
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  for (const view of views) {
    const label = [...document.querySelectorAll('label')].find(node => node.textContent.trim() === view);
    if (!label) throw new Error(`Navigation label missing: ${view}`);
    const started = performance.now();
    label.click();
    let stableAt = null;
    while (performance.now()-started < 15000) {
      const title = [...document.querySelectorAll('h1')].some(node => node.textContent.trim()===view);
      const footer = [...document.querySelectorAll('p')].some(node => node.textContent.includes('View prepared in'));
      const charts = document.querySelectorAll('.js-plotly-plot .main-svg').length;
      const busy = document.querySelector('[data-testid="stStatusWidget"] button');
      const ready = title && footer && charts >= minimumCharts[view] && !busy;
      if (ready) {
        stableAt ??= performance.now();
        if (performance.now()-stableAt >= 150) break;
      } else stableAt = null;
      await sleep(20);
    }
    if (stableAt === null) throw new Error(`View did not finish rendering: ${view}`);
    results[view] = {seconds:(performance.now()-started)/1000};
  }
  return {
    scope:'browser view switching after initial assets load; includes chart rendering and 150ms stability window',
    public_url:location.origin,
    measured_at:new Date().toISOString(),
    initial_page_load_verified:false,
    views:results,
  };
})()
