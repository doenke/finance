<script lang="ts">
  // Runs a FinTS job (discover accounts or sync) and walks the user through PIN, TAN method and TAN.
  import { onDestroy } from 'svelte';
  import { api, type BankLogin, type FintsJob } from './api.ts';

  let {
    login,
    kind,
    accountIds = null,
    onclose,
    ondone = () => {}
  }: { login: BankLogin; kind: 'discover' | 'sync'; accountIds?: number[] | null; onclose: () => void; ondone?: (job: FintsJob) => void } = $props();

  let pin = $state('');
  let job = $state<FintsJob | null>(null);
  let answer = $state('');
  let choice = $state('');
  let error = $state('');
  let starting = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  // svelte-ignore state_referenced_locally
  const needsPin = !login.has_pin;

  async function start(event?: SubmitEvent) {
    event?.preventDefault();
    error = '';
    starting = true;
    try {
      job = await api.post<FintsJob>(`/api/bank-logins/${login.id}/${kind}`, { pin: pin || null, account_ids: accountIds });
      pin = '';
      poll();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      starting = false;
    }
  }

  async function poll() {
    if (!job) return;
    try {
      job = await api.get<FintsJob>(`/api/fints/jobs/${job.id}`);
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    if (job.status === 'done') ondone(job);
    if (!['done', 'error', 'cancelled'].includes(job.status)) timer = setTimeout(poll, 1000);
  }

  async function send(value: string) {
    if (!job) return;
    await api.post(`/api/fints/jobs/${job.id}/answer`, { value });
    answer = '';
    choice = '';
  }

  async function cancel() {
    if (job && !['done', 'error', 'cancelled'].includes(job.status)) await api.post(`/api/fints/jobs/${job.id}/cancel`);
    onclose();
  }

  // svelte-ignore state_referenced_locally
  if (!needsPin) start();
  onDestroy(() => timer && clearTimeout(timer));
</script>

<div class="backdrop" role="presentation">
  <div class="dialog card stack" role="dialog" aria-modal="true" aria-labelledby="fints-title">
    <h2 id="fints-title">{login.name} – {kind === 'discover' ? 'Konten suchen' : 'Aktualisieren'}</h2>

    {#if !job}
      {#if needsPin}
        <form class="stack" onsubmit={start}>
          <label>PIN für {login.username} <input type="password" autocomplete="off" bind:value={pin} required maxlength="64" /></label>
          <p class="muted small">Die PIN wird nur für diesen Abruf verwendet und nicht gespeichert.</p>
          <div class="row">
            <button class="btn primary" type="submit" disabled={starting}>Verbinden</button>
            <button class="btn" type="button" onclick={onclose}>Abbrechen</button>
          </div>
        </form>
      {:else}
        <p class="muted">Starte …</p>
      {/if}
    {:else if job.status === 'running'}
      <p class="status"><span class="spinner" aria-hidden="true"></span> {job.message}</p>
    {:else if job.status === 'need_choice' && job.choices}
      <form
        class="stack"
        onsubmit={(e) => {
          e.preventDefault();
          send(choice);
        }}
      >
        <p>{job.message}</p>
        {#each job.choices as c (c.value)}
          <label class="radio"><input type="radio" name="choice" value={c.value} bind:group={choice} /> {c.label}</label>
        {/each}
        <div class="row"><button class="btn primary" type="submit" disabled={!choice}>Weiter</button></div>
      </form>
    {:else if job.status === 'need_tan' && job.challenge}
      {#if job.challenge.decoupled}
        <p class="status"><span class="spinner" aria-hidden="true"></span> Bitte gib den Auftrag in deiner Banking-App frei.</p>
        {#if job.challenge.text}<p class="muted small challenge">{job.challenge.text}</p>{/if}
      {:else}
        <form
          class="stack"
          onsubmit={(e) => {
            e.preventDefault();
            send(answer);
          }}
        >
          {#if job.challenge.text}<p class="challenge">{job.challenge.text}</p>{/if}
          {#if job.challenge.image}<img class="matrix" src={job.challenge.image} alt="TAN-Grafik zum Scannen" />{/if}
          {#if job.challenge.hhduc && !job.challenge.image}
            <p class="muted small">Flickercode wird nicht angezeigt – nutze am TAN-Generator die manuelle Eingabe mit den Angaben oben.</p>
          {/if}
          <label>TAN <input bind:value={answer} inputmode="numeric" autocomplete="one-time-code" required maxlength="20" /></label>
          <div class="row"><button class="btn primary" type="submit" disabled={!answer}>Senden</button></div>
        </form>
      {/if}
    {:else if job.status === 'done'}
      <p class="ok">Fertig.</p>
      {#if job.kind === 'sync' && job.result?.accounts}
        <ul class="summary">
          {#each job.result.accounts as a (a.account_id)}
            <li>
              <strong>{a.name}</strong>:
              {#if a.error}<span class="error">{a.error}</span>
              {:else}
                {#if a.balance !== undefined}Saldo aktualisiert{/if}{#if a.new_transactions !== undefined}, {a.new_transactions} neue Umsätze{/if}
                {#if a.positions !== undefined}{a.positions} Positionen{#if a.initial_deliveries}, Anfangsbestand übernommen{/if}{#if a.differences}, <span class="warn">{a.differences} Abweichungen</span>{/if}{/if}
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    {:else if job.status === 'error'}
      <p class="error">{job.error}</p>
    {:else if job.status === 'cancelled'}
      <p class="muted">Abgebrochen.</p>
    {/if}

    {#if error}<p class="error">{error}</p>{/if}
    {#if job}
      <div class="row end">
        <button class="btn" onclick={cancel}>{['done', 'error', 'cancelled'].includes(job.status) ? 'Schließen' : 'Abbrechen'}</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.45);
    display: grid;
    place-items: center;
    padding: 16px;
    z-index: 50;
  }
  .dialog {
    width: 100%;
    max-width: 440px;
    max-height: 90dvh;
    overflow: auto;
  }
  .dialog h2 {
    margin: 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .status {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .spinner {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    animation: spin 0.8s linear infinite;
    flex: none;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .challenge {
    white-space: pre-wrap;
  }
  .matrix {
    max-width: 240px;
    width: 100%;
    image-rendering: pixelated;
    background: #fff;
    padding: 8px;
    border-radius: 8px;
  }
  .radio {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--text);
  }
  .radio input {
    width: auto;
    min-height: auto;
  }
  .ok {
    color: var(--pos);
  }
  .warn {
    color: var(--warn);
  }
  .summary {
    margin: 0;
    padding-left: 18px;
    display: grid;
    gap: 4px;
  }
  .end {
    justify-content: flex-end;
  }
</style>
