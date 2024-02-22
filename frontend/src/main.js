import './index.css'

import { createApp } from 'vue'
import router from './router'
import App from './App.vue'

// Import Ionic Vue and CSS
import { IonicVue } from '@ionic/vue';
import '@ionic/vue/css/core.css';
import '@ionic/vue/css/normalize.css';
import '@ionic/vue/css/structure.css';
import '@ionic/vue/css/typography.css';
// Optional: Import Ionicons if you plan to use them
import '@ionic/vue/css/padding.css';
import '@ionic/vue/css/float-elements.css';
import '@ionic/vue/css/text-alignment.css';
import '@ionic/vue/css/text-transformation.css';
import '@ionic/vue/css/flex-utils.css';
import '@ionic/vue/css/display.css';

// Import Frappe UI components
import {
  Button,
  Card,
  Input,
  setConfig,
  frappeRequest,
  resourcesPlugin,
  FeatherIcon,
} from 'frappe-ui'

import './registerServiceWorker'

let app = createApp(App)

// Set Frappe UI configuration
setConfig('resourceFetcher', frappeRequest)

// Use IonicVue
app.use(IonicVue);

// Use Vue router
app.use(router)

// Use Frappe UI plugin
app.use(resourcesPlugin)

// Register Frappe UI components
app.component('Button', Button)
app.component('Card', Card)
app.component('Input', Input)
app.component('FeatherIcon', FeatherIcon)

// Mount the Vue app
app.mount('#app')
