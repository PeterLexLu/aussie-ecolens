const authPanel = document.querySelector("#authPanel");
const appPanel = document.querySelector("#appPanel");
const userBadge = document.querySelector("#userBadge");
const logoutButton = document.querySelector("#logoutButton");
const workspaceUserEmail = document.querySelector("#workspaceUserEmail");
const workspaceUserMenu = document.querySelector("#workspaceUserMenu");
const accountMenu = document.querySelector("#accountMenu");
const switchAccountButton = document.querySelector("#switchAccountButton");
const accountLogoutButton = document.querySelector("#accountLogoutButton");
const message = document.querySelector("#message");
const gallery = document.querySelector("#gallery");
const detectedBox = document.querySelector("#detectedBox");
const notifications = document.querySelector("#notificationsLog");
const metricTotal = document.querySelector("#metricTotal");
const metricReady = document.querySelector("#metricReady");
const metricPending = document.querySelector("#metricPending");
const metricTags = document.querySelector("#metricTags");
const libraryScopeTabs = document.querySelectorAll("[data-library-scope]");
const refreshButton = document.querySelector("#refreshButton");
const resetResultsButton = document.querySelector("#resetResultsButton");
const DEFAULT_API_BASE_URL = "https://ieh6h79gr3.execute-api.us-east-1.amazonaws.com";
const PAGE_SEQUENCE = [
  "library",
  "upload",
  "query-counts",
  "query-species",
  "query-file",
  "query-thumbnail",
  "bulk-tags",
  "notifications",
];
const DEFAULT_COGNITO = {
  region: "us-east-1",
  userPoolId: "us-east-1_ahvGMB95O",
  appClientId: "2scr7btsqhli8d0hcchdltvnf5",
  domain: "us-east-1ahvgmb95o.auth.us-east-1.amazoncognito.com",
};
const COGNITO_LOGIN_SCOPE = "openid email";
const MEDIA_PAGE_LIMIT = 50;
let appConfig = null;
let bearerToken = sessionStorage.getItem("aussieEcoLensIdToken") || "";
let activeSectionId = "library";
let libraryScope = "mine";
let currentLibraryFiles = [];
let currentResultFiles = [];
let currentResultLabel = "No query has been run yet.";
const mediaObjectUrlCache = new Map();

function setMessage(text) {
  message.textContent = text || "";
}

function updateFilePickerName(input) {
  const target = document.querySelector(`[data-file-name-for="${input.id}"]`);
  if (!target) return;
  target.textContent = input.files?.[0]?.name || "No file selected";
}

function showSection(sectionId = "library") {
  const requestedId = sectionId.replace(/^#/, "") || "library";
  const targetId = PAGE_SEQUENCE.includes(requestedId) ? requestedId : "library";
  const previousIndex = PAGE_SEQUENCE.indexOf(activeSectionId);
  const targetIndex = PAGE_SEQUENCE.indexOf(targetId);
  const direction = targetIndex >= previousIndex ? "next" : "previous";
  document.querySelectorAll(".page-section").forEach(section => {
    section.classList.toggle("active", section.id === targetId);
    section.classList.remove("page-enter-next", "page-enter-previous");
    if (section.id === targetId) {
      section.classList.add(direction === "next" ? "page-enter-next" : "page-enter-previous");
      window.setTimeout(() => section.classList.remove("page-enter-next", "page-enter-previous"), 420);
    }
  });
  document.querySelectorAll(".nav-link").forEach(link => {
    link.classList.toggle("active", link.dataset.section === targetId);
  });
  activeSectionId = targetId;
  if (window.location.hash !== `#${targetId}`) {
    window.history.replaceState({}, document.title, `${window.location.pathname}#${targetId}`);
  }
}

function updateMetrics(files = []) {
  const ready = files.filter(file => file.status === "ready").length;
  const pending = files.filter(file => statusInfo(file).category === "processing").length;
  const tags = new Set();
  for (const file of files) {
    for (const tag of Object.keys(file.tags || {})) tags.add(tag);
  }
  if (metricTotal) metricTotal.textContent = String(files.length);
  if (metricReady) metricReady.textContent = String(ready);
  if (metricPending) metricPending.textContent = String(pending);
  if (metricTags) metricTags.textContent = String(tags.size);
}

function isOwnedFile(file) {
  return file.isOwner === true || file.canDelete === true || (file.isOwner === undefined && file.canDelete === undefined);
}

function filesForCurrentLibraryScope() {
  if (libraryScope === "results") return currentResultFiles;
  return filterFilesForCurrentScope(currentLibraryFiles);
}

function filterFilesForCurrentScope(files = []) {
  return files.filter(file => libraryScope === "mine" ? isOwnedFile(file) : !isOwnedFile(file));
}

function renderCurrentLibrary() {
  const scopedFiles = filesForCurrentLibraryScope();
  if (resetResultsButton) resetResultsButton.classList.toggle("hidden", libraryScope !== "results");
  renderFiles(scopedFiles, {
    emptyText: libraryScope === "results"
      ? currentResultLabel
      : libraryScope === "mine"
      ? "No media uploaded by your account yet."
      : "No shared media files available.",
  });
}

function setLibraryScope(scope) {
  libraryScope = ["mine", "shared", "results"].includes(scope) ? scope : "mine";
  libraryScopeTabs.forEach(tab => {
    tab.classList.toggle("active", tab.dataset.libraryScope === libraryScope);
  });
  if (libraryScope !== "results") {
    detectedBox.classList.add("hidden");
  }
  renderCurrentLibrary();
}

function setQueryResults(files, label = "No matching files found.") {
  currentResultFiles = Array.isArray(files) ? files : [];
  currentResultLabel = label;
  detectedBox.classList.add("hidden");
  showSection("library");
  setLibraryScope("results");
}

function resetQueryResults() {
  currentResultFiles = [];
  currentResultLabel = "No query has been run yet.";
  detectedBox.classList.add("hidden");
  setMessage("Query results reset.");
  setLibraryScope("mine");
}

async function refreshCurrentLibraryView() {
  await refreshFiles({ render: false });
  if (libraryScope === "results" && currentResultFiles.length) {
    const latestById = new Map(currentLibraryFiles.map(file => [fileIdentifier(file), file]));
    currentResultFiles = currentResultFiles.map(file => latestById.get(fileIdentifier(file)) || file);
  }
  renderCurrentLibrary();
}

function statusInfo(file) {
  const rawStatus = String(file.status || "processing").toLowerCase().replace(/_/g, "-");
  const updatedAt = Date.parse(file.updatedAt || file.createdAt || "");
  const delayed = Number.isFinite(updatedAt) && Date.now() - updatedAt > 10 * 60 * 1000;

  if (rawStatus === "ready") {
    return { label: "Ready", category: "ready", detail: "" };
  }
  if (["failed", "error"].includes(rawStatus)) {
    return { label: "Failed", category: "failed", detail: "Processing failed. Please upload again or ask the owner to retry." };
  }
  if (delayed) {
    return { label: "Processing delayed", category: "processing", detail: "Processing is taking longer than expected. Try again later or ask the owner to re-upload." };
  }
  if (["pending", "processing", "awaiting-gcp", "awaiting-gcp-result", "uploaded"].includes(rawStatus)) {
    return { label: "Processing", category: "processing", detail: "Generating thumbnail and wildlife tags." };
  }
  return { label: rawStatus || "Processing", category: "processing", detail: "Processing status is being updated." };
}

function showSignedOut() {
  document.body.classList.remove("signed-in");
  authPanel.classList.remove("hidden");
  appPanel.classList.add("hidden");
  logoutButton.classList.add("hidden");
  userBadge.textContent = "Not signed in";
  if (workspaceUserEmail) workspaceUserEmail.textContent = "Not signed in";
  closeAccountMenu();
}

function closeAccountMenu() {
  if (!accountMenu || !workspaceUserMenu) return;
  accountMenu.classList.add("hidden");
  workspaceUserMenu.setAttribute("aria-expanded", "false");
}

function toggleAccountMenu() {
  if (!accountMenu || !workspaceUserMenu) return;
  const isOpen = !accountMenu.classList.contains("hidden");
  accountMenu.classList.toggle("hidden", isOpen);
  workspaceUserMenu.setAttribute("aria-expanded", String(!isOpen));
}

function clearLocalAuth() {
  bearerToken = "";
  sessionStorage.removeItem("aussieEcoLensIdToken");
  clearMediaObjectUrlCache();
}

async function signOutCurrentUser() {
  clearLocalAuth();
  closeAccountMenu();
  if (!appConfig?.authMode || appConfig.authMode !== "cognito") {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
  }
  await refreshSession();
}

async function switchAccount() {
  clearLocalAuth();
  closeAccountMenu();
  if (!appConfig) await loadConfig();
  window.location.href = cognitoLoginUrl();
}

async function api(path, options = {}) {
  const headers = {
    ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(options.headers || {}),
  };
  if (bearerToken) headers.Authorization = `Bearer ${bearerToken}`;
  const url = apiUrl(path);
  const isCrossOrigin = new URL(url, window.location.href).origin !== window.location.origin;
  const response = await fetch(url, {
    ...options,
    credentials: bearerToken || isCrossOrigin ? "omit" : "include",
    headers,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(data.error || data.message || "Request failed");
  return data;
}

function apiBaseUrl() {
  return window.AUSSIE_ECOLENS_API_BASE_URL
    || localStorage.getItem("AUSSIE_ECOLENS_API_BASE_URL")
    || appConfig?.apiBaseUrl
    || DEFAULT_API_BASE_URL
    || "";
}

function apiUrl(path) {
  const baseUrl = apiBaseUrl().replace(/\/$/, "");
  return baseUrl && path.startsWith("/") ? `${baseUrl}${path}` : path;
}

function formJson(form) {
  return Object.fromEntries(new FormData(form).entries());
}

async function sha256File(file) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)]
    .map(byte => byte.toString(16).padStart(2, "0"))
    .join("");
}

function getFileType(file) {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  return "other";
}

function textElement(tagName, text, className) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text || "";
  return element;
}

function normaliseMediaUrl(url) {
  if (typeof url !== "string") return "";
  const trimmed = url.trim();
  if (!trimmed || trimmed === "#" || trimmed.startsWith("#")) return "";
  try {
    const parsed = new URL(trimmed, window.location.origin);
    if (["http:", "https:"].includes(parsed.protocol)) return trimmed;
  } catch (error) {
    return "";
  }
  return "";
}

function safeHref(url) {
  return normaliseMediaUrl(url) || "#";
}

function fileIdentifier(file) {
  return file?.id || file?.fileId || "";
}

function clearMediaObjectUrlCache() {
  for (const objectUrl of mediaObjectUrlCache.values()) {
    URL.revokeObjectURL(objectUrl);
  }
  mediaObjectUrlCache.clear();
}

async function fetchMediaObjectUrl(mediaUrl) {
  const safeUrl = normaliseMediaUrl(mediaUrl);
  if (!safeUrl) throw new Error("Media URL is not available.");
  if (mediaObjectUrlCache.has(safeUrl)) return mediaObjectUrlCache.get(safeUrl);
  const headers = bearerToken ? { Authorization: `Bearer ${bearerToken}` } : {};
  const response = await fetch(apiUrl(safeUrl), { credentials: "omit", headers });
  if (!response.ok) {
    throw new Error(response.status === 401 ? "Please sign in to view this media." : "Media could not be loaded.");
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  mediaObjectUrlCache.set(safeUrl, objectUrl);
  return objectUrl;
}

function loadProtectedImage(image, mediaUrl) {
  fetchMediaObjectUrl(mediaUrl)
    .then(objectUrl => {
      image.src = objectUrl;
    })
    .catch(error => {
      image.replaceWith(textElement("span", error.message, "media-error"));
    });
}

async function openProtectedMedia(mediaUrl) {
  const popup = window.open("about:blank", "_blank");
  const objectUrl = await fetchMediaObjectUrl(mediaUrl);
  if (popup) {
    popup.opener = null;
    popup.location.href = objectUrl;
  } else {
    window.location.href = objectUrl;
  }
}

async function uploadWithPresignedUrl(file, checksum) {
  const initResponse = await api("/api/uploads/init", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      contentType: file.type || "application/octet-stream",
      fileType: getFileType(file),
      checksum,
    }),
  });

  if (initResponse.duplicate) return initResponse;

  const upload = initResponse.upload || {};
  const uploadResponse = await fetch(upload.url, {
    method: upload.method || "PUT",
    headers: upload.headers || { "content-type": file.type || "application/octet-stream" },
    body: file,
  }).catch(error => {
    throw new Error(`Presigned S3 upload failed before reaching storage. Check S3 bucket CORS for browser PUT requests. ${error.message}`);
  });
  if (!uploadResponse.ok) throw new Error("Presigned upload failed");

  return {
    duplicate: false,
    file: initResponse.file,
  };
}

async function uploadForCurrentEnvironment(file, checksum) {
  try {
    return await uploadWithPresignedUrl(file, checksum);
  } catch (error) {
    if (!String(error.message).includes("Not found")) throw error;
    const fallback = new FormData();
    fallback.append("file", file);
    return api("/api/upload", { method: "POST", body: fallback });
  }
}

async function refreshSession() {
  if (appConfig?.authMode === "cognito" && !bearerToken) {
    showSignedOut();
    return;
  }
  let data;
  try {
    data = await api("/api/me");
  } catch (error) {
    showSignedOut();
    if (appConfig?.authMode === "cognito") return;
    throw error;
  }
  authPanel.classList.toggle("hidden", data.authenticated);
  appPanel.classList.toggle("hidden", !data.authenticated);
  logoutButton.classList.toggle("hidden", !data.authenticated);
  userBadge.textContent = data.authenticated
    ? data.user.email || "Signed in"
    : "Not signed in";
  if (workspaceUserEmail) {
    workspaceUserEmail.textContent = data.authenticated
      ? data.user.email || "Signed in with Cognito"
      : "Not signed in";
  }
  document.body.classList.toggle("signed-in", data.authenticated);
  if (data.authenticated) {
    showSection(window.location.hash.slice(1) || "library");
    await refreshFiles();
    await refreshNotifications();
  }
}

async function loadConfig() {
  const data = await api("/api/config");
  appConfig = {
    authMode: data.authMode || "cognito",
    apiBaseUrl: data.apiBaseUrl || DEFAULT_API_BASE_URL,
    cognito: {
      ...DEFAULT_COGNITO,
      ...(data.cognito || {}),
    },
  };
}

function currentRedirectUri() {
  return window.location.origin + window.location.pathname;
}

function cognitoUrl(path, query) {
  const cognito = appConfig?.cognito || DEFAULT_COGNITO;
  return `https://${cognito.domain}${path}?${new URLSearchParams(query)}`;
}

function cognitoLoginUrl() {
  const cognito = appConfig?.cognito || DEFAULT_COGNITO;
  const redirectUri = cognito.redirectUri || currentRedirectUri();
  if (cognito.loginUrl) {
    const configured = new URL(cognito.loginUrl);
    configured.searchParams.set("redirect_uri", redirectUri);
    configured.searchParams.set("scope", COGNITO_LOGIN_SCOPE);
    return configured.toString();
  }
  return cognitoUrl("/login", {
    client_id: cognito.appClientId,
    response_type: "code",
    scope: COGNITO_LOGIN_SCOPE,
    redirect_uri: redirectUri,
  });
}

async function handleCognitoCallback() {
  const hash = new URLSearchParams(window.location.hash.slice(1));
  if (hash.get("id_token")) {
    bearerToken = hash.get("id_token");
    sessionStorage.setItem("aussieEcoLensIdToken", bearerToken);
    window.history.replaceState({}, document.title, window.location.pathname);
    setMessage("Signed in with Cognito.");
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  if (!code) return;
  setMessage("Completing Cognito sign-in...");
  try {
    const cognito = appConfig?.cognito || {};
    const tokenResponse = await fetch(cognito.tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: cognito.appClientId,
        code,
        redirect_uri: cognito.redirectUri || currentRedirectUri(),
      }),
    });
    const tokens = await tokenResponse.json();
    if (!tokenResponse.ok || !tokens.id_token) throw new Error(tokens.error_description || "Cognito token exchange failed");
    bearerToken = tokens.id_token;
    sessionStorage.setItem("aussieEcoLensIdToken", bearerToken);
    window.history.replaceState({}, document.title, window.location.pathname);
    setMessage("Signed in with Cognito.");
  } catch (error) {
    setMessage(error.message);
  }
}

function renderFiles(files, options = {}) {
  gallery.replaceChildren();
  updateMetrics(files);
  if (!files.length) {
    gallery.appendChild(textElement("p", options.emptyText || "No matching files yet.", "empty-state"));
    return;
  }
  for (const file of files) {
    const card = document.createElement("article");
    card.className = "card";
    const status = statusInfo(file);
    const originalUrl = normaliseMediaUrl(file.originalUrl);
    const thumbnailUrl = normaliseMediaUrl(file.thumbnailUrl);

    const preview = document.createElement("a");
    preview.className = "thumb";
    preview.href = "#";
    preview.dataset.openMedia = originalUrl;
    if (thumbnailUrl) {
      const image = document.createElement("img");
      image.loading = "lazy";
      image.alt = "";
      preview.appendChild(image);
      loadProtectedImage(image, thumbnailUrl);
    } else {
      preview.textContent = String(file.fileType || "file").toUpperCase();
    }

    const cardBody = document.createElement("div");
    cardBody.className = "card-body";
    cardBody.appendChild(textElement("div", file.originalName || "Unnamed file", "file-name"));
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.appendChild(textElement("span", isOwnedFile(file) ? "Mine" : "Shared", isOwnedFile(file) ? "owner-chip owner-chip-mine" : "owner-chip owner-chip-shared"));
    meta.appendChild(textElement("span", status.label, `status status-${status.category}`));
    cardBody.appendChild(meta);
    if (status.detail) {
      cardBody.appendChild(textElement("p", status.detail, "status-detail"));
    }

    const tags = document.createElement("div");
    tags.className = "tags";
    for (const [tag, count] of Object.entries(file.tags || {})) {
      tags.appendChild(textElement("span", `${tag}: ${count}`, "tag"));
    }
    cardBody.appendChild(tags);

    const actions = document.createElement("div");
    actions.className = "card-actions";

    const openLink = document.createElement("a");
    openLink.href = "#";
    openLink.dataset.openMedia = originalUrl;
    openLink.textContent = "Open";
    actions.appendChild(openLink);

    const useUrlButton = document.createElement("button");
    useUrlButton.type = "button";
    useUrlButton.dataset.useUrl = originalUrl;
    useUrlButton.disabled = !originalUrl;
    useUrlButton.textContent = "Use URL";
    actions.appendChild(useUrlButton);

    const useThumbnailButton = document.createElement("button");
    useThumbnailButton.type = "button";
    useThumbnailButton.dataset.useThumbnailUrl = thumbnailUrl;
    useThumbnailButton.disabled = !thumbnailUrl;
    useThumbnailButton.textContent = "Use Thumbnail";
    actions.appendChild(useThumbnailButton);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger";
    deleteButton.dataset.delete = originalUrl;
    deleteButton.disabled = !originalUrl || file.canDelete === false;
    deleteButton.title = file.canDelete === false ? "Only the owner can delete this file" : "Delete file";
    deleteButton.textContent = "Delete";
    actions.appendChild(deleteButton);

    cardBody.appendChild(actions);
    card.append(preview, cardBody);
    gallery.appendChild(card);
  }
}

async function refreshFiles(options = {}) {
  const data = await api(`/api/files?limit=${MEDIA_PAGE_LIMIT}`);
  currentLibraryFiles = data.files || [];
  if (options.render !== false) renderCurrentLibrary();
}

async function getFileStatus(fileId) {
  return api(`/api/files/${fileId}`);
}

async function refreshFilesAndFind(fileId) {
  const data = await api(`/api/files?limit=${MEDIA_PAGE_LIMIT}`);
  currentLibraryFiles = data.files || [];
  const file = currentLibraryFiles.find(item => fileIdentifier(item) === fileId);
  renderCurrentLibrary();
  return file;
}

function upsertLibraryFile(file) {
  if (!file || !fileIdentifier(file)) return;
  const id = fileIdentifier(file);
  const index = currentLibraryFiles.findIndex(item => fileIdentifier(item) === id);
  if (index >= 0) {
    currentLibraryFiles[index] = file;
  } else {
    currentLibraryFiles = [file, ...currentLibraryFiles];
  }
  if (libraryScope === "results") {
    const resultIndex = currentResultFiles.findIndex(item => fileIdentifier(item) === id);
    if (resultIndex >= 0) currentResultFiles[resultIndex] = file;
  }
  renderCurrentLibrary();
}

function uploadPollDelay(attempt) {
  if (attempt < 5) return 1000;
  if (attempt < 15) return 2000;
  return 5000;
}

async function pollFileUntilReady(fileId, attempts = 30) {
  if (!fileId) {
    await refreshFiles();
    return;
  }

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const data = await getFileStatus(fileId);
      const file = data.file || data;
      upsertLibraryFile(file);
      if (["ready", "failed"].includes(file.status)) {
        await refreshFiles();
        return;
      }
      setMessage(`Uploaded. Processing ${attempt + 1}/${attempts}; status: ${file.status || "pending"}.`);
    } catch (error) {
      const file = await refreshFilesAndFind(fileId);
      if (!file || ["ready", "failed"].includes(file.status)) return;
    }
    await new Promise(resolve => setTimeout(resolve, uploadPollDelay(attempt)));
  }
  await refreshFiles();
}

async function refreshNotifications() {
  const data = await api("/api/notifications");
  notifications.replaceChildren();
  if (!data.notifications.length) {
    notifications.appendChild(textElement("p", "No notifications yet."));
    return;
  }

  for (const notification of data.notifications) {
    const note = document.createElement("div");
    note.className = "note";

    const summary = document.createElement("div");
    const tag = document.createElement("b");
    tag.textContent = notification.tag || "tag";
    summary.append(tag, document.createTextNode(" matched a new file"));

    const createdAt = notification.createdAt || notification.created_at;
    const timestamp = createdAt ? new Date(createdAt).toLocaleString() : new Date().toLocaleString();
    const meta = textElement("div", `${notification.email || "subscriber"} · ${timestamp}`, "note-meta");

    const link = document.createElement("a");
    const notificationUrl = normaliseMediaUrl(notification.fileUrl || notification.file_url);
    link.href = "#";
    link.dataset.openMedia = notificationUrl;
    link.textContent = notificationUrl ? "Open file" : "File unavailable";
    if (!notificationUrl) link.setAttribute("aria-disabled", "true");

    note.append(summary, meta, link);
    notifications.appendChild(note);
  }
}

const signupForm = document.querySelector("#signupForm");
if (signupForm) {
  signupForm.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api("/api/auth/signup", { method: "POST", body: JSON.stringify(formJson(event.currentTarget)) });
      setMessage("Account created. Please sign in.");
      event.currentTarget.reset();
    } catch (error) {
      setMessage(error.message);
    }
  });
}

const loginForm = document.querySelector("#loginForm");
if (loginForm) {
  loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify(formJson(event.currentTarget)) });
      setMessage("Signed in.");
      await refreshSession();
    } catch (error) {
      setMessage(error.message);
    }
  });
}

document.querySelector("#cognitoLoginButton").addEventListener("click", async () => {
  if (!appConfig) await loadConfig();
  if (!appConfig?.cognito?.domain || !appConfig?.cognito?.appClientId) {
    setMessage("Cognito Hosted UI is not configured.");
    return;
  }
  window.location.href = cognitoLoginUrl();
});

logoutButton.addEventListener("click", async () => {
  await signOutCurrentUser();
});

if (workspaceUserMenu) {
  workspaceUserMenu.addEventListener("click", toggleAccountMenu);
}

if (accountLogoutButton) {
  accountLogoutButton.addEventListener("click", signOutCurrentUser);
}

if (switchAccountButton) {
  switchAccountButton.addEventListener("click", switchAccount);
}

document.addEventListener("click", event => {
  if (!accountMenu || !workspaceUserMenu) return;
  if (accountMenu.contains(event.target) || workspaceUserMenu.contains(event.target)) return;
  closeAccountMenu();
});

document.querySelectorAll(".native-file-input").forEach(input => {
  input.addEventListener("change", () => updateFilePickerName(input));
  updateFilePickerName(input);
});

libraryScopeTabs.forEach(tab => {
  tab.addEventListener("click", () => setLibraryScope(tab.dataset.libraryScope));
});

document.querySelector("#uploadForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const file = new FormData(form).get("file");
    const checksum = await sha256File(file);
    setMessage(`Checksum ready: ${checksum.slice(0, 12)}... Uploading.`);
    const data = await uploadForCurrentEnvironment(file, checksum);
    setMessage(data.duplicate ? "Duplicate detected; showing existing media record." : "Uploaded. Processing will generate thumbnails and tags.");
    form.reset();
    document.querySelectorAll(".native-file-input").forEach(updateFilePickerName);
    showSection("library");
    if (data.duplicate) {
      await refreshFiles();
    } else {
      upsertLibraryFile(data.file);
      await pollFileUntilReady(fileIdentifier(data.file));
    }
    await refreshNotifications();
  } catch (error) {
    setMessage(error.message);
  }
});

document.querySelector("#tagQueryForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const tags = JSON.parse(new FormData(event.currentTarget).get("tags"));
    const data = await api("/api/query/tags", { method: "POST", body: JSON.stringify({ tags, limit: MEDIA_PAGE_LIMIT }) });
    const results = data.results || data.files || [];
    setMessage(`Found ${results.length} result(s).`);
    setQueryResults(results, "No files match these tag counts.");
  } catch (error) {
    setMessage(error.message);
  }
});

document.querySelector("#speciesQueryForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const species = new FormData(event.currentTarget).get("species");
    const data = await api("/api/query/species", { method: "POST", body: JSON.stringify({ species, limit: MEDIA_PAGE_LIMIT }) });
    const results = data.results || data.files || [];
    setMessage(`Found ${results.length} result(s).`);
    setQueryResults(results, "No files match this species tag.");
  } catch (error) {
    setMessage(error.message);
  }
});

document.querySelector("#fileQueryForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    setMessage("Analyzing query file in the cloud model. This can take around 20-30 seconds.");
    detectedBox.classList.add("hidden");
    const data = await api("/api/query/by-file", { method: "POST", body: new FormData(form) });
    form.reset();
    document.querySelectorAll(".native-file-input").forEach(updateFilePickerName);
    setMessage(`Found ${(data.results || data.files || []).length} result(s).`);
    setQueryResults(data.results || data.files || [], "No files match the detected tags.");
    detectedBox.classList.remove("hidden");
    detectedBox.textContent = `Detected tags: ${JSON.stringify(data.detectedTags)}`;
  } catch (error) {
    setMessage(error.message.includes("Failed to fetch") ? "Query by file could not finish. Please retry with a smaller image." : error.message);
  }
});

document.querySelector("#thumbnailQueryForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const thumbnailUrl = new FormData(event.currentTarget).get("thumbnailUrl");
    const data = await api("/api/query/thumbnail", { method: "POST", body: JSON.stringify({ thumbnailUrl }) });
    const results = data.file ? [data.file] : data.files || data.results || [];
    setMessage(results.length ? "Original file found." : "No original file found.");
    setQueryResults(results, "No original file matches this thumbnail URL.");
  } catch (error) {
    setMessage(error.message);
  }
});

document.querySelector("#bulkTagForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const form = new FormData(event.currentTarget);
    const payload = {
      urls: form.get("urls").split(/\n+/).map(v => v.trim()).filter(Boolean),
      tags: form.get("tags").split(",").map(v => v.trim()).filter(Boolean),
      operation: Number(form.get("operation")),
    };
    const data = await api("/api/tags/bulk", { method: "POST", body: JSON.stringify(payload) });
    setMessage(`${data.changes} tag change(s) applied.`);
    await refreshFiles();
  } catch (error) {
    setMessage(error.message);
  }
});

document.querySelector("#subscribeForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const payload = formJson(form);
    const data = await api("/api/subscribe", { method: "POST", body: JSON.stringify(payload) });
    setMessage(data.snsStatus === "pending-confirmation" ? "Subscription saved. Confirm the AWS SNS email before alerts are delivered." : "Subscription saved.");
    form.reset();
    await refreshNotifications();
  } catch (error) {
    setMessage(error.message);
  }
});

refreshButton.addEventListener("click", refreshCurrentLibraryView);
resetResultsButton.addEventListener("click", resetQueryResults);

gallery.addEventListener("click", async event => {
  const openMediaLink = event.target.closest("[data-open-media]");
  if (openMediaLink) {
    event.preventDefault();
    try {
      await openProtectedMedia(openMediaLink.dataset.openMedia);
    } catch (error) {
      setMessage(error.message);
    }
    return;
  }

  const useUrlButton = event.target.closest("[data-use-url]");
  if (useUrlButton) {
    const urlsField = document.querySelector("#bulkUrls");
    const existing = urlsField.value.trim();
    urlsField.value = existing ? `${existing}\n${useUrlButton.dataset.useUrl}` : useUrlButton.dataset.useUrl;
    setMessage("URL added to bulk tag form.");
    showSection("bulk-tags");
    return;
  }

  const useThumbnailButton = event.target.closest("[data-use-thumbnail-url]");
  if (useThumbnailButton) {
    const thumbnailField = document.querySelector("#thumbnailUrl");
    thumbnailField.value = useThumbnailButton.dataset.useThumbnailUrl;
    setMessage("Thumbnail URL added to query form.");
    showSection("query-thumbnail");
    return;
  }

  const deleteButton = event.target.closest("[data-delete]");
  if (!deleteButton) return;
  await api("/api/files/delete", { method: "POST", body: JSON.stringify({ urls: [deleteButton.dataset.delete] }) });
  setMessage("File deleted from storage and database.");
  await refreshFiles();
});

loadConfig()
  .then(handleCognitoCallback)
  .then(refreshSession)
  .catch(error => setMessage(error.message));

document.querySelectorAll(".nav-link").forEach(link => {
  link.addEventListener("click", event => {
    event.preventDefault();
    showSection(link.dataset.section || "library");
  });
});
