<script lang="ts">
  // Small "i" button next to a heading; the explanation opens on demand instead of filling the page.
  import type { Snippet } from 'svelte';

  let { label = 'Erklärung', children }: { label?: string; children: Snippet } = $props();
  let open = $state(false);
  let alignRight = $state(false); // open towards the left when the button sits in the right half
  let root: HTMLElement | undefined = $state();

  function toggle() {
    if (!open && root) alignRight = root.getBoundingClientRect().left > window.innerWidth / 2;
    open = !open;
  }
  function onDocClick(e: MouseEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') open = false;
  }
</script>

<svelte:document onclick={onDocClick} onkeydown={onKey} />

<span class="info" bind:this={root}>
  <button type="button" class="i" aria-label={label} aria-expanded={open} onclick={toggle}>i</button>
  {#if open}
    <span class="pop" class:right={alignRight} role="note">{@render children()}</span>
  {/if}
</span>

<style>
  .info {
    position: relative;
    display: inline-block;
    vertical-align: middle;
    margin-left: 6px;
    font-size: 0.85rem;
    font-weight: 400;
  }
  .pop.right {
    left: auto;
    right: -8px;
  }
  .i {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--muted);
    font: italic 600 11px/16px Georgia, serif;
    padding: 0;
    cursor: pointer;
  }
  .i:hover,
  .i[aria-expanded='true'] {
    color: var(--accent-strong);
    border-color: var(--accent);
  }
  .pop {
    position: absolute;
    z-index: 20;
    top: 24px;
    left: -8px;
    width: min(340px, 80vw);
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    box-shadow: 0 6px 24px rgb(0 0 0 / 0.15);
    color: var(--text);
    line-height: 1.45;
    white-space: normal;
  }
</style>
