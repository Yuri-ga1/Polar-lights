export type ExportSize = {
  width: number;
  height: number;
  dpi: 150 | 300 | 600;
};
export const MAX_EXPORT_PIXELS = 32_000_000;

export function validateExportSize(size: ExportSize): string | undefined {
  if (
    !Number.isInteger(size.width) ||
    !Number.isInteger(size.height) ||
    size.width < 256 ||
    size.height < 256 ||
    size.width > 10000 ||
    size.height > 10000
  )
    return "Width and height must be whole numbers from 256 to 10,000 pixels.";
  if (![150, 300, 600].includes(size.dpi))
    return "Print DPI must be 150, 300, or 600.";
  if (size.width * size.height > MAX_EXPORT_PIXELS)
    return "Export exceeds 32 megapixels. Reduce dimensions or export individual charts.";
}
export function physicalSizeInches(size: ExportSize): [number, number] {
  return [size.width / size.dpi, size.height / size.dpi];
}

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** PNG pHYs stores integer pixels per metre, independently of pixel dimensions. */
export function withPngDpi(bytes: Uint8Array, dpi: number): Uint8Array {
  const ppm = Math.round(dpi / 0.0254);
  const chunk = new Uint8Array(21);
  const view = new DataView(chunk.buffer);
  view.setUint32(0, 9);
  chunk.set([112, 72, 89, 115], 4); // pHYs
  view.setUint32(8, ppm);
  view.setUint32(12, ppm);
  chunk[16] = 1;
  view.setUint32(17, crc32(chunk.subarray(4, 17)));
  // Insert after IHDR and discard an existing pHYs chunk to keep one density declaration.
  const pieces = [bytes.subarray(0, 33), chunk];
  let position = 33;
  while (position + 12 <= bytes.length) {
    const length = new DataView(
      bytes.buffer,
      bytes.byteOffset + position,
    ).getUint32(0);
    const end = position + 12 + length;
    if (end > bytes.length) break;
    const type = String.fromCharCode(
      ...bytes.subarray(position + 4, position + 8),
    );
    if (type !== "pHYs") pieces.push(bytes.subarray(position, end));
    position = end;
  }
  pieces.push(bytes.subarray(position));
  const result = new Uint8Array(
    pieces.reduce((total, piece) => total + piece.length, 0),
  );
  let offset = 0;
  for (const piece of pieces) {
    result.set(piece, offset);
    offset += piece.length;
  }
  return result;
}
