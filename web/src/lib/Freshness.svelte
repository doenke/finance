<script lang="ts">
  // Traffic light: how current is the data? Details on hover (desktop) or tap (phone).
  import { api } from './api.ts';
  import { formatDate } from './format.ts';

  interface Item {
    area: 'bank' | 'prices' | 'manual' | 'holdings' | 'valuation';
    name: string;
    status: 'green' | 'yellow' | 'red';
    last: string | null;
    message: string;
    url: string;
    account_id?: number;
    confirmable?: boolean;
  }
  interface Data {
    status: 'green' | 'yellow' | 'red';
    counts: Record<string, number>;
    items: Item[];
  }

  let data = $state<Data | null>(null);
  let open = $state(false);
  let pinned = $state(false);
  let root: HTMLElement | undefined = $state();
  let busy = $state<number | null>(null);

  async function load() {
    try {
      data = await api.get<Data>('/api/freshness');
    } catch {
      data = null;
    }
  }
  $effect(() => {
    load();
  });

  async function confirm(i: Item) {
    if (!i.account_id) return;
    busy = i.account_id;
    try {
      await api.post(`/api/accounts/${i.account_id}/confirm`, {});
      await load();
    } finally {
      busy = null;
    }
  }

  const LABEL = { green: 'Daten aktuell', yellow: 'Teilweise veraltet', red: 'Veraltet' };
  const AREA = { bank: 'Bankabruf', prices: 'Kurs', manual: 'Konto (Import)', holdings: 'Depot', valuation: 'Stand' };
  const problems = $derived((data?.items ?? []).filter((i) => i.status !== 'green'));

  function onDoc(e: MouseEvent) {
    if (pinned && root && !root.contains(e.target as Node)) (pinned = false), (open = false);
  }
</script>

<svelte:document onclick={onDoc} onkeydown={(e) => e.key === 'Escape' && ((pinned = false), (open = false))} />

{#if data}
  <span class="fresh" bind:this={root} role="group" onmouseenter={() => (open = true)} onmouseleave={() => !pinned && (open = false)}>
    <button class="pill {data.status}" aria-expanded={open} onclick={() => ((pinned = !pinned), (open = pinned))}>
      <i class="dot"></i>{LABEL[data.status]}
    </button>
    {#if open}
      <div class="pop" role="note">
        {#if !problems.length}
          <p>Alles aktuell: Kurse von heute oder dem letzten Handelstag, Bankabrufe der letzten 7 Tage, Importe und Stände im erwarteten Rhythmus.</p>
        {:else}
          <p class="muted">{data.counts.green} Quellen aktuell, {problems.length} {problems.length === 1 ? 'braucht' : 'brauchen'} einen Blick:</p>
          <ul>
            {#each problems as i (i.area + i.name)}
              <li>
                <i class="dot {i.status}"></i>
                <span class="what">
                  <a href={i.url}>{i.name}</a>
                  <span class="muted small">{AREA[i.area]} · {i.message}</span>
                </span>
                {#if i.confirmable && i.account_id}
                  <button class="mini" disabled={busy === i.account_id} onclick={() => confirm(i)} title="Seit dem letzten Stand hat sich nichts geändert">Stimmt so</button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
        <p class="rules muted">
          Grün: Kurse ≤ 3 Handelstage, Bankabrufe ≤ 7 Tage, Krypto-Kurse ≤ 2 Tage, Haushaltskonten per Import ≤ 35 Tage (Sparkonten ≤ 95), Depots und ihre
          Verrechnungskonten ohne Bankabruf ≤ 6 Monate seit Kauf oder Bestätigung, Sparpläne ≤ 40 Tage seit der letzten Ausführung, Renten und Immobilien ≤ 13 Monate. Gelb bis etwa zum Doppelten, danach rot.
          {#if data.items.length}Stand {formatDate(new Date().toISOString().slice(0, 10))}.{/if}
        </p>
      </div>
    {/if}
  </span>
{/if}

<style>
  .fresh {
    position: relative;
    display: inline-block;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.85rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex: none;
  }
  .pill.green .dot,
  .dot.green {
    background: #16a34a;
  }
  .pill.yellow .dot,
  .dot.yellow {
    background: #f59e0b;
  }
  .pill.red .dot,
  .dot.red {
    background: #dc2626;
  }
  .pop {
    position: absolute;
    z-index: 30;
    right: 0;
    top: calc(100% + 6px);
    width: min(420px, 90vw);
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--surface);
    box-shadow: 0 8px 28px rgb(0 0 0 / 0.18);
    font-size: 0.9rem;
    line-height: 1.4;
  }
  @media (max-width: 560px) {
    .pop {
      position: fixed;
      left: 12px;
      right: 12px;
      top: 64px;
      width: auto;
      max-height: 70vh;
      overflow-y: auto;
    }
  }
  .pop p {
    margin: 0 0 8px;
  }
  ul {
    list-style: none;
    margin: 0 0 8px;
    padding: 0;
    display: grid;
    gap: 6px;
  }
  li {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .what {
    display: grid;
    flex: 1;
    min-width: 0;
  }
  .what a {
    color: inherit;
  }
  .small {
    font-size: 0.8rem;
  }
  .rules {
    font-size: 0.75rem;
    margin: 0;
  }
  .mini {
    padding: 3px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.78rem;
    cursor: pointer;
    white-space: nowrap;
  }
</style>
