<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import Avatar from '#lib/Avatar.svelte';
  import Icon from '#lib/Icon.svelte';
  import Login from '#lib/Login.svelte';
  import PrivacyToggle from '#lib/PrivacyToggle.svelte';
  import { initPrivacy } from '#lib/privacy.svelte.ts';
  import { loadSession, session } from '#lib/session.svelte.ts';

  let { children } = $props();

  const nav = [
    { href: '/', label: 'Übersicht', short: 'Start', icon: 'home' },
    { href: '/konten', label: 'Konten', icon: 'wallet', also: ['/import'] },
    { href: '/anlagen', label: 'Anlagen', icon: 'trend', also: ['/wertpapiere'] },
    // Monthly/yearly balance and contracts are tabs (BudgetTabs).
    { href: '/bilanz', label: 'Budget', icon: 'bars', also: ['/jahresbilanz', '/vertraege', '/kategorien'] },
    { href: '/vorsorge', label: 'Vorsorge', icon: 'hourglass' },
    // Household, banks, audit log and the rest are reached from the settings.
    { href: '/einstellungen', label: 'Einstellungen', short: 'Optionen', icon: 'settings', also: ['/haushalt', '/banken', '/protokoll'] }
  ];


  const isActive = (href: string) => {
    if (href === '/') return page.url.pathname === '/';
    const item = nav.find((n) => n.href === href);
    return [href, ...(item?.also ?? [])].some((h) => page.url.pathname.startsWith(h));
  };

  onMount(() => {
    initPrivacy();
    loadSession();
  });
</script>

{#if session.loading}
  <div class="center muted">Lädt …</div>
{:else if session.error}
  <div class="center">
    <div class="card stack">
      <p class="error">Der Server ist nicht erreichbar: {session.error}</p>
      <button class="btn" onclick={loadSession}>Erneut versuchen</button>
    </div>
  </div>
{:else if !session.me}
  <Login />
{:else}
  <div class="shell">
    <nav class="sidebar" aria-label="Hauptnavigation">
      <a class="brand" href="/">
        <img src="/icon.svg" alt="" width="32" height="32" />
        <span>Finanzen</span>
      </a>
      {#each nav as item (item.href)}
        <a href={item.href} class:active={isActive(item.href)} aria-current={isActive(item.href) ? 'page' : undefined}>
          <Icon name={item.icon} />
          <span class="full">{item.label}</span>
          {#if item.short}<span class="short">{item.short}</span>{/if}
        </a>
      {/each}
      <div class="spacer"></div>
      <div class="privacy"><PrivacyToggle withLabel /></div>
      <a class="user" href="/einstellungen">
        <Avatar name={session.me.name} url={session.me.avatar_url} />
        <span>{session.me.name}</span>
      </a>
    </nav>
    <main>
      {@render children()}
    </main>
  </div>
{/if}

<style>
  .center {
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: 16px;
  }
  .shell {
    display: grid;
    grid-template-columns: 232px minmax(0, 1fr);
    min-height: 100dvh;
  }
  .sidebar {
    position: sticky;
    top: 0;
    height: 100dvh;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 16px 12px;
    border-right: 1px solid var(--border);
    background: var(--surface);
  }
  .sidebar a {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 10px;
    color: var(--text);
    text-decoration: none;
    font-weight: 500;
  }
  .sidebar a:hover {
    background: var(--surface-2);
  }
  .sidebar a.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }
  .brand {
    font-size: 1.15rem;
    font-weight: 700 !important;
    margin-bottom: 12px;
  }
  .spacer {
    flex: 1;
  }
  .user span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  main {
    padding: 24px;
    max-width: 1200px;
    width: 100%;
    min-width: 0;
  }

  .short {
    display: none;
  }
  /* six entries in the bottom bar: short labels on phones */
  @media (max-width: 560px) {
    .sidebar a:has(.short) .full {
      display: none;
    }
    .sidebar a .short {
      display: inline;
    }
  }
  @media (max-width: 760px) {
    .shell {
      grid-template-columns: minmax(0, 1fr);
    }
    .sidebar {
      position: fixed;
      top: auto;
      bottom: 0;
      left: 0;
      right: 0;
      height: auto;
      flex-direction: row;
      justify-content: space-around;
      padding: 6px 8px calc(6px + env(safe-area-inset-bottom));
      border-right: none;
      border-top: 1px solid var(--border);
      z-index: 10;
    }
    .sidebar a {
      flex-direction: column;
      gap: 2px;
      padding: 6px 2px;
      font-size: 0.75rem;
    }
    .sidebar a {
      flex: 1 1 0;
      min-width: 0;
    }
    .sidebar a span {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .brand,
    .spacer,
    .privacy,
    .user {
      display: none !important;
    }
    main {
      padding: 16px 16px calc(88px + env(safe-area-inset-bottom));
    }
  }
</style>
