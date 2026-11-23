<script lang="ts">
  import Icon from './Icon.svelte';
  import { privacy, setPrivate } from './privacy.svelte.ts';

  let { withLabel = false }: { withLabel?: boolean } = $props();
  const text = $derived(privacy.on ? 'Beträge zeigen' : 'Beträge verbergen');
</script>

<button class="toggle" class:labeled={withLabel} onclick={() => setPrivate(!privacy.on)} aria-pressed={privacy.on} aria-label={withLabel ? undefined : text} title={text}>
  <Icon name={privacy.on ? 'eye-off' : 'eye'} />
  {#if withLabel}<span>{text}</span>{/if}
</button>

<style>
  .toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    min-width: 40px;
    min-height: 40px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
    font: inherit;
  }
  .toggle[aria-pressed='true'] {
    background: var(--accent-soft);
    color: var(--accent-strong);
    border-color: transparent;
  }
  .labeled {
    justify-content: flex-start;
    padding: 10px 12px;
    border: 0;
    background: none;
    font-weight: 500;
    width: 100%;
  }
  .labeled:hover {
    background: var(--surface-2);
  }
</style>
