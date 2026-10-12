/* Shared offline renderer for server PNGs and browser previews. Plate carrée
   preserves the full [-180,180] × [-90,90] extent, including both poles. */
window.drawWorld = function (
  canvas,
  { spec, points, land, title, units = "" },
) {
  canvas.width = spec.width;
  canvas.height = spec.height;
  const ctx = canvas.getContext("2d"),
    a = spec.appearance,
    c = a.colorbar;
  const w = canvas.width,
    h = canvas.height;
  const left = a.axes ? 48 : 8,
    right = 18,
    top = a.subtitle ? 65 : 43,
    bottom = a.axes ? 35 : 18;
  const pw = w - left - right,
    ph = h - top - bottom;
  const x = (lon) => left + ((lon + 180) / 360) * pw;
  const y = (lat) => top + ((90 - lat) / 180) * ph;
  let low = spec.minimum,
    high = spec.maximum;
  const finite = points.filter((p) => p[2] != null && Number.isFinite(p[2]));
  if (a.autoRange && finite.length) {
    low = Infinity;
    high = -Infinity;
    for (const p of finite) {
      low = Math.min(low, p[2]);
      high = Math.max(high, p[2]);
    }
    if (high === low) high = low + 1;
  }
  const colors = a.colors.map(([t, rgb]) => [t, rgb.match(/\d+/g).map(Number)]);
  function color(t) {
    t = Math.max(0, Math.min(1, t));
    let i = 0;
    while (i + 1 < colors.length && colors[i + 1][0] <= t) i++;
    const [at, ca] = colors[i],
      [bt, cb] = colors[Math.min(i + 1, colors.length - 1)];
    const f = (t - at) / (bt - at || 1);
    return `rgb(${ca.map((v, j) => Math.round(v + (cb[j] - v) * f)).join(",")})`;
  }
  ctx.fillStyle = a.background;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#42556a";
  ctx.font = `${a.fontSize}px ${a.font}`;
  ctx.textAlign = "center";
  ctx.fillText(title, w / 2, 23, w - 20);
  if (a.subtitle) ctx.fillText(a.subtitle, w / 2, 45, w - 20);
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, pw, ph);
  ctx.clip();
  function continents(fill) {
    for (const feature of land.features) {
      const g = feature.geometry;
      const polygons = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
      for (const polygon of polygons) {
        ctx.beginPath();
        for (const ring of polygon) {
          ring.forEach(([lon, lat], i) =>
            i ? ctx.lineTo(x(lon), y(lat)) : ctx.moveTo(x(lon), y(lat)),
          );
          ctx.closePath();
        }
        if (fill) {
          ctx.fillStyle = "#d5e0e6";
          ctx.fill("evenodd");
        } else {
          ctx.strokeStyle = "#829ba9";
          ctx.lineWidth = 0.7;
          ctx.stroke();
        }
      }
    }
  }
  if (a.coastline) continents(true);
  if (a.graticule) {
    ctx.strokeStyle = "#91a5b0";
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    for (let lon = -180; lon <= 180; lon += 30) {
      ctx.moveTo(x(lon), y(-90));
      ctx.lineTo(x(lon), y(90));
    }
    for (let lat = -90; lat <= 90; lat += 30) {
      ctx.moveTo(x(-180), y(lat));
      ctx.lineTo(x(180), y(lat));
    }
    ctx.stroke();
  }
  ctx.globalAlpha = a.opacity;
  const ordered = points
    .filter((p) => a.showNoData || p[2] != null)
    .sort((p, q) => (p[2] ?? -Infinity) - (q[2] ?? -Infinity));
  for (const [lon, lat, value] of ordered) {
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || lat < -90 || lat > 90)
      continue;
    const longitude =
      lon >= -180 && lon <= 180
        ? lon
        : ((((lon + 180) % 360) + 360) % 360) - 180;
    ctx.fillStyle =
      value == null ? a.noData : color((value - low) / (high - low));
    ctx.beginPath();
    ctx.arc(x(longitude), y(lat), a.pointSize, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  if (a.coastline) continents(false);
  ctx.restore();
  ctx.fillStyle = "#42556a";
  ctx.strokeStyle = "#829ba9";
  ctx.font = `${a.labelSize}px ${a.font}`;
  if (a.axes) {
    ctx.strokeRect(left, top, pw, ph);
    for (let lon = -180; lon <= 180; lon += 60) {
      ctx.textAlign = "center";
      ctx.fillText(`${lon}°`, x(lon), h - 12);
    }
    for (let lat = -90; lat <= 90; lat += 30) {
      ctx.textAlign = "right";
      ctx.fillText(`${lat}°`, left - 5, y(lat) + 4);
    }
  }
  if (a.labels) {
    ctx.textAlign = "right";
    ctx.font = "9px system-ui";
    ctx.fillText("Natural Earth · Geographic", w - right - 4, top + ph - 5);
  }
  if (c.visible) {
    const vertical = c.orientation === "vertical";
    const len = Math.min(c.length, vertical ? ph - 40 : pw - 50),
      thick = c.thickness;
    const bx = Math.min(
      left + (pw * c.x) / 100,
      w - right - (vertical ? thick + 50 : len),
    );
    const by = Math.min(
      top + (ph * c.y) / 100 + c.fontSize + 5,
      h - bottom - (vertical ? len + 8 : thick + 25),
    );
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.fillRect(
      bx - 8,
      by - c.fontSize - 8,
      vertical ? thick + 58 : len + 16,
      (vertical ? len : thick + 22) + c.fontSize + 16,
    );
    const n = Math.ceil(len);
    for (let i = 0; i < n; i++) {
      ctx.fillStyle = color(i / (n - 1));
      if (vertical)
        ctx.fillRect(bx, by + len - ((i + 1) * len) / n, thick, len / n + 0.5);
      else ctx.fillRect(bx + (i * len) / n, by, len / n + 0.5, thick);
    }
    ctx.fillStyle = "#42556a";
    ctx.font = `${c.fontSize}px ${c.font}`;
    ctx.textAlign = "left";
    ctx.fillText(
      `${c.title}${c.units || units ? ` (${c.units || units})` : ""}`,
      bx,
      by - 5,
    );
    const ticks = c.ticks.length ? c.ticks : [low, (low + high) / 2, high];
    for (const tick of ticks.filter((v) => v >= low && v <= high)) {
      const t = (tick - low) / (high - low);
      ctx.textAlign = vertical ? "left" : "center";
      ctx.fillText(
        String(Number(tick.toPrecision(4))),
        vertical ? bx + thick + 4 : bx + t * len,
        vertical ? by + (1 - t) * len + 4 : by + thick + c.fontSize + 3,
      );
    }
  }
};
