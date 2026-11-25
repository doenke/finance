<script lang="ts">
  // Return per account (ranked by IRR) and how each account adds up to the household's total return.
  import { api } from './api.ts';
  import { flattenBreakdown, rankByIrr, type Breakdown } from './returns.ts';
  import { formatPercent, toNumber } from './format.ts';
  import Money from './Money.svelte';
  import PeriodPicker from './PeriodPicker.svelte';

  let { personId = null }: { personId?: number | null } = $props();
  let period = $state('1Y');
  let data = $state<Breakdown | null>(null);
  let error = $state('');
  let loading = $state(true);

  $effect(() => {
    const p = period;
    const person = personId;
    loading = true;
    api
      .get<Breakdown>(`/api/performance/breakdown?period=${p}${person !== null ? `&person_id=${person}` : ''}`)
      .then((d) => {
        data = d;
        error = '';
      })
      .catch((e) => (error = (e as Error).message))
      .finally(() => (loading = false));
  });

  // fractions from the API -> percent
  // fractions from the API -> percent; tiny values count as zero (no "−0,00 %")
  const pc = (v: string | null | undefined) => {
    if (v === null || v === undefined) return null;
    const n = toNumber(v) * 100;
    return Math.abs(n) < 0.005 ? 0 : n;
  };
  const pctText = (v: string | null | undefined) => (pc(v) === null ? '–' : formatPercent(pc(v)));
  const ppText = (v: string | null | undefined) => {
    const n = pc(v);
    if (n === null) return '–';
    return `${n > 0 ? '+' : ''}${n.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} Pp`;
  };

  // Depots and crypto accounts appear with their single positions; fees and taxes without a position
  // stay as one line per account so that the waterfall still adds up.
  const rows = $derived(flattenBreakdown(data?.items ?? []));
  const ranked = $derived(rankByIrr(rows));
  const maxIrr = $derived(Math.max(0.0001, ...ranked.map((r) => Math.abs(pc(r.irr) ?? 0))));

  // Waterfall: positive contributions first (largest first), then negative ones.
  const steps = $derived.by(() => {
    const items = rows.filter((i) => i.contribution !== null && toNumber(i.contribution) !== 0);
    items.sort((a, b) => toNumber(b.contribution) - toNumber(a.contribution));
    let cum = 0;
    return items.map((i) => {
      const c = (pc(i.contribution) ?? 0) as number;
      const from = cum;
      cum += c;
      return { item: i, from, to: cum, value: c };
    });
  });
  const total = $derived(pc(data?.total?.simple_return) ?? 0);
  const scale = $derived.by(() => {
    const points = [0, total, ...steps.flatMap((s) => [s.from, s.to])];
    const lo = Math.min(...points);
    const hi = Math.max(...points);
    return { lo, span: Math.max(hi - lo, 0.0001) };
  });
  const pos = (v: number) => ((v - scale.lo) / scale.span) * 100;
</script>

{#if error}
  <p class="error">{error}</p>
{:else if data && data.items.length}
  <section class="card stack" aria-busy={loading}>
    <div class="row head">
      <h2>Rendite je Anlage</h2>
      <PeriodPicker bind:value={period} />
    </div>

    <ul class="ranking">
      {#each ranked as i (i.key)}
        {@const v = pc(i.irr)}
        <li>
          <div class="label">
            <a href={i.href} title={i.name}>{i.name}</a>
            <span class="muted small">{i.sub}</span>
          </div>
          <div class="bar-wrap" aria-hidden="true">
            <div class="axis"></div>
            {#if v !== null}
              <div class="bar" class:neg={v < 0} style:left="{v < 0 ? 50 - (Math.abs(v) / maxIrr) * 50 : 50}%" style:width="{(Math.abs(v) / maxIrr) * 50}%"></div>
            {/if}
          </div>
          <strong class="irr num" class:pos-text={(v ?? 0) > 0} class:neg-text={(v ?? 0) < 0}>{v === null ? '–' : formatPercent(v)}</strong>
          <span class="details muted small">
            TTWROR {pctText(i.ttwror_pa ?? i.ttwror)} · Gewinn <Money value={i.gain} cents={false} colored />
          </span>
        </li>
      {/each}
    </ul>
    <p class="muted small">
      Sortiert nach IZF pro Jahr – eurer persönlichen Rendite inklusive des Zeitpunkts der Ein- und Auszahlungen. Depots und Krypto erscheinen
      mit ihren einzelnen Positionen; Kosten und Steuern ohne Position stehen unten in der Zusammensetzung.
    </p>

    {#if steps.length && data.total}
      <h3>Woraus sich die Gesamtrendite zusammensetzt</h3>
      <ul class="waterfall">
        {#each steps as s (s.item.key)}
          <li>
            <span class="label ellipsis">{s.item.name}</span>
            <div class="track" aria-hidden="true">
              <div class="zero" style:left="{pos(0)}%"></div>
              <div class="seg" class:neg={s.value < 0} style:left="{pos(Math.min(s.from, s.to))}%" style:width="{Math.max(0.6, Math.abs(pos(s.to) - pos(s.from)))}%"></div>
            </div>
            <span class="value">
              <Money value={s.item.gain} cents={false} colored />
              <span class="num small" class:pos-text={s.value > 0} class:neg-text={s.value < 0}>{ppText(s.item.contribution)}</span>
            </span>
          </li>
        {/each}
        <li class="sum">
          <span class="label">Gesamt</span>
          <div class="track" aria-hidden="true">
            <div class="zero" style:left="{pos(0)}%"></div>
            <div class="seg total" class:neg={total < 0} style:left="{pos(Math.min(0, total))}%" style:width="{Math.max(0.6, Math.abs(pos(total) - pos(0)))}%"></div>
          </div>
          <span class="value">
            <Money value={data.total.gain} cents={false} colored />
            <strong class="num small" class:pos-text={total > 0} class:neg-text={total < 0}>{pctText(data.total.simple_return)}</strong>
          </span>
        </li>
      </ul>
      <p class="muted small">
        Beitrag in Prozentpunkten (Pp) = Gewinn der Anlage geteilt durch das im Zeitraum durchschnittlich eingesetzte Kapital des Haushalts
        (<Money value={data.total.avg_capital} cents={false} />). Zusammen ergeben sie die Gesamtrendite des Zeitraums. TTWROR
        ({pctText(data.total.ttwror)}) und IZF ({pctText(data.total.irr)} p. a.) in der Renditekarte gewichten Ein- und Auszahlungen anders und
        weichen deshalb etwas ab. Kredite zählen nicht mit.
      </p>
    {/if}
  </section>
{/if}

<style>
  h2,
  h3 {
    margin: 0;
  }
  h3 {
    font-size: 1rem;
    margin-top: 8px;
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
    margin: 0;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pos-text {
    color: var(--pos);
  }
  .neg-text {
    color: var(--neg);
  }
  .ranking,
  .waterfall {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .ranking li {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(80px, 1fr) minmax(0, 1.1fr);
    grid-template-areas: 'label bar irr' 'label bar details';
    column-gap: 12px;
    row-gap: 2px;
    align-items: center;
    padding: 8px 0;
    border-top: 1px solid var(--border);
  }
  .ranking .label {
    grid-area: label;
  }
  .ranking .bar-wrap {
    grid-area: bar;
  }
  .irr {
    grid-area: irr;
    text-align: right;
  }
  .details {
    grid-area: details;
    text-align: right;
  }
  .label {
    display: grid;
    min-width: 0;
  }
  .label a {
    color: inherit;
    text-decoration: none;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .label a:hover {
    text-decoration: underline;
  }
  .bar-wrap {
    position: relative;
    height: 10px;
  }
  .axis {
    position: absolute;
    left: 50%;
    top: -3px;
    bottom: -3px;
    width: 1px;
    background: var(--border);
  }
  .bar,
  .seg {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 3px;
    background: var(--pos);
    opacity: 0.85;
  }
  .bar.neg,
  .seg.neg {
    background: var(--neg);
  }
  .waterfall li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(80px, 1.4fr) auto;
    gap: 12px;
    align-items: center;
    padding: 6px 0;
  }
  .waterfall .sum {
    border-top: 1px solid var(--border);
    font-weight: 600;
    margin-top: 4px;
    padding-top: 10px;
  }
  .track {
    position: relative;
    height: 14px;
  }
  .zero {
    position: absolute;
    top: -4px;
    bottom: -4px;
    width: 1px;
    background: var(--muted);
    opacity: 0.5;
  }
  .seg.total {
    opacity: 1;
  }
  .value {
    display: grid;
    justify-items: end;
    text-align: right;
    min-width: 92px;
  }
  @media (max-width: 560px) {
    .ranking li {
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: 'label irr' 'bar bar' 'details details';
      row-gap: 6px;
    }
    .details {
      text-align: left;
    }
    .waterfall li {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .waterfall .track {
      grid-column: 1 / -1;
      grid-row: 2;
    }
  }
</style>
