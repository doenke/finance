<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Instrument, type Position, type Trade } from './api.ts';
  import DecimalInput from './DecimalInput.svelte';
  import { formatDate, formatNumber, formatPercent, today } from './format.ts';
  import Icon from './Icon.svelte';
  import { label, meta } from './meta.svelte.ts';
  import Money from './Money.svelte';
  import SymbolSearch from './SymbolSearch.svelte';

  let { accountId, accountKind, onchange = () => {} }: { accountId: number; accountKind: string; onchange?: () => void } = $props();

  const defaultInstrumentKind: Record<string, string> = { depot: 'etf', krypto: 'crypto', stak: 'stak', edelmetall: 'metal' };

  let positions = $state<Position[]>([]);
  let trades = $state<Trade[]>([]);
  let instruments = $state<Instrument[]>([]);
  let form = $state<null | { id: number | null; date: string; type: string; instrument_id: number | null; quantity: string; price: string; amount: string; fees: string; taxes: string; note: string }>(null);
  let newInstrument = $state<null | { kind: string; name: string; isin: string; symbol: string; unit: string; price_source: string; price_symbol: string }>(null);
  let error = $state('');
  let showAll = $state(false);

  async function load() {
    [positions, trades, instruments] = await Promise.all([
      api.get<Position[]>(`/api/accounts/${accountId}/positions`),
      api.get<Trade[]>(`/api/accounts/${accountId}/trades`),
      api.get<Instrument[]>('/api/instruments')
    ]);
  }

  const instrumentName = (id: number | null) => instruments.find((i) => i.id === id)?.name ?? '–';
  const needsInstrument = $derived(form ? ['buy', 'sell', 'deliver_in', 'deliver_out', 'dividend', 'split', 'advance_tax'].includes(form.type) : false);
  const needsQuantity = $derived(form ? ['buy', 'sell', 'deliver_in', 'deliver_out', 'split'].includes(form.type) : false);
  const hasPrice = $derived(form ? ['buy', 'sell', 'deliver_in', 'deliver_out'].includes(form.type) : false);
  const totalValue = $derived(positions.reduce((s, p) => s + Number(p.value), 0));
  const totalCost = $derived(positions.reduce((s, p) => s + Number(p.cost), 0));

  function startNew(type = 'buy', instrumentId: number | null = null) {
    newInstrument = null;
    form = { id: null, date: today(), type, instrument_id: instrumentId, quantity: '', price: '', amount: '', fees: '', taxes: '', note: '' };
  }

  function startEdit(t: Trade) {
    newInstrument = null;
    form = { id: t.id, date: t.date, type: t.type, instrument_id: t.instrument_id, quantity: t.quantity, price: t.price ?? '', amount: t.amount, fees: t.fees, taxes: t.taxes, note: t.note };
  }

  function startNewInstrument() {
    const kind = defaultInstrumentKind[accountKind] ?? 'etf';
    newInstrument = { kind, name: '', isin: '', symbol: '', unit: kind === 'metal' ? 'g' : 'piece', price_source: kind === 'stak' ? 'manual' : 'onvista', price_symbol: '' };
  }

  async function saveInstrument() {
    if (!newInstrument || !form) return;
    error = '';
    try {
      const body: Record<string, any> = { ...newInstrument };
      if (newInstrument.kind === 'metal') body.details = { price_unit: 'oz', fineness: '0.9999' };
      const created = await api.post<Instrument>('/api/instruments', body);
      instruments = [...instruments, created];
      form.instrument_id = created.id;
      newInstrument = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    error = '';
    const body = {
      ...form,
      instrument_id: needsInstrument || form.instrument_id ? form.instrument_id : null,
      quantity: form.quantity || '0',
      price: form.price || null,
      amount: form.amount || '0',
      fees: form.fees || '0',
      taxes: form.taxes || '0'
    };
    try {
      if (form.id === null) await api.post(`/api/accounts/${accountId}/trades`, body);
      else await api.put(`/api/accounts/${accountId}/trades/${form.id}`, body);
      form = null;
      await load();
      onchange();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(t: Trade) {
    if (!confirm('Transaktion löschen?')) return;
    await api.del(`/api/accounts/${accountId}/trades/${t.id}`);
    await load();
    onchange();
  }

  onMount(load);
</script>

<section class="card stack">
  <div class="row head">
    <h2>Positionen</h2>
    <button class="btn" onclick={() => startNew()}><Icon name="plus" size={18} /> Transaktion</button>
  </div>
  {#if positions.length === 0}
    <p class="muted">Noch keine Positionen. Leg mit „Transaktion“ einen Kauf oder eine Einlieferung an.</p>
  {:else}
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Wertpapier</th><th class="r hide-sm">Bestand</th><th class="r hide-sm">Kurs</th><th class="r">Wert</th><th class="r hide-sm">Einstand</th><th class="r">G/V</th></tr>
        </thead>
        <tbody>
          {#each positions as p (p.instrument.id)}
            <tr>
              <td>
                <a href="/wertpapiere/{p.instrument.id}">{p.instrument.name}</a>
                <div class="muted small">{p.instrument.isin ?? p.instrument.price_symbol ?? label(meta.value?.instrument_kinds, p.instrument.kind)}</div>
              </td>
              <td class="r num hide-sm">{formatNumber(p.quantity, 8)}</td>
              <td class="r hide-sm">
                {#if p.price}<Money value={p.price} currency={p.instrument.currency} /><div class="small" class:muted={!p.stale} class:warn={p.stale}>{formatDate(p.price_date)}{p.stale ? ' · veraltet' : ''}</div>{:else}<span class="warn">kein Kurs</span>{/if}
              </td>
              <td class="r"><Money value={p.value} /><div class="muted small show-sm">{formatNumber(p.quantity, 8)} Stück</div></td>
              <td class="r hide-sm"><Money value={p.cost} /></td>
              <td class="r"><Money value={p.gain} colored /><div class="small">{formatPercent(p.gain_pct)}</div></td>
            </tr>
          {/each}
        </tbody>
        <tfoot>
          <tr>
            <td>Summe</td><td class="hide-sm"></td><td class="hide-sm"></td>
            <td class="r"><Money value={totalValue} /></td>
            <td class="r hide-sm"><Money value={totalCost} /></td>
            <td class="r"><Money value={totalValue - totalCost} colored /></td>
          </tr>
        </tfoot>
      </table>
    </div>
  {/if}
</section>

{#if form}
  <form class="card stack" onsubmit={save}>
    <h2>{form.id === null ? 'Neue Transaktion' : 'Transaktion bearbeiten'}</h2>
    <div class="grid">
      <label>
        Art
        <select bind:value={form.type}>
          {#each meta.value?.trade_types ?? [] as t (t.key)}<option value={t.key}>{t.label}</option>{/each}
        </select>
      </label>
      <label>Datum <input type="date" bind:value={form.date} required /></label>
      {#if needsInstrument || form.instrument_id}
        <label class="wide">
          Wertpapier
          <div class="row nowrap">
            <select bind:value={form.instrument_id} required={needsInstrument}>
              <option value={null}>– bitte wählen –</option>
              {#each instruments as i (i.id)}<option value={i.id}>{i.name}{i.isin ? ` (${i.isin})` : ''}</option>{/each}
            </select>
            <button type="button" class="btn" onclick={startNewInstrument}>Neu</button>
          </div>
        </label>
      {/if}
    </div>

    {#if newInstrument}
      <div class="grid sub">
        <label>
          Art
          <select bind:value={newInstrument.kind}>
            {#each meta.value?.instrument_kinds ?? [] as k (k.key)}<option value={k.key}>{k.label}</option>{/each}
          </select>
        </label>
        <label class="wide2">Name <input bind:value={newInstrument.name} placeholder="z. B. iShares Core MSCI World" /></label>
        <label>ISIN <input bind:value={newInstrument.isin} maxlength="12" /></label>
        <label>
          Einheit
          <select bind:value={newInstrument.unit}>
            {#each meta.value?.units ?? [] as u (u.key)}<option value={u.key}>{u.label}</option>{/each}
          </select>
        </label>
        <label>
          Kursquelle
          <select bind:value={newInstrument.price_source}>
            <option value="onvista">onvista</option>
            <option value="yahoo">Yahoo Finance</option>
            <option value="manual">manuell</option>
          </select>
        </label>
        {#if newInstrument.price_source !== 'manual'}
          <div class="wide2 field">
            <span class="field-label">{newInstrument.price_source === 'onvista' ? 'onvista-Wertpapier' : 'Yahoo-Symbol'}</span>
            <SymbolSearch
              source={newInstrument.price_source}
              bind:symbol={newInstrument.price_symbol}
              query={newInstrument.isin || newInstrument.name}
              onpick={(r) => {
                if (newInstrument && !newInstrument.name) newInstrument.name = r.name;
              }}
            />
          </div>
        {/if}
        <div class="row wide">
          <button type="button" class="btn primary" onclick={saveInstrument} disabled={!newInstrument.name}>Wertpapier anlegen</button>
          <button type="button" class="btn" onclick={() => (newInstrument = null)}>Abbrechen</button>
        </div>
      </div>
    {/if}

    <div class="grid">
      {#if needsQuantity}
        <label>{form.type === 'split' ? 'Faktor (z. B. 4 bei 1:4)' : 'Stück / Menge'} <DecimalInput bind:value={form.quantity} required /></label>
      {/if}
      {#if hasPrice}
        <label>Kurs <DecimalInput bind:value={form.price} suffix="€" /></label>
        <label>Kurswert <DecimalInput bind:value={form.amount} suffix="€" placeholder="Stück × Kurs" /></label>
      {:else if form.type !== 'split'}
        <label>Betrag <DecimalInput bind:value={form.amount} suffix="€" required /></label>
      {/if}
      {#if form.type !== 'split'}
        <label>Gebühren <DecimalInput bind:value={form.fees} suffix="€" /></label>
        <label>Steuern <DecimalInput bind:value={form.taxes} suffix="€" /></label>
      {/if}
      <label class="wide">Notiz <input bind:value={form.note} /></label>
    </div>
    {#if error}<p class="error">{error}</p>{/if}
    <div class="row">
      <button class="btn primary" type="submit">Speichern</button>
      <button class="btn" type="button" onclick={() => (form = null)}>Abbrechen</button>
    </div>
  </form>
{/if}

<section class="card stack">
  <h2>Transaktionen</h2>
  {#if trades.length === 0}
    <p class="muted">Noch keine Transaktionen.</p>
  {:else}
    <ul class="list">
      {#each showAll ? trades : trades.slice(0, 15) as t (t.id)}
        <li>
          <button class="item" onclick={() => startEdit(t)}>
            <span class="muted">{formatDate(t.date)}</span>
            <span class="text">
              <span>{label(meta.value?.trade_types, t.type)}{t.instrument_id ? ` · ${instrumentName(t.instrument_id)}` : ''}</span>
              {#if Number(t.quantity)}<span class="muted small">{formatNumber(t.quantity, 8)} {t.type === 'split' ? '× Faktor' : 'Stück'}{t.price ? ` à ${formatNumber(t.price, 4)}` : ''}</span>{/if}
            </span>
            <span class="r"><Money value={t.amount} /></span>
          </button>
          <button class="btn icon danger" aria-label="Transaktion löschen" onclick={() => remove(t)}><Icon name="trash" size={16} /></button>
        </li>
      {/each}
    </ul>
    {#if trades.length > 15 && !showAll}
      <button class="btn" onclick={() => (showAll = true)}>Alle {trades.length} Transaktionen zeigen</button>
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
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.95rem;
  }
  th {
    font-weight: 500;
    color: var(--muted);
    text-align: left;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  td {
    padding: 8px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  tfoot td {
    font-weight: 600;
    border-bottom: 0;
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
  .small {
    font-size: 0.8rem;
  }
  .warn {
    color: var(--warn);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
  }
  .sub {
    padding: 12px;
    background: var(--surface-2);
    border-radius: 10px;
  }
  .wide {
    grid-column: 1 / -1;
  }
  .wide2 {
    grid-column: span 2;
  }
  .field {
    display: grid;
    gap: 4px;
  }
  .field-label {
    font-size: 0.9rem;
    color: var(--muted);
  }
  .nowrap {
    flex-wrap: nowrap;
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
  .btn.icon {
    padding: 0;
    width: 36px;
    min-height: 36px;
  }
  .show-sm {
    display: none;
  }
  @media (max-width: 520px) {
    .hide-sm {
      display: none;
    }
    .show-sm {
      display: block;
    }
    .wide2 {
      grid-column: 1 / -1;
    }
    .item {
      grid-template-columns: 1fr auto;
    }
    .item > .muted:first-child {
      grid-column: 1 / -1;
      font-size: 0.8rem;
    }
  }
</style>
