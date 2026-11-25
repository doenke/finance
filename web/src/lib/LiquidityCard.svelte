<script lang="ts">
  // Available vs. bound assets (and debts) with the date bound assets become free.
  import { api } from './api.ts';
  import { formatDate, formatMoney, formatNumber, formatPercent, toNumber } from './format.ts';
  import Money from './Money.svelte';

  interface Pos {
    instrument_id: number;
    name: string;
    quantity: string;
    value: string;
    cost: string;
    gain: string;
    gain_pct: string | null;
    price_missing: boolean;
  }
  interface Item {
    account_id: number;
    name: string;
    kind_label: string;
    value: string;
    bucket: 'available' | 'bound' | 'liability';
    group: 'current' | 'invested' | 'bound' | 'liability';
    automatic: boolean;
    free_from: string | null;
    free_reason: string | null;
    positions: Pos[] | null;
  }
  interface Liquidity {
    available: string;
    current: string;
    invested: string;
    bound: string;
    liabilities: string;
    net: string;
    available_share: string | null;
    items: Item[];
  }

  let { personId = null }: { personId?: number | null } = $props();
  let data = $state<Liquidity | null>(null);
  let showAll = $state(false);
  let open = $state<Record<number, boolean>>({});
  const expandable = (i: Item) => (i.positions?.length ?? 0) > 0;

  $effect(() => {
    const person = personId;
    api
      .get<Liquidity>(`/api/liquidity${person !== null ? `?person_id=${person}` : ''}`)
      .then((d) => (data = d))
      .catch(() => (data = null));
  });

  const share = $derived(data?.available_share !== null && data?.available_share !== undefined ? toNumber(data.available_share) : null);
  const available = $derived((data?.items ?? []).filter((i) => i.bucket === 'available'));
  const current = $derived(available.filter((i) => i.group === 'current'));
  const invested = $derived(available.filter((i) => i.group === 'invested'));
  const assets = $derived(data ? toNumber(data.available) + toNumber(data.bound) : 0);
  const shareOf = (v: string | undefined) => (assets > 0 && v !== undefined ? Math.max(0, toNumber(v)) / assets : 0);
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

{#snippet positionList(i: Item)}
  <li class="positions">
    <ul>
      {#each i.positions! as p (p.instrument_id)}
        <li>
          <span class="name">
            <span class="ellipsis" title={p.name}>{p.name}</span>
            <span class="muted small">
              <span class="money">{formatNumber(p.quantity)}</span> Stk.{#if p.price_missing} · ohne Kurs{/if}
            </span>
          </span>
          <span class="val">
            <Money value={p.value} cents={false} />
            {#if p.gain_pct !== null}
              <span class="small" class:pos={toNumber(p.gain) >= 0} class:neg={toNumber(p.gain) < 0}>{formatPercent(toNumber(p.gain_pct) * 100)}</span>
            {/if}
          </span>
        </li>
      {/each}
      <li class="small"><a href="/konten/{i.account_id}" class="more">Zum Konto</a></li>
    </ul>
  </li>
{/snippet}

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
        <span class="muted"><i class="dot cur"></i>Haushaltskonten</span>
        <strong><Money value={data.current} cents={false} /></strong>
        <span class="muted small">sofort nutzbar</span>
      </div>
      <div>
        <span class="muted"><i class="dot inv"></i>Angelegt</span>
        <strong><Money value={data.invested} cents={false} /></strong>
        <span class="muted small">Tagesgeld, Depots, Krypto</span>
      </div>
      <div>
        <span class="muted"><i class="dot bound"></i>Gebunden</span>
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
    {#if assets > 0}
      <div
        class="bar"
        role="img"
        aria-label="{Math.round(shareOf(data.current) * 100)} % Haushaltskonten, {Math.round(shareOf(data.invested) * 100)} % angelegt, {Math.round(shareOf(data.bound) * 100)} % gebunden"
      >
        <div class="cur" style:width="{shareOf(data.current) * 100}%"></div>
        <div class="inv" style:width="{shareOf(data.invested) * 100}%"></div>
        <div class="bound" style:width="{shareOf(data.bound) * 100}%"></div>
      </div>
    {/if}

    <div class="lists">
      {#each [{ title: 'Haushaltskonten', items: current }, { title: 'Angelegt', items: invested }] as col (col.title)}
        <div>
          <h3>{col.title}</h3>
          <ul>
            {#each showAll ? col.items : col.items.slice(0, LIMIT) as i (i.account_id)}
              <li>
                {#if expandable(i)}
                  <button class="toggle" aria-expanded={!!open[i.account_id]} onclick={() => (open[i.account_id] = !open[i.account_id])}>
                    <span class="chev" class:rot={open[i.account_id]} aria-hidden="true">›</span>
                    <span class="ellipsis">{i.name}</span>
                    <span class="muted small count">{i.positions!.length}</span>
                  </button>
                {:else}
                  <a href="/konten/{i.account_id}" class="name" class:indent={col.items.some(expandable)}>{i.name}</a>
                {/if}
                <Money value={i.value} cents={false} colored={toNumber(i.value) < 0} />
              </li>
              {#if open[i.account_id] && i.positions}{@render positionList(i)}{/if}
            {/each}
            {#if !col.items.length}<li class="muted small">–</li>{/if}
          </ul>
        </div>
      {/each}
      <div>
        <h3>Gebunden <span class="muted small">– frei ab</span></h3>
        <ul>
          {#each showAll ? bound : bound.slice(0, LIMIT) as i (i.account_id)}
            <li>
              <span class="name" class:indent={!expandable(i) && bound.some(expandable)}>
                {#if expandable(i)}
                  <button class="toggle" aria-expanded={!!open[i.account_id]} onclick={() => (open[i.account_id] = !open[i.account_id])}>
                    <span class="chev" class:rot={open[i.account_id]} aria-hidden="true">›</span>
                    <span class="ellipsis">{i.name}</span>
                  </button>
                {:else}
                  <a href="/konten/{i.account_id}">{i.name}</a>
                {/if}
                <span class="muted small" class:indent={expandable(i)}>
                  {#if i.free_from}{formatDate(i.free_from)} · {yearsUntil(i.free_from)}{i.free_reason && i.free_reason !== 'frei ab' ? ` (${i.free_reason})` : ''}{:else}{i.kind_label}{/if}
                </span>
              </span>
              <Money value={i.value} cents={false} />
            </li>
            {#if open[i.account_id] && i.positions}{@render positionList(i)}{/if}
          {/each}
        </ul>
      </div>
    </div>
    {#if current.length > LIMIT || invested.length > LIMIT || bound.length > LIMIT}
      <button class="link small" onclick={() => (showAll = !showAll)}>{showAll ? 'Weniger anzeigen' : 'Alle anzeigen'}</button>
    {/if}
    <p class="muted small">
      Verfügbar ist, was ihr kurzfristig nutzen könntet: auf den Haushaltskonten sofort (abzüglich Kreditkarten), angelegt in Tagesgeld, Depots, Krypto und
      Edelmetallen innerhalb weniger Tage. Welche Konten Haushaltskonten sind, legst du unter Konten fest. Gebunden sind Festgeld,
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
  .cur {
    background: var(--series-3);
  }
  .inv {
    background: var(--series-4);
  }
  .bound {
    background: var(--series-1);
  }
  .bar div + div {
    border-left: 2px solid var(--surface);
  }
  .dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
    vertical-align: -1px;
  }
  .dot.cur {
    background: var(--series-3);
  }
  .dot.inv {
    background: var(--series-4);
  }
  .dot.bound {
    background: var(--series-1);
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
  .toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    color: inherit;
    cursor: pointer;
    text-align: left;
  }
  .toggle:hover .ellipsis {
    text-decoration: underline;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
  .count {
    flex: none;
  }
  /* Aligns rows without a chevron with the names of expandable rows (chevron width + gap). */
  .indent {
    padding-left: calc(1em + 6px);
  }
  li.positions {
    display: block;
    padding: 0 0 6px 1.4em;
    border-top: 0;
  }
  li.positions li {
    padding: 4px 0;
    font-size: 0.9rem;
  }
  .val {
    display: grid;
    justify-items: end;
    flex: none;
  }
  .pos {
    color: var(--pos);
  }
  .neg {
    color: var(--neg);
  }
  .more {
    color: var(--accent-strong);
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
