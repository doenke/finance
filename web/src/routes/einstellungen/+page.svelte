<script lang="ts">
  import { onMount } from 'svelte';
  import Avatar from '#lib/Avatar.svelte';
  import Icon from '#lib/Icon.svelte';
  import { logout, session } from '#lib/session.svelte.ts';
  import { getTheme, setTheme, type Theme } from '#lib/theme.ts';

  let theme = $state<Theme>('system');
  onMount(() => (theme = getTheme()));

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
