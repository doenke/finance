<script lang="ts">
  // Return per account (ranked by IRR) and how each account adds up to the household's total return.
  import { api } from './api.ts';
  import { formatPercent, toNumber } from './format.ts';
  import Money from './Money.svelte';
  import PeriodPicker from './PeriodPicker.svelte';

  interface Pos {
    instrument_id: number;
    name: string;
    gain: string;
    irr: string | null;
    ttwror: string | null;
    ttwror_pa: string | null;
    contribution: string | null;
    sold: boolean;
  }
  interface Item {
    positions: Pos[] | null;
    account_id: number;
    name: string;
    kind_label: string;
    start_value: string;
    end_value: string;
    net_flows: string;
    gain: string;
    irr: string | null;
    ttwror: string | null;
    ttwror_pa: string | null;
    avg_capital: string;
    contribution: string | null;
    weight: string | null;
  }
  interface Breakdown {
    from: string | null;
    to: string;
    total: { gain: string; avg_capital: string; simple_return: string | null; irr: string | null; ttwror: string | null; ttwror_pa: string | null } | null;
    items: Item[];
  }

  let { personId = null }: { personId?: number | null } = $props();
  let period = $state('1Y');
  let data = $state<Breakdown | null>(null);
  let error = $state('');
  let loading = $state(true);
  // holdings accounts opened into their positions (ranking and waterfall)
  let open = $state<Record<number, boolean>>({});
  const hasPositions = (i: Item) => (i.positions?.length ?? 0) > 0;

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

  const ranked = $derived(data?.items ?? []);
  const maxIrr = $derived(
    Math.max(
      0.0001,
      ...ranked.flatMap((i) => [Math.abs(pc(i.irr) ?? 0), ...(open[i.account_id] ? (i.positions ?? []).map((p) => Math.abs(pc(p.irr) ?? 0)) : [])])
    )
  );

  // Waterfall: positive contributions first (largest first), then negative ones.
  // An opened depot is replaced by its positions; what is left over (fees and taxes without a position) stays as its own step.
  const steps = $derived.by(() => {
    const rows: { key: string; name: string; gain: string; contribution: string | null }[] = [];
    for (const i of data?.items ?? []) {
      if (open[i.account_id] && hasPositions(i)) {
        let gain = toNumber(i.gain);
        let contribution = toNumber(i.contribution);
        for (const p of i.positions!) {
          rows.push({ key: `p${i.account_id}-${p.instrument_id}`, name: p.name, gain: p.gain, contribution: p.contribution });
          gain -= toNumber(p.gain);
          contribution -= toNumber(p.contribution);
        }
        if (Math.abs(gain) >= 0.5) rows.push({ key: `r${i.account_id}`, name: `${i.name}: Kosten & Steuern`, gain: String(gain), contribution: String(contribution) });
      } else {
        rows.push({ key: `a${i.account_id}`, name: i.name, gain: i.gain, contribution: i.contribution });
      }
    }
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
      {#each ranked as i (i.account_id)}
        {@const v = pc(i.irr)}
        <li>
          <div class="label">
            {#if hasPositions(i)}
              <button class="toggle" aria-expanded={!!open[i.account_id]} onclick={() => (open[i.account_id] = !open[i.account_id])}>
                <span class="chev" class:rot={open[i.account_id]} aria-hidden="true">›</span>
                <span class="ellipsis">{i.name}</span>
              </button>
              <span class="muted small">{i.kind_label} · {i.positions!.length} Positionen</span>
            {:else}
              <a href="/konten/{i.account_id}">{i.name}</a>
              <span class="muted small">{i.kind_label}</span>
            {/if}
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
        {#if open[i.account_id] && i.positions}
          {#each i.positions as p (p.instrument_id)}
            {@const pv = pc(p.irr)}
            <li class="sub">
              <div class="label">
                <span class="ellipsis" title={p.name}>{p.name}</span>
                {#if p.sold}<span class="muted small">verkauft</span>{/if}
              </div>
              <div class="bar-wrap" aria-hidden="true">
                <div class="axis"></div>
                {#if pv !== null}
                  <div class="bar" class:neg={pv < 0} style:left="{pv < 0 ? 50 - (Math.abs(pv) / maxIrr) * 50 : 50}%" style:width="{(Math.abs(pv) / maxIrr) * 50}%"></div>
                {/if}
              </div>
              <strong class="irr num" class:pos-text={(pv ?? 0) > 0} class:neg-text={(pv ?? 0) < 0}>{pv === null ? '–' : formatPercent(pv)}</strong>
              <span class="details muted small">
                TTWROR {pctText(p.ttwror_pa ?? p.ttwror)} · Gewinn <Money value={p.gain} cents={false} colored /> · {ppText(p.contribution)}
              </span>
            </li>
          {/each}
        {/if}
      {/each}
    </ul>
    <p class="muted small">
      Sortiert nach IZF pro Jahr – eurer persönlichen Rendite inklusive des Zeitpunkts der Ein- und Auszahlungen. Depots und Krypto klappst du
      auf, dann stehen auch in der Zusammensetzung unten die einzelnen Positionen statt des Depots.
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
  .ranking li.sub {
    padding: 6px 0 6px 1.4em;
    border-top: 1px dashed var(--border);
    font-size: 0.92rem;
  }
  .toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    font-weight: 500;
    color: inherit;
    cursor: pointer;
    text-align: left;
  }
  .toggle:hover .ellipsis {
    text-decoration: underline;
  }
  .chev {
    display: inline-block;
    width: 1em;
    color: var(--muted);
    transition: transform 0.15s;
  }
  .chev.rot {
    transform: rotate(90deg);
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
