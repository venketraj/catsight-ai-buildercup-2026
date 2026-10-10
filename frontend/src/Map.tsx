/**
 * UI-3 - choropleth of hazard intensity by admin-1 region.
 *
 * Plain SVG, no map library or tiles: 82 KB of simplified Natural Earth
 * shapes (public domain), an equirectangular projection corrected for
 * latitude, fitted to the countries the event touched. Colour is one hue,
 * light to dark by band (dataviz: sequential = one hue; on a dark surface the
 * stronger bands are the lighter, more salient steps). Identity is never
 * colour alone - the legend names every band, hover names the region, and a
 * table alternative lists every value (UI-12).
 */

import { useEffect, useMemo, useState } from "react";

import { API_BASE, formatUsd, unlessAborted } from "./api";

interface Feature {
  properties: { code: string; name: string; country: string; in_book: boolean };
  geometry: { type: "MultiPolygon"; coordinates: number[][][][] };
}

interface RegionValue {
  code: string;
  name: string | null;
  country: string | null;
  intensity: number | null;
  band: number | null;
}

interface Exposure {
  cedents: { cedent_id: string; cedent: string; tsi_usd_m: number }[];
}

/** Bands 1-5, weakest to strongest, from the reference blue ramp (steps
 * 600, 450, 350, 250, 150): monotonic lightness, and on the dark surface the
 * strongest band is the brightest. Adjacent steps of one hue cannot reach the
 * categorical ΔE 15 floor (validator: 9.9), so band identity is always
 * carried a second way too - legend labels, the band number on hover, and
 * the table view. */
// The steps live in styles.css (--band-1..5) so the light theme can reverse
// the ramp: there the strongest band is the darkest.
const BAND_FILL = [1, 2, 3, 4, 5].map((n) => `var(--band-${n})`);
const NO_HAZARD = "var(--no-hazard)";
/** Land outside the event: visibly land, clearly not part of the story. */
const OUT_OF_SCOPE = "var(--out-of-scope)";
const W = 640;
const H = 460;

export function HazardMap({ eventId, peril }: { eventId: string; peril: "WS" | "EQ" | string }) {
  const [features, setFeatures] = useState<Feature[] | null>(null);
  const [values, setValues] = useState<RegionValue[]>([]);
  const [unit, setUnit] = useState("");
  const [thresholds, setThresholds] = useState<number[]>([]);
  const [hover, setHover] = useState<{ code: string; x: number; y: number } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [exposure, setExposure] = useState<Exposure | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      fetch("/regions.geojson", { signal }).then((r) => r.json()),
      fetch(`${API_BASE}/api/events/${encodeURIComponent(eventId)}/regions`, { signal }).then((r) => r.json()),
      fetch(`${API_BASE}/api/methodology`, { signal }).then((r) => r.json()),
    ])
      .then(([geo, ev, method]) => {
        setFeatures(geo.features as Feature[]);
        setValues(ev.regions as RegionValue[]);
        setUnit(ev.unit);
        const bands = method?.vulnerability?.bands ?? {};
        setThresholds(peril === "WS" ? bands.wind_ms ?? [] : bands.mmi ?? []);
      })
      .catch(unlessAborted(setError));
    return () => controller.abort();
  }, [eventId, peril]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setExposure(null);
    fetch(`${API_BASE}/api/regions/${encodeURIComponent(selected)}/exposure?peril=${peril}`, {
      signal: controller.signal,
    })
      .then((r) => r.json())
      .then(setExposure)
      .catch(unlessAborted(setError));
    return () => controller.abort();
  }, [selected, peril]);

  const byCode = useMemo(() => new Map(values.map((v) => [v.code, v])), [values]);
  const countries = useMemo(
    () => new Set(values.map((v) => v.country).filter(Boolean) as string[]),
    [values],
  );

  const projected = useMemo(() => {
    if (!features || countries.size === 0) return null;
    const inScope = features.filter((f) => countries.has(f.properties.country));
    // Fit to the AFFECTED regions, not the whole country: Japan's far-south
    // islands would otherwise shrink the impact zone to a corner.
    const affected = inScope.filter((f) => byCode.has(f.properties.code));
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const f of affected.length ? affected : inScope)
      for (const poly of f.geometry.coordinates)
        for (const [x, y] of poly[0] ?? []) {
          if (x === undefined || y === undefined) continue;
          minX = Math.min(minX, x); maxX = Math.max(maxX, x);
          minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        }
    const padX = (maxX - minX) * 0.06;
    const padY = (maxY - minY) * 0.06;
    minX -= padX; maxX += padX; minY -= padY; maxY += padY;
    const k = Math.cos((((minY + maxY) / 2) * Math.PI) / 180);
    const scale = Math.min((W - 20) / ((maxX - minX) * k), (H - 20) / (maxY - minY));
    const ox = (W - (maxX - minX) * k * scale) / 2;
    const oy = (H - (maxY - minY) * scale) / 2;
    const project = (x: number, y: number) =>
      [ox + (x - minX) * k * scale, oy + (maxY - y) * scale] as const;
    return inScope.map((f) => ({
      f,
      d: f.geometry.coordinates
        .map((poly) =>
          (poly[0] ?? [])
            .map(([x, y], i) => {
              const [px, py] = project(x ?? 0, y ?? 0);
              return `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`;
            })
            .join("") + "Z",
        )
        .join(""),
    }));
  }, [features, countries, byCode]);

  const fillFor = (code: string) => {
    const v = byCode.get(code);
    if (!v) return OUT_OF_SCOPE;
    if (!v.band) return NO_HAZARD;
    return BAND_FILL[Math.min(v.band, 5) - 1] ?? NO_HAZARD;
  };

  const bandLabel = (band: number) => {
    const lo = thresholds[band - 1];
    const hi = thresholds[band];
    if (lo === undefined) return "";
    return hi === undefined ? `≥ ${lo} ${unit}` : `${lo}–${hi} ${unit}`;
  };

  const hovered = hover ? byCode.get(hover.code) : undefined;
  const selectedValue = selected ? byCode.get(selected) : undefined;
  const rows = [...values].sort((a, b) => (b.intensity ?? 0) - (a.intensity ?? 0));

  return (
    <section className="panel map-panel">
      <h2>Where it hit · {peril === "WS" ? "peak wind" : "shaking intensity"} by region</h2>
      {error && <p className="banner error">{error}</p>}
      {!projected && !error && <p className="note">Loading the map…</p>}
      {projected && (
        <div className="map-layout">
          <div className="map-wrap" onMouseLeave={() => setHover(null)}>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" style={{ overflow: "hidden" }}
                 aria-label={`Map of ${values.length} affected regions coloured by intensity`}>
              {projected.map(({ f, d }) => {
                const code = f.properties.code;
                const active = code === selected || code === hover?.code;
                return (
                  <path
                    key={code}
                    d={d}
                    style={{
                      fill: fillFor(code),
                      stroke: active ? "var(--ink)" : "var(--bg)",
                      cursor: byCode.has(code) ? "pointer" : "default",
                    }}
                    strokeWidth={active ? 1.6 : 0.6}
                    tabIndex={byCode.has(code) ? 0 : -1}
                    aria-label={`${f.properties.name}${byCode.get(code)?.intensity != null ? `, ${byCode.get(code)?.intensity} ${unit}` : ""}`}
                    onMouseMove={(e) => {
                      const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                      setHover({ code, x: e.clientX - box.left, y: e.clientY - box.top });
                    }}
                    onClick={() => byCode.has(code) && setSelected(code)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && byCode.has(code) && setSelected(code)}
                  />
                );
              })}
            </svg>
            {hover && (
              <div className="map-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
                <strong>{hovered?.name ?? projected.find((p) => p.f.properties.code === hover.code)?.f.properties.name}</strong>
                <div>
                  {hovered?.intensity != null
                    ? `${hovered.intensity} ${unit}${hovered.band ? ` · band ${hovered.band}` : ""}`
                    : "not affected by this event"}
                </div>
              </div>
            )}
          </div>

          <div className="map-side">
            <div className="legend" aria-label="Legend">
              <div className="legend-title">{peril === "WS" ? "Peak 1-min wind" : "Intensity (MMI)"}</div>
              {[5, 4, 3, 2, 1].map((band) => (
                <div key={band} className="legend-row">
                  <span className="swatch" style={{ background: BAND_FILL[band - 1] }} />
                  band {band} · {bandLabel(band)}
                </div>
              ))}
              <div className="legend-row">
                <span className="swatch" style={{ background: NO_HAZARD }} /> below band 1
              </div>
              <div className="legend-row">
                <span className="swatch" style={{ background: OUT_OF_SCOPE }} /> not in the event
              </div>
            </div>

            <div className="region-detail">
              {!selectedValue && <p className="note">Click a region to see insured value by insurer.</p>}
              {selectedValue && (
                <>
                  <strong>{selectedValue.name}</strong>
                  <div className="note">
                    {selectedValue.intensity} {unit}
                    {selectedValue.band ? ` · band ${selectedValue.band}` : ""}
                  </div>
                  {!exposure && <p className="note">Loading exposure…</p>}
                  {exposure && exposure.cedents.length === 0 && (
                    <p className="note">No insured exposure in the book here.</p>
                  )}
                  {exposure && exposure.cedents.length > 0 && (
                    <table>
                      <tbody>
                        {exposure.cedents.map((c) => (
                          <tr key={c.cedent_id}>
                            <td>{c.cedent}</td>
                            <td className="num">{formatUsd(c.tsi_usd_m)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
      <details className="map-table">
        <summary>Show as a table ({values.length} regions)</summary>
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th>Country</th>
              <th className="num">Intensity</th>
              <th className="num">Band</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code}>
                <td>{r.name ?? r.code}</td>
                <td>{r.country}</td>
                <td className="num">{r.intensity ?? "-"} {unit}</td>
                <td className="num">{r.band ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
      <p className="note">
        Boundaries: Natural Earth (public domain), simplified. Intensity at each region's centroid
        from {peril === "WS" ? "NOAA IBTrACS" : "USGS ShakeMap"}.
      </p>
    </section>
  );
}
