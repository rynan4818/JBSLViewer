"use strict";
window.ui = SwaggerUIBundle({url: "/openapi.json", dom_id: "#swagger-ui", deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis], layout: "BaseLayout", validatorUrl: null,
  withCredentials: true, persistAuthorization: false, displayRequestDuration: true,
  defaultModelsExpandDepth: 0, docExpansion: "list"});
