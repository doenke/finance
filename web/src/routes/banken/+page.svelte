<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Account, type Bank, type BankLogin, type FintsAccount, type FintsJob } from '#lib/api.ts';
  import FintsDialog from '#lib/FintsDialog.svelte';
  import { formatDate } from '#lib/format.ts';
  import { blzFromIban, normalizeIban } from '#lib/iban.ts';
  import Icon from '#lib/Icon.svelte';
  import { loadMeta, meta } from '#lib/meta.svelte.ts';
  import { session } from '#lib/session.svelte.ts';

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
  interface BankForm {
    id: number | null;
    name: string;
    blz: string;
    server_url: string;
  }
  interface LoginForm {
    id: number | null;
    username: string;
    customer_id: string;
    store_pin: boolean;
    pin: string;
    auto_sync: boolean;
    reset_tan: boolean;
  }

  let banks = $state<Bank[]>([]);
  let accounts = $state<Account[]>([]);
  let status = $state<Status | null>(null);
  // New bank: bank and own login in one form. Edit bank: only bank. Own login at an existing bank: only login.
  let bankForm = $state<BankForm | null>(null);
  let loginForm = $state<LoginForm | null>(null);
  let loginBank = $state<Bank | null>(null);
  let dialog = $state<{ login: BankLogin; kind: 'discover' | 'sync' } | null>(null);
  let linking = $state<{ login: BankLogin; rows: LinkRow[] } | null>(null);
  let error = $state('');
  let iban = $state('');
  const ibanState = $derived.by(() => {
    const clean = normalizeIban(iban);
    if (!clean) return '';
    if (clean.length < 22) return 'typing';
    return blzFromIban(clean) ? 'ok' : 'invalid';
  });
  const existing = $derived(bankForm && bankForm.id === null ? banks.find((b) => b.blz === bankForm!.blz) : undefined);
  const editing = $derived(bankForm !== null || loginForm !== null);

  function onIban() {
    const blz = blzFromIban(iban);
    if (blz && bankForm) bankForm.blz = blz;
  }

  async function load() {
    await loadMeta();
    [banks, accounts, status] = await Promise.all([api.get<Bank[]>('/api/banks'), api.get<Account[]>('/api/accounts'), api.get<Status>('/api/fints/status')]);
  }
  onMount(load);

  const emptyLogin = (): LoginForm => ({ id: null, username: '', customer_id: '', store_pin: false, pin: '', auto_sync: false, reset_tan: false });

  function close() {
    bankForm = null;
    loginForm = null;
    loginBank = null;
    error = '';
  }

  function startNewBank() {
    close();
    iban = '';
    bankForm = { id: null, name: '', blz: '', server_url: '' };
    loginForm = emptyLogin();
  }

  function startEditBank(b: Bank) {
    close();
    iban = '';
    bankForm = { id: b.id, name: b.name, blz: b.blz, server_url: b.server_url };
  }

  function startNewLogin(b: Bank) {
    close();
    loginBank = b;
    loginForm = emptyLogin();
  }

  function startEditLogin(b: Bank, l: BankLogin) {
    close();
    loginBank = b;
    loginForm = { id: l.id, username: l.username, customer_id: l.customer_id, store_pin: l.store_pin, pin: '', auto_sync: l.auto_sync, reset_tan: false };
  }

  function useExisting() {
    if (!existing) return;
    const keep = loginForm;
    close();
    loginBank = existing;
    loginForm = keep ?? emptyLogin();
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    try {
      let bankId = loginBank?.id ?? null;
      if (bankForm) {
        const bank = bankForm.id === null ? await api.post<Bank>('/api/banks', bankForm) : await api.put<Bank>(`/api/banks/${bankForm.id}`, bankForm);
        bankId = bank.id;
      }
      let created: BankLogin | null = null;
      if (loginForm && bankId !== null) {
        const body = { ...loginForm, pin: loginForm.pin || null };
        if (loginForm.id === null) created = await api.post<BankLogin>(`/api/banks/${bankId}/logins`, body);
        else await api.put<BankLogin>(`/api/bank-logins/${loginForm.id}`, body);
      }
      close();
      await load();
      if (created) dialog = { login: created, kind: 'discover' };
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function removeBank(b: Bank) {
    if (!confirm(`Bank „${b.name}“ löschen?`)) return;
    await api.del(`/api/banks/${b.id}`);
    await load();
  }

  async function removeLogin(l: BankLogin) {
    const whose = l.mine ? 'deinen Zugang' : `den Zugang von ${l.owner}`;
    if (!confirm(`${whose} bei „${l.name}“ löschen? Konten und Umsätze bleiben erhalten, werden aber nicht mehr abgerufen.`)) return;
    await api.del(`/api/bank-logins/${l.id}`);
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
        bic: r.bic,
        account_id: r.action === 'link' ? r.account_id : null,
        create_kind: r.action === 'create' ? r.create_kind : null,
        create_name: r.action === 'create' ? r.create_name : null
      }));
    try {
      await api.post(`/api/bank-logins/${linking.login.id}/link`, { items });
      const login = linking.login;
      linking = null;
      await load();
      const fresh = banks.flatMap((b) => b.logins).find((l) => l.id === login.id);
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
    <h1>Banken</h1>
    <button class="btn primary" onclick={startNewBank} disabled={!status?.product_id}><Icon name="plus" size={18} /> Bank</button>
  </div>
  <p class="muted">
    Per FinTS holt Finanzen Salden, Umsätze und Depotbestände direkt von der Bank. Die Bank mit Adresse und
    Bankleitzahl gilt für den ganzen Haushalt; Anmeldename und PIN hinterlegt jede Person selbst.
  </p>

  {#if status && !status.product_id}
    <p class="error">FINTS_PRODUCT_ID fehlt in der .env – ohne die Registrierungsnummer ist kein Abruf möglich.</p>
  {/if}
  {#if error && !editing}<p class="error">{error}</p>{/if}

  {#if editing}
    <form class="card stack" onsubmit={save}>
      <h2>
        {#if bankForm?.id === null}Neue Bank{:else if bankForm}Bank bearbeiten{:else if loginForm?.id === null}Dein Zugang bei {loginBank?.name}{:else}Zugang bei {loginBank?.name} bearbeiten{/if}
      </h2>
      {#if bankForm}
        <div class="grid">
          <label>Name <input bind:value={bankForm.name} required maxlength="120" placeholder="z. B. Sparkasse" /></label>
          <label>
            IBAN eines Kontos dort
            <input bind:value={iban} oninput={onIban} placeholder="DE89 3704 0044 0532 0130 00" autocomplete="off" maxlength="42" aria-describedby="iban-hint" />
            <span id="iban-hint" class="hint" class:bad={ibanState === 'invalid'} class:good={ibanState === 'ok'}>
              {#if ibanState === 'ok'}Bankleitzahl übernommen.{:else if ibanState === 'invalid'}Das ist keine gültige deutsche IBAN.{:else}Füllt die Bankleitzahl aus – wird nicht gespeichert.{/if}
            </span>
          </label>
          <label>
            Bankleitzahl
            <input bind:value={bankForm.blz} required inputmode="numeric" pattern={'[0-9]{8}'} maxlength="8" />
            <span class="hint">8 Ziffern – Stellen 5 bis 12 der IBAN</span>
          </label>
          <label class="wide">FinTS-Adresse <input bind:value={bankForm.server_url} required placeholder="https://…" /></label>
        </div>
        {#if existing}
          <p class="small warn">
            „{existing.name}“ mit dieser Bankleitzahl gibt es schon.
            <button class="btn" type="button" onclick={useExisting}>Dort deinen Zugang hinzufügen</button>
          </p>
        {/if}
        <p class="muted small">
          Die FinTS-Adresse steht meist auf der Webseite der Bank unter „FinTS“ oder „HBCI“, oder in der Bankenliste der Deutschen Kreditwirtschaft, die es zur Produktregistrierung
          gibt.{#if bankForm.id !== null} Ändern sich Adresse oder Bankleitzahl, wählt jeder Zugang beim nächsten Abruf das TAN-Verfahren neu.{/if}
        </p>
      {/if}
      {#if loginForm}
        {#if bankForm}<h3>Dein Zugang</h3>{/if}
        <div class="grid">
          <label>Anmeldename / Legitimations-ID <input bind:value={loginForm.username} required autocomplete="off" /></label>
          <label>Kunden-ID (falls abweichend) <input bind:value={loginForm.customer_id} autocomplete="off" /></label>
        </div>
        <p class="muted small">Der Anmeldename ist derselbe wie im Online-Banking. Nur du siehst ihn und kannst mit diesem Zugang abrufen.</p>
        <label class="check"><input type="checkbox" bind:checked={loginForm.store_pin} /> PIN verschlüsselt speichern</label>
        {#if loginForm.store_pin}
          <div class="grid">
            <label>PIN {loginForm.id !== null ? '(leer lassen = unverändert)' : ''}<input type="password" bind:value={loginForm.pin} autocomplete="new-password" maxlength="64" required={loginForm.id === null} /></label>
            <label class="check"><input type="checkbox" bind:checked={loginForm.auto_sync} /> Jede Nacht automatisch abrufen</label>
          </div>
          <p class="muted small">
            Mit gespeicherter PIN kann Finanzen nachts selbst abrufen. Banken verlangen trotzdem etwa alle 90 Tage eine Freigabe per TAN – dann erscheint hier ein
            Hinweis.{#if status && !status.secrets_key} <span class="error">SECRETS_KEY fehlt in der .env.</span>{/if}
          </p>
        {:else}
          <p class="muted small">Ohne gespeicherte PIN fragt Finanzen bei jedem Abruf danach.</p>
        {/if}
        {#if loginForm.id !== null}
          <label class="check"><input type="checkbox" bind:checked={loginForm.reset_tan} /> TAN-Verfahren neu auswählen</label>
        {/if}
      {/if}
      {#if error}<p class="error">{error}</p>{/if}
      <div class="row">
        <button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" onclick={close}>Abbrechen</button>
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

  {#if banks.length === 0 && !editing}
    <div class="card"><p class="muted">Noch keine Banken.</p></div>
  {/if}
  {#each banks as b (b.id)}
    <section class="card stack">
      <div class="row head">
        <div class="grow">
          <h2>{b.name}</h2>
          <div class="muted small url">BLZ {b.blz} · {b.server_url}</div>
        </div>
        <div class="row">
          {#if !b.logins.some((l) => l.mine)}
            <button class="btn" onclick={() => startNewLogin(b)} disabled={!status?.product_id}><Icon name="plus" size={18} /> Mein Zugang</button>
          {/if}
          <button class="btn icon" aria-label="Bank bearbeiten" onclick={() => startEditBank(b)}><Icon name="edit" size={18} /></button>
          {#if !b.logins.length}
            <button class="btn icon danger" aria-label="Bank löschen" onclick={() => removeBank(b)}><Icon name="trash" size={18} /></button>
          {/if}
        </div>
      </div>
      {#if !b.logins.length}
        <p class="muted small">Noch kein Zugang – lege mit „Mein Zugang“ deine Anmeldedaten an.</p>
      {/if}
      {#each b.logins as l (l.id)}
        <div class="login stack">
          <div class="row head">
            <div class="grow">
              <strong>{l.mine ? 'Dein Zugang' : `Zugang von ${l.owner || 'unbekannt'}`}</strong>
              <div class="muted small">
                {[l.mine ? l.username : '', l.tan_mechanism_name, l.auto_sync ? 'automatisch' : ''].filter(Boolean).join(' · ') || ' '}
              </div>
            </div>
            <div class="row">
              {#if l.mine}
                <button class="btn primary" onclick={() => (dialog = { login: l, kind: 'sync' })} disabled={!l.account_ids.length}>Aktualisieren</button>
                <button class="btn" onclick={() => (dialog = { login: l, kind: 'discover' })}>Konten suchen</button>
                <button class="btn icon" aria-label="Zugang bearbeiten" onclick={() => startEditLogin(b, l)}><Icon name="edit" size={18} /></button>
              {/if}
              {#if l.mine || session.me?.is_admin}
                <button class="btn icon danger" aria-label="Zugang löschen" onclick={() => removeLogin(l)}><Icon name="trash" size={18} /></button>
              {/if}
            </div>
          </div>
          <p class="small">Zuletzt abgerufen: {fmtTime(l.last_sync_at)}</p>
          {#if l.needs_tan}<p class="warn small">Die Bank möchte eine neue Freigabe per TAN{l.mine ? ' – bitte einmal „Aktualisieren“.' : ` – das kann nur ${l.owner} erledigen.`}</p>{/if}
          {#if l.last_error && !l.needs_tan}<p class="error small">Letzter Fehler: {l.last_error}</p>{/if}
          {#if l.account_ids.length}
            <ul class="accounts small">
              {#each l.account_ids as id (id)}<li><a href="/konten/{id}">{accountName(id)}</a></li>{/each}
            </ul>
          {:else if l.mine}
            <p class="muted small">Noch keine Konten verknüpft – „Konten suchen“.</p>
          {/if}
        </div>
      {/each}
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
  .hint {
    font-size: 0.8rem;
    color: var(--muted);
  }
  .hint.bad {
    color: var(--neg);
  }
  .hint.good {
    color: var(--pos);
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
  .grow {
    flex: 1;
    min-width: 0;
  }
  .url {
    overflow-wrap: anywhere;
  }
  h3 {
    margin: 8px 0 0;
    font-size: 1rem;
  }
  .login {
    border-top: 1px solid var(--border);
    padding-top: 12px;
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
