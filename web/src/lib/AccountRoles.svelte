<script lang="ts">
  // Which accounts are household accounts (income and everyday spending) and which are savings.
  import { onMount } from 'svelte';
  import { api } from './api.ts';

  interface FlowAccount {
    id: number;
    name: string;
    kind: string;
    role: 'spending' | 'saving';
    automatic: boolean;
  }
  let accounts = $state<FlowAccount[]>([]);

  async function load() {
    accounts = await api.get<FlowAccount[]>('/api/flow-roles');
  }
  onMount(load);

  async function setRole(a: FlowAccount, role: 'spending' | 'saving') {
    await api.put(`/api/accounts/${a.id}/flow-role`, { role });
    await load();
  }

  const labels = { spending: 'Haushaltskonto', saving: 'Sparkonto' };
</script>

{#if accounts.length}
  <section class="card stack">
    <h2>Haushalts- und Sparkonten</h2>
    <p class="muted small">
      Auf Haushaltskonten gehen Einnahmen ein und laufende Ausgaben ab. Was von dort auf Sparkonten (Tagesgeld, Depots …) fließt, zählt in der Monatsbilanz als
      gespart; Geld zwischen zwei Haushaltskonten zählt nicht. Die Übersicht zeigt Haushaltskonten und Angelegtes getrennt.
    </p>
    <ul>
      {#each accounts as a (a.id)}
        <li>
          <span class="name"><a href="/konten/{a.id}">{a.name}</a>{#if a.automatic}<span class="muted small auto">automatisch</span>{/if}</span>
          <span class="seg" role="radiogroup" aria-label="Rolle von {a.name}">
            {#each ['spending', 'saving'] as const as r (r)}
              <button role="radio" aria-checked={a.role === r} class:active={a.role === r} onclick={() => setRole(a, r)}>{labels[r]}</button>
            {/each}
          </span>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  h2 {
    margin: 0;
  }
  .small {
    font-size: 0.85rem;
  }
  p.small {
    margin: 0;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  li a {
    color: inherit;
    text-decoration: none;
  }
  .name {
    flex: 1;
    min-width: 0;
  }
  .auto {
    margin-left: 8px;
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    margin-left: auto;
  }
  .seg button {
    font: inherit;
    font-size: 0.9rem;
    border: 0;
    background: var(--surface);
    color: var(--text);
    padding: 6px 10px;
    cursor: pointer;
  }
  .seg button + button {
    border-left: 1px solid var(--border);
  }
  .seg button.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 600;
  }
</style>
