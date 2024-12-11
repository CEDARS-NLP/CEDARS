const TRUSTED_ORIGINS = ["http://localhost:3000", "https://dev.app.superbio.ai"];

window.addEventListener("message", (event) => {
  if (!isTrustedOrigin(event.origin)) {
    console.log("Event received from invalid URL:", event.origin);
    return;
  }

  console.log("Trusted origin:", event.origin);
  // Process event data here
});
