export async function subscribeToTag(api, payload) {
  return api("/api/subscribe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listNotifications(api) {
  return api("/api/notifications");
}

export function formatNotification(notification) {
  return {
    tag: notification.tag,
    email: notification.email,
    fileUrl: notification.file_url || notification.fileUrl,
    createdAt: notification.created_at || notification.createdAt,
  };
}

