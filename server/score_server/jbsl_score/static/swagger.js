'use strict';
window.ui = SwaggerUIBundle({
  url: '/admin/openapi.json',
  dom_id: '#swagger-ui',
  deepLinking: true,
  filter: true,
  displayRequestDuration: false,
  defaultModelsExpandDepth: -1,
  defaultModelExpandDepth: 3,
  supportedSubmitMethods: [],
  tryItOutEnabled: false,
  validatorUrl: null,
  persistAuthorization: false,
  withCredentials: false,
  queryConfigEnabled: false,
  syntaxHighlight: false,
  presets: [SwaggerUIBundle.presets.apis],
  // Documentation has no need to collect credentials or offer an authorization dialog.
  plugins: [() => ({components: {authorizeBtn: () => null, authorizeOperationBtn: () => null}})],
  layout: 'BaseLayout'
});
