const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const ts = require('typescript');
const vm = require('node:vm');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function renderToggle(savedTheme, mounted) {
  const selected = [];
  const module = { exports: {} };
  const source = ts.transpileModule(fs.readFileSync('components/app/theme-toggle.tsx', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const mockedRequire = (name) => {
    if (name === 'react')
      return { ...React, useState: () => [mounted, () => {}], useEffect: () => {} };
    if (name === 'next-themes')
      return { useTheme: () => ({ theme: savedTheme, setTheme: (t) => selected.push(t) }) };
    if (name === '@phosphor-icons/react') {
      const Icon = (props) => React.createElement('svg', props);
      return { MonitorIcon: Icon, MoonIcon: Icon, SunIcon: Icon };
    }
    if (name === '@/lib/shadcn/utils')
      return { cn: (...values) => values.filter(Boolean).join(' ') };
    return require(name);
  };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`)(
    mockedRequire,
    module,
    module.exports
  );
  const tree = module.exports.ThemeToggle({});
  return {
    html: renderToStaticMarkup(tree),
    buttons: tree.props.children.filter((c) => c.type === 'button'),
    selected,
  };
}

test('theme toggle server and initial browser markup match for every saved theme', () => {
  const server = renderToggle(undefined, false).html;
  for (const theme of ['dark', 'light', 'system']) {
    assert.equal(renderToggle(theme, false).html, server);
  }
});

test('mounted theme toggle selects exactly the saved theme and preserves controls', () => {
  for (const [index, theme] of ['dark', 'light', 'system'].entries()) {
    const { buttons, selected } = renderToggle(theme, true);
    assert.deepEqual(
      buttons.map((button) => button.props['aria-pressed']),
      [0, 1, 2].map((i) => i === index)
    );
    buttons.forEach((button) => button.props.onClick());
    assert.deepEqual(selected, ['dark', 'light', 'system']);
  }
});
