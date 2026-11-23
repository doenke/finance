<script lang="ts">
  // Returns of a scope (household, account, person) with chart, benchmark and period table.
  import { api, type Instrument, type PerformanceData } from './api.ts';
  import { benchmarkChoice, setBenchmark } from './benchmark.svelte.ts';
  import LineChart, { type Series } from './charts/LineChart.svelte';
  import { formatMoney, formatPercent, toNumber } from './format.ts';
  import Money from './Money.svelte';
  import PeriodPicker from './PeriodPicker.svelte';

  let { title = 'Rendite', params = {}, showTable = true }: { title?: string; params?: Record<string, string | number | null>; showTable?: boolean } = $props();

  let period = $state('1Y');
  let mode = $state<'return' | 'value'>('return');
  let data = $state<PerformanceData | null>(null);
  let bench = $state<{ date: string; ttwror: string | null }[]>([]);
  let instruments = $state<Instrument[]>([]);
  let loading = $state(true);
  let error = $state('');

  const query = $derived(
    Object.entries(params)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join('&')
  );

  $effect(() => {
    const q = query;
    const p = period;
    loading = true;
    api
      .get<PerformanceData>(`/api/performance?period=${p}${q ? `&${q}` : ''}`)
      .then((d) => {
        data = d;
        error = '';
      })
      .catch((e) => (error = (e as Error).message))
      .finally(() => (loading = false));
  });

  $effect(() => {
    api.get<Instrument[]>('/api/instruments').then((list) => (instruments = list.filter((i) => i.last_price)));
  });

  $effect(() => {
    const id = benchmarkChoice.id;
    const from = data?.from;
    if (!id || !from) {
      bench = [];
      return;
    }
    api
      .get<{ date: string; ttwror: string | null }[]>(`/api/benchmark/${id}?start=${from}&end=${data?.to}`)
      .then((b) => (bench = b))
      .catch(() => (bench = []));
  });

  const pct = (v: number) => `${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 1 })} %`;
  const eur = (v: number) => formatMoney(v, 'EUR', false);

  const chartSeries = $derived.by((): Series[] => {
    const s = data?.series ?? [];
    if (mode === 'value') {
      return [
        { key: 'value', label: 'Wert', color: 'var(--series-1)', points: s.map((p) => ({ date: p.date, value: toNumber(p.value) })) },
        { key: 'invested', label: 'Eingezahlt', color: 'var(--series-2)', dashed: true, points: s.map((p) => ({ date: p.date, value: toNumber(p.invested) })) }
      ];
    }
    const out: Series[] = [{ key: 'ttwror', label: 'Eure Rendite (TTWROR)', color: 'var(--series-1)', points: s.map((p) => ({ date: p.date, value: toNumber(p.ttwror) })) }];
    if (bench.length && s.length) {
      // Align the benchmark to our dates (both are sampled from the same range).
      const byDate = new Map(bench.map((b) => [b.date, b.ttwror === null ? null : toNumber(b.ttwror)]));
      let last: number | null = null;
      const points = s.map((p) => {
        const v = byDate.get(p.date);
        if (v !== undefined) last = v;
        return { date: p.date, value: v !== undefined ? v : last };
      });
      const name = instruments.find((i) => i.id === benchmarkChoice.id)?.name ?? 'Benchmark';
      out.push({ key: 'bench', label: name, color: 'var(--series-2)', points });
    }
    return out;
  });

  const periodLabels: Record<string, string> = { '1M': '1 Monat', YTD: 'Seit Jahresbeginn', '1Y': '1 Jahr', '3Y': '3 Jahre', '5Y': '5 Jahre', ALL: 'Seit Beginn' };
  const fmtRate = (v: string | null | undefined) => (v === null || v === undefined ? '–' : formatPercent(toNumber(v) * 100));
</script>

<section class="card stack">
  <div class="row head">
    <h2>{title}</h2>
    <PeriodPicker bind:value={period} />
  </div>
  {#if error}
    <p class="error">{error}</p>
  {:else if data && !data.summary}
    <p class="muted">Noch keine Daten für eine Auswertung.</p>
  {:else if data?.summary}
    {@const s = data.summary}
    <div class="tiles" class:loading>
      <div><span class="muted">Wert</span><strong><Money value={s.end_value} cents={false} /></strong></div>
      <div><span class="muted">Ein-/Auszahlungen</span><strong><Money value={s.net_flows} cents={false} /></strong></div>
      <div><span class="muted">Gewinn</span><strong><Money value={s.gain} cents={false} colored /></strong></div>
      <div>
        <span class="muted" title="Zeitgewichtete Rendite: wie gut die Anlagen selbst gelaufen sind – unabhängig davon, wann ihr Geld ein- oder ausgezahlt habt.">TTWROR ⓘ</span>
        <strong class:pos={toNumber(s.ttwror) > 0} class:neg={toNumber(s.ttwror) < 0}>{fmtRate(s.ttwror)}</strong>
        {#if s.ttwror_pa}<span class="muted small">{fmtRate(s.ttwror_pa)} p. a.</span>{/if}
      </div>
      <div>
        <span class="muted" title="Interner Zinsfuß: eure persönliche Rendite pro Jahr – berücksichtigt, wann ihr wie viel investiert habt.">IZF p. a. ⓘ</span>
        <strong class:pos={toNumber(s.irr) > 0} class:neg={toNumber(s.irr) < 0}>{fmtRate(s.irr)}</strong>
      </div>
    </div>

    <div class="row controls">
      <div class="seg" role="radiogroup" aria-label="Ansicht">
        <button role="radio" aria-checked={mode === 'return'} class:active={mode === 'return'} onclick={() => (mode = 'return')}>Rendite</button>
        <button role="radio" aria-checked={mode === 'value'} class:active={mode === 'value'} onclick={() => (mode = 'value')}>Wert</button>
      </div>
      {#if mode === 'return' && instruments.length}
        <label class="bench">
          Vergleich mit
          <select value={benchmarkChoice.id ?? ''} onchange={(e) => setBenchmark(e.currentTarget.value ? Number(e.currentTarget.value) : null)}>
            <option value="">– kein Vergleich –</option>
            {#each instruments as i (i.id)}<option value={i.id}>{i.name}</option>{/each}
          </select>
        </label>
      {/if}
    </div>
    {#if data.series.length > 1}
      <LineChart series={chartSeries} format={mode === 'value' ? eur : pct} zeroLine={mode === 'return'} ariaLabel="{title}: Verlauf" />
    {/if}

    {#if showTable}
      <details>
        <summary>Alle Zeiträume</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Zeitraum</th><th class="r">Gewinn</th><th class="r">TTWROR</th><th class="r">p. a.</th><th class="r">IZF p. a.</th></tr></thead>
            <tbody>
              {#each Object.entries(data.periods) as [key, r] (key)}
                <tr>
                  <td>{periodLabels[key] ?? key}</td>
                  <td class="r"><Money value={r.gain} colored /></td>
                  <td class="r">{fmtRate(r.ttwror)}</td>
                  <td class="r">{fmtRate(r.ttwror_pa)}</td>
                  <td class="r">{fmtRate(r.irr)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </details>
    {/if}
  {:else}
    <p class="muted">Lädt …</p>
  {/if}
</section>

<style>
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 12px;
  }
  .tiles div {
    display: grid;
  }
  .tiles span {
    font-size: 0.85rem;
  }
  .tiles strong {
    font-size: 1.2rem;
    font-variant-numeric: tabular-nums;
  }
  .loading {
    opacity: 0.6;
  }
  .pos {
    color: var(--pos);
  }
  .neg {
    color: var(--neg);
  }
  .small {
    font-size: 0.8rem;
  }
  .controls {
    justify-content: space-between;
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .seg button {
    font: inherit;
    font-size: 0.85rem;
    border: 0;
    background: var(--surface);
    color: var(--text);
    padding: 6px 12px;
    cursor: pointer;
  }
  .seg button + button {
    border-left: 1px solid var(--border);
  }
  .seg button.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 600;
  }
  .bench {
    flex-direction: row;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 8px;
    min-width: 0;
    max-width: 100%;
  }
  .bench select {
    width: auto;
    max-width: min(260px, 100%);
    min-width: 0;
  }
  details summary {
    cursor: pointer;
    color: var(--accent);
  }
  .table-wrap {
    overflow-x: auto;
    margin-top: 8px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    font-weight: 500;
    color: var(--muted);
    text-align: left;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
</style>
