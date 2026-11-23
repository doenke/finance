<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import { formatDate } from '#lib/format.ts';
  import Avatar from '#lib/Avatar.svelte';
  import Icon from '#lib/Icon.svelte';
  import { logout, session } from '#lib/session.svelte.ts';
  import { getTheme, setTheme, type Theme } from '#lib/theme.ts';

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
  {/if}

  <section class="card stack">
    <h2>Darstellung</h2>
    <div class="segmented" role="radiogroup" aria-label="Farbschema">
      {#each themes as t (t.value)}
        <button role="radio" aria-checked={theme === t.value} class:active={theme === t.value} onclick={() => choose(t.value)}>{t.label}</button>
      {/each}
    </div>
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

  <section class="card stack">
    <h2>Daten exportieren</h2>
    <p class="muted small">Alles als JSON (vollständig, lässt sich wiederherstellen) oder Buchungen und Depot-Transaktionen als CSV für Excel.</p>
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
  .files {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
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
