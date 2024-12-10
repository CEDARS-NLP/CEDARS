const TRUSTED_ORIGINS = ["http://localhost:3000", "https://dev.app.superbio.ai", "https://msk-superbio.com"];

function isTrustedOrigin(origin) {
  // Allow all subdomains of msk-superbio.com and specific origins
  const regex = /^https:\/\/([a-zA-Z0-9.-]+)\.msk-superbio\.com$/;
  return TRUSTED_ORIGINS.includes(origin) || regex.test(origin);
}

window.addEventListener("message", (event) => {
  if (!isTrustedOrigin(event.origin)) {
    console.log("Event received from invalid URL:", event.origin);
    return;
  }

  console.log("Trusted origin:", event.origin);
  // Process event data here
});
