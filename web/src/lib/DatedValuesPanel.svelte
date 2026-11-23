<script lang="ts">
  // List of dated values: balance snapshots or valuations.
  import { onMount } from 'svelte';
  import { api } from './api.ts';
  import DecimalInput from './DecimalInput.svelte';
  import { formatDate, today } from './format.ts';
  import Icon from './Icon.svelte';
  import Money from './Money.svelte';

  let {
    accountId,
    endpoint,
    field,
    title,
    hint = '',
    negate = false,
    onchange = () => {}
  }: { accountId: number; endpoint: 'balances' | 'valuations'; field: 'amount' | 'value'; title: string; hint?: string; negate?: boolean; onchange?: () => void } = $props();

  let items = $state<any[]>([]);
  let form = $state<{ date: string; value: string; note: string } | null>(null);
  let error = $state('');

  async function load() {
    items = await api.get<any[]>(`/api/accounts/${accountId}/${endpoint}`);
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    error = '';
    const value = negate ? String(-Math.abs(Number(form.value))) : form.value;
    try {
      await api.post(`/api/accounts/${accountId}/${endpoint}`, { date: form.date, [field]: value, note: form.note });
      form = null;
      await load();
      onchange();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(id: number) {
    if (!confirm('Eintrag löschen?')) return;
    await api.del(`/api/accounts/${accountId}/${endpoint}/${id}`);
    await load();
    onchange();
  }

  onMount(load);
</script>

<section class="card stack">
  <div class="row head">
    <h2>{title}</h2>
    <button class="btn" onclick={() => (form = { date: today(), value: '', note: '' })}><Icon name="plus" size={18} /> Eintrag</button>
  </div>
  {#if hint}<p class="muted small">{hint}</p>{/if}
  {#if form}
    <form class="edit" onsubmit={save}>
      <label>Stichtag <input type="date" bind:value={form.date} required /></label>
      <label>Betrag <DecimalInput bind:value={form.value} suffix="€" required /></label>
      {#if field === 'value'}<label>Notiz <input bind:value={form.note} placeholder="z. B. Standmitteilung 2025" /></label>{/if}
      <div class="row">
        <button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" onclick={() => (form = null)}>Abbrechen</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </form>
  {/if}
  {#if items.length === 0}
    <p class="muted">Noch keine Einträge.</p>
  {:else}
    <table>
      <tbody>
        {#each items as item (item.id)}
          <tr>
            <td>{formatDate(item.date)}</td>
            <td class="muted small">{item.note ?? (item.source === 'manual' ? '' : item.source)}</td>
            <td class="r"><Money value={item[field]} /></td>
            <td class="r"><button class="btn icon danger" aria-label="Löschen" onclick={() => remove(item.id)}><Icon name="trash" size={16} /></button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .edit {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
    align-items: end;
    padding: 12px;
    background: var(--surface-2);
    border-radius: 10px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  td {
    padding: 8px 4px;
    border-top: 1px solid var(--border);
  }
  tr:first-child td {
    border-top: 0;
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
  .btn.icon {
    padding: 0;
    width: 36px;
    min-height: 36px;
  }
</style>
