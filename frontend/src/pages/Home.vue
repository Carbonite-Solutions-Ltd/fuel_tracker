<template>
<!-- <div class="max-w-3xl py-12 mx-auto">
  <ul>
    <li v-for="action in actions.data" :key="action.name"></li>
    {{ action.name }}
  </ul>
</div> -->

<Button @click="dialog1 = true">
  Show Dialog
</Button>
<Dialog
  :options="{
    title: 'Confirm',
    message: 'Are you sure you want to confirm this action?',
    size: 'xl',
    actions: [
      {
        label: 'Confirm',
        variant: 'solid',
        onClick: () => {
                },
      },
    ],
  }"
  v-model="dialog1"
/>
</template>

<script>
import { Dialog, createListResource } from 'frappe-ui'

// const actions = createListResource({
//   doctype: 'Make',
//   fields: ["name"],
//   limit: 100
// })

// actions.reload()
</script>


