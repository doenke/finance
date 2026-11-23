<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Account, type BankLogin, type FintsAccount, type FintsJob } from '#lib/api.ts';
  import FintsDialog from '#lib/FintsDialog.svelte';
  import { formatDate } from '#lib/format.ts';
  import Icon from '#lib/Icon.svelte';
  import { loadMeta, meta } from '#lib/meta.svelte.ts';

  interface Status {
    product_id: boolean;
    secrets_key: boolean;
    schedule: string;
  }
  interface LinkRow extends FintsAccount {
    action: 'skip' | 'create' | 'link';
    create_kind: string;
    create_name: string;
    account_id: number | null;
  }

  let banks = $state<BankLogin[]>([]);
  let accounts = $state<Account[]>([]);
  let status = $state<Status | null>(null);
  let form = $state<null | { id: number | null; name: string; blz: string; server_url: string; username: string; customer_id: string; store_pin: boolean; pin: string; auto_sync: boolean; reset_tan: boolean }>(null);
  let dialog = $state<{ login: BankLogin; kind: 'discover' | 'sync' } | null>(null);
  let linking = $state<{ login: BankLogin; rows: LinkRow[] } | null>(null);
  let error = $state('');

  async function load() {
    await loadMeta();
    [banks, accounts, status] = await Promise.all([api.get<BankLogin[]>('/api/banks'), api.get<Account[]>('/api/accounts'), api.get<Status>('/api/fints/status')]);
  }
  onMount(load);

  function startNew() {
    form = { id: null, name: '', blz: '', server_url: '', username: '', customer_id: '', store_pin: false, pin: '', auto_sync: false, reset_tan: false };
  }

  function startEdit(b: BankLogin) {
    form = { id: b.id, name: b.name, blz: b.blz, server_url: b.server_url, username: b.username, customer_id: b.customer_id, store_pin: b.store_pin, pin: '', auto_sync: b.auto_sync, reset_tan: false };
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    error = '';
    const body = { ...form, pin: form.pin || null };
    try {
      const saved = form.id === null ? await api.post<BankLogin>('/api/banks', body) : await api.put<BankLogin>(`/api/banks/${form.id}`, body);
      const isNew = form.id === null;
      form = null;
      await load();
      if (isNew) dialog = { login: saved, kind: 'discover' };
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(b: BankLogin) {
    if (!confirm(`Bankzugang „${b.name}“ löschen? Konten und Umsätze bleiben erhalten, werden aber nicht mehr abgerufen.`)) return;
    await api.del(`/api/banks/${b.id}`);
    await load();
  }

  function onDiscovered(login: BankLogin, job: FintsJob) {
    const rows: LinkRow[] = (job.result?.accounts ?? []).map((a: FintsAccount) => ({
      ...a,
      action: a.linked_account_id ? 'link' : 'create',
      create_kind: a.suggested_kind,
      create_name: `${a.product_name || 'Konto'} ${login.name}`.trim(),
      account_id: a.linked_account_id
    }));
    linking = { login, rows };
  }

  async function saveLinks() {
    if (!linking) return;
    const items = linking.rows
      .filter((r) => r.action !== 'skip')
      .map((r) => ({
        iban: r.iban,
        accountnumber: r.accountnumber,
        subaccount: r.subaccount,
        blz: r.blz,
        account_id: r.action === 'link' ? r.account_id : null,
        create_kind: r.action === 'create' ? r.create_kind : null,
        create_name: r.action === 'create' ? r.create_name : null
      }));
    try {
      await api.post(`/api/banks/${linking.login.id}/link`, { items });
      const login = linking.login;
      linking = null;
      await load();
      const fresh = banks.find((b) => b.id === login.id);
      if (fresh && confirm('Konten verknüpft. Jetzt gleich Salden und Umsätze abrufen?')) dialog = { login: fresh, kind: 'sync' };
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const accountName = (id: number) => accounts.find((a) => a.id === id)?.name ?? '?';
  const fmtTime = (iso: string | null) => (iso ? `${formatDate(iso.slice(0, 10))}, ${new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}` : 'noch nie');
</script>

<svelte:head><title>Banken – Finanzen</title></svelte:head>

<div class="stack">
  <div class="row head">
    <h1>Bankzugänge</h1>
    <button class="btn primary" onclick={startNew} disabled={!status?.product_id}><Icon name="plus" size={18} /> Bankzugang</button>
  </div>
  <p class="muted">Per FinTS holt Finanzen Salden, Umsätze und Depotbestände direkt von der Bank – zum Beispiel von Sparkasse, DKB und OLB.</p>

  {#if status && !status.product_id}
    <p class="error">FINTS_PRODUCT_ID fehlt in der .env – ohne die Registrierungsnummer ist kein Abruf möglich.</p>
  {/if}
  {#if error}<p class="error">{error}</p>{/if}

  {#if form}
    <form class="card stack" onsubmit={save}>
      <h2>{form.id === null ? 'Neuer Bankzugang' : 'Bankzugang bearbeiten'}</h2>
      <div class="grid">
        <label>Name <input bind:value={form.name} required maxlength="120" placeholder="z. B. Sparkasse" /></label>
        <label>Bankleitzahl <input bind:value={form.blz} required inputmode="numeric" pattern={'[0-9]{8}'} maxlength="8" /></label>
        <label class="wide">FinTS-Adresse <input bind:value={form.server_url} required placeholder="https://…" /></label>
        <label>Anmeldename / Legitimations-ID <input bind:value={form.username} required autocomplete="off" /></label>
        <label>Kunden-ID (falls abweichend) <input bind:value={form.customer_id} autocomplete="off" /></label>
      </div>
      <p class="muted small">
        Die FinTS-Adresse steht meist auf der Webseite der Bank unter „FinTS“ oder „HBCI“, oder in der Bankenliste der Deutschen Kreditwirtschaft, die es zur Produktregistrierung gibt.
        Der Anmeldename ist derselbe wie im Online-Banking.
      </p>
      <label class="check"><input type="checkbox" bind:checked={form.store_pin} /> PIN verschlüsselt speichern</label>
      {#if form.store_pin}
        <div class="grid">
          <label>PIN {form.id !== null ? '(leer lassen = unverändert)' : ''}<input type="password" bind:value={form.pin} autocomplete="new-password" maxlength="64" required={form.id === null} /></label>
          <label class="check"><input type="checkbox" bind:checked={form.auto_sync} /> Jede Nacht automatisch abrufen</label>
        </div>
        <p class="muted small">
          Mit gespeicherter PIN kann Finanzen nachts selbst abrufen. Banken verlangen trotzdem etwa alle 90 Tage eine Freigabe per TAN – dann
          erscheint hier ein Hinweis.{#if status && !status.secrets_key} <span class="error">SECRETS_KEY fehlt in der .env.</span>{/if}
        </p>
      {:else}
        <p class="muted small">Ohne gespeicherte PIN fragt Finanzen bei jedem Abruf danach.</p>
      {/if}
      {#if form.id !== null}
        <label class="check"><input type="checkbox" bind:checked={form.reset_tan} /> TAN-Verfahren neu auswählen</label>
      {/if}
      <div class="row">
        <button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" onclick={() => (form = null)}>Abbrechen</button>
      </div>
    </form>
  {/if}

  {#if linking}
    <section class="card stack">
      <h2>Konten bei {linking.login.name}</h2>
      <p class="muted small">Wähle, welche Konten Finanzen übernehmen soll – als neues Konto oder verknüpft mit einem, das du schon angelegt hast.</p>
      {#each linking.rows as r, i (i)}
        <div class="link-row">
          <div>
            <strong>{r.product_name || 'Konto'}</strong>
            <div class="muted small">{r.iban ?? `Konto ${r.accountnumber}`}{r.owner ? ` · ${r.owner}` : ''}</div>
          </div>
          <select bind:value={r.action}>
            <option value="create">neu anlegen</option>
            <option value="link">verknüpfen</option>
            <option value="skip">nicht übernehmen</option>
          </select>
          {#if r.action === 'create'}
            <select bind:value={r.create_kind}>
              {#each meta.value?.kinds ?? [] as k (k.key)}<option value={k.key}>{k.label}</option>{/each}
            </select>
            <input bind:value={r.create_name} aria-label="Name" />
          {:else if r.action === 'link'}
            <select bind:value={r.account_id}>
              <option value={null}>– Konto wählen –</option>
              {#each accounts as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
            </select>
          {/if}
        </div>
      {/each}
      <div class="row">
        <button class="btn primary" onclick={saveLinks}>Übernehmen</button>
        <button class="btn" onclick={() => (linking = null)}>Abbrechen</button>
      </div>
    </section>
  {/if}

  {#if banks.length === 0 && !form}
    <div class="card"><p class="muted">Noch keine Bankzugänge.</p></div>
  {/if}
  {#each banks as b (b.id)}
    <section class="card stack">
      <div class="row head">
        <div>
          <h2>{b.name}</h2>
          <div class="muted small">BLZ {b.blz} · {b.username}{b.tan_mechanism_name ? ` · ${b.tan_mechanism_name}` : ''}{b.auto_sync ? ' · automatisch' : ''}</div>
        </div>
        <div class="row">
          <button class="btn primary" onclick={() => (dialog = { login: b, kind: 'sync' })} disabled={!b.account_ids.length}>Aktualisieren</button>
          <button class="btn" onclick={() => (dialog = { login: b, kind: 'discover' })}>Konten suchen</button>
          <button class="btn icon" aria-label="Bearbeiten" onclick={() => startEdit(b)}><Icon name="edit" size={18} /></button>
          <button class="btn icon danger" aria-label="Löschen" onclick={() => remove(b)}><Icon name="trash" size={18} /></button>
        </div>
      </div>
      <p class="small">Zuletzt abgerufen: {fmtTime(b.last_sync_at)}</p>
      {#if b.needs_tan}<p class="warn small">Die Bank möchte eine neue Freigabe per TAN – bitte einmal „Aktualisieren“.</p>{/if}
      {#if b.last_error && !b.needs_tan}<p class="error small">Letzter Fehler: {b.last_error}</p>{/if}
      {#if b.account_ids.length}
        <ul class="accounts small">
          {#each b.account_ids as id (id)}<li><a href="/konten/{id}">{accountName(id)}</a></li>{/each}
        </ul>
      {:else}
        <p class="muted small">Noch keine Konten verknüpft – „Konten suchen“.</p>
      {/if}
    </section>
  {/each}
</div>

{#if dialog}
  <FintsDialog
    login={dialog.login}
    kind={dialog.kind}
    onclose={() => {
      dialog = null;
      load();
    }}
    ondone={(job) => {
      if (dialog?.kind === 'discover') {
        const login = dialog.login;
        dialog = null;
        onDiscovered(login, job);
      }
    }}
  />
{/if}

<style>
  .head {
    justify-content: space-between;
    align-items: flex-start;
  }
  .head h1,
  .head h2 {
    margin: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    align-items: end;
  }
  .wide {
    grid-column: 1 / -1;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .warn {
    color: var(--warn);
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
  .btn.icon {
    padding: 0;
    width: 40px;
  }
  .accounts {
    margin: 0;
    padding-left: 18px;
  }
  .link-row {
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr 1.4fr;
    gap: 8px;
    align-items: center;
    padding: 8px 0;
    border-top: 1px solid var(--border);
  }
  @media (max-width: 760px) {
    .link-row {
      grid-template-columns: 1fr;
    }
  }
</style>
