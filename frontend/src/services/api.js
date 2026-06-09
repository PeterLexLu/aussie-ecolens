const defaultOptions = {
  credentials: "include",
};

export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...defaultOptions,
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

