export function parseTagCountQuery(rawJson) {
  const parsed = JSON.parse(rawJson);
  return Object.fromEntries(
    Object.entries(parsed).map(([tag, count]) => [tag, Number(count)])
  );
}

export function parseCsvTags(rawTags) {
  return rawTags
    .split(",")
    .map(tag => tag.trim())
    .filter(Boolean);
}

export function parseUrlLines(rawUrls) {
  return rawUrls
    .split(/\n+/)
    .map(url => url.trim())
    .filter(Boolean);
}

export async function queryByTags(api, tags) {
  return api("/api/query/tags", {
    method: "POST",
    body: JSON.stringify({ tags }),
  });
}

export async function queryBySpecies(api, species) {
  return api("/api/query/species", {
    method: "POST",
    body: JSON.stringify({ species }),
  });
}

export async function queryByThumbnail(api, thumbnailUrl) {
  return api("/api/query/thumbnail", {
    method: "POST",
    body: JSON.stringify({ thumbnailUrl }),
  });
}

export async function bulkUpdateTags(api, payload) {
  return api("/api/tags/bulk", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

