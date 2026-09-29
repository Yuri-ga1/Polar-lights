import type { StyleSpec } from "../store";
import { styledScale } from "./colors";
export function Colorbar({
  style,
  range,
  units,
}: {
  style: StyleSpec;
  range: [number, number];
  units: string;
}) {
  const c = style.colorbar;
  if (!c.visible) return null;
  const vertical = c.orientation === "vertical";
  const stops = styledScale(style)
    .map(([at, color]) => `${color} ${at * 100}%`)
    .join(",");
  const ticks = c.ticks.length
    ? c.ticks
    : [range[0], (range[0] + range[1]) / 2, range[1]];
  return (
    <div
      className="colorbar"
      data-testid="colorbar"
      style={{
        left: `${c.x}%`,
        top: `${c.y}%`,
        fontFamily: c.font,
        fontSize: c.fontSize,
      }}
    >
      <div>
        {c.title}
        {(c.units || units) && ` (${c.units || units})`}
      </div>
      <div
        className="colorbar-scale"
        style={{
          position: "relative",
          marginBottom: vertical ? 4 : 22,
          marginRight: vertical ? 50 : 0,
          width: vertical ? c.thickness : c.length,
          height: vertical ? c.length : c.thickness,
          background: `linear-gradient(${vertical ? "to top" : "to right"},${stops})`,
        }}
      >
        {ticks
          .filter((t) => t >= range[0] && t <= range[1])
          .map((t) => (
            <span
              key={t}
              style={{
                position: "absolute",
                whiteSpace: "nowrap",
                ...(vertical
                  ? {
                      bottom: `${((t - range[0]) / (range[1] - range[0])) * 100}%`,
                      left: c.thickness + 4,
                      transform: "translateY(50%)",
                    }
                  : {
                      left: `${((t - range[0]) / (range[1] - range[0])) * 100}%`,
                      top: c.thickness + 3,
                      transform: "translateX(-50%)",
                    }),
              }}
            >
              {Number(t.toPrecision(4))}
            </span>
          ))}
      </div>
    </div>
  );
}
