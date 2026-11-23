<script lang="ts">
  // Bookings of an account; `fixedKind` restricts the list to one kind (e.g. loan prepayments).
  import { onMount } from 'svelte';
  import { api, type Transaction } from './api.ts';
  import DecimalInput from './DecimalInput.svelte';
  import { formatDate, today } from './format.ts';
  import Icon from './Icon.svelte';
  import { label, meta } from './meta.svelte.ts';
  import Money from './Money.svelte';

  let {
    accountId,
    title = 'Umsätze',
    fixedKind = null,
    kinds = null,
    positiveOnly = false,
    onchange = () => {}
  }: { accountId: number; title?: string; fixedKind?: string | null; kinds?: string[] | null; positiveOnly?: boolean; onchange?: () => void } = $props();

  let items = $state<Transaction[]>([]);
  let q = $state('');
  let form = $state<{ id: number | null; booking_date: string; amount: string; kind: string; counterparty: string; purpose: string } | null>(null);
  let error = $state('');
  let showAll = $state(false);

  async function load() {
    const params = new URLSearchParams({ limit: '200' });
    if (q) params.set('q', q);
    const all = await api.get<Transaction[]>(`/api/accounts/${accountId}/transactions?${params}`);
    items = fixedKind ? all.filter((t) => t.kind === fixedKind) : kinds ? all.filter((t) => kinds!.includes(t.kind)) : all;
  }

  function startNew() {
    form = { id: null, booking_date: today(), amount: '', kind: fixedKind ?? kinds?.[0] ?? 'other', counterparty: '', purpose: '' };
  }

  function startEdit(t: Transaction) {
    form = { id: t.id, booking_date: t.booking_date, amount: positiveOnly ? String(Math.abs(Number(t.amount))) : t.amount, kind: t.kind, counterparty: t.counterparty, purpose: t.purpose };
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    error = '';
    const body = { ...form, amount: positiveOnly ? String(Math.abs(Number(form.amount))) : form.amount };
    try {
      if (form.id === null) await api.post(`/api/accounts/${accountId}/transactions`, body);
      else await api.put(`/api/accounts/${accountId}/transactions/${form.id}`, body);
      form = null;
      await load();
      onchange();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(t: Transaction) {
    if (!confirm('Buchung löschen?')) return;
    await api.del(`/api/accounts/${accountId}/transactions/${t.id}`);
    await load();
    onchange();
  }

  const kindOptions = $derived((meta.value?.transaction_kinds ?? []).filter((k) => !kinds || kinds.includes(k.key)));

  onMount(load);
</script>

<section class="card stack">
  <div class="row head">
    <h2>{title}</h2>
    <button class="btn" onclick={startNew}><Icon name="plus" size={18} /> Buchung</button>
  </div>
  {#if !fixedKind && !kinds}
    <input type="search" placeholder="Suchen (Empfänger, Verwendungszweck)" bind:value={q} oninput={load} />
  {/if}

  {#if form}
    <form class="edit" onsubmit={save}>
      <label>Datum <input type="date" bind:value={form.booking_date} required /></label>
      <label>Betrag <DecimalInput bind:value={form.amount} suffix="€" required placeholder={positiveOnly ? '' : '− für Ausgaben'} /></label>
      {#if !fixedKind}
        <label>
          Art
          <select bind:value={form.kind}>
            {#each kindOptions as k (k.key)}<option value={k.key}>{k.label}</option>{/each}
          </select>
        </label>
      {/if}
      <label>Empfänger / Auftraggeber <input bind:value={form.counterparty} maxlength="255" /></label>
      <label class="wide">Verwendungszweck <input bind:value={form.purpose} /></label>
      <div class="row wide">
        <button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" onclick={() => (form = null)}>Abbrechen</button>
      </div>
      {#if error}<p class="error wide">{error}</p>{/if}
    </form>
  {/if}

  {#if items.length === 0}
    <p class="muted">Noch keine Buchungen.</p>
  {:else}
    <ul class="list">
      {#each showAll ? items : items.slice(0, 25) as t (t.id)}
        <li>
          <button class="item" onclick={() => startEdit(t)}>
            <span class="date muted">{formatDate(t.booking_date)}</span>
            <span class="text">
              <span class="cp">{t.counterparty || label(meta.value?.transaction_kinds, t.kind)}</span>
              {#if t.purpose}<span class="muted small purpose">{t.purpose}</span>{/if}
            </span>
            <span class="amount"><Money value={t.amount} colored /></span>
          </button>
          <button class="btn icon danger" aria-label="Buchung löschen" onclick={() => remove(t)}><Icon name="trash" size={16} /></button>
        </li>
      {/each}
    </ul>
    {#if items.length > 25 && !showAll}
      <button class="btn" onclick={() => (showAll = true)}>Alle {items.length} Buchungen zeigen</button>
    {/if}
  {/if}
</section>

<style>
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .edit {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
    padding: 12px;
    background: var(--surface-2);
    border-radius: 10px;
  }
  .wide {
    grid-column: 1 / -1;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .list li + li {
    border-top: 1px solid var(--border);
  }
  .item {
    flex: 1;
    min-width: 0;
    display: grid;
    grid-template-columns: 88px 1fr auto;
    gap: 12px;
    align-items: center;
    padding: 10px 0;
    background: none;
    border: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .text {
    display: grid;
    min-width: 0;
  }
  .cp,
  .purpose {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .small {
    font-size: 0.85rem;
  }
  .amount {
    white-space: nowrap;
  }
  .btn.icon {
    padding: 0;
    width: 36px;
    min-height: 36px;
  }
  @media (max-width: 520px) {
    .item {
      grid-template-columns: 1fr auto;
    }
    .date {
      grid-column: 1 / -1;
      font-size: 0.8rem;
    }
  }
</style>
