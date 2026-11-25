<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import { formatDateTime } from '#lib/format.ts';

  interface Entry {
    id: number;
    at: string;
    actor: string;
    via: 'app' | 'mcp';
    client: string;
    action: string;
    target: string;
    detail: string;
  }

  let items = $state<Entry[]>([]);
  let more = $state(false);
  let loading = $state(false);
  let error = $state('');
  let filter = $state('');

  async function load(append = false) {
    loading = true;
    error = '';
    try {
      const before = append && items.length ? `&before=${items[items.length - 1].id}` : '';
      const res = await api.get<{ items: Entry[]; more: boolean }>(`/api/audit?limit=100${before}`);
      items = append ? [...items, ...res.items] : res.items;
      more = res.more;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(() => load());

  const shown = $derived.by(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;
    return items.filter((e) => [e.actor, e.client, e.action, e.target, e.detail].join(' ').toLowerCase().includes(q));
  });
</script>

<svelte:head><title>Änderungsprotokoll – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Änderungsprotokoll</h1>
  <p class="muted small">
    Jede Änderung in der App und über KI-Assistenten, mit Person und Zeitpunkt – auch An- und Abmeldungen. Zugangsdaten, PINs und TANs stehen hier nie.
  </p>

  <input type="search" placeholder="Suchen (Person, Aktion, Konto …)" bind:value={filter} aria-label="Protokoll durchsuchen" />

  {#if error}<p class="error">{error}</p>{/if}

  <section class="card">
    {#if shown.length}
      <ul class="log">
        {#each shown as e (e.id)}
          <li>
            <div class="line">
              <strong>{e.action}</strong>
              {#if e.target}<span>· {e.target}</span>{/if}
            </div>
            {#if e.detail}<div class="detail">{e.detail}</div>{/if}
            <div class="muted small">
              {formatDateTime(e.at)} · {e.actor || 'Unbekannt'}{#if e.via === 'mcp'}
                <span class="badge">über {e.client || 'KI-Assistent'}</span>{/if}
            </div>
          </li>
        {/each}
      </ul>
    {:else if !loading}
      <p class="muted small">{filter ? 'Nichts gefunden.' : 'Noch keine Einträge.'}</p>
    {/if}
  </section>

  {#if more}
    <div><button class="btn" onclick={() => load(true)} disabled={loading}>{loading ? 'Lädt …' : 'Ältere laden'}</button></div>
  {/if}
</div>

<style>
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .log {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .log li {
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    display: grid;
    gap: 2px;
    min-width: 0;
  }
  .log li:first-child {
    padding-top: 0;
  }
  .log li:last-child {
    border-bottom: 0;
    padding-bottom: 0;
  }
  .line,
  .detail {
    overflow-wrap: anywhere;
  }
  .detail {
    font-size: 0.9rem;
  }
  .badge {
    display: inline-block;
    padding: 0 6px;
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-size: 0.8rem;
  }
  .error {
    color: var(--warn);
  }
</style>
