<script lang="ts">
  // Positions side by side: indexed price chart, weights, risk vs. return, key figures and correlations.
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
  }
  interface Compare {
    from: string;
    to: string;
    total_value: string;
    dates: string[];
    items: Item[];
    correlation: (number | null)[][];
  }

  let { accountId = null, personId = null, title = 'Positionen im Vergleich' }: { accountId?: number | null; personId?: number | null; title?: string } = $props();
  let period = $state('1Y');
  let data = $state<Compare | null>(null);
  let error = $state('');

  $effect(() => {
    const q = new URLSearchParams({ period });
    if (accountId !== null) q.set('account_id', String(accountId));
    if (personId !== null) q.set('person_id', String(personId));
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
    const top = new Set([...items].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).slice(0, MAX_SERIES).map((i) => i.instrument_id));
    return items.filter((i) => top.has(i.instrument_id));
  });
  const colorOf = (id: number) => {
    const i = charted.findIndex((c) => c.instrument_id === id);
    return i >= 0 ? `var(--series-${i + 1})` : 'var(--muted)';
  };
  const series = $derived<Series[]>(
    charted.map((it) => ({
      key: String(it.instrument_id),
      label: it.name,
      color: colorOf(it.instrument_id),
      points: (data?.dates ?? []).map((d, k) => ({ date: d, value: it.points[k] }))
    }))
  );
  const pct = (v: number) => `${v > 0 ? '+' : ''}${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 1 })} %`;
  const pctOrDash = (v: number | null | undefined) => (v === null || v === undefined ? '–' : formatPercent(v * 100));
  const weights = $derived(
    [...(data?.items ?? [])].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).map((i) => ({ key: String(i.instrument_id), label: i.name, value: toNumber(i.value), color: colorOf(i.instrument_id) }))
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
{:else if data && data.items.length >= 2}
  <section class="card stack">
    <div class="row head">
      <h2>{title}</h2>
      <PeriodPicker bind:value={period} />
    </div>

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
        <h3>Rendite und Schwankung</h3>
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
          <p class="muted small">Oben links ist gut: viel Rendite bei wenig Schwankung. Schwankung = annualisierte Standardabweichung der Tagesrenditen im letzten Jahr.</p>
        {:else}
          <p class="muted small">Für dieses Diagramm fehlen noch Kurse – sie werden nach dem nächsten Kursabruf nachgeladen.</p>
        {/if}
      </div>
    </div>

    <div>
      <h3>Kennzahlen</h3>
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
                <td class="name"><span class="swatch" style:background={colorOf(i.instrument_id)}></span><a href="/wertpapiere/{i.instrument_id}">{i.name}</a></td>
                <td class="r"><Money value={i.value} cents={false} /></td>
                <td class="r num">{i.weight === null ? '–' : `${Math.round(i.weight * 100)} %`}</td>
                <td class="r"><Money value={i.gain} cents={false} colored /> <span class="muted small">{pctOrDash(i.gain_pct)}</span></td>
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
      <p class="muted small">Renditen hier sind reine Kursentwicklung (ohne Ausschüttungen) – gut für den Vergleich der Wertpapiere untereinander. „–“ heißt: so weit reichen die Kurse nicht zurück.</p>
    </div>

    {#if data.items.length >= 2}
      <div>
        <h3>Wie ähnlich bewegen sie sich? <span class="muted small">(Korrelation, {periodLabel[period]})</span></h3>
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
      </div>
    {/if}
    {#if accountId !== null}<a class="small" href="/wertpapiere">Alle Depots zusammen vergleichen →</a>{/if}
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
</style>
