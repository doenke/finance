<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import { formatDate, formatDateTime } from '#lib/format.ts';
  import Avatar from '#lib/Avatar.svelte';
  import Icon from '#lib/Icon.svelte';
  import NotificationSettings from '#lib/NotificationSettings.svelte';
  import { logout, session } from '#lib/session.svelte.ts';
  import { getTheme, setTheme, type Theme } from '#lib/theme.ts';
  import { privacy, setPrivate } from '#lib/privacy.svelte.ts';

  interface SyncStatus {
    finished_at?: string;
    running?: boolean;
    updated?: number;
    total?: number;
    errors?: { instrument: string; message: string }[];
    schedule: string;
  }

  interface BackupInfo {
    files: { name: string; size: number; created_at: string }[];
    schedule: string;
    keep_days: number;
    last: { ok?: boolean; error?: string };
  }
  let backups = $state<BackupInfo | null>(null);
  let backingUp = $state(false);

  async function loadBackups() {
    if (session.me?.is_admin) backups = await api.get<BackupInfo>('/api/admin/backups');
  }

  async function backupNow() {
    backingUp = true;
    try {
      await api.post('/api/admin/backups');
      await loadBackups();
    } finally {
      backingUp = false;
    }
  }

  interface McpInfo {
    url: string;
    clients: { id: string; name: string; hosts: string[]; users: string[]; connected_at: string; last_used_at: string | null }[];
  }
  let mcp = $state<McpInfo | null>(null);
  let copied = $state(false);

  async function loadMcp() {
    mcp = await api.get<McpInfo>('/api/mcp/clients');
  }

  async function disconnect(id: string, name: string) {
    if (!confirm(`„${name}“ trennen? Der Assistent verliert sofort den Zugriff.`)) return;
    await api.del(`/api/mcp/clients/${encodeURIComponent(id)}`);
    await loadMcp();
  }

  async function copyUrl() {
    if (!mcp) return;
    try {
      await navigator.clipboard.writeText(mcp.url);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      /* clipboard not available */
    }
  }

  interface Device {
    id: number;
    user_agent: string;
    created_at: string;
    last_seen_at: string;
    current: boolean;
  }
  let devices = $state<Device[]>([]);

  async function loadDevices() {
    devices = await api.get<Device[]>('/api/sessions');
  }

  async function endDevice(d: Device) {
    if (!confirm(`${deviceName(d.user_agent)} abmelden?`)) return;
    await api.del(`/api/sessions/${d.id}`);
    await loadDevices();
  }

  async function endOthers() {
    if (!confirm('Alle anderen Geräte abmelden? Dort musst du dich danach neu anmelden.')) return;
    await api.post('/api/sessions/revoke-others');
    await loadDevices();
  }

  function deviceName(ua: string): string {
    const os = /iPhone|iPad/.test(ua) ? (ua.includes('iPad') ? 'iPad' : 'iPhone') : /Android/.test(ua) ? 'Android' : /Mac OS X/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : '';
    const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : '';
    return [browser, os].filter(Boolean).join(' auf ') || 'Unbekanntes Gerät';
  }

  interface AdminUser {
    id: number;
    name: string;
    email: string;
    is_admin: boolean;
    disabled: boolean;
    last_login_at: string | null;
    sessions: number;
    assistants: number;
  }
  let users = $state<AdminUser[]>([]);
  let userError = $state('');

  async function loadUsers() {
    if (session.me?.is_admin) users = await api.get<AdminUser[]>('/api/admin/users');
  }

  async function logoutUser(u: AdminUser) {
    if (!confirm(`${u.name} auf allen Geräten abmelden und verbundene Assistenten trennen?`)) return;
    userError = '';
    try {
      await api.post(`/api/admin/users/${u.id}/logout`);
      await loadUsers();
    } catch (e) {
      userError = (e as Error).message;
    }
  }

  async function toggleLock(u: AdminUser) {
    const question = u.disabled
      ? `${u.name} wieder freischalten?`
      : `${u.name} sperren? Alle Sitzungen und Assistenten-Zugänge enden sofort, eine neue Anmeldung ist nicht mehr möglich.`;
    if (!confirm(question)) return;
    userError = '';
    try {
      await api.put(`/api/admin/users/${u.id}/disabled`, { disabled: !u.disabled });
      await loadUsers();
    } catch (e) {
      userError = (e as Error).message;
    }
  }

  let theme = $state<Theme>('system');
  let sync = $state<SyncStatus | null>(null);
  let starting = $state(false);

  async function loadSync() {
    sync = await api.get<SyncStatus>('/api/prices/status');
  }

  let switchInfo = $state('');
  async function switchOnvista() {
    if (!confirm('Alle Wertpapiere, die bisher Kurse von Yahoo bekommen, auf onvista umstellen? Wertpapiere ohne ISIN bleiben bei Yahoo.')) return;
    const res = await api.post<{ switched: number; missing: string[] }>('/api/prices/switch-to-onvista');
    switchInfo = `${res.switched} umgestellt${res.missing.length ? ` – nicht gefunden: ${res.missing.join(', ')}` : ''}. Die Kurse werden jetzt neu geladen.`;
    setTimeout(loadSync, 5000);
  }

  async function startSync() {
    starting = true;
    await api.post('/api/prices/sync');
    setTimeout(async () => {
      await loadSync();
      starting = false;
    }, 4000);
  }

  onMount(() => {
    theme = getTheme();
    loadSync();
    loadBackups();
    loadMcp();
    loadDevices();
    loadUsers();
  });

  const finished = $derived(sync?.finished_at ? new Date(sync.finished_at) : null);

  function choose(t: Theme) {
    theme = t;
    setTheme(t);
  }

  async function doLogout() {
    await logout();
    location.href = '/';
  }

  const themes: { value: Theme; label: string }[] = [
    { value: 'system', label: 'Wie das System' },
    { value: 'light', label: 'Hell' },
    { value: 'dark', label: 'Dunkel' }
  ];
</script>

<svelte:head><title>Einstellungen – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Einstellungen</h1>

  {#if session.me}
    <section class="card row">
      <Avatar name={session.me.name} url={session.me.avatar_url} size={48} />
      <div class="grow">
        <strong>{session.me.name}</strong>
        <div class="muted small">{session.me.email}{session.me.is_admin ? ' · Admin' : ''}</div>
      </div>
      <button class="btn" onclick={doLogout}><Icon name="logout" size={18} /> Abmelden</button>
    </section>
    <a class="card row navlink" href="/haushalt">
      <Icon name="people" />
      <div class="grow">
        <strong>Haushalt</strong>
        <div class="muted small">Personen und wem welche Konten gehören</div>
      </div>
      <span class="muted">›</span>
    </a>
    <a class="card row navlink" href="/banken">
      <Icon name="bank" />
      <div class="grow">
        <strong>Banken</strong>
        <div class="muted small">Bankzugänge und automatischer Abruf (FinTS)</div>
      </div>
      <span class="muted">›</span>
    </a>
    <a class="card row navlink" href="/protokoll">
      <Icon name="history" />
      <div class="grow">
        <strong>Änderungsprotokoll</strong>
        <div class="muted small">Wer hat wann was geändert – in der App und über KI-Assistenten</div>
      </div>
      <span class="muted">›</span>
    </a>
  {/if}

  <section class="card stack">
    <h2>Darstellung</h2>
    <div class="segmented" role="radiogroup" aria-label="Farbschema">
      {#each themes as t (t.value)}
        <button role="radio" aria-checked={theme === t.value} class:active={theme === t.value} onclick={() => choose(t.value)}>{t.label}</button>
      {/each}
    </div>
    <label class="check">
      <input type="checkbox" checked={privacy.on} onchange={(e) => setPrivate(e.currentTarget.checked)} />
      Privatmodus: Beträge verbergen
    </label>
    <p class="muted small">Praktisch, wenn du die App jemandem zeigst. Prozentwerte bleiben sichtbar. Gilt nur auf diesem Gerät; umschalten geht auch mit dem Auge auf der Übersicht.</p>
  </section>

  <section class="card stack">
    <h2>Kurse</h2>
    <p class="muted small">
      Kurse kommen täglich automatisch von onvista oder Yahoo Finance – je nachdem, was beim Wertpapier eingestellt ist –, Wechselkurse von der EZB
      (Zeitplan <code>{sync?.schedule}</code>, Europe/Berlin). Klappt Yahoo nicht, springt onvista über die ISIN ein.
    </p>
    {#if finished}
      <p class="small">
        Zuletzt aktualisiert am {formatDate(sync?.finished_at?.slice(0, 10))} um {finished.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}:
        {sync?.updated} von {sync?.total} Wertpapieren.
      </p>
    {:else}
      <p class="muted small">Noch nie aktualisiert.</p>
    {/if}
    {#if sync?.errors?.length}
      <ul class="errors small">
        {#each sync.errors as e (e.instrument)}<li><strong>{e.instrument}:</strong> {e.message}</li>{/each}
      </ul>
    {/if}
    <div class="row">
      <button class="btn" onclick={startSync} disabled={starting}>{starting ? 'Läuft …' : 'Alle Kurse jetzt aktualisieren'}</button>
      <button class="btn" onclick={switchOnvista}>Yahoo-Wertpapiere auf onvista umstellen</button>
    </div>
    {#if switchInfo}<p class="small">{switchInfo}</p>{/if}
  </section>

  <NotificationSettings />

  {#if mcp}
    <section class="card stack">
      <h2>KI-Assistenten (MCP)</h2>
      <p class="muted small">
        Claude und andere Assistenten können über MCP deine Konten lesen und Werte, Buchungen und Käufe eintragen – löschen können sie nichts. Trage diese Adresse als
        Connector ein; beim Verbinden meldest du dich an und bestätigst den Zugriff.
      </p>
      <div class="row wrap">
        <code class="url">{mcp.url}</code>
        <button class="btn" onclick={copyUrl}>{copied ? 'Kopiert' : 'Kopieren'}</button>
      </div>
      {#if mcp.clients.length}
        <ul class="files small">
          {#each mcp.clients as c (c.id)}
            <li class="row wrap">
              <span class="grow">
                <strong>{c.name}</strong>
                <span class="muted">· {c.hosts.join(', ')} · {c.users.join(', ')} · verbunden {formatDate(c.connected_at)}{c.last_used_at ? ` · zuletzt ${formatDate(c.last_used_at)}` : ''}</span>
              </span>
              <button class="btn" onclick={() => disconnect(c.id, c.name)}>Trennen</button>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted small">Noch kein Assistent verbunden.</p>
      {/if}
    </section>
  {/if}

  {#if devices.length}
    <section class="card stack">
      <h2>Angemeldete Geräte</h2>
      <p class="muted small">Hier bist du gerade angemeldet. Kennst du ein Gerät nicht, melde es ab.</p>
      <ul class="files small">
        {#each devices as d (d.id)}
          <li class="row wrap">
            <span class="grow">
              <strong>{deviceName(d.user_agent)}</strong>
              <span class="muted">· {d.current ? 'dieses Gerät' : `zuletzt ${formatDateTime(d.last_seen_at)}`} · angemeldet {formatDate(d.created_at.slice(0, 10))}</span>
            </span>
            {#if !d.current}<button class="btn" onclick={() => endDevice(d)}>Abmelden</button>{/if}
          </li>
        {/each}
      </ul>
      {#if devices.length > 1}
        <div><button class="btn" onclick={endOthers}>Alle anderen Geräte abmelden</button></div>
      {/if}
    </section>
  {/if}

  {#if session.me?.is_admin && users.length}
    <section class="card stack">
      <h2>Benutzer</h2>
      <p class="muted small">
        Wer sich angemeldet hat. Wer den Haushalt verlässt oder ein Gerät verloren hat: überall abmelden oder sperren. Admin-Rechte kommen aus der Gruppe im Anmeldedienst und
        gelten ab der nächsten Anmeldung.
      </p>
      {#if userError}<p class="error small">{userError}</p>{/if}
      <ul class="files small">
        {#each users as u (u.id)}
          <li class="row wrap">
            <span class="grow">
              <strong>{u.name}</strong>
              <span class="muted">
                {u.is_admin ? '· Admin ' : ''}· {u.disabled ? 'gesperrt' : `${u.sessions} ${u.sessions === 1 ? 'Gerät' : 'Geräte'}${u.assistants ? `, ${u.assistants} ${u.assistants === 1 ? 'Assistent' : 'Assistenten'}` : ''}`}
                · zuletzt angemeldet {u.last_login_at ? formatDateTime(u.last_login_at) : '–'}
              </span>
            </span>
            {#if u.id !== session.me?.id}
              {#if !u.disabled && (u.sessions || u.assistants)}<button class="btn" onclick={() => logoutUser(u)}>Überall abmelden</button>{/if}
              <button class="btn" onclick={() => toggleLock(u)}>{u.disabled ? 'Entsperren' : 'Sperren'}</button>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <section class="card stack">
    <h2>Daten exportieren</h2>
    <p class="muted small">
      Alles als JSON – ohne Anmeldesitzungen, Assistenten-Zugänge und Bank-Zugangsdaten (PINs, Anmeldenamen anderer Personen) – oder Buchungen und Depot-Transaktionen als CSV
      für Excel. Eine vollständige Sicherung zum Wiederherstellen gibt es für Admins unter „Sicherungen“.
    </p>
    <div class="row">
      <a class="btn" href="/api/export/json" download>Alles (JSON)</a>
      <a class="btn" href="/api/export/transactions.csv" download>Buchungen (CSV)</a>
      <a class="btn" href="/api/export/trades.csv" download>Transaktionen (CSV)</a>
    </div>
  </section>

  {#if session.me?.is_admin && backups}
    <section class="card stack">
      <h2>Sicherungen</h2>
      <p class="muted small">
        Jeden Tag wird automatisch eine Sicherung ins Datenverzeichnis geschrieben (Zeitplan <code>{backups.schedule}</code>), {backups.keep_days} Tage aufbewahrt.
        {#if backups.last?.ok === false}<span class="error">Letzte Sicherung fehlgeschlagen: {backups.last.error}</span>{/if}
      </p>
      {#if backups.files.length}
        <ul class="files small">
          {#each backups.files.slice(0, 7) as f (f.name)}
            <li><a href="/api/admin/backups/{f.name}" download>{f.name}</a> <span class="muted">{Math.round(f.size / 1024)} KB</span></li>
          {/each}
        </ul>
      {:else}
        <p class="muted small">Noch keine Sicherung vorhanden.</p>
      {/if}
      <div><button class="btn" onclick={backupNow} disabled={backingUp}>{backingUp ? 'Sichert …' : 'Jetzt sichern'}</button></div>
    </section>
  {/if}

  <section class="card stack">
    <h2>Über</h2>
    <p class="muted">Finanzen · Version <span class="num">{session.config?.version}</span></p>
  </section>
</div>

<style>
  .grow {
    flex: 1;
    min-width: 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .url {
    overflow-wrap: anywhere;
    flex: 1;
    min-width: 0;
  }
  .wrap {
    flex-wrap: wrap;
  }
  .check {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--text);
  }
  .check input {
    width: auto;
    min-height: auto;
  }
  .navlink {
    color: inherit;
    text-decoration: none;
  }
  .files {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
  }
  .error {
    color: var(--warn);
  }
  .errors {
    color: var(--warn);
    margin: 0;
    padding-left: 18px;
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    width: fit-content;
    max-width: 100%;
  }
  .segmented button {
    font: inherit;
    border: 0;
    background: var(--surface);
    color: var(--text);
    padding: 8px 14px;
    cursor: pointer;
  }
  .segmented button + button {
    border-left: 1px solid var(--border);
  }
  .segmented button.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 600;
  }
</style>
