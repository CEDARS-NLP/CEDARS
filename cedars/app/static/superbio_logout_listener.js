window.addEventListener("message", (event) => {
    var origin = event.origin;

    if (!TRUSTED_ORIGINS.includes(origin)) {
        console.log("Event recived from invalid URL", origin, ". Halting event.");
        return ;
    }

    const data = JSON.parse(event.data);
    if (data.event_type === "auth") {
        // ignore event if auth, there is a seperate listener on the login page to handle auth calls.
        return ;
    }
    else if (data.event_type === "logout") {
        console.log("Logging out user.");
        window.location.href = "/auth/logout";
    }
    else {
        console.log("Unknown event_type received :", data.event_type);
    }
});