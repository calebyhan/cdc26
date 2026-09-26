(async () => {
  const appWindow = document.querySelector('iframe[title="streamlitApp"]')?.contentWindow || window;
  const doc = appWindow.document;
  const view = window.ewsBenchmarkView;
  const minimumCharts = {'Risk leaderboard':0,'Company detail':3,'Enforcement timeline':2,'Backtest results':3,'Limitations':0};
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  let stableAt = null;
  while (performance.now()-window.ewsBenchmarkStarted < 15000) {
    const title = [...doc.querySelectorAll('h1')].some(node => node.textContent.trim()===view);
    const footer = [...doc.querySelectorAll('p')].some(node => node.textContent.includes('View prepared in'));
    const charts = [...doc.querySelectorAll('[data-testid="stPlotlyChart"]')];
    const drawn = charts.every(node => node.querySelector(".js-plotly-plot .main-svg"));
    const idle = doc.querySelector("[data-testid=stApp]")?.getAttribute("data-test-script-state") === "notRunning";
    const ready = title && footer && idle && drawn && charts.length >= minimumCharts[view];
    if (ready) {
      stableAt ??= performance.now();
      if (performance.now()-stableAt >= 150) break;
    } else stableAt = null;
    await sleep(20);
  }
  if (stableAt === null) throw new Error(`View did not finish rendering: ${view}`);
  return {seconds:(performance.now()-window.ewsBenchmarkStarted)/1000,url:location.origin};
})()
