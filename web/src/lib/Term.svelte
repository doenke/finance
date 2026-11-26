<script lang="ts" module>
  // Explanations of the return measures, shown behind an "i" wherever they appear.
  export const TERMS = {
    ttwror:
      'TTWROR – zeitgewichtete Rendite: Wie gut haben sich die Anlagen selbst entwickelt? Wann und wie viel ihr ein- oder ausgezahlt habt, spielt keine Rolle. Damit lässt sie sich direkt mit Fonds, ETFs und Indizes vergleichen. „p. a.“ heißt: auf ein Jahr umgerechnet.',
    izf: 'IZF – interner Zinsfuß, eure persönliche Rendite pro Jahr: Sie berücksichtigt, wann ihr wie viel Geld eingesetzt habt – so viel Zins hätte ein Sparbuch mit genau diesen Ein- und Auszahlungen bringen müssen. Habt ihr vor einem Anstieg viel nachgekauft, ist sie höher als die TTWROR, vor einem Rückgang niedriger.'
  } as const;
</script>

<script lang="ts">
  import Info from './Info.svelte';

  let { term, label }: { term: keyof typeof TERMS; label?: string } = $props();
  const DEFAULT = { ttwror: 'TTWROR', izf: 'IZF p. a.' };
</script>

<span class="term">{label ?? DEFAULT[term]}<Info label="Was bedeutet {DEFAULT[term]}?">{TERMS[term]}</Info></span>

<style>
  .term {
    white-space: nowrap;
  }
</style>
