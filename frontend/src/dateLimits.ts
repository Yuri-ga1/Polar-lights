/** Date fields display UTC clock values without a zone suffix. */
export function utcToday(now = new Date()): string {
  return now.toISOString().slice(0, 10);
}

export function latestUtcDateTime(now = new Date()): string {
  return `${utcToday(now)}T23:59:59`;
}

export function isFutureUtcDate(value: string, now = new Date()): boolean {
  return /^\d{4}-\d{2}-\d{2}/.test(value) && value.slice(0, 10) > utcToday(now);
}
