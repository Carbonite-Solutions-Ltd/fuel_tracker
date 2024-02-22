module.exports = {
    pwa: {
      name: 'Fuel Tracker',
      themeColor: '#4DBA87',
      msTileColor: '#000000',
      appleMobileWebAppCapable: 'yes',
      appleMobileWebAppStatusBarStyle: 'black',
      // Further customization goes here
      workboxPluginMode: 'InjectManifest',
        workboxOptions: {
      swSrc: 'src/service-worker.js', // path to your custom service worker file
    },
    },
  };
  