<script lang="ts">
  import { page } from '$app/state';
  import { api, type Instrument, type PriceRow } from '#lib/api.ts';
  import DecimalInput from '#lib/DecimalInput.svelte';
  import { formatDate, today } from '#lib/format.ts';
  import Icon from '#lib/Icon.svelte';
  import { loadMeta, meta } from '#lib/meta.svelte.ts';
  import Money from '#lib/Money.svelte';
  import SymbolSearch from '#lib/SymbolSearch.svelte';

  let instrument = $state<Instrument | null>(null);
  let prices = $state<PriceRow[]>([]);
  let form = $state<Instrument | null>(null);
  let priceForm = $state<{ date: string; close: string } | null>(null);
  let error = $state('');
  let saved = $state(false);
  let syncing = $state(false);
  let syncInfo = $state('');

  async function syncPrices(full = false) {
    if (!instrument) return;
    syncing = true;
    syncInfo = '';
    error = '';
    try {
      const res = await api.post<{ updated: number }>(`/api/prices/instruments/${instrument.id}?full=${full}`);
      syncInfo = res.updated ? `${res.updated} Kurse geladen.` : 'Keine neuen Kurse.';
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      syncing = false;
    }
  }

  async function load() {
    await loadMeta();
    const id = page.params.id;
    instrument = (await api.get<Instrument[]>('/api/instruments')).find((i) => String(i.id) === id) ?? null;
    if (!instrument) {
      error = 'Wertpapier nicht gefunden';
      return;
    }
    form = { ...instrument, details: { ...instrument.details } };
    prices = await api.get<PriceRow[]>(`/api/instruments/${id}/prices?limit=50`);
  }

  $effect(() => {
    void page.params.id;
    load();
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form || !instrument) return;
    error = '';
    saved = false;
    try {
      const symbolChanged = form.price_symbol !== instrument.price_symbol || form.price_source !== instrument.price_source;
      instrument = await api.put<Instrument>(`/api/instruments/${instrument.id}`, form);
      saved = true;
      if (symbolChanged && instrument.price_source !== 'manual' && instrument.price_symbol) await syncPrices(true);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function savePrice(event: SubmitEvent) {
    event.preventDefault();
    if (!priceForm || !instrument) return;
    try {
      await api.post(`/api/instruments/${instrument.id}/prices`, priceForm);
      priceForm = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function removePrice(p: PriceRow) {
    if (!instrument || !confirm('Kurs löschen?')) return;
    await api.del(`/api/instruments/${instrument.id}/prices/${p.id}`);
    await load();
  }
</script>

<svelte:head><title>{instrument?.name ?? 'Wertpapier'} – Finanzen</title></svelte:head>

<div class="stack">
  <button class="back link" onclick={() => history.back()}>← zurück</button>
  {#if error}<p class="error">{error}</p>{/if}
  {#if form && instrument}
    <h1>{instrument.name}</h1>
    <form class="card stack" onsubmit={save}>
      <div class="grid">
        <label class="wide">Name <input bind:value={form.name} required /></label>
        <label>
          Art
          <select bind:value={form.kind}>
            {#each meta.value?.instrument_kinds ?? [] as k (k.key)}<option value={k.key}>{k.label}</option>{/each}
          </select>
        </label>
        <label>ISIN <input bind:value={form.isin} maxlength="12" /></label>
        <label>WKN <input bind:value={form.wkn} maxlength="6" /></label>
        <label>Währung <input bind:value={form.currency} maxlength="3" /></label>
        <label>
          Einheit
          <select bind:value={form.unit}>
            {#each meta.value?.units ?? [] as u (u.key)}<option value={u.key}>{u.label}</option>{/each}
          </select>
        </label>
        <label>
          Kursquelle
          <select bind:value={form.price_source}>
            <option value="onvista">onvista</option>
            <option value="yahoo">Yahoo Finance</option>
            <option value="manual">manuell</option>
          </select>
        </label>
        {#if form.price_source !== 'manual'}
          <div class="field wide">
            <span class="field-label">{form.price_source === 'onvista' ? 'onvista-Wertpapier' : 'Yahoo-Symbol'}</span>
            <SymbolSearch source={form.price_source} bind:symbol={form.price_symbol} query={form.isin || form.name} />
          </div>
        {/if}
        {#if form.kind === 'metal'}
          <label>Feingehalt <DecimalInput bind:value={form.details.fineness} placeholder="0,9999" /></label>
          <label>
            Kurs bezieht sich auf
            <select bind:value={form.details.price_unit}>
              <option value="oz">Feinunze</option>
              <option value="g">Gramm</option>
            </select>
          </label>
        {/if}
      </div>
      <div class="row">
        <button class="btn primary" type="submit">Speichern</button>
        {#if saved}<span class="muted">Gespeichert.</span>{/if}
      </div>
    </form>

    <section class="card stack">
      <div class="row head">
        <h2>Kurse</h2>
        <div class="row">
          {#if instrument.price_source !== 'manual' && instrument.price_symbol}
            <button class="btn" onclick={() => syncPrices(false)} disabled={syncing}>{syncing ? 'Lädt …' : 'Kurse jetzt laden'}</button>
          {/if}
          <button class="btn" onclick={() => (priceForm = { date: today(), close: '' })}><Icon name="plus" size={18} /> Kurs</button>
        </div>
      </div>
      {#if syncInfo}<p class="muted small">{syncInfo}</p>{/if}
      {#if instrument.price_source === 'manual'}
        <p class="muted small">Für dieses Wertpapier trägst du die Kurse selbst ein – zum Beispiel den festgesetzten Wert je STAK-Zertifikat. Er gilt bis zum nächsten Eintrag.</p>
      {/if}
      {#if priceForm}
        <form class="edit" onsubmit={savePrice}>
          <label>Datum <input type="date" bind:value={priceForm.date} required /></label>
          <label>Kurs <DecimalInput bind:value={priceForm.close} suffix={instrument.currency === 'EUR' ? '€' : ''} required /></label>
          <div class="row">
            <button class="btn primary" type="submit">Speichern</button>
            <button class="btn" type="button" onclick={() => (priceForm = null)}>Abbrechen</button>
          </div>
        </form>
      {/if}
      {#if prices.length === 0}
        <p class="muted">Noch keine Kurse.</p>
      {:else}
        <table>
          <tbody>
            {#each prices as p (p.id)}
              <tr>
                <td>{formatDate(p.date)}</td>
                <td class="muted small">{p.source === 'manual' ? 'manuell' : p.source}</td>
                <td class="r"><Money value={p.close} currency={instrument.currency} /></td>
                <td class="r"><button class="btn icon danger" aria-label="Kurs löschen" onclick={() => removePrice(p)}><Icon name="trash" size={16} /></button></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}
</div>

<style>
  .link {
    background: none;
    border: 0;
    color: var(--accent);
    font: inherit;
    font-size: 0.9rem;
    cursor: pointer;
    padding: 0;
    text-align: left;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
  }
  .wide {
    grid-column: 1 / -1;
  }
  .field {
    display: grid;
    gap: 4px;
  }
  .field-label {
    font-size: 0.9rem;
    color: var(--muted);
  }
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
  }
  .btn.icon {
    padding: 0;
    width: 36px;
    min-height: 36px;
  }
</style>
