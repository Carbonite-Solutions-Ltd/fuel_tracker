import './index.css'
import Dexie from 'dexie';
import { createApp } from 'vue'
import router from './router'
import App from './App.vue'


import {
  Button,
  Card,
  Input,
  setConfig,
  frappeRequest,
  resourcesPlugin,
} from 'frappe-ui'

let app = createApp(App)

setConfig('resourceFetcher', frappeRequest)

app.use(router)
app.use(resourcesPlugin)

app.component('Button', Button)
app.component('Card', Card)
app.component('Input', Input)

app.mount('#app')


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/src/service-worker.js').then(registration => {
      console.log('SW registered: ', registration);
    }).catch(registrationError => {
      console.log('SW registration failed: ', registrationError);
    });
  });
}

// Assuming Dexie.js is included in your project
export const db = new Dexie('FuelTrackerDB');
db.version(1).stores({
  fuelUsed: '++id, date, fuel_tanker, site, reg_no, resource_type, make, type, resource'
});

export async function saveFuelUsedOffline(data) {
  db.fuelUsed.add(data).then(() => {
    console.log('Fuel used saved for syncing');
  });
}

// Call saveFuelUsedOffline() when the user submits the form but is offline.
window.addEventListener('online', () => {
  db.fuelUsed.each(fuelUsed => {
    // Implement logic to submit saved data to the server
    console.log(fuelUsed);
    // After successful submission, delete the record from IndexedDB
    db.fuelUsed.delete(fuelUsed.id);
  });
});
