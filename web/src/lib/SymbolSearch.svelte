<script lang="ts">
  // Finds the Yahoo symbol for a security (search by ISIN, name or ticker).
  import { api } from './api.ts';

  interface Result {
    symbol: string;
    name: string;
    exchange: string;
    type: string;
  }

  let {
    symbol = $bindable(),
    query = '',
    source = 'onvista',
    onpick = () => {}
  }: { symbol?: string | null; query?: string; source?: string; onpick?: (r: Result) => void } = $props();

  let results = $state<Result[]>([]);
  let searching = $state(false);
  let error = $state('');
  let searched = $state(false);

  async function search() {
    const q = (query || symbol || '').trim();
    if (q.length < 2) {
      error = 'Bitte ISIN oder Name eingeben.';
      return;
    }
    searching = true;
    error = '';
    try {
      results = await api.get<Result[]>(`/api/prices/search?q=${encodeURIComponent(q)}&source=${source}`);
      searched = true;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      searching = false;
    }
  }

  function pick(r: Result) {
    symbol = r.symbol;
    results = [];
    searched = false;
    onpick(r);
  }
</script>

<div class="wrap">
  <div class="row nowrap">
    <input bind:value={symbol} placeholder={source === 'onvista' ? 'per ISIN suchen' : 'z. B. EUNL.DE, BTC-EUR'} autocomplete="off" aria-label="Kurs-Symbol" />
    <button type="button" class="btn" onclick={search} disabled={searching}>{searching ? 'Sucht …' : 'Suchen'}</button>
  </div>
  {#if error}<p class="error small">{error}</p>{/if}
  {#if results.length}
    <ul class="results">
      {#each results as r (r.symbol)}
        <li>
          <button type="button" onclick={() => pick(r)}>
            <strong>{r.symbol}</strong>
            <span class="muted">{r.name}</span>
            <span class="muted small">{r.exchange} · {r.type}</span>
          </button>
        </li>
      {/each}
    </ul>
  {:else if searched}
    <p class="muted small">Nichts gefunden – versuch es mit dem Namen statt der ISIN.</p>
  {/if}
</div>

<style>
  .wrap {
    display: grid;
    gap: 6px;
  }
  .nowrap {
    flex-wrap: nowrap;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .results {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    background: var(--surface);
  }
  .results li + li {
    border-top: 1px solid var(--border);
  }
  .results button {
    display: grid;
    gap: 2px;
    width: 100%;
    text-align: left;
    padding: 8px 12px;
    background: none;
    border: 0;
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  .results button:hover {
    background: var(--surface-2);
  }
</style>
