export async function getFileStatus(api, fileId) {
  return api(`/api/files/${fileId}`);
}

export function inferStatus(file) {
  if (file.status) return file.status;
  if (file.thumbnailUrl || Object.keys(file.tags || {}).length) return "ready";
  return "processing";
}

export function isTerminalStatus(status) {
  return status === "ready" || status === "failed";
}

