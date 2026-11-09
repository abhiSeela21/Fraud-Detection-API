import type { Item, Transaction } from './api/client';

export const money = (value: string | number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));
export const eventTime = (value: string) =>
  new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  }).format(new Date(value));
export const title = (value: string) =>
  value.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
export function locationName(transaction: Transaction): string {
  const latitude = transaction.location.latitude;
  if (Math.abs(latitude - 41.8781) < 0.01) return 'Chicago, US';
  if (Math.abs(latitude - 40.7128) < 0.01) return 'New York, US';
  if (Math.abs(latitude - 51.5074) < 0.01) return 'London, GB';
  return `${transaction.location.country} · ${latitude.toFixed(2)}, ${transaction.location.longitude.toFixed(2)}`;
}
export function shortId(item: Item): string {
  return item.transaction.client_transaction_id.slice(0, 8).toUpperCase();
}
