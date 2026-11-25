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
  const debts = $derived((data?.items ?? []).filter((i) => i.bucket === 'liability'));
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

    <div class="groups">
      <div class="group avail">
        <div class="ghead">
          <span class="glabel">Verfügbar</span>
          <strong class="gsum"><Money value={data.available} cents={false} /></strong>
          {#if share !== null}<span class="muted small">{Math.round(share * 100)} % des Vermögens</span>{/if}
        </div>
        <div class="cols">
          {#each [{ title: 'Haushaltskonten', hint: 'sofort nutzbar', dot: 'cur', sum: data.current, items: current }, { title: 'Angelegt', hint: 'in wenigen Tagen', dot: 'inv', sum: data.invested, items: invested }] as col (col.title)}
            <div>
              <div class="chead">
                <span class="ctitle"><i class="dot {col.dot}"></i>{col.title}</span>
                <strong><Money value={col.sum} cents={false} /></strong>
              </div>
              <div class="muted small csub">{col.hint}</div>
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
        </div>
      </div>

      <div class="group bnd">
        <div class="ghead">
          <span class="glabel">Gebunden</span>
          <strong class="gsum"><Money value={data.bound} cents={false} /></strong>
          {#if share !== null}<span class="muted small">{100 - Math.round(share * 100)} % des Vermögens</span>{/if}
        </div>
        <div>
          <div class="chead">
            <span class="ctitle"><i class="dot bound"></i>Frei ab</span>
          </div>
          <div class="muted small csub">Altersvorsorge, Festgeld, Beteiligungen</div>
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
            {#if !bound.length}<li class="muted small">–</li>{/if}
          </ul>
        </div>
      </div>
    </div>

    {#if debts.length}
      <div class="debts">
        <div class="dline">
          <span class="glabel">Schulden</span>
          {#each debts as d (d.account_id)}
            <a href="/konten/{d.account_id}" class="debt">{d.name} <Money value={d.value} cents={false} /></a>
          {/each}
        </div>
        <div class="dline net">
          <span>Verfügbar nach Schulden <strong><Money value={toNumber(data.available) + toNumber(data.liabilities)} cents={false} colored /></strong></span>
          <span>Vermögen netto <strong><Money value={data.net} cents={false} /></strong></span>
        </div>
      </div>
    {/if}
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
  h2 {
    margin: 0;
  }
  .small {
    font-size: 0.8rem;
  }
  p.small {
    margin: 0;
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
  /* Verfügbar (two columns) and Gebunden (one column), each headed by its sum */
  .groups {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 16px 24px;
  }
  .cols {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px 24px;
  }
  .ghead {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 4px 12px;
    padding-bottom: 6px;
    margin-bottom: 10px;
    border-bottom: 2px solid var(--muted);
  }
  .avail .ghead {
    border-image: linear-gradient(90deg, var(--series-3), var(--series-4)) 1;
  }
  .bnd .ghead {
    border-bottom-color: var(--series-1);
  }
  .glabel {
    font-weight: 600;
  }
  .gsum {
    font-size: 1.5rem;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .chead {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
  }
  .ctitle {
    font-weight: 600;
    font-size: 0.95rem;
  }
  .chead strong {
    font-size: 1.05rem;
    font-variant-numeric: tabular-nums;
  }
  .csub {
    margin-bottom: 4px;
  }
  .debts {
    display: grid;
    gap: 6px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }
  .dline {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 20px;
  }
  .debt {
    white-space: nowrap;
  }
  .net {
    font-size: 0.9rem;
    color: var(--muted);
  }
  .net strong {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  @media (max-width: 900px) {
    .groups {
      grid-template-columns: 1fr;
    }
  }
  @media (max-width: 560px) {
    .cols {
      grid-template-columns: 1fr;
    }
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
