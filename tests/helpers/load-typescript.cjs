// Load trusted repo TypeScript in Node tests, including real generated validators.
const { readFileSync, existsSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.resolve(__dirname, '../..');
function createLoader(overrides = {}) {
  const cache = new Map();
  function load(relative) {
    const filename = path.resolve(root, relative);
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = { exports: {} };
    cache.set(filename, module);
    const nativeRequire = createRequire(filename);
    function requireLocal(specifier) {
      if (Object.hasOwn(overrides, specifier)) return overrides[specifier];
      const target = specifier.startsWith('@/')
        ? path.join(root, specifier.slice(2))
        : path.resolve(path.dirname(filename), specifier);
      if ((specifier.startsWith('.') || specifier.startsWith('@/')) && existsSync(`${target}.ts`))
        return load(`${target}.ts`);
      return nativeRequire(specifier);
    }
    const output = ts.transpileModule(readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    vm.runInThisContext(`(function(require,module,exports){${output}\n})`, { filename })(
      requireLocal,
      module,
      module.exports
    );
    return module.exports;
  }
  return load;
}
module.exports = { load: createLoader(), createLoader };
