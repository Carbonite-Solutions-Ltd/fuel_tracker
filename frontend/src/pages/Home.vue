<template>
    <ion-page>
    <ion-header>
      <ion-toolbar>
        <ion-title>Fuel Tracker</ion-title>
      </ion-toolbar>
    </ion-header>
  </ion-page>

  <div class="flex flex-row items-center justify-between mt-2 mr-2 ml-2">
    <h1 class="text-5xl font-black text-gray-900">Fuel Tracker</h1>
    <Button @click="issueFuelDialogShown = true" icon-left="plus">Issue Fuel</Button>
</div>

 <card title="Fuel Used List" class="mt-10 mr-2 ml-2">
  <div >
  <ul>
    <li v-for="action in actions.data" :key="action.resource">
    <span>{{ action.resource }} - {{ action.fuel_issued_lts }}</span>
    </li>
  </ul>
</div>
 </card>

<Dialog :options="{
  title: 'Issue Fuel',
  actions: [
    {
      label: 'Issue Fuel',
      appearance: 'primary',
      handler:({ close }) => {
        issueFuel()
        close() // closing dialog
      },
    },
    {label: 'Cancel' },
  ],              
}" v-model="issueFuelDialogShown">
<template #body-content>
  <div>
    <Autocomplete :options="ListOfSite" Variant title="Single option" placeholder= "Select Site" />
    <Autocomplete Variant title="Single option" placeholder= "Select Fuel Tanker"/>
    <Autocomplete Variant title="Single option" placeholder= "Select Resource" />
    <Input type="text" placeholder= "Enter Odometer" required/>
    <Input type="text" placeholder= "Enter Fuel Issued(LTS)" required/>
  </div>
</template>
</Dialog>


</template>

<script setup>

import { reactive } from 'vue'
import { ref, computed } from 'vue'
import { Button, Dialog, Input, Autocomplete } from 'frappe-ui'
import { createResource } from 'frappe-ui'
import { createListResource } from 'frappe-ui'
import { session } from '../data/session'
import { Checkbox } from 'frappe-ui'
import { Select } from 'frappe-ui'
import { Card } from 'frappe-ui'
import { FeatherIcon } from 'frappe-ui'


const actions = createListResource({
  doctype: 'Fuel Used',
  fields: ["resource","fuel_issued_lts"],
  limit: 100,
  filters: {
    docstatus: 1,
  }
})

actions.reload()

const issueFuelDialogShown = ref(false)

const issueFuel = () => {
  actions.insert.submit({

  })
}

const sites = createListResource({
  doctype: 'Site',
  fields: ['name', 'name'],
  transform(sites) {
    return sites.map((s) => ({label: s.name, value: s.name}))
  }
})
sites.reload()

const ListOfSite = computed(() => {
  if (sites.list.loading || !sites.data){
    return []
  }
  

  return sites.data
})
</script>





