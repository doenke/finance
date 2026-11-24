<script lang="ts">
  // Available vs. bound assets (and debts) with the date bound assets become free.
  import { api } from './api.ts';
  import { formatDate, formatMoney, toNumber } from './format.ts';
  import Money from './Money.svelte';

  interface Item {
    account_id: number;
    name: string;
    kind_label: string;
    value: string;
    bucket: 'available' | 'bound' | 'liability';
    automatic: boolean;
    free_from: string | null;
    free_reason: string | null;
  }
  interface Liquidity {
    available: string;
    bound: string;
    liabilities: string;
    net: string;
    available_share: string | null;
    items: Item[];
  }

  let { personId = null }: { personId?: number | null } = $props();
  let data = $state<Liquidity | null>(null);
  let showAll = $state(false);

  $effect(() => {
    const person = personId;
    api
      .get<Liquidity>(`/api/liquidity${person !== null ? `?person_id=${person}` : ''}`)
      .then((d) => (data = d))
      .catch(() => (data = null));
  });

  const share = $derived(data?.available_share !== null && data?.available_share !== undefined ? toNumber(data.available_share) : null);
  const available = $derived((data?.items ?? []).filter((i) => i.bucket === 'available'));
  const bound = $derived((data?.items ?? []).filter((i) => i.bucket === 'bound'));
  const LIMIT = 5;
  const yearsUntil = (d: string) => {
    const years = (new Date(d).getTime() - Date.now()) / (365.25 * 864e5);
    if (years < 1) {
      const months = Math.max(1, Math.round(years * 12));
      return `in ${months} Monat${months === 1 ? '' : 'en'}`;
    }
    return `in ${Math.round(years)} Jahr${Math.round(years) === 1 ? '' : 'en'}`;
  };
</script>

{#if data && (available.length || bound.length)}
  <section class="card stack">
    <h2>Verfügbar und gebunden</h2>
    <div class="tiles">
      <div>
        <span class="muted">Verfügbar</span>
        <strong class="big"><Money value={data.available} cents={false} /></strong>
        {#if share !== null}<span class="muted small">{Math.round(share * 100)} % des Vermögens</span>{/if}
      </div>
      <div>
        <span class="muted">Gebunden</span>
        <strong><Money value={data.bound} cents={false} /></strong>
        {#if share !== null}<span class="muted small">{100 - Math.round(share * 100)} %</span>{/if}
      </div>
      {#if toNumber(data.liabilities) !== 0}
        <div>
          <span class="muted">Schulden</span>
          <strong><Money value={data.liabilities} cents={false} /></strong>
        </div>
      {/if}
    </div>
    {#if share !== null}
      <div class="bar" role="img" aria-label="{Math.round(share * 100)} % verfügbar, {100 - Math.round(share * 100)} % gebunden">
        <div class="avail" style:width="{Math.max(0, Math.min(1, share)) * 100}%"></div>
        <div class="bound" style:width="{(1 - Math.max(0, Math.min(1, share))) * 100}%"></div>
      </div>
      <div class="legend small muted"><span><i class="dot avail"></i>verfügbar</span><span><i class="dot bound"></i>gebunden</span></div>
    {/if}

    <div class="lists">
      <div>
        <h3>Verfügbar</h3>
        <ul>
          {#each showAll ? available : available.slice(0, LIMIT) as i (i.account_id)}
            <li>
              <a href="/konten/{i.account_id}" class="name">{i.name}</a>
              <Money value={i.value} cents={false} colored={toNumber(i.value) < 0} />
            </li>
          {/each}
        </ul>
      </div>
      <div>
        <h3>Gebunden <span class="muted small">– frei ab</span></h3>
        <ul>
          {#each showAll ? bound : bound.slice(0, LIMIT) as i (i.account_id)}
            <li>
              <span class="name">
                <a href="/konten/{i.account_id}">{i.name}</a>
                <span class="muted small">
                  {#if i.free_from}{formatDate(i.free_from)} · {yearsUntil(i.free_from)}{i.free_reason && i.free_reason !== 'frei ab' ? ` (${i.free_reason})` : ''}{:else}{i.kind_label}{/if}
                </span>
              </span>
              <Money value={i.value} cents={false} />
            </li>
          {/each}
        </ul>
      </div>
    </div>
    {#if available.length > LIMIT || bound.length > LIMIT}
      <button class="link small" onclick={() => (showAll = !showAll)}>{showAll ? 'Weniger anzeigen' : 'Alle anzeigen'}</button>
    {/if}
    <p class="muted small">
      Verfügbar ist, was ihr kurzfristig nutzen könntet: Konten, Tagesgeld, Depots, Krypto, Edelmetalle (abzüglich Kreditkarten). Gebunden sind Festgeld,
      Altersvorsorge, Immobilien, Beteiligungen und sonstige Anlagen. Je Konto änderst du das unter „Bearbeiten“ → Verfügbarkeit.
    </p>
  </section>
{/if}

<style>
  h2,
  h3 {
    margin: 0;
  }
  h3 {
    font-size: 0.95rem;
    margin-bottom: 4px;
  }
  .small {
    font-size: 0.8rem;
  }
  p.small {
    margin: 0;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr));
    gap: 16px;
    align-items: end;
  }
  .tiles div {
    display: grid;
  }
  .tiles strong {
    font-size: 1.15rem;
    font-variant-numeric: tabular-nums;
  }
  .tiles .big {
    font-size: 1.8rem;
    line-height: 1.1;
  }
  .bar {
    display: flex;
    height: 12px;
    border-radius: 6px;
    overflow: hidden;
    background: var(--surface-2);
  }
  .avail {
    background: var(--series-3);
  }
  .bound {
    background: var(--series-1);
  }
  .legend {
    display: flex;
    gap: 16px;
  }
  .dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
    vertical-align: -1px;
  }
  .lists {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr));
    gap: 16px 24px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  .name {
    display: grid;
    min-width: 0;
  }
  a {
    color: inherit;
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  a:hover {
    text-decoration: underline;
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
</style>
