<script lang="ts">
  let { name, url = null, color = '#15803d', size = 32 }: { name: string; url?: string | null; color?: string; size?: number } =
    $props();
  const initials = $derived(
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join('') || '?'
  );
  let failed = $state(false);
</script>

{#if url && !failed}
  <img src={url} alt="" width={size} height={size} style:width="{size}px" style:height="{size}px" onerror={() => (failed = true)} />
{:else}
  <span class="initials" style:background={color} style:width="{size}px" style:height="{size}px" style:font-size="{size * 0.4}px"
    >{initials}</span
  >
{/if}

<style>
  img,
  .initials {
    border-radius: 50%;
    flex: none;
  }
  img {
    object-fit: cover;
  }
  .initials {
    display: inline-grid;
    place-items: center;
    color: #fff;
    font-weight: 600;
  }
</style>
