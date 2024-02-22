<template>
    <ion-page>
    <ion-header>
      <ion-toolbar>
        <div class="flex flex-row items-center justify-between mt-2 mr-2 ml-0">
        <ion-title>Fuel Tracker</ion-title>
        <div>
        <FeatherIcon @click="issueFuelDialogShown = true" src="././public/favicon.png" style="width: 24px; height: 24px;" />
        </div>   
        </div>
      </ion-toolbar>
    </ion-header>
  </ion-page>

  <div class="flex flex-row items-center justify-between mt-2 mr-2 ml-2">
    <h1 class="text-5xl font-black text-gray-900"></h1>
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
  <div class="space-y-4">
    <Variant title="Single option">
      <div class="p-2">
        <Autocomplete
          :options="ListOfSite"
          v-model="sites.name"
          placeholder="Select Site"
        />
      </div>
    </Variant>
    <Variant title="Single option">
      <div class="p-2">
        <Autocomplete
          :options="ListOfFuelTanker"
          v-model="fuelTankers.tanker"
          placeholder="Select Fuel Tanker"
        />
      </div>
    </Variant>
    <Variant title="Single option">
      <div class="p-2">
        <Autocomplete
          :options="ListOfResource"
          v-model="Resources.name"
          placeholder="Select Resource"
        />
      </div>
    </Variant>
    <Variant>
      <div class="p-2">
        <Input
        type="number"
          placeholder="Type In Odometer Reading"
        />
      </div>
    </Variant>
    <Variant>
      <div class="p-2">
        <Input
        type="number"
          placeholder="Type In Fuel Issued (LTS)"
        />
      </div>
    </Variant>
    <Variant>
    <div class="p-2">
    <FileUploader
      :fileTypes="['image/*']"
      :validateFile="validateFileFunction"
      @success="onSuccess"
    >
      <template
        v-slot="{
          file,
          uploading,
          progress,
          uploaded,
          message,
          error,
          total,
          success,
          openFileSelector,
        }"
      >
        <Button @click="openFileSelector" :loading="uploading">
          {{ uploading ? `Uploading ${progress}%` : 'Upload Img of Odometer' }}
        </Button>
      </template>
    </FileUploader>
  </div>
</Variant>
  </div>
</template>
</Dialog>


</template>

<script setup>


import { ref, computed, reactive } from 'vue'
import { Checkbox, Select, FeatherIcon, createResource, FileUploader, Button, Dialog, Input, Autocomplete, Card, createListResource } from 'frappe-ui'
import { session } from '../data/session'




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
  actions.insert.submit(action)
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



//List of Fuel Tanker
const fuelTankers = createListResource({
  doctype: 'Fuel Tanker',
  fields: ['tanker', 'tanker'],
  transform(fuelTankers) {
    return fuelTankers.map((s) => ({label: s.tanker, value: s.tanker}))
  }
})
fuelTankers.reload()

const ListOfFuelTanker = computed(() => {
  if (fuelTankers.list.loading || !fuelTankers.data){
    return []
  }

  return fuelTankers.data
})




//List of Resource
const Resources = createListResource({
  doctype: 'Resource',
  fields: ['name', 'name'],
  transform(fuelTankers) {
    return fuelTankers.map((s) => ({label: s.name, value: s.name}))
  }
})
Resources.reload()

const ListOfResource = computed(() => {
  if (Resources.list.loading || !Resources.data){
    return []
  }

  return Resources.data
})




const validateFileFunction = (fileObject) => {}
const onSuccess = (file) => {}
</script>





