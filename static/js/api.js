async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function formatDate(timestamp) {
  const date = new Date(timestamp * 1000);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function withVersion(url, mtime) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${mtime}`;
}
