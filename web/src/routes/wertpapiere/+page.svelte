<script lang="ts">
  // The comparison moved to the Anlagen page; keep old links working.
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => goto('/anlagen', { replaceState: true }));
</script>
