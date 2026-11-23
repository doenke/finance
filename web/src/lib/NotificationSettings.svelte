<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from './api.ts';
  import { formatDate } from './format.ts';

  type Prefs = Record<string, { push: boolean; email: boolean; [key: string]: unknown }>;
  interface State {
    push_available: boolean;
    email_available: boolean;
    vapid_public_key: string | null;
    email: string;
    events: { key: string; label: string; channels: string[] }[];
    prefs: Prefs;
    devices: { endpoint: string; device: string; created_at: string; last_used_at: string | null }[];
    recent: { title: string; channels: string; sent_at: string }[];
  }

  let info = $state<State | null>(null);
  let prefs = $state<Prefs>({});
  let endpoint = $state<string | null>(null);
  let busy = $state(false);
  let message = $state('');
  let error = $state('');
  let dirty = $state(false);

  const pushSupported = typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const isIos = typeof navigator !== 'undefined' && /iphone|ipad/i.test(navigator.userAgent);
  const thisDevice = $derived(!!endpoint && !!info?.devices.some((d) => d.endpoint === endpoint));

  function apply(s: State) {
    info = s;
    prefs = structuredClone(s.prefs);
    dirty = false;
  }

  async function load() {
    apply(await api.get<State>('/api/notifications'));
    if (pushSupported) {
      const reg = await navigator.serviceWorker.getRegistration();
      endpoint = (await reg?.pushManager.getSubscription())?.endpoint ?? null;
    }
  }
  onMount(load);

  function keyBytes(base64url: string): Uint8Array {
    const b64 = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  }

  function deviceName(): string {
    const ua = navigator.userAgent;
    const os = /android/i.test(ua) ? 'Android' : /iphone|ipad/i.test(ua) ? 'iOS' : /mac/i.test(ua) ? 'Mac' : /windows/i.test(ua) ? 'Windows' : /linux/i.test(ua) ? 'Linux' : 'Gerät';
    const browser = /edg\//i.test(ua) ? 'Edge' : /firefox/i.test(ua) ? 'Firefox' : /chrome|crios/i.test(ua) ? 'Chrome' : /safari/i.test(ua) ? 'Safari' : 'Browser';
    return `${browser} auf ${os}`;
  }

  async function enablePush() {
    if (!info?.vapid_public_key) return;
    busy = true;
    error = '';
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        error = 'Benachrichtigungen sind für Finanzen im Browser blockiert – in den Website-Einstellungen erlauben.';
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(info.vapid_public_key) as BufferSource }));
      const json = sub.toJSON();
      apply(await api.post<State>('/api/notifications/subscriptions', { endpoint: sub.endpoint, p256dh: json.keys?.p256dh, auth: json.keys?.auth, device: deviceName() }));
      endpoint = sub.endpoint;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function removeDevice(ep: string) {
    busy = true;
    try {
      if (ep === endpoint) {
        const reg = await navigator.serviceWorker.getRegistration();
        await (await reg?.pushManager.getSubscription())?.unsubscribe();
        endpoint = null;
      }
      apply(await api.post<State>('/api/notifications/subscriptions/remove', { endpoint: ep }));
    } finally {
      busy = false;
    }
  }

  async function save() {
    error = '';
    try {
      apply(await api.put<State>('/api/notifications/prefs', prefs));
      message = 'Gespeichert.';
      setTimeout(() => (message = ''), 2500);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function sendTest() {
    error = '';
    message = '';
    try {
      const res = await api.post<{ push: number; email: boolean }>('/api/notifications/test');
      const parts = [res.push ? `Push an ${res.push} Gerät${res.push > 1 ? 'e' : ''}` : '', res.email ? `E-Mail an ${info?.email}` : ''].filter(Boolean);
      message = `Gesendet: ${parts.join(' und ')}.`;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const channelOk = (ch: string) => (ch === 'push' ? info?.push_available : info?.email_available && !!info?.email);
</script>

{#if info}
  <section class="card stack">
    <h2>Benachrichtigungen</h2>
    <p class="muted small">Finanzen meldet sich, wenn etwas zu tun ist – per Push auf deinem Handy oder Rechner und per E-Mail. Die Einstellungen gelten nur für dich.</p>

    <div class="stack tight">
      <strong class="small">Push auf diesem Gerät</strong>
      {#if !info.push_available}
        <p class="muted small">Web-Push ist noch nicht eingerichtet: Es fehlen <code>VAPID_PUBLIC_KEY</code> und <code>VAPID_PRIVATE_KEY</code> in der .env (siehe README).</p>
      {:else if !pushSupported}
        <p class="muted small">
          {isIos ? 'Auf iPhone und iPad gibt es Push nur, wenn Finanzen über „Zum Home-Bildschirm“ installiert ist – öffne es von dort.' : 'Dieser Browser unterstützt keine Push-Nachrichten.'}
        </p>
      {:else if thisDevice}
        <div class="row wrap">
          <span class="small">Aktiv für {deviceName()}.</span>
          <button class="btn" onclick={() => endpoint && removeDevice(endpoint)} disabled={busy}>Ausschalten</button>
        </div>
      {:else}
        <div><button class="btn primary" onclick={enablePush} disabled={busy}>Push auf diesem Gerät einschalten</button></div>
      {/if}
      {#if info.devices.filter((d) => d.endpoint !== endpoint).length}
        <ul class="list small">
          {#each info.devices.filter((d) => d.endpoint !== endpoint) as d (d.endpoint)}
            <li class="row wrap">
              <span class="grow">{d.device || 'Gerät'} <span class="muted">· seit {formatDate(d.created_at.slice(0, 10))}</span></span>
              <button class="btn" onclick={() => removeDevice(d.endpoint)} disabled={busy}>Entfernen</button>
            </li>
          {/each}
        </ul>
      {/if}
      <span class="small muted">
        E-Mail:
        {#if !info.email_available}nicht eingerichtet (<code>SMTP_HOST</code>, <code>SMTP_FROM</code> fehlen){:else if !info.email}keine Adresse im Login hinterlegt{:else}an {info.email}{/if}
      </span>
    </div>

    <div class="events">
      <div class="ev head small muted"><span>Ereignis</span><span>Push</span><span>E-Mail</span></div>
      {#each info.events as ev (ev.key)}
        {@const p = prefs[ev.key]}
        <div class="ev">
          <div class="stack tight">
            <span>{ev.label}</span>
            {#if ev.key === 'maturity'}
              <label class="inline small muted">
                <input type="number" min="1" max="365" bind:value={p.days} oninput={() => (dirty = true)} /> Tage vorher
              </label>
            {:else if ev.key === 'value_change'}
              <span class="inline small muted">
                <select bind:value={p.period} onchange={() => (dirty = true)} aria-label="Zeitraum">
                  <option value="day">an einem Tag</option>
                  <option value="week">in einer Woche</option>
                </select>
                ab
                <input type="text" inputmode="decimal" bind:value={p.percent} oninput={() => (dirty = true)} aria-label="Prozent" /> %
                oder
                <input type="text" inputmode="decimal" bind:value={p.amount} oninput={() => (dirty = true)} aria-label="Betrag" placeholder="–" /> €
              </span>
            {:else if ev.key === 'valuation_due'}
              <label class="inline small muted">
                wenn älter als <input type="number" min="1" max="60" bind:value={p.months} oninput={() => (dirty = true)} /> Monate
              </label>
            {:else if ev.key === 'monthly_report'}
              <span class="small muted">Am 1. jedes Monats: Nettovermögen, Veränderung, Rendite und größte Bewegungen.</span>
            {/if}
          </div>
          {#each ['push', 'email'] as ch (ch)}
            <span class="cell">
              {#if ev.channels.includes(ch)}
                <input type="checkbox" bind:checked={p[ch as 'push' | 'email']} onchange={() => (dirty = true)} aria-label="{ev.label}: {ch === 'push' ? 'Push' : 'E-Mail'}" disabled={!channelOk(ch)} />
              {:else}
                <span class="muted">–</span>
              {/if}
            </span>
          {/each}
        </div>
      {/each}
    </div>

    {#if error}<p class="error small">{error}</p>{/if}
    {#if message}<p class="small">{message}</p>{/if}
    <div class="row wrap">
      <button class="btn primary" onclick={save} disabled={!dirty}>Speichern</button>
      <button class="btn" onclick={sendTest}>Testnachricht senden</button>
    </div>

    {#if info.recent.length}
      <details class="small">
        <summary>Zuletzt gesendet</summary>
        <ul class="list">
          {#each info.recent as r, i (i)}
            <li>{formatDate(r.sent_at.slice(0, 10))} · {r.title} <span class="muted">({r.channels.replace('email', 'E-Mail').replace('push', 'Push')})</span></li>
          {/each}
        </ul>
      </details>
    {/if}
  </section>
{/if}

<style>
  h2 {
    margin: 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .tight {
    gap: 4px;
  }
  .wrap {
    flex-wrap: wrap;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
  }
  .events {
    display: grid;
    border-top: 1px solid var(--border);
  }
  .ev {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 56px 56px;
    gap: 8px;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .ev.head {
    padding: 6px 0;
  }
  .ev.head span:not(:first-child),
  .cell {
    text-align: center;
  }
  .cell input {
    width: 20px;
    height: 20px;
    min-height: auto;
  }
  .inline {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .inline input {
    width: 72px;
    min-height: 32px;
    padding: 4px 8px;
  }
  .inline select {
    width: auto;
    min-height: 32px;
    padding: 4px 8px;
  }
</style>
