<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { api, type Account } from '#lib/api.ts';
  import { formatDate, formatNumber } from '#lib/format.ts';
  import Icon from '#lib/Icon.svelte';
  import { label, loadMeta, meta } from '#lib/meta.svelte.ts';
  import Money from '#lib/Money.svelte';

  type Kind = 'bookings' | 'pp' | 'bsdex';
  interface Batch {
    id: number;
    kind: string;
    account_name: string | null;
    filename: string;
    count: number;
    created_at: string;
  }

  let kind = $state<Kind>('bookings');
  let accounts = $state<Account[]>([]);
  let accountId = $state<number | null>(null);
  let filename = $state('');
  let text = $state('');
  let preview = $state<any>(null);
  let mapping = $state<Record<string, number | null>>({});
  let dateFormat = $state('');
  let invert = $state(false);
  let profileName = $state('');
  let profiles = $state<Record<string, any>>({});
  let batches = $state<Batch[]>([]);
  let error = $state('');
  let info = $state('');
  let busy = $state(false);

  const targets = $derived(
    accounts.filter((a) => !a.closed && (kind === 'bsdex' ? a.kind === 'krypto' : kind === 'pp' ? a.mode === 'holdings' : a.mode !== 'holdings'))
  );
  const endpoint = $derived(kind === 'pp' ? 'portfolio-performance' : kind);
  const fields = [
    { key: 'booking_date', label: 'Buchungstag', required: true },
    { key: 'amount', label: 'Betrag', required: true },
    { key: 'counterparty', label: 'Empfänger / Auftraggeber' },
    { key: 'purpose', label: 'Verwendungszweck' },
    { key: 'value_date', label: 'Valuta' }
  ];

  async function load() {
    await loadMeta();
    [accounts, batches, profiles] = await Promise.all([
      api.get<Account[]>('/api/accounts'),
      api.get<Batch[]>('/api/import/batches'),
      api.get<Record<string, any>>('/api/import/profiles')
    ]);
  }
  onMount(async () => {
    await load();
    await pickUpShared();
  });

  function decode(buf: ArrayBuffer): string {
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(buf);
    } catch {
      return new TextDecoder('windows-1252').decode(buf); // older bank exports
    }
  }

  /** Guesses the export type from the header line. */
  function detectKind(content: string): Kind {
    const head = content.replace(/^\ufeff/, '').split(/\r?\n/, 1)[0] ?? '';
    if (head.includes('Kryptowährung') && head.includes('Transaktionsentgelt')) return 'bsdex';
    if (/Wertpapiername|Security Name/i.test(head) || (/(^|[;,])"?(Datum|Date)"?[;,]/.test(head) && /Typ|Type/.test(head) && /Stück|Shares/.test(head))) return 'pp';
    return 'bookings';
  }

  function useFile(name: string, content: string, autodetect: boolean) {
    filename = name;
    text = content;
    mapping = {};
    if (autodetect) {
      const detected = detectKind(content);
      if (detected !== kind) {
        kind = detected;
        accountId = null;
      }
      // Preselect the only fitting account, e.g. the one crypto depot for BSDEX.
      if (accountId === null && targets.length === 1) accountId = targets[0].id;
    }
  }

  async function pickUpShared() {
    const flag = page.url.searchParams.get('geteilt');
    if (!flag) return;
    history.replaceState(history.state, '', '/import');
    if (flag === 'fehler') {
      error = 'Die geteilte Datei konnte nicht gelesen werden. Teile sie bitte noch einmal oder wähle sie unten aus.';
      return;
    }
    try {
      const cache = await caches.open('finanzen-share');
      const res = await cache.match('/__shared/file');
      if (!res) {
        error = 'Die geteilte Datei ist nicht angekommen – bitte noch einmal teilen.';
        return;
      }
      const name = decodeURIComponent(res.headers.get('X-Filename') ?? 'geteilt.csv');
      useFile(name, decode(await res.arrayBuffer()), true);
      await cache.delete('/__shared/file');
      await runPreview();
      info = `„${name}“ empfangen${accountId === null ? ' – wähle jetzt das Konto.' : '.'}`;
    } catch {
      error = 'Die geteilte Datei konnte nicht gelesen werden.';
    }
  }

  async function onFile(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    const content = decode(await file.arrayBuffer());
    useFile(file.name, content, false);
    await runPreview();
  }

  function body() {
    if (kind === 'pp') return { account_id: accountId, text, filename };
    if (kind === 'bsdex') return { account_id: accountId, text, filename, create_settlement: true };
    return {
      account_id: accountId,
      text,
      filename,
      mapping: Object.keys(mapping).length ? mapping : null,
      date_format: dateFormat || null,
      invert,
      profile: profileName || null
    };
  }

  async function runPreview() {
    error = '';
    info = '';
    preview = null;
    if (!accountId || !text) return;
    busy = true;
    try {
      const url = `/api/import/${endpoint}/preview`;
      preview = await api.post<any>(url, body());
      if (kind === 'bookings') mapping = { ...preview.mapping };
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function applyProfile(name: string) {
    const p = profiles[name];
    if (!p) return;
    mapping = { ...p.mapping };
    dateFormat = p.date_format ?? '';
    invert = !!p.invert;
    profileName = name;
    runPreview();
  }

  async function commit() {
    busy = true;
    error = '';
    try {
      const url = `/api/import/${endpoint}/commit`;
      const res = await api.post<any>(url, body());
      info =
        kind === 'bsdex'
          ? `${res.trades} Orders und ${res.cash} Euro-Buchungen übernommen${res.skipped ? `, ${res.skipped} übersprungen` : ''}.`
          : `${res.imported} ${kind === 'pp' ? 'Transaktionen' : 'Buchungen'} übernommen${res.skipped ? `, ${res.skipped} übersprungen` : ''}.`;
      preview = null;
      text = '';
      filename = '';
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function undo(b: Batch) {
    if (!confirm(`Import „${b.filename || b.kind}“ mit ${b.count} Einträgen rückgängig machen?`)) return;
    await api.del(`/api/import/batches/${b.id}`);
    await load();
  }

  const bsdexKind: Record<string, string> = { buy: 'Kauf', sell: 'Verkauf', deposit: 'Einzahlung', withdrawal: 'Auszahlung' };
  const statusLabel: Record<string, string> = { new: 'neu', duplicate: 'schon da', error: 'Fehler', skipped: 'übersprungen' };
</script>

<svelte:head><title>Import – Finanzen</title></svelte:head>

<div class="stack">
  <a class="back" href="/konten">← Konten</a>
  <h1>Import</h1>

  <section class="card stack">
    <div class="seg" role="radiogroup" aria-label="Art des Imports">
      <button role="radio" aria-checked={kind === 'bookings'} class:active={kind === 'bookings'} onclick={() => { kind = 'bookings'; accountId = null; preview = null; }}>Kontoumsätze (CSV)</button>
      <button role="radio" aria-checked={kind === 'pp'} class:active={kind === 'pp'} onclick={() => { kind = 'pp'; accountId = null; preview = null; }}>Portfolio Performance</button>
      <button role="radio" aria-checked={kind === 'bsdex'} class:active={kind === 'bsdex'} onclick={() => { kind = 'bsdex'; accountId = null; preview = null; }}>BSDEX</button>
    </div>
    <p class="muted small">
      {#if kind === 'bookings'}
        CSV-Export deiner Bank, z. B. Sparkasse („CSV-CAMT“), DKB oder OLB. Die Spalten werden erkannt; du kannst sie unten anpassen und als Vorlage speichern. Doppelte Buchungen werden übersprungen.
      {:else if kind === 'bsdex'}
        Den CSV-Export deiner Transaktionen aus BSDEX. Ausgeführte Käufe und Verkäufe landen im Krypto-Depot, Einzahlungen und der
        Euro-Anteil jeder Order auf dessen Verrechnungskonto – fehlt eins, legt Finanzen „… – Euro“ an. Abgelehnte Orders werden übersprungen. Wähle
        als Ziel ein Konto der Art „Krypto“.
      {:else}
        In Portfolio Performance: Depot auswählen → Rechtsklick „Export“ → „Umsätze (CSV)“. Käufe, Verkäufe, Ein- und Auslieferungen, Dividenden, Zinsen, Steuern und Gebühren werden übernommen, Wertpapiere bei Bedarf angelegt.
      {/if}
    </p>
    <div class="grid">
      <label>
        In Konto
        <select bind:value={accountId} onchange={runPreview}>
          <option value={null}>– bitte wählen –</option>
          {#each targets as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
        </select>
      </label>
      <label>
        Datei
        <input type="file" accept=".csv,.txt,text/csv" onchange={onFile} disabled={!accountId} />
        {#if filename && text}<span class="muted small">Geladen: {filename}</span>{/if}
      </label>
      {#if kind === 'bookings' && Object.keys(profiles).length}
        <label>
          Vorlage
          <select onchange={(e) => applyProfile(e.currentTarget.value)}>
            <option value="">–</option>
            {#each Object.keys(profiles) as name (name)}<option value={name}>{name}</option>{/each}
          </select>
        </label>
      {/if}
    </div>
  </section>

  {#if error}<p class="error">{error}</p>{/if}
  {#if info}<p class="ok">{info}</p>{/if}

  {#if preview && kind === 'bookings'}
    <section class="card stack">
      <h2>Spalten</h2>
      <div class="grid">
        {#each fields as f (f.key)}
          <label>
            {f.label}{f.required ? ' *' : ''}
            <select bind:value={mapping[f.key]} onchange={runPreview}>
              <option value={null}>–</option>
              {#each preview.header as h, i (i)}<option value={i}>{h || `Spalte ${i + 1}`}</option>{/each}
            </select>
          </label>
        {/each}
        <label>
          Datumsformat
          <select bind:value={dateFormat} onchange={runPreview}>
            <option value="">automatisch</option>
            <option value="%d.%m.%Y">TT.MM.JJJJ</option>
            <option value="%d.%m.%y">TT.MM.JJ</option>
            <option value="%Y-%m-%d">JJJJ-MM-TT</option>
            <option value="%m/%d/%Y">MM/TT/JJJJ</option>
          </select>
        </label>
        <label class="check"><input type="checkbox" bind:checked={invert} onchange={runPreview} /> Vorzeichen umdrehen</label>
        <label>Als Vorlage speichern <input bind:value={profileName} placeholder="z. B. Sparkasse" /></label>
      </div>
    </section>
  {/if}

  {#if preview}
    <section class="card stack">
      <div class="row head">
        <h2>Vorschau</h2>
        <span class="muted">
          {preview.summary.new} neu · {preview.summary.duplicate} schon vorhanden{#if preview.summary.skipped} · {preview.summary.skipped} übersprungen{/if}{#if preview.summary.error} · <span class="error">{preview.summary.error} Fehler</span>{/if}
        </span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            {#if kind === 'bookings'}
              <tr><th>Status</th><th>Datum</th><th>Empfänger / Auftraggeber</th><th>Verwendungszweck</th><th class="r">Betrag</th></tr>
            {:else if kind === 'bsdex'}
              <tr><th>Status</th><th>Datum</th><th>Art</th><th class="r">Menge</th><th class="r">Kurs</th><th class="r">Betrag</th><th class="r">Gebühr</th></tr>
            {:else}
              <tr><th>Status</th><th>Datum</th><th>Art</th><th>Wertpapier</th><th class="r">Stück</th><th class="r">Betrag</th></tr>
            {/if}
          </thead>
          <tbody>
            {#each preview.rows.slice(0, 200) as r (r.line)}
              <tr class={r.status}>
                <td><span class="badge {r.status}">{statusLabel[r.status]}</span>{#if r.error || r.message}<div class="small muted">{r.error || r.message}</div>{/if}</td>
                <td>{formatDate(r.booking_date ?? r.date)}</td>
                {#if kind === 'bsdex'}
                  <td>{r.kind ? bsdexKind[r.kind] : '–'}{r.coin ? ` ${r.coin}` : ''}</td>
                  <td class="r">{Number(r.quantity) ? `${formatNumber(r.quantity, 8)} ${r.symbol}` : ''}</td>
                  <td class="r">{#if r.price}<Money value={r.price} />{/if}</td>
                  <td class="r">{#if Number(r.amount)}<Money value={r.amount} />{/if}</td>
                  <td class="r">{#if Number(r.fee)}<Money value={r.fee} />{/if}</td>
                {:else if kind === 'bookings'}
                  <td>{r.counterparty}</td>
                  <td class="purpose">{r.purpose}</td>
                  <td class="r">{#if r.amount !== null}<Money value={r.amount} colored />{/if}</td>
                {:else}
                  <td>{r.type ? label(meta.value?.trade_types, r.type) : '–'}</td>
                  <td>{r.name}<div class="small muted">{r.isin}</div></td>
                  <td class="r">{Number(r.quantity) ? formatNumber(r.quantity, 6) : ''}</td>
                  <td class="r"><Money value={r.amount} /></td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if kind === 'bsdex'}
        <p class="muted small">
          Euro-Buchungen gehen auf {preview.settlement ? `„${preview.settlement.name}“` : 'ein neues Verrechnungskonto'}.
        </p>
      {/if}
      <div class="row">
        <button class="btn primary" onclick={commit} disabled={busy || !preview.summary.new}>{preview.summary.new} übernehmen</button>
        <button class="btn" onclick={() => (preview = null)}>Abbrechen</button>
      </div>
    </section>
  {/if}

  <section class="card stack">
    <h2>Letzte Importe</h2>
    {#if batches.length === 0}
      <p class="muted">Noch keine Importe.</p>
    {:else}
      <ul class="list">
        {#each batches as b (b.id)}
          <li>
            <div class="grow">
              <strong>{b.filename || (b.kind === 'bookings' ? 'Kontoumsätze' : b.kind === 'bsdex' ? 'BSDEX' : 'Portfolio Performance')}</strong>
              <div class="muted small">{b.account_name} · {b.count} Einträge · {formatDate(b.created_at.slice(0, 10))}</div>
            </div>
            <button class="btn danger" onclick={() => undo(b)}><Icon name="trash" size={16} /> Rückgängig</button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>

<style>
  .back {
    text-decoration: none;
    font-size: 0.9rem;
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    width: fit-content;
    max-width: 100%;
  }
  .seg button {
    font: inherit;
    border: 0;
    background: var(--surface);
    color: var(--text);
    padding: 8px 14px;
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
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
    align-items: end;
  }
  input[type='file'] {
    padding: 6px;
  }
  .check {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--text);
    min-height: 40px;
  }
  .check input {
    width: auto;
    min-height: auto;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .ok {
    color: var(--pos);
  }
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .table-wrap {
    overflow-x: auto;
    max-height: 60vh;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    position: sticky;
    top: 0;
    background: var(--surface);
    font-weight: 500;
    color: var(--muted);
    text-align: left;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  tr.duplicate,
  tr.skipped {
    opacity: 0.55;
  }
  .purpose {
    max-width: 320px;
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
  .badge {
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--surface-2);
    white-space: nowrap;
  }
  .badge.new {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }
  .badge.error {
    color: var(--neg);
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 0;
  }
  .list li + li {
    border-top: 1px solid var(--border);
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
</style>
