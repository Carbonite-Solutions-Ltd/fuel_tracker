<template>
    <div class="fuel-used-form">
      <h2>Enter Details for Fuel Used</h2>
      <form @submit.prevent="preventDefault">
        <div class="p-2">
          <TextInput
            v-model="fuelUsedData.date"
            type="date"
            size="sm"
            variant="subtle"
            placeholder="Select Date"
            :disabled="false"
          />
        </div>
  
        <!-- Frappe UI Autocomplete for Fuel Tanker -->
        <div class="p-2">
          <Autocomplete
            :options="tankers"
            v-model="fuelUsedData.fuel_tanker"
            placeholder="Select Fuel Tanker"
          />
        </div>
  
        <!-- Frappe UI Autocomplete for Site -->
        <div class="p-2">
          <Autocomplete
            :options="sites"
            v-model="fuelUsedData.site"
            placeholder="Select Site"
          />
        </div>
  
        <!-- Frappe UI Autocomplete for Site -->
        <div class="p-2">
          <Autocomplete
            :options="resources"
            v-model="fuelUsedData.resource"
            placeholder="Select Resource"
          />
        </div>
        <!-- Readonly TextInput for Reg No -->
        <div class="p-2">
          <TextInput
            v-model="fuelUsedData.reg_no"
            label="Registration Number"
            placeholder="Registration Number"
            readonly
          />
        </div>
  
        <!-- Readonly TextInput for Resource Type -->
        <div class="p-2">
          <TextInput
            v-model="fuelUsedData.resource_type"
            label="Resource Type"
            placeholder="Resource Type"
            readonly
          />
        </div>
  
        <!-- Readonly TextInput for Make -->
        <div class="p-2">
          <TextInput
            v-model="fuelUsedData.make"
            label="Make"
            placeholder="Make"
            readonly
          />
        </div>
  
        <!-- Readonly TextInput for Type -->
        <div class="p-2">
          <TextInput
            v-model="fuelUsedData.type"
            label="Type"
            placeholder="Type"
            readonly
          />
        </div>
  
        
  
        <!-- Submit Button -->
        <div class="p-4">
          <button type="button" @click="submitFuelUsed" :disabled="isSubmitting">
            Submit
          </button>
  
        </div>
      </form>
    </div>
  </template>
  
  <script>
  import { Autocomplete, TextInput } from 'frappe-ui';
  import { saveFuelUsedOffline } from '/src/main.js';
  import { db } from '/src/main.js';

    export default {
    components: {
        Autocomplete,
        TextInput,
    },
    data() {
        return {
        fuelUsedData: {
            date: '',
            fuel_tanker: '',
            site: '',
            reg_no: '',
            resource_type: '',
            make: '',
            type: '',
            resource: '',
        },
        isSubmitting: false,
        tankers: [],
        sites: [],
        resources: [],
        };
    },
    mounted() {
    this.fetchFuelTankerOptions();
    this.fetchSiteOptions();
    this.fetchResources();

    window.addEventListener('online', async () => {
        alert("Internet connection restored, attempting to sync offline data...");

        console.log('Back online, syncing submissions...');
        const submissions = await db.fuelUsed.toArray();
        if (submissions.length > 0) {
            for (const submission of submissions) {
                try {
                    const response = await fetch('/api/resource/Fuel Used', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Frappe-CSRF-Token': window.csrf_token,
                        },
                        body: JSON.stringify({ data: submission }),
                    });

                    if (response.ok) {
                        console.log('Submission synced successfully', submission);
                        await db.fuelUsed.delete(submission.id);
                    } else {
                        console.error('Failed to sync submission', submission);
                    }
                } catch (error) {
                    console.error('Error syncing submission', submission, error);
                }
            }
            alert('All offline data has been synced.');
            this.resetForm(); // Optionally reset the form or update the UI as needed.
        } else {
            console.log("No offline data to sync.");
        }
    });

    },
    watch: {
    'fuelUsedData.resource': {
      immediate: true,
      async handler(newVal) {
        if (newVal && newVal.value) {
          await this.fetchResourceDetails(newVal.value);
        } else {
          // Clear related fields if resource is cleared or not selected
          this.clearRelatedFields();
        }
      },
    },
  },
  
    methods: {
      async fetchFuelTankerOptions() {
        const apiUrl = '/api/method/fuel_tracker.api.get_fuel_tanker_options';
        try {
          const response = await fetch(apiUrl, {
            headers: { 'X-Frappe-CSRF-Token': window.csrf_token },
          });
          if (!response.ok) {
            throw new Error(`Failed to fetch fuel tanker options: ${response.statusText}`);
          }
          const data = await response.json();
          this.tankers = data.message || [];
        } catch (error) {
          console.error('Error fetching fuel tanker options:', error);
        }
        // Implementation remains the same
      },
      async fetchSiteOptions() {
        const apiUrl = '/api/method/fuel_tracker.api.get_site_options';
        try {
          const response = await fetch(apiUrl, {
            headers: { 'X-Frappe-CSRF-Token': window.csrf_token },
          });
          if (!response.ok) {
            throw new Error(`Failed to fetch site options: ${response.statusText}`);
          }
          const data = await response.json();
          this.sites = data.message || [];
        } catch (error) {
          console.error('Error fetching site options:', error);
        }
        // Implementation remains the same
      },
  
      async fetchResources() {
        const apiUrl = '/api/method/fuel_tracker.api.get_resources';
        try {
          const response = await fetch(apiUrl, {
            headers: { 'X-Frappe-CSRF-Token': window.csrf_token },
          });
          if (!response.ok) {
            throw new Error('Failed to fetch resources');
          }
          const data = await response.json();
          this.resources = data.message || [];
        } catch (error) {
          console.error('Error fetching resources:', error);
        }
      },
  
      clearRelatedFields() {
      this.fuelUsedData.reg_no = '';
      this.fuelUsedData.resource_type = '';
      this.fuelUsedData.make = '';
      this.fuelUsedData.type = '';
      },
  
      async fetchResourceDetails(resourceName) {
      console.log(`Fetching details for: ${resourceName}`);
      const apiUrl = `/api/method/fuel_tracker.api.get_resource_details?resource_name=${encodeURIComponent(resourceName)}`;
      try {
        const response = await fetch(apiUrl, {
          headers: { 'X-Frappe-CSRF-Token': window.csrf_token },
        });
        if (!response.ok) {
          throw new Error(`Failed to fetch details for the selected resource: ${response.statusText}`);
        }
        const { message } = await response.json();
        if (message && message !== 'No details found for the selected resource.') {
          // Update fields with the fetched details
          this.fuelUsedData.reg_no = message.reg_no || '';
          this.fuelUsedData.resource_type = message.resource_type || '';
          this.fuelUsedData.make = message.make || '';
          this.fuelUsedData.type = message.type || '';
        } else {
          // Clear the fields if no details are found
          this.clearRelatedFields();
        }
      } catch (error) {
        console.error(`Error fetching details for the selected resource: ${error}`);
        this.clearRelatedFields();
      }
    },
    // Inside your Vue component
        async submitFuelUsed() {
        this.isSubmitting = true;
        let payload = {
            ...this.fuelUsedData,
            fuel_tanker: this.fuelUsedData.fuel_tanker?.value,
            site: JSON.stringify(this.fuelUsedData.site), // Stringify complex objects
            resource: this.fuelUsedData.resource?.value,
        };

        try {
            if (!navigator.onLine) {
            // Offline, save submission locally
            console.log('Offline, attempting to save submission:', payload);
            await saveFuelUsedOffline(payload); // Assuming this function is correctly imported or accessible
            alert('You are offline. Data has been saved locally and will sync when you are back online.');
            this.resetForm();
            } else {
            // Online - proceed with submission
            const response = await fetch('/api/resource/Fuel Used', {
                method: 'POST',
                headers: {
                'Content-Type': 'application/json',
                'X-Frappe-CSRF-Token': window.csrf_token,
                },
                body: JSON.stringify({ data: payload }),
            });

            if (!response.ok) {
                throw new Error('Failed to save Fuel Used.');
            }

            alert('Fuel Used saved successfully.');
            this.resetForm();
            }
        } catch (error) {
            console.error('Error:', error);
            alert(`Error: ${error.message}`);
        } finally {
            this.isSubmitting = false;
        }
        },


    resetForm() {
      this.fuelUsedData = {
        date: '',
        fuel_tanker: '',
        site: '',
        reg_no: '',
        resource_type: '',
        make: '',
        type: '',
        resource: '',
      };
    },
    preventDefault() {
      // This method should actually be used to prevent form submission, if it's not already doing so.
    },
  },
};


  </script>