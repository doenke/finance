<script lang="ts">
  import { api } from '#lib/api.ts';
  import BookingTable, { type Booking, type CategoryOption } from '#lib/BookingTable.svelte';
  import BudgetTabs from '#lib/BudgetTabs.svelte';
  import { formatDate, formatMoney, toNumber } from '#lib/format.ts';
  import Money from '#lib/Money.svelte';

  interface MonthRow {
    month: string;
    income: string;
    expenses: string;
    savings: string;
    savings_rate: number | null;
    rest: string;
  }
  interface Totals {
    income: string;
    expenses: string;
    savings: string;
    rest: string;
    savings_rate: number | null;
  }
  interface Entry {
    name: string;
    amount: string;
    previous: string | null;
    bookings: Booking[];
  }
  type Section = 'expenses' | 'savings' | 'income';
  interface YearData {
    period: string;
    label: string;
    from: string;
    to: string;
    compare_from: string;
    compare_to: string;
    months: MonthRow[];
    totals: Totals;
    previous: Totals | null;
    average: { income: string; expenses: string; savings: string; rest: string };
    detail: Record<Section, Entry[]>;
    years: number[];
  }

  let period = $state('ytd');
  let data = $state<YearData | null>(null);
  let categories = $state<CategoryOption[]>([]);
  let error = $state('');
  let loading = $state(false);
  let opened = $state<{ section: Section; name: string } | null>(null);

  async function load() {
    loading = true;
    try {
      data = await api.get<YearData>(`/api/cashflow/year?period=${period}`);
      error = '';
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }
  $effect(() => {
    void period;
    load();
  });
  $effect(() => {
    api.get<CategoryOption[]>('/api/categories').then((c) => (categories = c));
  });

  const MONTHS = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
  const monthLabel = (m: string) => `${MONTHS[Number(m.slice(5)) - 1]} ${m.slice(2, 4)}`;
  const pct = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 0 })} %`);
  const eur = (v: number) => formatMoney(v, 'EUR', false);
  // change against the comparison period; null without a meaningful base
  const change = (cur: string | number, prev: string | number | null | undefined) => {
    if (prev === null || prev === undefined) return null;
    const p = toNumber(prev);
    return Math.abs(p) < 1 ? null : (toNumber(cur) - p) / Math.abs(p);
  };
  const changeText = (c: number | null) =>
    c === null ? '' : `${c > 0 ? '+' : ''}${(c * 100).toLocaleString('de-DE', { maximumFractionDigits: 0 })} %`;
  const n = $derived(data?.months.length ?? 1);
  const SECTION_LABEL: Record<Section, string> = { expenses: 'Ausgaben', savings: 'Gespart', income: 'Einnahmen' };
  const openEntry = $derived(opened && data ? (data.detail[opened.section].find((e) => e.name === opened!.name) ?? null) : null);
  const toggle = (section: Section, name: string) =>
    (opened = opened?.section === section && opened.name === name ? null : { section, name });

  const TILES = [
    { key: 'income', label: 'Einnahmen', good: 1 },
    { key: 'expenses', label: 'Ausgaben', good: -1 },
    { key: 'savings', label: 'Gespart', good: 1 },
    { key: 'rest', label: 'Übrig', good: 1 }
  ] as const;
  const maxMonth = $derived(Math.max(1, ...(data?.months ?? []).flatMap((m) => [toNumber(m.income), toNumber(m.expenses)])));
</script>

<svelte:head><title>Jahresbilanz – Finanzen</title></svelte:head>

{#snippet entries(section: Section, good: number)}
  {@const list = data?.detail[section] ?? []}
  {#if list.length}
    <div class="table-wrap">
      <table class="entries">
        <thead>
          <tr>
            <th></th>
            <th class="r">Summe</th>
            <th class="r hide-sm">Ø Monat</th>
            {#if data?.previous}<th class="r hide-sm">Vorjahr</th><th class="r">±</th>{/if}
          </tr>
        </thead>
        <tbody>
          {#each list as e (e.name)}
            {@const c = change(e.amount, e.previous)}
            <tr class:on={opened?.section === section && opened.name === e.name}>
              <td>
                {#if e.bookings.length}
                  <button class="entry" onclick={() => toggle(section, e.name)}>{e.name}</button>
                {:else}<span class="muted">{e.name}</span>{/if}
              </td>
              <td class="r"><Money value={e.amount} cents={false} /></td>
              <td class="r muted hide-sm"><Money value={toNumber(e.amount) / n} cents={false} /></td>
              {#if data?.previous}
                <td class="r muted hide-sm"><Money value={e.previous ?? 0} cents={false} /></td>
                <td class="r small" class:good={c !== null && c * good > 0} class:bad={c !== null && c * good < 0}>{changeText(c)}</td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <p class="muted small">Keine Buchungen.</p>
  {/if}
{/snippet}

<div class="stack">
  <h1>Jahresbilanz</h1>
  <BudgetTabs />

  <div class="periods" role="group" aria-label="Zeitraum">
    <button class:active={period === 'ytd'} onclick={() => (period = 'ytd')}>Seit Jahresbeginn</button>
    <button class:active={period === '12m'} onclick={() => (period = '12m')}>Letzte 12 Monate</button>
    {#each data?.years ?? [] as y (y)}
      <button class:active={period === String(y)} onclick={() => (period = String(y))}>{y}</button>
    {/each}
  </div>
  {#if error}<p class="error">{error}</p>{/if}

  {#if data}
    {@const t = data.totals}
    <section class="card stack" aria-busy={loading}>
      <div class="row head">
        <h2>{data.label}</h2>
        <span class="muted small">
          {formatDate(data.from)} – {formatDate(data.to)}{#if data.previous}{' · '}verglichen mit {formatDate(data.compare_from)} – {formatDate(data.compare_to)}{/if}
        </span>
      </div>
      <div class="tiles">
        {#each TILES as k (k.key)}
          {@const c = change(t[k.key], data.previous?.[k.key])}
          <div>
            <span class="muted">{k.label}</span>
            <strong><Money value={t[k.key]} cents={false} colored={k.key === 'savings' || k.key === 'rest'} /></strong>
            <span class="muted small">Ø <Money value={data.average[k.key]} cents={false} /> im Monat</span>
            {#if data.previous}
              <span class="small">
                <span class:good={c !== null && c * k.good > 0} class:bad={c !== null && c * k.good < 0}>{changeText(c) || '±0 %'}</span>
                <span class="muted">ggü. <Money value={data.previous[k.key]} cents={false} /></span>
              </span>
            {/if}
          </div>
        {/each}
        <div>
          <span class="muted">Sparquote</span>
          <strong>{pct(t.savings_rate)}</strong>
          {#if data.previous}<span class="muted small">Vorjahr {pct(data.previous.savings_rate)}</span>{/if}
        </div>
      </div>

      <div class="table-wrap">
        <table class="months">
          <thead>
            <tr><th></th><th class="r">Einnahmen</th><th class="r">Ausgaben</th><th class="r">Gespart</th><th class="r hide-sm">Quote</th><th class="hide-sm"></th></tr>
          </thead>
          <tbody>
            {#each data.months as m (m.month)}
              <tr>
                <td><a href="/bilanz?monat={m.month}">{monthLabel(m.month)}</a></td>
                <td class="r"><Money value={m.income} cents={false} /></td>
                <td class="r"><Money value={m.expenses} cents={false} /></td>
                <td class="r"><Money value={m.savings} cents={false} colored /></td>
                <td class="r muted hide-sm">{pct(m.savings_rate)}</td>
                <td class="spark hide-sm" aria-hidden="true">
                  <div class="b inc" style:width="{(toNumber(m.income) / maxMonth) * 100}%"></div>
                  <div class="b exp" style:width="{(toNumber(m.expenses) / maxMonth) * 100}%"></div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    <section class="card stack">
      <h2>Ausgaben nach Kategorie</h2>
      {@render entries('expenses', -1)}
    </section>

    {#if opened}
      <section class="card stack">
        <div class="row head">
          <h3>{opened.name} <span class="muted small">· {SECTION_LABEL[opened.section]} {data.label}</span></h3>
          <button class="link small" onclick={() => (opened = null)}>Schließen</button>
        </div>
        {#if openEntry && openEntry.bookings.length}
          <BookingTable bookings={openEntry.bookings} {categories} onchanged={load} />
          <p class="muted small">{openEntry.bookings.length} Buchung{openEntry.bookings.length === 1 ? '' : 'en'} · Summe <Money value={openEntry.amount} /></p>
        {:else}
          <p class="muted small">Im Zeitraum keine Buchungen.</p>
        {/if}
      </section>
    {/if}

    <div class="split">
      <section class="card stack">
        <h2>Einnahmen</h2>
        {@render entries('income', 1)}
      </section>
      <section class="card stack">
        <h2>Gespart</h2>
        {@render entries('savings', 1)}
      </section>
    </div>
    <p class="muted small">
      „Seit Jahresbeginn“ vergleicht mit denselben Tagen im Vorjahr, „Letzte 12 Monate“ zählt die zwölf abgeschlossenen Monate vor dem laufenden.
      Ein Klick auf eine Zeile zeigt die Buchungen dahinter; dort kannst du die Kategorie einzelner Buchungen ändern.
    </p>
  {:else if !error}
    <p class="muted">Lädt …</p>
  {/if}
</div>

<style>
  h2,
  h3 {
    margin: 0;
  }
  .head {
    justify-content: space-between;
    flex-wrap: wrap;
  }
  .small {
    font-size: 0.8rem;
  }
  p.small {
    margin: 0;
  }
  .periods {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .periods button {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.9rem;
    cursor: pointer;
  }
  .periods button.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
    border-color: var(--accent);
    font-weight: 600;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr));
    gap: 16px;
  }
  .tiles div {
    display: grid;
    align-content: start;
    gap: 2px;
  }
  .tiles strong {
    font-size: 1.3rem;
    font-variant-numeric: tabular-nums;
  }
  .good {
    color: var(--pos);
  }
  .bad {
    color: var(--neg);
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr));
    gap: 16px;
  }
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    font-weight: 500;
    color: var(--muted);
    font-size: 0.8rem;
    text-align: left;
    padding: 0 8px 4px 0;
  }
  td {
    padding: 6px 8px 6px 0;
    border-top: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
  tr.on td {
    background: var(--surface-2);
  }
  .entry,
  .link {
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .entry:hover {
    text-decoration: underline;
  }
  tr.on .entry {
    font-weight: 600;
  }
  .link {
    color: var(--accent-strong);
  }
  .months a {
    color: inherit;
  }
  .spark {
    width: 30%;
    min-width: 80px;
  }
  .spark .b {
    height: 5px;
    border-radius: 3px;
    min-width: 1px;
  }
  .spark .b + .b {
    margin-top: 2px;
  }
  .b.inc {
    background: var(--series-3);
  }
  .b.exp {
    background: var(--series-2);
  }
  @media (max-width: 560px) {
    .hide-sm {
      display: none;
    }
  }
</style>
