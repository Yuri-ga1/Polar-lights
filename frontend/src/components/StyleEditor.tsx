import { useEffect, useState } from "react";
import type { Product } from "../api/contracts";
import { useWorkspace, type ChartSpec, type StyleSpec } from "../store";
import { colorbarSchema } from "../workspace/schema";
import { Check, Choice, Numeric, Text, Field } from "./Controls";
export function projectionOptions(product: Product) {
  return product.graphType === "map" && product.capabilities.projection
    ? (["geographic", "north-polar", "south-polar"] as const)
    : [];
}
export function StyleEditor({
  chart,
  product,
}: {
  chart: ChartSpec;
  product: Product;
}) {
  const s = chart.styleSpec,
    c = s.colorbar,
    m = s.map;
  const update = (patch: Partial<StyleSpec>) =>
    useWorkspace.getState().update(chart.id, { styleSpec: { ...s, ...patch } });
  const cb = (patch: Partial<typeof c>) =>
    update({ colorbar: { ...c, ...patch } });
  const map = (patch: Partial<typeof m>) => update({ map: { ...m, ...patch } });
  const [stops, setStops] = useState(JSON.stringify(c.stops));
  const [stopError, setStopError] = useState("");
  const [latitudeDrafts, setLatitudeDrafts] = useState(() =>
    m.auroraGeomagneticLatitudes.map(String),
  );
  const [latitudeError, setLatitudeError] = useState("");
  useEffect(() => {
    setStops(JSON.stringify(c.stops));
  }, [c.stops]);
  useEffect(() => {
    setLatitudeDrafts(m.auroraGeomagneticLatitudes.map(String));
  }, [m.auroraGeomagneticLatitudes]);
  const applyLatitudes = () => {
    const values = latitudeDrafts.map((draft) => {
      const normalized = draft.trim().replace("−", "-").replace(",", ".");
      if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized)) return NaN;
      return Number(normalized);
    });
    if (
      values.some(
        (value) => !Number.isFinite(value) || value < -90 || value > 90,
      )
    ) {
      setLatitudeError("Enter each latitude between -90 and 90.");
      return;
    }
    setLatitudeError("");
    map({ auroraGeomagneticLatitudes: values });
  };
  return (
    <section aria-label="Appearance">
      <fieldset>
        <legend>Style</legend>
        <Text
          label="Title"
          value={s.title}
          onChange={(title) => update({ title })}
        />
        <Text
          label="Subtitle"
          value={s.subtitle}
          onChange={(subtitle) => update({ subtitle })}
        />
        <Check
          label="Show legend"
          value={s.legend}
          onChange={(legend) => update({ legend })}
        />
        <Choice
          label="Font"
          value={s.font}
          options={["system-ui", "serif", "monospace"]}
          onChange={(font) => update({ font })}
        />
        <Numeric
          label="Font size"
          value={s.fontSize}
          min={8}
          max={40}
          onChange={(v) => v && update({ fontSize: v })}
        />
        <Numeric
          label="Label size"
          value={s.labelSize}
          min={8}
          max={40}
          onChange={(v) => v && update({ labelSize: v })}
        />
        <Text
          label="Background"
          type="color"
          value={s.background}
          onChange={(background) => update({ background })}
        />
      </fieldset>
      {product.graphType !== "map" && (
        <details>
          <summary>Axes and plot</summary>
          <Check
            label="Show axes"
            value={s.axes}
            onChange={(axes) => update({ axes })}
          />
          <Check
            label="Show grid"
            value={s.grid}
            onChange={(grid) => update({ grid })}
          />
          <Text
            label="X axis label"
            value={s.xLabel}
            onChange={(xLabel) => update({ xLabel })}
          />
          <Text
            label="Y axis label"
            value={s.yLabel}
            onChange={(yLabel) => update({ yLabel })}
          />
          <Text
            label="Visual start (UTC)"
            value={s.xMin}
            onChange={(xMin) => update({ xMin })}
          />
          <Text
            label="Visual end (UTC)"
            value={s.xMax}
            onChange={(xMax) => update({ xMax })}
          />
          <Numeric
            label="Y minimum"
            value={s.yMin}
            onChange={(yMin) => update({ yMin })}
          />
          <Numeric
            label="Y maximum"
            value={s.yMax}
            onChange={(yMax) => update({ yMax })}
          />
          <Check
            label="Plot toolbar"
            value={s.modebar}
            onChange={(modebar) => update({ modebar })}
          />
          <Check
            label="Scroll to zoom"
            value={s.scrollZoom}
            onChange={(scrollZoom) => update({ scrollZoom })}
          />
          {(["l", "r", "t", "b"] as const).map((key) => (
            <Numeric
              key={key}
              label={`Margin ${key}`}
              value={s.margins[key]}
              min={0}
              max={200}
              onChange={(v) =>
                v !== undefined &&
                update({ margins: { ...s.margins, [key]: v } })
              }
            />
          ))}
        </details>
      )}
      {product.graphType === "timeseries" && (
        <details>
          <summary>Lines and markers</summary>
          <Numeric
            label="Line width"
            value={s.lineWidth}
            min={0.5}
            max={12}
            step={0.5}
            onChange={(v) => v && update({ lineWidth: v })}
          />
          <Choice
            label="Line style"
            value={s.lineDash}
            options={["solid", "dot", "dash", "dashdot"]}
            onChange={(lineDash) => update({ lineDash })}
          />
          <Check
            label="Show markers"
            value={s.markers}
            onChange={(markers) => update({ markers })}
          />
          <Numeric
            label="Marker size"
            value={s.markerSize}
            min={1}
            max={30}
            onChange={(v) => v && update({ markerSize: v })}
          />
          <Choice
            label="Marker shape"
            value={s.markerSymbol}
            options={["circle", "square", "diamond", "cross"]}
            onChange={(markerSymbol) => update({ markerSymbol })}
          />
        </details>
      )}
      {product.capabilities.colorbar && (
        <details open>
          <summary>Colorbar</summary>
          <Check
            label="Show colorbar"
            value={c.visible}
            onChange={(visible) => cb({ visible })}
          />
          <Choice
            label="Palette"
            value={s.palette}
            options={["viridis", "plasma", "ice"]}
            onChange={(palette) => update({ palette })}
          />
          <Check
            label="Reverse palette"
            value={c.reverse}
            onChange={(reverse) => cb({ reverse })}
          />
          <Choice
            label="Color range"
            value={c.range}
            options={
              s.vmin !== undefined && s.vmax !== undefined
                ? ["recommended", "auto", "manual"]
                : ["auto", "manual"]
            }
            onChange={(range) => cb({ range })}
          />
          {c.range === "recommended" && (
            <p className="hint">
              Product range: {s.vmin} to {s.vmax}.
            </p>
          )}
          {c.range === "manual" && (
            <>
              <Numeric
                label="vmin"
                value={s.vmin}
                onChange={(vmin) => update({ vmin })}
              />
              <Numeric
                label="vmax"
                value={s.vmax}
                onChange={(vmax) => update({ vmax })}
              />
              {s.vmin != null && s.vmax != null && s.vmin >= s.vmax && (
                <p role="alert">
                  vmax must exceed vmin. Automatic bounds are used.
                </p>
              )}
            </>
          )}
          <Choice
            label="Color mode"
            value={c.mode}
            options={["continuous", "discrete"]}
            onChange={(mode) => cb({ mode })}
          />
          {c.mode === "discrete" && (
            <Numeric
              label="Levels"
              value={c.levels}
              min={2}
              max={32}
              onChange={(v) => v && cb({ levels: Math.round(v) })}
            />
          )}
          <Choice
            label="Colorbar orientation"
            value={c.orientation}
            options={["horizontal", "vertical"]}
            onChange={(orientation) => cb({ orientation })}
          />
          {(["x", "y", "length", "thickness", "fontSize"] as const).map(
            (key) => (
              <Numeric
                key={key}
                label={`Colorbar ${key}`}
                value={c[key]}
                min={
                  key === "length"
                    ? 40
                    : key === "fontSize"
                      ? 8
                      : key === "thickness"
                        ? 4
                        : 0
                }
                max={
                  key === "length"
                    ? 600
                    : key === "fontSize"
                      ? 32
                      : key === "thickness"
                        ? 60
                        : 90
                }
                onChange={(v) => v !== undefined && cb({ [key]: v })}
              />
            ),
          )}
          <Text
            label="Colorbar title"
            value={c.title}
            onChange={(title) => cb({ title })}
          />
          <Text
            label="Colorbar units"
            value={c.units}
            onChange={(units) => cb({ units })}
          />
          <Text
            label="Colorbar font"
            value={c.font}
            onChange={(font) => cb({ font })}
          />
          <Field label="Colorbar ticks (comma separated)">
            <input
              defaultValue={c.ticks.join(",")}
              key={c.ticks.join(",")}
              onBlur={(e) => {
                const ticks = e.target.value.trim()
                  ? e.target.value.split(",").map(Number)
                  : [];
                if (ticks.every(Number.isFinite) && ticks.length <= 32)
                  cb({ ticks });
                else setStopError("Ticks must be a list of numbers.");
              }}
            />
          </Field>
          <Field label="Custom stops JSON">
            <textarea
              value={stops}
              onChange={(e) => setStops(e.target.value)}
              placeholder={
                '[{"at":0,"color":"#000000"},{"at":1,"color":"#ffffff"}]'
              }
            />
          </Field>
          <button
            type="button"
            onClick={() => {
              try {
                const parsed = colorbarSchema.shape.stops.parse(
                  JSON.parse(stops),
                );
                if (parsed.length === 1) throw new Error();
                cb({ stops: parsed.sort((a, b) => a.at - b.at) });
                setStopError("");
              } catch {
                setStopError(
                  "Use zero or 2–32 stops with at between 0 and 1 and a #RRGGBB color.",
                );
              }
            }}
          >
            Apply custom stops
          </button>
          {stopError && <p role="alert">{stopError}</p>}
        </details>
      )}
      {(projectionOptions(product).length > 0 ||
        product.productId === "aurora-map") && (
        <details open>
          <summary>Map view</summary>
          {projectionOptions(product).length > 0 && (
            <Choice
              label="Projection"
              value={m.projection}
              options={projectionOptions(product)}
              onChange={(projection) => map({ projection })}
            />
          )}
          <Check
            label="Coastline"
            value={m.coastline}
            onChange={(coastline) => map({ coastline })}
          />
          <Check
            label="Geographic grid"
            value={m.graticule}
            onChange={(graticule) => map({ graticule })}
          />
          <Check
            label="Map labels"
            value={m.labels}
            onChange={(labels) => map({ labels })}
          />
          {product.productId === "aurora-map" && (
            <>
              <Check
                label="Show geomagnetic line"
                value={m.showAuroraGeomagnetic}
                onChange={(showAuroraGeomagnetic) =>
                  map({ showAuroraGeomagnetic })
                }
              />
              {latitudeDrafts.map((draft, index) => (
                <div className="geomagnetic-line-editor" key={index}>
                  <Field label={`Geomagnetic latitude ${index + 1} (°)`}>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={draft}
                      onChange={(event) => {
                        const next = [...latitudeDrafts];
                        next[index] = event.target.value;
                        setLatitudeDrafts(next);
                        setLatitudeError("");
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          applyLatitudes();
                        }
                      }}
                    />
                  </Field>
                  <button
                    type="button"
                    aria-label={`Remove geomagnetic latitude ${index + 1}`}
                    onClick={() => {
                      setLatitudeDrafts(
                        latitudeDrafts.filter(
                          (_, lineIndex) => lineIndex !== index,
                        ),
                      );
                      setLatitudeError("");
                    }}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => {
                  setLatitudeDrafts([...latitudeDrafts, ""]);
                  setLatitudeError("");
                }}
              >
                Add geomagnetic line
              </button>
              <button type="button" onClick={applyLatitudes}>
                Apply lines
              </button>
              {latitudeError && <p role="alert">{latitudeError}</p>}
              <Check
                label="Solar terminator"
                value={m.showAuroraTerminator}
                onChange={(showAuroraTerminator) =>
                  map({ showAuroraTerminator })
                }
              />
            </>
          )}
          <Numeric
            label="Point size"
            value={m.pointSize}
            min={1}
            max={30}
            onChange={(v) => v && map({ pointSize: v })}
          />
          <Numeric
            label="Opacity"
            value={m.opacity}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => v !== undefined && map({ opacity: v })}
          />
          <Check
            label="Show no-data points"
            value={m.showNoData}
            onChange={(showNoData) => map({ showNoData })}
          />
          {m.showNoData && (
            <Text
              label="No-data color"
              type="color"
              value={c.noData}
              onChange={(noData) => cb({ noData })}
            />
          )}
          {(["longitude", "latitude", "zoom", "bearing", "pitch"] as const).map(
            (key) => (
              <Numeric
                key={key}
                label={`Camera ${key}`}
                value={m[key]}
                min={
                  key === "longitude" || key === "bearing"
                    ? -180
                    : key === "latitude"
                      ? -85
                      : 0
                }
                max={
                  key === "longitude" || key === "bearing"
                    ? 180
                    : key === "latitude"
                      ? 85
                      : key === "zoom"
                        ? 10
                        : 60
                }
                step={key === "zoom" ? 0.1 : 1}
                onChange={(v) => v !== undefined && map({ [key]: v })}
              />
            ),
          )}
          <p className="hint">
            Polar views use an azimuthal equidistant display of geographic
            coordinates.
          </p>
        </details>
      )}
      {product.productId === "kp" && (
        <details open>
          <summary>Geomagnetic storm levels</summary>
          <p className="hint">G1–G5 are horizontal Kp reference lines.</p>
          {s.stormLines.map((line, index) => (
            <fieldset key={line.level}>
              <legend>
                {line.level} · Kp {line.value}
              </legend>
              <Check
                label={`Show ${line.level}`}
                value={line.visible}
                onChange={(visible) =>
                  update({
                    stormLines: s.stormLines.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, visible } : item,
                    ),
                  })
                }
              />
              <Text
                label={`${line.level} color`}
                type="color"
                value={line.color}
                onChange={(color) =>
                  update({
                    stormLines: s.stormLines.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, color } : item,
                    ),
                  })
                }
              />
              <Numeric
                label={`${line.level} width`}
                value={line.width}
                min={0.5}
                max={12}
                step={0.5}
                onChange={(width) =>
                  width !== undefined &&
                  update({
                    stormLines: s.stormLines.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, width } : item,
                    ),
                  })
                }
              />
              <Choice
                label={`${line.level} style`}
                value={line.dash}
                options={["solid", "dot", "dash", "dashdot"]}
                onChange={(dash) =>
                  update({
                    stormLines: s.stormLines.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, dash } : item,
                    ),
                  })
                }
              />
            </fieldset>
          ))}
        </details>
      )}
    </section>
  );
}
