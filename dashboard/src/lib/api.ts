/**
 * Returns the API base URL, auto-detected from the current hostname.
 * - Direct LAN access (192.168.1.x, localhost) → local API on :8000
 * - Any other host (CloudFlare tunnel, etc.) → https://api.indicagent.com
 *
 * NEXT_PUBLIC_API_BASE_URL overrides detection if set.
 */
export function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  if (typeof window === "undefined") return "http://localhost:8000";
  const hostname = window.location.hostname;
  if (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname.startsWith("192.168.")
  ) {
    return `http://${hostname}:8000`;
  }
  return "https://api.indicagent.com";
}
