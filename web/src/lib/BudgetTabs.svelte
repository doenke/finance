<script lang="ts">
  import { page } from '$app/state';
  const tabs = [
    { href: '/bilanz', label: 'Monatsbilanz' },
    { href: '/jahresbilanz', label: 'Jahresbilanz' },
    { href: '/vertraege', label: 'Verträge & Abos' },
    { href: '/kategorien', label: 'Kategorien' }
  ];
</script>

<nav class="tabs" aria-label="Budget">
  {#each tabs as t (t.href)}
    <a href={t.href} class:active={page.url.pathname.startsWith(t.href)} aria-current={page.url.pathname.startsWith(t.href) ? 'page' : undefined}>{t.label}</a>
  {/each}
</nav>

<style>
  .tabs {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    width: fit-content;
    max-width: 100%;
    overflow-x: auto;
  }
  a {
    white-space: nowrap;
    padding: 8px 14px;
    color: var(--text);
    text-decoration: none;
    background: var(--surface);
  }
  a + a {
    border-left: 1px solid var(--border);
  }
  a.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 600;
  }
</style>
