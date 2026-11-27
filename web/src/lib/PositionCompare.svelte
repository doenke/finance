<script lang="ts">
  // Positions side by side: indexed price chart, weights, risk vs. return, key figures and correlations.
  import Info from './Info.svelte';
  import { api } from './api.ts';
  import BarList from './charts/BarList.svelte';
  import LineChart, { type Series } from './charts/LineChart.svelte';
  import { formatMoney, formatPercent, toNumber } from './format.ts';
  import Money from './Money.svelte';
  import PeriodPicker from './PeriodPicker.svelte';

  interface Item {
    instrument_id: number;
    name: string;
    isin: string | null;
    kind: string;
    value: string;
    cost: string;
    gain: string;
    gain_pct: number | null;
    weight: number | null;
    returns: Record<string, number | null>;
    period_return: number | null;
    volatility: number | null;
    max_drawdown: number | null;
    history_from: string | null;
    points: (number | null)[];
    candidate: boolean;
  }
  interface Compare {
    from: string;
    to: string;
    total_value: string;
    dates: string[];
    items: Item[];
    correlation: (number | null)[][];
  }

  let {
    accountId = null,
    personId = null,
    title = 'Positionen im Vergleich',
    period = $bindable('1Y'),
    showPeriod = true
  }: { accountId?: number | null; personId?: number | null; title?: string; period?: string; showPeriod?: boolean } = $props();
  let data = $state<Compare | null>(null);
  let error = $state('');

  // Candidates: securities you think about buying, compared alongside (remembered on this device).
  const KEY = 'finanzen:compare-candidates';
  function loadCandidates(): number[] {
    try {
      return JSON.parse(localStorage.getItem(KEY) ?? '[]').filter((x: unknown) => Number.isInteger(x));
    } catch {
      return [];
    }
  }
  let candidates = $state<number[]>(loadCandidates());
  function saveCandidates(ids: number[]) {
    candidates = ids.slice(0, 3);
    try {
      localStorage.setItem(KEY, JSON.stringify(candidates));
    } catch {
      // ignore
    }
  }
  let query = $state('');
  let adding = $state(false);
  let addError = $state('');
  async function addCandidate(e: SubmitEvent) {
    e.preventDefault();
    if (query.trim().length < 2) return;
    adding = true;
    addError = '';
    try {
      const c = await api.post<{ instrument_id: number }>('/api/prices/candidates', { query: query.trim() });
      if (!candidates.includes(c.instrument_id)) saveCandidates([...candidates, c.instrument_id]);
      query = '';
    } catch (err) {
      addError = (err as Error).message;
    } finally {
      adding = false;
    }
  }

  $effect(() => {
    const q = new URLSearchParams({ period });
    if (accountId !== null) q.set('account_id', String(accountId));
    if (personId !== null) q.set('person_id', String(personId));
    if (candidates.length) q.set('extra', candidates.join(','));
    api
      .get<Compare>(`/api/positions/compare?${q}`)
      .then((d) => {
        data = d;
        error = '';
      })
      .catch((e) => (error = (e as Error).message));
  });

  const MAX_SERIES = 5;
  // The five largest positions get a color; colors follow the stable order of the instruments, not their rank.
  const charted = $derived.by(() => {
    const items = data?.items ?? [];
    const held = items.filter((i) => !i.candidate);
    const top = new Set([...held].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).slice(0, MAX_SERIES).map((i) => i.instrument_id));
    return [...items.filter((i) => top.has(i.instrument_id)), ...items.filter((i) => i.candidate)];
  });
  const colorOf = (id: number) => {
    const i = charted.findIndex((c) => c.instrument_id === id);
    return i >= 0 ? `var(--series-${(i % 8) + 1})` : 'var(--muted)';
  };
  const series = $derived<Series[]>(
    charted.map((it) => ({
      key: String(it.instrument_id),
      label: it.name,
      color: colorOf(it.instrument_id),
      dashed: it.candidate,
      points: (data?.dates ?? []).map((d, k) => ({ date: d, value: it.points[k] }))
    }))
  );
  const pct = (v: number) => `${v > 0 ? '+' : ''}${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 1 })} %`;
  const pctOrDash = (v: number | null | undefined) => (v === null || v === undefined ? '–' : formatPercent(v * 100));
  const weights = $derived(
    [...(data?.items ?? [])].filter((i) => !i.candidate).sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).map((i) => ({ key: String(i.instrument_id), label: i.name, value: toNumber(i.value), color: colorOf(i.instrument_id) }))
  );
  const eur = (v: number) => formatMoney(v, 'EUR', false);

  // Scatter: risk (x) vs. return of the chosen period (y)
  const W = 520;
  const H = 300;
  const pad = { l: 52, r: 16, t: 16, b: 40 };
  const dots = $derived((data?.items ?? []).filter((i) => i.volatility !== null && i.period_return !== null));
  const xMax = $derived(Math.max(0.05, ...dots.map((d) => d.volatility as number)) * 1.15);
  const yMin = $derived(Math.min(0, ...dots.map((d) => d.period_return as number)));
  const yMax = $derived(Math.max(0.05, ...dots.map((d) => d.period_return as number)));
  const ySpan = $derived((yMax - yMin) * 1.2 || 0.1);
  const yLo = $derived(yMin - (ySpan - (yMax - yMin)) / 2);
  const sx = (v: number) => pad.l + (v / xMax) * (W - pad.l - pad.r);
  const sy = (v: number) => pad.t + (1 - (v - yLo) / ySpan) * (H - pad.t - pad.b);
  const ticks = (lo: number, hi: number, n = 4) => Array.from({ length: n + 1 }, (_, k) => lo + ((hi - lo) * k) / n);

  // Correlation cell color: blue = move together, red = opposite, gray = unrelated
  function cellColor(c: number | null): string {
    if (c === null) return 'transparent';
    const share = Math.round(Math.min(1, Math.abs(c)) * 85);
    return `color-mix(in oklab, var(${c >= 0 ? '--div-pos' : '--div-neg'}) ${share}%, var(--div-mid))`;
  }
  const short = (name: string) => (name.length > 18 ? `${name.slice(0, 17)}…` : name);
  const periodLabel: Record<string, string> = { '1M': '1 Monat', YTD: 'seit Jahresbeginn', '1Y': '1 Jahr', '3Y': '3 Jahre', '5Y': '5 Jahre', ALL: 'seit Beginn' };
</script>

{#if error}
  <p class="error">{error}</p>
{:else if data && (data.items.length >= 2 || candidates.length)}
  <section class="card stack">
    <div class="row head">
      <h2>{title}</h2>
      {#if showPeriod}<PeriodPicker bind:value={period} />{/if}
    </div>
    <form class="row cand" onsubmit={addCandidate}>
      <input bind:value={query} placeholder="ISIN oder Name eines Fonds, ETFs, einer Aktie …" aria-label="Wertpapier zum Vergleich" />
      <button class="btn" type="submit" disabled={adding}>{adding ? 'Lädt Kurse …' : 'Zum Vergleich'}</button>
    </form>
    {#if addError}<p class="error small">{addError}</p>{/if}
    {#if candidates.length}
      <div class="chips" aria-label="Wertpapiere zum Vergleich">
        {#each candidates as id (id)}
          {@const it = data.items.find((x) => x.instrument_id === id)}
          <span class="chip">
            <span class="swatch dash" style:border-color={colorOf(id)}></span>
            {it?.name ?? 'Wertpapier'}
            <button aria-label="{it?.name ?? 'Wertpapier'} aus dem Vergleich nehmen" title="Aus dem Vergleich nehmen" onclick={() => saveCandidates(candidates.filter((c) => c !== id))}>×</button>
          </span>
        {/each}
        {#if candidates.length > 1}<button class="link small" onclick={() => saveCandidates([])}>alle entfernen</button>{/if}
      </div>
      <p class="muted small">Gestrichelt: Wertpapiere zum Vergleich, die ihr (noch) nicht habt. Sie zählen bei Gewichtung und Wert nicht mit.</p>
    {/if}

    <div>
      <h3>Kursentwicklung ({periodLabel[period]})</h3>
      <LineChart {series} format={pct} zeroLine ariaLabel="Kursentwicklung der Positionen im Vergleich" />
      {#if data.items.length > MAX_SERIES}<p class="muted small">Gezeigt werden die {MAX_SERIES} größten Positionen.</p>{/if}
    </div>

    <div class="split">
      <div>
        <h3>Gewichtung</h3>
        <BarList items={weights} format={eur} money />
      </div>
      <div>
        <h3>Rendite und Schwankung<Info>Oben links ist gut: viel Rendite bei wenig Schwankung. Schwankung = annualisierte Standardabweichung der Tagesrenditen im gewählten Zeitraum.</Info></h3>
        {#if dots.length >= 2}
          <svg viewBox="0 0 {W} {H}" class="scatter" role="img" aria-label="Rendite im Zeitraum gegen Schwankung pro Jahr">
            {#each ticks(0, xMax) as t, ti (ti)}
              <line x1={sx(t)} x2={sx(t)} y1={pad.t} y2={H - pad.b} class="grid" />
              <text x={sx(t)} y={H - pad.b + 16} text-anchor="middle" class="tick">{Math.round(t * 100)} %</text>
            {/each}
            {#each ticks(yLo, yLo + ySpan) as t, ti (ti)}
              <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} class="grid" class:zero={Math.abs(t) < 1e-9} />
              <text x={pad.l - 6} y={sy(t)} text-anchor="end" dominant-baseline="middle" class="tick">{Math.round(t * 100)} %</text>
            {/each}
            {#if yLo < 0 && yLo + ySpan > 0}<line x1={pad.l} x2={W - pad.r} y1={sy(0)} y2={sy(0)} class="axis0" />{/if}
            <text x={W - pad.r} y={H - 4} text-anchor="end" class="axis-label">Schwankung p. a. →</text>
            <text x={pad.l} y={10} class="axis-label">↑ Rendite {periodLabel[period]}</text>
            {#each dots as d (d.instrument_id)}
              <g>
                <title>{d.name}: Rendite {pct(d.period_return as number)}, Schwankung {Math.round((d.volatility as number) * 100)} % p. a.</title>
                <circle cx={sx(d.volatility as number)} cy={sy(d.period_return as number)} r="12" fill="transparent" />
                <circle cx={sx(d.volatility as number)} cy={sy(d.period_return as number)} r="6" fill={colorOf(d.instrument_id)} class="dot" />
                {#if dots.length <= 6}
                  <text x={sx(d.volatility as number) + 9} y={sy(d.period_return as number) - 8} class="dot-label">{short(d.name)}</text>
                {/if}
              </g>
            {/each}
          </svg>
        {:else}
          <p class="muted small">Für dieses Diagramm fehlen noch Kurse – sie werden nach dem nächsten Kursabruf nachgeladen.</p>
        {/if}
      </div>
    </div>

    <div>
      <h3>Kennzahlen<Info>Renditen hier sind reine Kursentwicklung (ohne Ausschüttungen) – gut für den Vergleich der Wertpapiere untereinander. „–“ heißt: so weit reichen die Kurse nicht zurück.</Info></h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Position</th>
              <th class="r">Wert</th>
              <th class="r">Anteil</th>
              <th class="r">G/V seit Kauf</th>
              <th class="r">1 M</th>
              <th class="r">YTD</th>
              <th class="r">1 J</th>
              <th class="r">3 J</th>
              <th class="r">5 J</th>
              <th class="r" title="Annualisierte Schwankung der Tagesrenditen im letzten Jahr">Schwankung</th>
              <th class="r" title="Größter Rückgang vom Höchststand im gewählten Zeitraum">Max. Rückgang</th>
            </tr>
          </thead>
          <tbody>
            {#each data.items as i (i.instrument_id)}
              <tr>
                <td class="name">
                  <span class="swatch" style:background={colorOf(i.instrument_id)}></span><a href="/wertpapiere/{i.instrument_id}">{i.name}</a>
                  {#if i.candidate}
                    <span class="badge">zum Vergleich</span>
                    <button class="x" aria-label="{i.name} aus dem Vergleich nehmen" title="Aus dem Vergleich nehmen" onclick={() => saveCandidates(candidates.filter((c) => c !== i.instrument_id))}>×</button>
                  {/if}
                </td>
                {#if i.candidate}
                  <td class="r muted">–</td>
                  <td class="r muted">–</td>
                  <td class="r muted">–</td>
                {:else}
                  <td class="r"><Money value={i.value} cents={false} /></td>
                  <td class="r num">{i.weight === null ? '–' : `${Math.round(i.weight * 100)} %`}</td>
                  <td class="r"><Money value={i.gain} cents={false} colored /> <span class="muted small">{pctOrDash(i.gain_pct)}</span></td>
                {/if}
                {#each ['1M', 'YTD', '1Y', '3Y', '5Y'] as p (p)}
                  <td class="r num" class:pos={(i.returns[p] ?? 0) > 0} class:neg={(i.returns[p] ?? 0) < 0}>{pctOrDash(i.returns[p])}</td>
                {/each}
                <td class="r num">{i.volatility === null ? '–' : `${Math.round(i.volatility * 100)} %`}</td>
                <td class="r num neg">{i.max_drawdown === null || i.max_drawdown === 0 ? '–' : formatPercent(i.max_drawdown * 100)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    {#if data.items.length >= 2}
      <details class="corr">
        <summary><h3>Wie ähnlich bewegen sie sich? <span class="muted small">(Korrelation, {periodLabel[period]})</span></h3></summary>
        <div class="table-wrap">
          <table class="heat">
            <thead>
              <tr>
                <th></th>
                {#each data.items as i (i.instrument_id)}<th class="colhead" title={i.name}><span class="swatch" style:background={colorOf(i.instrument_id)}></span>{short(i.name)}</th>{/each}
              </tr>
            </thead>
            <tbody>
              {#each data.items as row, r (row.instrument_id)}
                <tr>
                  <th class="rowhead" title={row.name}><span class="swatch" style:background={colorOf(row.instrument_id)}></span>{short(row.name)}</th>
                  {#each data.correlation[r] as c, k (k)}
                    <td
                      class="cell"
                      class:strong={c !== null && Math.abs(c) >= 0.6}
                      style:background={cellColor(c)}
                      title="{row.name} / {data.items[k].name}: {c === null ? 'zu wenig gemeinsame Kurse' : c.toLocaleString('de-DE', { maximumFractionDigits: 2 })}"
                    >
                      {c === null ? '–' : c.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="muted small">
          1 = bewegen sich gleich, 0 = unabhängig, −1 = gegenläufig. Je niedriger die Werte, desto besser streuen die Positionen das Risiko.
          <span class="legend"><i style:background="var(--div-neg)"></i>gegenläufig <i style:background="var(--div-mid)"></i>unabhängig <i style:background="var(--div-pos)"></i>gleichläufig</span>
        </p>
      </details>
    {/if}
    {#if accountId !== null}<a class="small" href="/anlagen">Alle Depots zusammen vergleichen →</a>{/if}
  </section>
{/if}

<style>
  h2,
  h3 {
    margin: 0;
  }
  h3 {
    font-size: 1rem;
    margin-bottom: 8px;
  }
  .head {
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
  }
  .small {
    font-size: 0.8rem;
  }
  p.small {
    margin: 6px 0 0;
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
    gap: 24px;
  }
  .scatter {
    width: 100%;
    height: auto;
    display: block;
  }
  .grid {
    stroke: var(--grid);
    stroke-width: 1;
  }
  .axis0 {
    stroke: var(--muted);
    stroke-width: 1;
    opacity: 0.6;
  }
  .tick,
  .axis-label {
    fill: var(--muted);
    font-size: 13px;
  }
  .dot {
    stroke: var(--surface);
    stroke-width: 2;
  }
  .dot-label {
    fill: var(--text);
    font-size: 13px;
  }
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th,
  td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    text-align: left;
  }
  th {
    color: var(--muted);
    font-weight: 500;
  }
  .r {
    text-align: right;
  }
  .pos {
    color: var(--pos);
  }
  .neg {
    color: var(--neg);
  }
  .name a {
    color: inherit;
    text-decoration: none;
  }
  .name a:hover {
    text-decoration: underline;
  }
  .swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
    vertical-align: -1px;
  }
  .heat {
    width: auto;
  }
  .heat td,
  .heat th {
    border: 2px solid var(--surface);
  }
  .cell {
    text-align: center;
    min-width: 64px;
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  .cell.strong {
    color: #fff;
  }
  .colhead {
    font-size: 0.8rem;
  }
  .rowhead {
    font-size: 0.85rem;
  }
  .legend {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    margin-left: 8px;
  }
  .legend i {
    display: inline-block;
    width: 12px;
    height: 10px;
    border-radius: 3px;
    margin-left: 6px;
  }
  .corr summary {
    cursor: pointer;
    list-style-position: outside;
  }
  .corr summary h3 {
    display: inline;
  }
  .corr[open] summary {
    margin-bottom: 8px;
  }
  .cand {
    gap: 8px;
    flex-wrap: wrap;
  }
  .cand input {
    flex: 1;
    min-width: 200px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 4px 3px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.85rem;
  }
  .chip button {
    border: 0;
    background: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 1.1rem;
    line-height: 1;
    padding: 0 6px;
  }
  .chip button:hover {
    color: var(--neg);
  }
  .swatch.dash {
    display: inline-block;
    width: 16px;
    height: 0;
    border-top: 2px dashed;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--accent-strong);
    cursor: pointer;
    font: inherit;
  }
  .badge {
    margin-left: 6px;
    padding: 1px 6px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-size: 0.7rem;
    font-weight: 600;
  }
  .x {
    margin-left: 4px;
    border: 0;
    background: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
  }
  .x:hover {
    color: var(--neg);
  }
</style>
