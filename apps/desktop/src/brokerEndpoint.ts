import { useSyncExternalStore } from "react";

export const DEFAULT_BROKER_ENDPOINT = "http://192.168.1.52:8765";
const preferenceKey = "local-ai-lab.broker-endpoint.v1";
const changedEvent = "local-ai-lab:broker-endpoint-changed";
let unsavedEndpoint: string | undefined;

export function getBrokerEndpoint(): string {
  if (unsavedEndpoint !== undefined) return unsavedEndpoint;
  if (typeof window === "undefined") return DEFAULT_BROKER_ENDPOINT;
  try {
    return window.localStorage.getItem(preferenceKey) ?? DEFAULT_BROKER_ENDPOINT;
  } catch {
    return DEFAULT_BROKER_ENDPOINT;
  }
}

export function setBrokerEndpoint(endpoint: string): void {
  unsavedEndpoint = endpoint;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(preferenceKey, endpoint);
    unsavedEndpoint = undefined;
  } catch {
    // Keep the edited address available for this session if storage is blocked.
  }
  window.dispatchEvent(new Event(changedEvent));
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === preferenceKey || event.key === null) {
      unsavedEndpoint = undefined;
      onChange();
    }
  };
  window.addEventListener(changedEvent, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(changedEvent, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useBrokerEndpoint(): [string, (endpoint: string) => void] {
  return [useSyncExternalStore(subscribe, getBrokerEndpoint, getBrokerEndpoint), setBrokerEndpoint];
}
