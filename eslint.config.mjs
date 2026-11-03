// ESLint flat config for the inline <script> blocks of templates/*.html.
// tools/extract_inline_js.py writes them to build/inline-js/ (line numbers match the
// templates). The goal is catching undefined identifiers such as a missing helper.
import globals from "globals";

export default [
  {
    files: ["build/inline-js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "script",
      globals: {
        ...globals.browser,
        // Tailwind Play CDN build loaded from static/vendor before the inline config block.
        tailwind: "writable",
      },
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    rules: {
      "no-undef": "error",
    },
  },
];
