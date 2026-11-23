<script lang="ts">
  // What-if scenarios for a loan: compare prepayments, a higher installment and the follow-up rate.
  import { untrack } from 'svelte';
  import { api, type Account } from './api.ts';
  import LineChart, { type Series } from './charts/LineChart.svelte';
  import DecimalInput from './DecimalInput.svelte';
  import { formatDate, formatMoney, toNumber } from './format.ts';
  import Money from './Money.svelte';

  interface Extra {
    date: string;
    amount: string;
    repeat: boolean;
    until: string;
  }
  interface Scenario {
    name: string;
    include_planned: boolean;
    extras: Extra[];
    installment: string;
    installment_from: string;
    followup_rate: string;
  }
  interface Result {
    name: string;
    end_date: string | null;
    interest_remaining: string;
    payments_remaining: string;
    prepayments_remaining: string;
    balance_at_fixed_until: string | null;
    balance_today: string;
    interest_saved: string;
    months_saved: number | null;
    series: { date: string; balance: string }[];
  }

  let { account }: { account: Account } = $props();

  function fromSaved(raw: any): Scenario {
    return {
      name: raw.name ?? 'Szenario',
      include_planned: raw.include_planned ?? true,
      extras: (raw.extra_prepayments ?? []).map((p: any) => ({ date: p.date, amount: String(p.amount), repeat: p.repeat === 'yearly', until: p.until ?? '' })),
      installment: raw.installment ? String(raw.installment) : '',
      installment_from: raw.installment_from ?? '',
      followup_rate: raw.followup_rate ? String(raw.followup_rate) : ''
    };
  }

  const initial = untrack(() => account.details.scenarios as any[] | undefined);
  let scenarios = $state<Scenario[]>(
    initial?.length
      ? initial.map(fromSaved)
      : [{ name: 'Mit geplanten Sondertilgungen', include_planned: true, extras: [], installment: '', installment_from: '', followup_rate: '' }]
  );
  let results = $state<Result[]>([]);
  let fixedUntil = $state<string | null>(null);
  let error = $state('');
  let busy = $state(false);

  function toPayload(s: Scenario) {
    return {
      name: s.name || 'Szenario',
      include_planned: s.include_planned,
      extra_prepayments: s.extras.filter((e) => e.date && e.amount).map((e) => ({ date: e.date, amount: e.amount, repeat: e.repeat ? 'yearly' : null, until: e.until || null })),
      installment: s.installment || null,
      installment_from: s.installment_from || null,
      followup_rate: s.followup_rate || null
    };
  }

  async function calculate(save = false) {
    busy = true;
    error = '';
    try {
      const res = await api.post<{ fixed_until: string | null; results: Result[] }>(`/api/accounts/${account.id}/scenarios`, {
        scenarios: scenarios.map(toPayload),
        save
      });
      results = res.results;
      fixedUntil = res.fixed_until;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function add() {
    scenarios.push({ name: `Szenario ${scenarios.length + 1}`, include_planned: false, extras: [], installment: '', installment_from: '', followup_rate: '' });
  }

  $effect(() => {
    void account.id;
    untrack(() => calculate());
  });

  const colors = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)'];
  const chart = $derived.by((): Series[] => {
    if (!results.length) return [];
    // Common axis: the start and every year end; a loan paid off during a year shows 0 at that year end.
    const start = results.map((r) => r.series[0]?.date).filter(Boolean).sort()[0] as string;
    const lastYear = Math.max(...results.map((r) => Number((r.series[r.series.length - 1]?.date ?? start).slice(0, 4))));
    const dates = [start];
    for (let y = Number(start.slice(0, 4)); y <= lastYear; y++) if (`${y}-12-31` > start) dates.push(`${y}-12-31`);
    return results.map((r, i) => {
      const map = new Map(r.series.map((p) => [p.date, toNumber(p.balance)]));
      const first = r.series[0]?.date ?? start;
      return {
        key: r.name + i,
        label: r.name,
        color: colors[i % colors.length],
        dashed: i === 0,
        points: dates.map((d) => ({ date: d, value: d < first ? null : (map.get(d) ?? (d === start ? (map.get(first) ?? null) : 0)) }))
      };
    });
  });

  const eur = (v: number) => formatMoney(v, 'EUR', false);
  const duration = (months: number | null) => {
    if (months === null) return '–';
    if (months === 0) return '±0';
    const sign = months > 0 ? '' : '+';
    const m = Math.abs(months);
    const y = Math.floor(m / 12);
    const rest = m % 12;
    return `${sign}${y ? `${y} J ` : ''}${rest ? `${rest} M` : ''}`.trim() + (months > 0 ? ' früher' : ' später');
  };
</script>

<section class="card stack">
  <div class="row head">
    <h2>Szenarien</h2>
    <span class="muted small">Was wäre, wenn …</span>
  </div>
  <p class="muted small">
    Vergleiche verschiedene Wege mit dem Plan ganz ohne Sondertilgungen: geplante oder zusätzliche Sondertilgungen, eine höhere Rate ab einem
    Stichtag oder einen anderen Zins nach der Zinsbindung.
  </p>

  {#each scenarios as s, i (i)}
    <div class="scenario">
      <div class="row top">
        <span class="swatch" style:background={colors[(i + 1) % colors.length]}></span>
        <input class="name" bind:value={s.name} aria-label="Name des Szenarios" maxlength="60" />
        <button class="btn danger small-btn" onclick={() => scenarios.splice(i, 1)} aria-label="Szenario entfernen">Entfernen</button>
      </div>
      <div class="grid">
        <label class="check"><input type="checkbox" bind:checked={s.include_planned} /> geplante Sondertilgungen</label>
        <label>Neue Rate <DecimalInput bind:value={s.installment} suffix="€" /></label>
        <label>ab <input type="date" bind:value={s.installment_from} /></label>
        <label>Zins nach Zinsbindung <DecimalInput bind:value={s.followup_rate} suffix="%" placeholder={account.details.followup_rate ?? 'wie Vertrag'} /></label>
      </div>
      {#each s.extras as e, j (j)}
        <div class="grid extra">
          <label>Zusätzliche Sondertilgung am <input type="date" bind:value={e.date} /></label>
          <label>Betrag <DecimalInput bind:value={e.amount} suffix="€" /></label>
          <label class="check"><input type="checkbox" bind:checked={e.repeat} /> jährlich</label>
          {#if e.repeat}<label>bis <input type="date" bind:value={e.until} /></label>{/if}
          <button class="btn danger small-btn" onclick={() => s.extras.splice(j, 1)}>Entfernen</button>
        </div>
      {/each}
      <div><button class="link" onclick={() => s.extras.push({ date: '', amount: '', repeat: false, until: '' })}>+ zusätzliche Sondertilgung</button></div>
    </div>
  {/each}

  <div class="row">
    {#if scenarios.length < 4}<button class="btn" onclick={add}>+ Szenario</button>{/if}
    <button class="btn primary" onclick={() => calculate(true)} disabled={busy}>{busy ? 'Rechnet …' : 'Berechnen und merken'}</button>
  </div>
  {#if error}<p class="error">{error}</p>{/if}

  {#if results.length}
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Szenario</th>
            <th class="r">Schuldenfrei</th>
            <th class="r">Restschuld {fixedUntil ? formatDate(fixedUntil) : 'Zinsbindung'}</th>
            <th class="r">Zinsen noch</th>
            <th class="r">Ersparnis</th>
            <th class="r">Laufzeit</th>
          </tr>
        </thead>
        <tbody>
          {#each results as r, i (r.name + i)}
            <tr class:base={i === 0}>
              <td><span class="swatch" class:dashed={i === 0} style:background={i === 0 ? 'none' : colors[i % colors.length]} style:border-color={colors[i % colors.length]}></span>{r.name}</td>
              <td class="r">{r.end_date ? formatDate(r.end_date) : 'nicht absehbar'}</td>
              <td class="r">{#if r.balance_at_fixed_until !== null}<Money value={r.balance_at_fixed_until} cents={false} />{:else}–{/if}</td>
              <td class="r"><Money value={r.interest_remaining} cents={false} /></td>
              <td class="r">{#if i === 0}–{:else}<Money value={r.interest_saved} cents={false} colored />{/if}</td>
              <td class="r">{i === 0 ? '–' : duration(r.months_saved)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <LineChart series={chart} format={eur} ariaLabel="Restschuld je Szenario" />
    <p class="muted small">Restschuld jeweils zum Jahresende. Gestrichelt: ohne Sondertilgungen.</p>
  {/if}
</section>

<style>
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .scenario {
    display: grid;
    gap: 10px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 12px;
  }
  .top {
    flex-wrap: nowrap;
  }
  .name {
    font-weight: 600;
    flex: 1;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 10px;
    align-items: end;
  }
  .extra {
    padding-top: 8px;
    border-top: 1px dashed var(--border);
  }
  .check {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--text);
    min-height: 40px;
  }
  .check input {
    width: auto;
    min-height: auto;
  }
  .small-btn {
    min-height: 36px;
    font-size: 0.85rem;
  }
  .link {
    background: none;
    border: 0;
    color: var(--accent);
    font: inherit;
    font-size: 0.9rem;
    cursor: pointer;
    padding: 0;
  }
  .swatch {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 3px;
    margin-right: 8px;
    vertical-align: -1px;
    flex: none;
    border: 2px solid transparent;
  }
  .swatch.dashed {
    border-style: dashed;
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
    text-align: left;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  td {
    padding: 8px;
    border-bottom: 1px solid var(--border);
  }
  tr.base td {
    color: var(--muted);
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
</style>
