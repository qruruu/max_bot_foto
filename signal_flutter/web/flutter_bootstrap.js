{{flutter_js}}
{{flutter_build_config}}
_flutter.loader.load({
  config: {canvasKitBaseUrl: 'canvaskit/'},
  onEntrypointLoaded: async function(engineInitializer) {
    const app = await engineInitializer.initializeEngine();
    await app.runApp();
    document.getElementById('opening')?.remove();
  }
});
