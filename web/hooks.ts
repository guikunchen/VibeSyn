import { useCallback, useEffect, useState } from "react";

export function usePolling<T>(
  load: () => Promise<T>,
  intervalMs: number | null,
  dependencies: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setError("");
      setData(await load());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    } finally {
      setLoading(false);
    }
  }, dependencies);

  useEffect(() => {
    void refresh();
    if (!intervalMs) return;
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(timer);
  }, [refresh, intervalMs]);

  return { data, setData, error, setError, loading, refresh };
}
