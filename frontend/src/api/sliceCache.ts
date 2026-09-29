import { hashKey } from "@tanstack/react-query";
import type { DataSpec, MapResult } from "./contracts";
export class SliceCache {
  private entries = new Map<
    string,
    { value: MapResult; bytes: number; owners: Set<string>; used: number }
  >();
  constructor(
    readonly maxEntries = 8,
    readonly maxBytes = 64 * 1024 * 1024,
    readonly ttl = 60_000,
  ) {}
  get size() {
    return this.entries.size;
  }
  get bytes() {
    return [...this.entries.values()].reduce((n, e) => n + e.bytes, 0);
  }
  private prefix(product: string, p: DataSpec) {
    const { format: _format, ...data } = p;
    void _format;
    return hashKey([product, data]);
  }
  get(product: string, p: DataSpec, owner: string) {
    const prefix = this.prefix(product, p);
    for (const [key, e] of [...this.entries].reverse()) {
      if (!key.startsWith(prefix + "|")) continue;
      if (Date.now() - e.used > this.ttl) {
        this.entries.delete(key);
        continue;
      }
      e.owners.add(owner);
      this.entries.delete(key);
      this.entries.set(key, e);
      return e.value;
    }
  }
  set(product: string, p: DataSpec, value: MapResult, owner: string) {
    const prefix = this.prefix(product, p),
      key = prefix + "|" + (value.metadata.datasetVersion ?? "unversioned"),
      bytes = value.lat.length * 32;
    for (const k of this.entries.keys())
      if (k.startsWith(prefix + "|") && k !== key) this.entries.delete(k);
    const owners = this.entries.get(key)?.owners ?? new Set<string>();
    owners.add(owner);
    this.entries.delete(key);
    if (bytes > this.maxBytes) return;
    this.entries.set(key, { value, bytes, owners, used: Date.now() });
    while (this.size > this.maxEntries || this.bytes > this.maxBytes)
      this.entries.delete(this.entries.keys().next().value!);
  }
  release(owner: string) {
    for (const [key, e] of this.entries) {
      e.owners.delete(owner);
      if (!e.owners.size) this.entries.delete(key);
    }
  }
  clear() {
    this.entries.clear();
  }
}
export const sliceCache = new SliceCache();
