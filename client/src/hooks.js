import { useCallback, useEffect, useState } from 'react';

/** Runs an async loader, exposing its data, error and a refresh handle. */
export function useAsync(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: '', loading: true });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: '' }));
    try {
      const data = await loader();
      setState({ data, error: '', loading: false });
    } catch (err) {
      setState({ data: null, error: err.message, loading: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run };
}
