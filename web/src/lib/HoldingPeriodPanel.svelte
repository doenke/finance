<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type HoldingPeriod } from './api.ts';
  import { formatDate, formatNumber, toNumber } from './format.ts';
  import { meta } from './meta.svelte.ts';
  import Money from './Money.svelte';

  let { accountId }: { accountId: number } = $props();

  let data = $state<HoldingPeriod | null>(null);
  let open = $state<Record<number, boolean>>({});

  onMount(async () => {
    data = await api.get<HoldingPeriod>(`/api/accounts/${accountId}/holding-period`);
  });

  // Pieces need no unit; grams, ounces etc. are shown.
  const unit = (key: string) => (!key || key === 'piece' ? '' : (meta.value?.units.find((u) => u.key === key)?.label ?? key));

  function inDays(days: number): string {
    if (days <= 1) return 'morgen';
    if (days < 60) return `in ${days} Tagen`;
    const months = Math.round(days / 30.4);
    return `in etwa ${months} Monaten`;
  }

  function yearHint(short: number, exemption: number): string {
    if (short < 0) return 'Verlust – lässt sich mit anderen privaten Veräußerungsgewinnen verrechnen.';
    if (short === 0) return '';
    if (short < exemption) return `Unter der Freigrenze von ${formatNumber(exemption, 0)} € – steuerfrei, wenn ihr keine weiteren privaten Veräußerungsgewinne habt.`;
    return `Über der Freigrenze von ${formatNumber(exemption, 0)} € – der ganze Betrag ist steuerpflichtig.`;
  }
</script>

{#if data && (data.positions.length || data.years.length)}
  <section class="card stack">
    <div>
      <h2>Haltefrist</h2>
      <p class="muted small">
        Verkäufe nach mehr als einem Jahr sind steuerfrei (§ 23 EStG). Finanzen rechnet nach FIFO: Was du zuerst gekauft hast, gilt als zuerst verkauft.
      </p>
    </div>

    {#each data.positions as p (p.instrument.id)}
      <div class="pos stack">
        <strong>{p.instrument.name}</strong>
        <div class="split">
          <div class="box free">
            <span class="muted small">Steuerfrei verkaufbar</span>
            <strong class="num">{formatNumber(p.free_quantity, 8)} {unit(p.instrument.unit)}</strong>
            {#if p.free_value !== null}<span class="small"><Money value={p.free_value} /> · G/V <Money value={p.free_gain} colored /></span>{/if}
          </div>
          <div class="box">
            <span class="muted small">Noch in der Frist</span>
            <strong class="num">{formatNumber(p.locked_quantity, 8)} {unit(p.instrument.unit)}</strong>
            {#if p.locked_value !== null && toNumber(p.locked_quantity) > 0}<span class="small"><Money value={p.locked_value} /> · G/V <Money value={p.locked_gain} colored /></span>{/if}
          </div>
        </div>
        {#if p.next_free_date}
          {@const lot = p.lots.find((l) => l.free_from === p.next_free_date)}
          <p class="small">
            Nächste Freigabe am <strong>{formatDate(p.next_free_date)}</strong> ({inDays(lot?.days_left ?? 0)}): {formatNumber(p.next_free_quantity, 8)}
            {unit(p.instrument.unit)}
          </p>
        {/if}
        <button class="link small" onclick={() => (open[p.instrument.id] = !open[p.instrument.id])}>
          {open[p.instrument.id] ? 'Kaufposten ausblenden' : `${p.lots.length} Kaufposten anzeigen`}
        </button>
        {#if open[p.instrument.id]}
          <div class="table-wrap">
            <table class="small">
              <thead>
                <tr><th>Gekauft</th><th>Frei ab</th><th class="r">Menge</th><th class="r">Einstand</th><th class="r">Wert</th><th class="r">G/V</th></tr>
              </thead>
              <tbody>
                {#each p.lots as l, i (i)}
                  <tr class:done={l.free}>
                    <td>{formatDate(l.date)}</td>
                    <td>{l.free ? 'frei' : formatDate(l.free_from)}</td>
                    <td class="r num">{formatNumber(l.quantity, 8)}</td>
                    <td class="r"><Money value={l.cost} /></td>
                    <td class="r">{#if l.value !== null}<Money value={l.value} />{:else}–{/if}</td>
                    <td class="r">{#if l.gain !== null}<Money value={l.gain} colored />{:else}–{/if}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/each}

    {#if data.years.length}
      <div class="stack">
        <h3>Verkäufe nach Jahr</h3>
        {#each data.years as y (y.year)}
          <div class="year">
            <strong>{y.year}</strong>
            <span class="small">innerhalb der Frist <Money value={y.short_gain} colored /> · steuerfrei <Money value={y.long_gain} colored /></span>
            {#if yearHint(toNumber(y.short_gain), toNumber(y.exemption))}<span class="muted small">{yearHint(toNumber(y.short_gain), toNumber(y.exemption))}</span>{/if}
          </div>
        {/each}
        <p class="muted small">Keine Steuerberatung. Die Freigrenze gilt je Person und Jahr für alle privaten Veräußerungsgeschäfte zusammen.</p>
      </div>
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
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .pos {
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 8px;
  }
  .box {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    min-width: 0;
  }
  .box.free {
    background: var(--accent-soft);
    border-color: transparent;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--accent-strong);
    cursor: pointer;
    font: inherit;
    width: fit-content;
  }
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th,
  td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    white-space: nowrap;
  }
  th {
    color: var(--muted);
    font-weight: 500;
  }
  .r {
    text-align: right;
  }
  tr.done td {
    color: var(--muted);
  }
  .year {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
