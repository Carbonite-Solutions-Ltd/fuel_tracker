const registerServiceWorker = async () => {
  if ("serviceWorker" in navigator) {
    try {
      const registration = await navigator.serviceWorker.register("./service-worker.js", { scope: "/" });
      
      registration.addEventListener('updatefound', () => {
        const newWorker = registration.installing;
        console.log('Service worker update found!');

        newWorker.addEventListener('statechange', () => {
          switch(newWorker.state) {
            case 'installed':
              if (navigator.serviceWorker.controller) {
                console.log('New or updated content is available.');
              } else {
                console.log('Content is now available offline!');
              }
              break;
            case 'redundant':
              console.error('The installing service worker became redundant.');
              break;
            default:
              console.log(`Service worker state changed to: ${newWorker.state}`);
              break;
          }
        });
      });

      if (registration.installing) {
        console.log("Service worker installing");
      } else if (registration.waiting) {
        console.log("Service worker installed");
      } else if (registration.active) {
        console.log("Service worker active");
      }
    } catch (error) {
      console.error(`Service worker registration failed with ${error}`);
    }
  }
};

// Start the service worker registration process
registerServiceWorker();
