// Campaign Organizer processing endpoints return generated files as base64
// inside a normal JSON response (see the backend plan for why — this app has
// no existing binary/blob-response pattern, and reusing apiUpload's JSON
// assumption was preferred over introducing one for a stateless tool).
// This is the one bit of genuinely new plumbing: decode base64 -> Blob ->
// trigger a browser download via a synthetic anchor click.
export function downloadBase64File(base64, filename, mimeType = "application/zip") {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: mimeType }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
