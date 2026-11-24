<script lang="ts">
  // Line chart for time series with one shared y-axis, crosshair and tooltip.
  export interface Series {
    key: string;
    label: string;
    color: string; // CSS color, e.g. 'var(--series-1)'
    points: { date: string; value: number | null }[];
    dashed?: boolean;
  }

  let {
    series,
    format,
    height = 240,
    zeroLine = false,
    area = false,
    ariaLabel = 'Diagramm',
    money = false
  }: { series: Series[]; format: (v: number) => string; height?: number; zeroLine?: boolean; area?: boolean; ariaLabel?: string; money?: boolean } = $props();

  let width = $state(0);
  let hover = $state<number | null>(null);

  const pad = { top: 12, right: 12, bottom: 26, left: 8 };
  const dates = $derived(series[0]?.points.map((p) => p.date) ?? []);
  const allValues = $derived(series.flatMap((s) => s.points.map((p) => p.value)).filter((v): v is number => v !== null && Number.isFinite(v)));
  const yDomain = $derived.by(() => {
    if (!allValues.length) return [0, 1];
    let min = Math.min(...allValues);
    let max = Math.max(...allValues);
    if (zeroLine || area) {
      min = Math.min(min, 0);
      max = Math.max(max, 0);
    }
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const span = max - min;
    return [min - span * 0.05, max + span * 0.08];
  });
  const ticks = $derived(niceTicks(yDomain[0], yDomain[1], 4));
  const labelWidth = $derived(Math.max(...ticks.map((t) => format(t).length), 3) * 7 + 8);
  const plotLeft = $derived(pad.left + labelWidth);
  const plotW = $derived(Math.max(10, width - plotLeft - pad.right));
  const plotH = $derived(height - pad.top - pad.bottom);

  const x = (i: number) => plotLeft + (dates.length > 1 ? (i / (dates.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => pad.top + plotH - ((v - yDomain[0]) / (yDomain[1] - yDomain[0])) * plotH;

  function niceTicks(min: number, max: number, count: number): number[] {
    const raw = (max - min) / count;
    const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
    const out: number[] = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v / step) * step + 0); // + 0 turns -0 into 0
    return [...new Set(out)];
  }

  function path(points: { value: number | null }[]): string {
    let d = '';
    let pen = false;
    points.forEach((p, i) => {
      if (p.value === null || !Number.isFinite(p.value)) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
      pen = true;
    });
    return d;
  }

  function areaPath(points: { value: number | null }[]): string {
    const line = path(points);
    if (!line) return '';
    const valid = points.map((p, i) => ({ p, i })).filter((e) => e.p.value !== null);
    const first = valid[0].i;
    const last = valid[valid.length - 1].i;
    return `${line}L${x(last)},${y(0)}L${x(first)},${y(0)}Z`;
  }

  const xTicks = $derived.by(() => {
    if (dates.length < 2) return [] as number[];
    const n = Math.max(2, Math.min(6, Math.floor(plotW / 110)));
    // few dates (e.g. an account with data since yesterday) would repeat indexes
    return [...new Set(Array.from({ length: n }, (_, k) => Math.round((k / (n - 1)) * (dates.length - 1))))];
  });

  function dateLabel(iso: string, spanDays: number): string {
    const [yy, mm, dd] = iso.split('-');
    return spanDays > 400 ? `${mm}/${yy.slice(2)}` : `${dd}.${mm}.`;
  }
  const spanDays = $derived(dates.length > 1 ? (Date.parse(dates[dates.length - 1]) - Date.parse(dates[0])) / 86400000 : 0);

  function onMove(event: PointerEvent) {
    const rect = (event.currentTarget as SVGElement).getBoundingClientRect();
    const px = event.clientX - rect.left;
    if (dates.length < 2) return;
    const i = Math.round(((px - plotLeft) / plotW) * (dates.length - 1));
    hover = Math.max(0, Math.min(dates.length - 1, i));
  }

  const lastLabels = $derived(
    series.length > 1 && series.length <= 4
      ? series
          .map((s) => {
            const last = [...s.points].reverse().find((p) => p.value !== null);
            return last ? { key: s.key, label: s.label, color: s.color, y: y(last.value as number) } : null;
          })
          .filter((l): l is NonNullable<typeof l> => l !== null)
      : []
  );
</script>

<div class="chart" bind:clientWidth={width} style:min-height="{height}px">
  {#if series.length > 1}
    <ul class="legend">
      {#each series as s (s.key)}
        <li><span class="swatch" class:dashed={s.dashed} style:background={s.dashed ? 'none' : s.color} style:border-color={s.color}></span>{s.label}</li>
      {/each}
    </ul>
  {/if}
  {#if width > 0}
  <svg {width} {height} role="img" aria-label={ariaLabel} onpointermove={onMove} onpointerleave={() => (hover = null)}>
    {#each ticks as t (t)}
      <line x1={plotLeft} x2={plotLeft + plotW} y1={y(t)} y2={y(t)} class="grid" class:zero={t === 0} />
      <text x={plotLeft - 6} y={y(t)} class="tick" class:money text-anchor="end" dominant-baseline="middle">{format(Object.is(t, -0) || Math.abs(t) < 1e-12 ? 0 : t)}</text>
    {/each}
    {#each xTicks as i (i)}
      <text x={x(i)} y={height - 6} class="tick" text-anchor={i === 0 ? 'start' : i === dates.length - 1 ? 'end' : 'middle'}>{dateLabel(dates[i], spanDays)}</text>
    {/each}
    {#each series as s (s.key)}
      {#if area}<path d={areaPath(s.points)} fill={s.color} opacity="0.12" />{/if}
      <path d={path(s.points)} fill="none" stroke={s.color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" stroke-dasharray={s.dashed ? '5 4' : undefined} />
    {/each}
    {#if hover !== null}
      <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH} class="cross" />
      {#each series as s (s.key)}
        {#if s.points[hover]?.value !== null && s.points[hover]?.value !== undefined}
          <circle cx={x(hover)} cy={y(s.points[hover].value as number)} r="4.5" fill={s.color} class="dot" />
        {/if}
      {/each}
    {/if}
  </svg>
  {/if}
  {#if hover !== null && width > 0}
    <div class="tooltip" style:left="{Math.min(x(hover) + 12, width - 190)}px">
      <div class="tdate">{dates[hover].split('-').reverse().join('.')}</div>
      {#each series as s (s.key)}
        <div class="trow">
          <span class="swatch" style:background={s.color}></span>
          <span class="tlabel">{s.label}</span>
          <strong class:money>{s.points[hover]?.value !== null && s.points[hover]?.value !== undefined ? format(s.points[hover].value as number) : '–'}</strong>
        </div>
      {/each}
    </div>
  {/if}
  {#if lastLabels.length}
    <span class="sr-only">{lastLabels.map((l) => l.label).join(', ')}</span>
  {/if}
</div>

<style>
  .chart {
    position: relative;
    width: 100%;
    min-width: 0;
    overflow: hidden;
    touch-action: pan-y;
  }
  svg {
    display: block;
    overflow: visible;
  }
  .grid {
    stroke: var(--grid);
    stroke-width: 1;
  }
  .grid.zero {
    stroke: var(--muted);
    stroke-opacity: 0.5;
  }
  .tick {
    font-size: 11px;
    fill: var(--muted);
    font-variant-numeric: tabular-nums;
  }
  .cross {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 3 3;
  }
  .dot {
    stroke: var(--surface);
    stroke-width: 2;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    list-style: none;
    margin: 0 0 8px;
    padding: 0;
    font-size: 0.85rem;
    color: var(--muted);
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .swatch {
    width: 14px;
    height: 3px;
    border-radius: 2px;
    display: inline-block;
    border-top: 0 solid;
  }
  .swatch.dashed {
    border-top: 2px dashed;
    height: 0;
  }
  .tooltip {
    position: absolute;
    top: 28px;
    min-width: 170px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
    padding: 8px 10px;
    font-size: 0.85rem;
    pointer-events: none;
    z-index: 2;
  }
  .tdate {
    color: var(--muted);
    margin-bottom: 4px;
  }
  .trow {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .tlabel {
    flex: 1;
    color: var(--muted);
  }
  .trow strong {
    font-variant-numeric: tabular-nums;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
</style>
