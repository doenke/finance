<script lang="ts">
  import { api, type Account, type Schedule, type ScheduleRow } from './api.ts';
  import { formatDate } from './format.ts';
  import Money from './Money.svelte';

  let { account, refresh = 0 }: { account: Account; refresh?: number } = $props();

  let schedule = $state<Schedule | null>(null);
  let withPlanned = $state(true);
  let error = $state('');
  let open = $state<Record<number, boolean>>({});

  async function load() {
    error = '';
    try {
      schedule = await api.get<Schedule>(`/api/accounts/${account.id}/schedule?planned=${withPlanned}`);
    } catch (e) {
      schedule = null;
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void refresh;
    void withPlanned;
    load();
  });

  const years = $derived.by(() => {
    const map = new Map<number, ScheduleRow[]>();
    for (const r of schedule?.rows ?? []) {
      const y = Number(r.date.slice(0, 4));
      map.set(y, [...(map.get(y) ?? []), r]);
    }
    return [...map.entries()].map(([year, rows]) => ({
      year,
      rows,
      payment: rows.reduce((s, r) => s + Number(r.payment), 0),
      interest: rows.reduce((s, r) => s + Number(r.interest), 0),
      principal: rows.reduce((s, r) => s + Number(r.principal), 0),
      prepayment: rows.reduce((s, r) => s + Number(r.prepayment), 0),
      balance: rows[rows.length - 1].balance
    }));
  });

  const allowanceLeft = $derived(schedule?.prepayment_allowance ? Number(schedule.prepayment_allowance) - Number(schedule.prepaid_this_year) : null);

  function exportCsv() {
    if (!schedule) return;
    const lines = ['Datum;Rate;Zinsen;Tilgung;Sondertilgung;Restschuld'];
    const n = (v: string) => v.replace('.', ',');
    for (const r of schedule.rows) lines.push([r.date, n(r.payment), n(r.interest), n(r.principal), n(r.prepayment), n(r.balance)].join(';'));
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `tilgungsplan-${account.name.replace(/[^\w-]+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
</script>

<section class="card stack">
  <div class="row head">
    <h2>Tilgungsplan</h2>
    <label class="check"><input type="checkbox" bind:checked={withPlanned} /> mit geplanten Sondertilgungen</label>
  </div>
  {#if error}
    <p class="muted">{error} <a href="/konten/{account.id}/bearbeiten">Darlehensdaten ergänzen</a></p>
  {:else if schedule}
    <div class="facts">
      <div><span class="muted">Restschuld heute</span><strong><Money value={schedule.balance_today} /></strong></div>
      {#if schedule.balance_at_fixed_until !== null}
        <div><span class="muted">Ende Zinsbindung ({formatDate(account.details.fixed_until)})</span><strong><Money value={schedule.balance_at_fixed_until} /></strong></div>
      {/if}
      <div><span class="muted">Schuldenfrei</span><strong>{schedule.end_date ? formatDate(schedule.end_date) : 'nicht absehbar'}</strong></div>
      <div><span class="muted">Zinsen bisher</span><strong><Money value={schedule.interest_paid} /></strong></div>
      <div><span class="muted">Zinsen noch</span><strong><Money value={schedule.interest_remaining} /></strong></div>
      {#if allowanceLeft !== null}
        <div><span class="muted">Sondertilgung {new Date().getFullYear()} noch möglich</span><strong class:over={allowanceLeft < 0}><Money value={allowanceLeft} /></strong></div>
      {/if}
    </div>
    {#if allowanceLeft !== null && allowanceLeft < 0}
      <p class="error">Die Sondertilgungen in diesem Jahr liegen über dem vertraglichen Recht.</p>
    {/if}
    {#if schedule.start_date && schedule.start_date !== account.details.disbursed_on}
      <p class="muted small">Berechnet ab dem Bankstand vom {formatDate(schedule.start_date)}.</p>
    {/if}

    <div class="table-wrap">
      <table>
        <thead><tr><th>Jahr / Datum</th><th class="r">Rate</th><th class="r">Zinsen</th><th class="r">Tilgung</th><th class="r">Sondertilgung</th><th class="r">Restschuld</th></tr></thead>
        <tbody>
          {#each years as y (y.year)}
            <tr class="year" onclick={() => (open[y.year] = !open[y.year])}>
              <td><button class="link" aria-expanded={!!open[y.year]}>{open[y.year] ? '▾' : '▸'} {y.year}</button></td>
              <td class="r"><Money value={y.payment} /></td>
              <td class="r"><Money value={y.interest} /></td>
              <td class="r"><Money value={y.principal} /></td>
              <td class="r">{#if y.prepayment}<Money value={y.prepayment} />{/if}</td>
              <td class="r"><Money value={y.balance} /></td>
            </tr>
            {#if open[y.year]}
              {#each y.rows as r, i (i)}
                <tr class="detail" class:planned={r.planned}>
                  <td>{formatDate(r.date)}{r.planned ? ' (geplant)' : ''}</td>
                  <td class="r">{#if Number(r.payment)}<Money value={r.payment} />{/if}</td>
                  <td class="r">{#if Number(r.payment)}<Money value={r.interest} />{/if}</td>
                  <td class="r">{#if Number(r.payment)}<Money value={r.principal} />{/if}</td>
                  <td class="r">{#if Number(r.prepayment)}<Money value={r.prepayment} />{/if}</td>
                  <td class="r"><Money value={r.balance} /></td>
                </tr>
              {/each}
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
    <div><button class="btn" onclick={exportCsv}>Als CSV exportieren</button></div>
  {/if}
</section>

<style>
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .check {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--text);
  }
  .check input {
    width: auto;
    min-height: auto;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 12px;
  }
  .facts div {
    display: grid;
  }
  .facts span {
    font-size: 0.85rem;
  }
  .over {
    color: var(--neg);
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92rem;
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
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
  .year {
    cursor: pointer;
    font-weight: 500;
  }
  .year:hover {
    background: var(--surface-2);
  }
  .detail td {
    font-size: 0.85rem;
    color: var(--muted);
  }
  .planned td {
    font-style: italic;
  }
  .link {
    background: none;
    border: 0;
    font: inherit;
    color: inherit;
    cursor: pointer;
    padding: 0;
  }
</style>
