window.addEventListener("message", (event) => {
    var origin = event.origin;
  
    if (!TRUSTED_ORIGINS.includes(origin)) {
      console.log("Event recived from invalid URL", origin, ". Halting event.");
      return ;
    }
  
  
    const data = JSON.parse(event.data);
    console.log("Received token:", data.access_token);
    console.log("Event type :", data.event_type);
  
    if (data.event_type === "auth") {
        // Send the token to the backend
        fetch('/auth/token-login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ token: data.access_token , user_id: data.id }),
        })
        .then(response => response.json())
        .then(data => {
          if (data.message) {
            console.log('Login successful:', data.message);
            
            // Send a login confirmation message to superbio server
            window.parent.postMessage({type: 'auth', data: 'successful'}, '*');

            window.location.href = '/stats';
          } else {
            console.error('Login failed:', data.error);
            // Handle login failure (e.g., show an error message)
          }
        })
        .catch((error) => {
          console.error('Error:', error);
        });
    }
    else if (data.event_type === "logout") {
        console.log("Logging out user.");
        window.location.href = "/auth/logout";
    }
    else {
        console.log("Unknown event_type received :", data.event_type);
    }
    
  });