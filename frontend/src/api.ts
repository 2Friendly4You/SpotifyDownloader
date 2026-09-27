export type ApiResult<T> = {
  ok: boolean;
  status: number;
  data: T;
};

export async function apiFetch<T = Record<string, unknown>>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResult<T>> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers,
  });

  let data: T;
  try {
    data = (await response.json()) as T;
  } catch {
    data = {} as T;
  }

  return { ok: response.ok, status: response.status, data };
}
