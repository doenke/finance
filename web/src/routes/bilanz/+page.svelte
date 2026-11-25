<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import BudgetTabs from '#lib/BudgetTabs.svelte';
  import BarList from '#lib/charts/BarList.svelte';
  import { formatDate, formatMoney, toNumber } from '#lib/format.ts';
  import Money from '#lib/Money.svelte';

  interface MonthRow {
    month: string;
    income: string;
    expenses: string;
    savings: string;
    savings_rate: number | null;
    rest: string;
    internal: string;
  }
  interface Entry {
    name: string;
    amount: string;
  }
  interface FlowAccount {
    id: number;
    name: string;
    kind: string;
    role: 'spending' | 'saving';
    automatic: boolean;
  }
  interface Cashflow {
    months: MonthRow[];
    month: string;
    detail: {
      income: Entry[];
      expenses: Entry[];
      savings: Entry[];
      uncategorized: { date: string; amount: string; counterparty: string; purpose: string; account: string }[];
    };
    accounts: FlowAccount[];
  }

  let data = $state<Cashflow | null>(null);
  let selected = $state<string | null>(null);
  let error = $state('');

  async function load(month: string | null = selected) {
    try {
      data = await api.get<Cashflow>(`/api/cashflow?months=12${month ? `&month=${month}` : ''}`);
      selected = data.month;
    } catch (e) {
      error = (e as Error).message;
    }
  }
  onMount(() => load(null));

  async function setRole(a: FlowAccount, role: 'spending' | 'saving' | null) {
    await api.put(`/api/accounts/${a.id}/flow-role`, { role });
    await load();
  }

  const MONTHS = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
  const monthLabel = (m: string, long = false) => {
    const name = MONTHS[Number(m.slice(5)) - 1];
    return long ? `${name} ${m.slice(0, 4)}` : `${name} ${m.slice(2, 4)}`;
  };
  const current = $derived(data?.months.find((m) => m.month === selected) ?? null);
  const withIncome = $derived((data?.months ?? []).filter((m) => toNumber(m.income) > 0));
  const avgRate = $derived.by(() => {
    const inc = withIncome.reduce((s, m) => s + toNumber(m.income), 0);
    const sav = withIncome.reduce((s, m) => s + toNumber(m.savings), 0);
    return inc > 0 ? sav / inc : null;
  });
  const pct = (v: number | null) => (v === null ? '–' : `${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 0 })} %`);
  const eur = (v: number) => formatMoney(v, 'EUR', false);

  // grouped bars: income, expenses, savings per month (fixed series order = fixed colors)
  const SERIES = [
    { key: 'income', label: 'Einnahmen', color: 'var(--series-3)' },
    { key: 'expenses', label: 'Ausgaben', color: 'var(--series-2)' },
    { key: 'savings', label: 'Gespart', color: 'var(--series-1)' }
  ] as const;
  let width = $state(0);
  const W = $derived(width || 760);
  const H = 260;
  const pad = $derived({ l: W < 500 ? 52 : 64, r: 4, t: 12, b: 28 });
  const maxV = $derived(Math.max(1, ...(data?.months ?? []).flatMap((m) => [toNumber(m.income), toNumber(m.expenses), Math.abs(toNumber(m.savings))])));
  const minV = $derived(Math.min(0, ...(data?.months ?? []).map((m) => toNumber(m.savings))));
  const yTicks = $derived.by(() => {
    const span = maxV - minV;
    const raw = span / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw) ?? raw;
    const out: number[] = [];
    for (let v = Math.ceil(minV / step) * step; v <= maxV + 1e-9; v += step) out.push(Math.round(v / step) * step + 0);
    return [...new Set(out)];
  });
  const lo = $derived(Math.min(minV, yTicks[0] ?? 0));
  const hi = $derived(Math.max(maxV, yTicks[yTicks.length - 1] ?? maxV));
  const sy = (v: number) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const groupW = $derived((W - pad.l - pad.r) / Math.max(1, data?.months.length ?? 1));
  const barW = $derived(Math.max(3, Math.min(16, (groupW - 10) / 3 - 2)));
  const roleLabel = { spending: 'Alltag', saving: 'Sparen' };
</script>

<svelte:head><title>Monatsbilanz – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Monatsbilanz</h1>
  <BudgetTabs />
  <p class="muted">
    Was kam rein, was ging raus, was habt ihr gespart – aus den echten Buchungen. Gespart ist, was von den Alltagskonten auf Sparkonten fließt (abzüglich
    Entnahmen) plus direkte Sparbeiträge wie Riester oder Sparpläne. Geld zwischen Konten derselben Rolle zählt nicht.
  </p>
  {#if error}<p class="error">{error}</p>{/if}

  {#if data}
    <section class="card stack">
      <div class="row head">
        <h2>Letzte 12 Monate</h2>
        <span class="muted small">Ø Sparquote {pct(avgRate)}</span>
      </div>
      <ul class="legend small">
        {#each SERIES as s (s.key)}<li><span class="swatch" style:background={s.color}></span>{s.label}</li>{/each}
      </ul>
      <div class="chart" bind:clientWidth={width}>
      {#if width > 0}
      <svg width={W} height={H} class="bars" role="img" aria-label="Einnahmen, Ausgaben und Gespartes je Monat">
        {#each yTicks as t, ti (ti)}
          <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} class="grid" class:zero={t === 0} />
          <text x={pad.l - 6} y={sy(t)} text-anchor="end" dominant-baseline="middle" class="tick money">{eur(t)}</text>
        {/each}
        {#each data.months as m, k (m.month)}
          {@const x0 = pad.l + k * groupW + (groupW - 3 * barW - 4) / 2}
          <g class="month" class:sel={m.month === selected} role="button" tabindex="0" aria-label="{monthLabel(m.month, true)} anzeigen" onclick={() => load(m.month)} onkeydown={(e) => e.key === 'Enter' && load(m.month)}>
            <title>{monthLabel(m.month, true)}: Einnahmen {formatMoney(m.income)}, Ausgaben {formatMoney(m.expenses)}, gespart {formatMoney(m.savings)}</title>
            <rect x={pad.l + k * groupW} y={pad.t} width={groupW} height={H - pad.t - pad.b} class="hit" />
            {#each SERIES as s, j (s.key)}
              {@const v = toNumber(m[s.key])}
              <rect x={x0 + j * (barW + 2)} y={Math.min(sy(v), sy(0))} width={barW} height={Math.max(1, Math.abs(sy(v) - sy(0)))} rx="3" fill={s.color} />
            {/each}
            {#if groupW >= 44 || k % 2 === (data.months.length - 1) % 2}
              <text x={pad.l + k * groupW + groupW / 2} y={H - 8} text-anchor="middle" class="tick" class:strong={m.month === selected}>{groupW >= 44 ? monthLabel(m.month) : MONTHS[Number(m.month.slice(5)) - 1]}</text>
            {/if}
          </g>
        {/each}
      </svg>
      {/if}
      </div>
      <p class="muted small">Tipp: Monat antippen, um ihn unten im Detail zu sehen.</p>
    </section>

    {#if current}
      <section class="card stack">
        <h2>{monthLabel(current.month, true)}</h2>
        <div class="tiles">
          <div><span class="muted">Einnahmen</span><strong><Money value={current.income} cents={false} /></strong></div>
          <div><span class="muted">Ausgaben</span><strong><Money value={current.expenses} cents={false} /></strong></div>
          <div><span class="muted">Gespart</span><strong><Money value={current.savings} cents={false} colored /></strong></div>
          <div><span class="muted">Sparquote</span><strong>{pct(current.savings_rate)}</strong></div>
          <div>
            <span class="muted" title="Einnahmen minus Ausgaben minus Gespartes – das, was auf den Alltagskonten mehr (oder weniger) geworden ist">Übrig</span>
            <strong><Money value={current.rest} cents={false} colored /></strong>
          </div>
        </div>
        <div class="split">
          <div>
            <h3>Ausgaben nach Kategorie</h3>
            {#if data.detail.expenses.length}
              <BarList items={data.detail.expenses.map((e) => ({ key: e.name, label: e.name, value: toNumber(e.amount) }))} format={eur} money />
            {:else}<p class="muted small">Keine Ausgaben.</p>{/if}
          </div>
          <div class="stack">
            <div>
              <h3>Gespart</h3>
              <ul class="list">
                {#each data.detail.savings as s (s.name)}<li><span>{s.name}</span><Money value={s.amount} cents={false} colored /></li>{/each}
                {#if !data.detail.savings.length}<li class="muted">Nichts gespart.</li>{/if}
              </ul>
            </div>
            <div>
              <h3>Einnahmen</h3>
              <ul class="list">
                {#each data.detail.income as s (s.name)}<li><span>{s.name}</span><Money value={s.amount} cents={false} /></li>{/each}
                {#if !data.detail.income.length}<li class="muted">Keine Einnahmen.</li>{/if}
              </ul>
            </div>
          </div>
        </div>
        {#if data.detail.uncategorized.length}
          <details>
            <summary class="small">Größte Ausgaben ohne Kategorie</summary>
            <div class="table-wrap">
              <table class="small">
                <tbody>
                  {#each data.detail.uncategorized as u, i (i)}
                    <tr>
                      <td>{formatDate(u.date)}</td>
                      <td class="r"><Money value={u.amount} /></td>
                      <td>{u.counterparty}</td>
                      <td class="muted">{u.account}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </details>
        {/if}
      </section>
    {/if}

    <section class="card stack">
      <h2>Rolle der Konten</h2>
      <p class="muted small">Alltag: Gehalt, laufende Ausgaben. Sparen: Rücklagen und Anlagen. Ein Gemeinschaftskonto, das hier fehlt, legst du unter Konten an (IBAN reicht).</p>
      <ul class="roles">
        {#each data.accounts as a (a.id)}
          <li>
            <span>{a.name}{#if a.automatic}<span class="muted small auto">automatisch</span>{/if}</span>
            <span class="seg" role="radiogroup" aria-label="Rolle von {a.name}">
              {#each ['spending', 'saving'] as r (r)}
                <button role="radio" aria-checked={a.role === r} class:active={a.role === r} onclick={() => setRole(a, r as 'spending' | 'saving')}>{roleLabel[r as 'spending' | 'saving']}</button>
              {/each}
            </span>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  h1,
  h2,
  h3 {
    margin: 0;
  }
  h3 {
    font-size: 1rem;
    margin-bottom: 8px;
  }
  .small {
    font-size: 0.85rem;
  }
  p.small {
    margin: 0;
  }
  .head {
    justify-content: space-between;
    align-items: center;
  }
  .legend {
    display: flex;
    gap: 16px;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
  }
  .chart {
    width: 100%;
    min-height: 260px;
  }
  .bars {
    display: block;
  }
  .auto {
    margin-left: 8px;
  }
  .grid {
    stroke: var(--grid);
  }
  .grid.zero {
    stroke: var(--muted);
    opacity: 0.6;
  }
  .tick {
    fill: var(--muted);
    font-size: 12px;
  }
  .tick.strong {
    fill: var(--text);
    font-weight: 600;
  }
  .hit {
    fill: transparent;
  }
  .month {
    cursor: pointer;
  }
  .month:hover .hit,
  .month.sel .hit {
    fill: var(--surface-2);
  }
  .month:focus-visible {
    outline: 2px solid var(--accent);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(130px, 100%), 1fr));
    gap: 16px;
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
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
    gap: 24px;
  }
  .list,
  .roles {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li,
  .roles li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    flex-shrink: 0;
  }
  .seg button {
    font: inherit;
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
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  td {
    padding: 4px 8px 4px 0;
    border-top: 1px solid var(--border);
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
</style>
