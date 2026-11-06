// typescript-eslint supports the TypeScript 6 API only (TS 7 is a native port without it).
// Lint loads @typescript/typescript6 whenever a package asks for "typescript"; tsc and next
// build keep TypeScript 7.
const Module = require("node:module");
const resolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  return resolve.call(this, request === "typescript" ? "@typescript/typescript6" : request, ...rest);
};
