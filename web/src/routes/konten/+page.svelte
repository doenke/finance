<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Account } from '#lib/api.ts';
  import { formatDate, toNumber } from '#lib/format.ts';
  import Icon from '#lib/Icon.svelte';
  import { label, loadMeta, meta } from '#lib/meta.svelte.ts';
  import Money from '#lib/Money.svelte';
  import PersonFilter from '#lib/PersonFilter.svelte';
  import { household, loadPersons, shareOf } from '#lib/persons.svelte.ts';

  let accounts = $state<Account[]>([]);
  let loaded = $state(false);
  let error = $state('');
  let showClosed = $state(false);

  onMount(async () => {
    try {
      await Promise.all([loadMeta(), loadPersons()]);
      accounts = await api.get<Account[]>('/api/accounts');
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  });

  const visible = $derived(accounts.filter((a) => (showClosed || !a.closed) && shareOf(a) > 0));
  const groups = $derived.by(() => {
    const order = meta.value?.asset_classes.map((c) => c.key) ?? [];
    const map = new Map<string, Account[]>();
    for (const a of visible) map.set(a.asset_class, [...(map.get(a.asset_class) ?? []), a]);
    return [...map.entries()]
      .sort((x, y) => order.indexOf(x[0]) - order.indexOf(y[0]))
      .map(([key, items]) => ({ key, label: label(meta.value?.asset_classes, key), items, total: items.reduce((s, a) => s + toNumber(a.value) * shareOf(a), 0) }));
  });
  const assets = $derived(groups.filter((g) => g.key !== 'liabilities').reduce((s, g) => s + g.total, 0));
  const debts = $derived(groups.filter((g) => g.key === 'liabilities').reduce((s, g) => s + g.total, 0));
  const hasClosed = $derived(accounts.some((a) => a.closed));
  const filtered = $derived(household.filter !== null);
</script>

<svelte:head><title>Konten – Finanzen</title></svelte:head>

<div class="stack">
  <div class="row head">
    <h1>Konten &amp; Anlagen</h1>
    <div class="row">
      <a class="btn" href="/import">Import</a>
      <a class="btn primary" href="/konten/neu"><Icon name="plus" size={18} /> Konto</a>
    </div>
  </div>
  <PersonFilter />
  {#if error}<p class="error">{error}</p>{/if}

  {#if loaded && accounts.length === 0}
    <div class="card stack empty">
      <h2>Noch keine Konten</h2>
      <p class="muted">Leg dein erstes Konto an – zum Beispiel das Girokonto, das Depot oder die Wohnung. Kontostände und Umsätze kannst du erst einmal von Hand eintragen.</p>
      <a class="btn primary" href="/konten/neu">Erstes Konto anlegen</a>
    </div>
  {:else if loaded}
    <div class="summary card">
      <div><span class="muted">Vermögen</span><strong><Money value={assets} cents={false} /></strong></div>
      <div><span class="muted">Schulden</span><strong><Money value={debts} cents={false} /></strong></div>
      <div><span class="muted">Netto</span><strong><Money value={assets + debts} cents={false} colored /></strong></div>
    </div>

    {#each groups as g (g.key)}
      <section class="card group">
        <header>
          <h2>{g.label}</h2>
          <strong><Money value={g.total} /></strong>
        </header>
        <ul>
          {#each g.items as a (a.id)}
            <li>
              <a href="/konten/{a.id}">
                <div class="grow">
                  <div class="name">{a.name}{a.closed ? ' (aufgelöst)' : ''}</div>
                  <div class="muted small">
                    {a.kind_label}{a.institution ? ` · ${a.institution}` : ''}{a.owners.length > 1 ? ' · gemeinsam' : ''}
                    {#if a.value_as_of}· Stand {formatDate(a.value_as_of)}{/if}
                    {#if a.missing_prices}· <span class="warn">{a.missing_prices} ohne Kurs</span>{/if}
                  </div>
                </div>
                <div class="value">
                  <Money value={toNumber(a.value) * shareOf(a)} />
                  {#if filtered && shareOf(a) < 1}<div class="muted small">Anteil {Math.round(shareOf(a) * 100)} %</div>{/if}
                </div>
              </a>
            </li>
          {/each}
        </ul>
      </section>
    {/each}

    {#if hasClosed}
      <label class="check"><input type="checkbox" bind:checked={showClosed} /> Aufgelöste Konten zeigen</label>
    {/if}
  {/if}
</div>

<style>
  .head {
    justify-content: space-between;
  }
  .head h1 {
    margin: 0;
  }
  .summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
    gap: 12px;
  }
  .summary div {
    display: grid;
  }
  .summary strong {
    font-size: 1.25rem;
  }
  .group {
    padding: 0;
    overflow: hidden;
  }
  .group header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
  }
  .group h2 {
    margin: 0;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li + li {
    border-top: 1px solid var(--border);
  }
  li a {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 12px 16px;
    color: inherit;
    text-decoration: none;
  }
  li a:hover {
    background: var(--surface-2);
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .name {
    font-weight: 500;
  }
  .value {
    text-align: right;
    white-space: nowrap;
  }
  .small {
    font-size: 0.85rem;
  }
  .warn {
    color: var(--warn);
  }
  .check {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
  }
  .check input {
    width: auto;
    min-height: auto;
  }
  .empty {
    justify-items: start;
  }
  @media (max-width: 520px) {
    .summary strong {
      font-size: 1.05rem;
    }
  }
</style>
