# Spike 0a: React 19 source location in Next.js 16

- **Date:** 2026-10-19
- **Versions:** next 16.4.2 (Turbopack, with `cacheComponents: true` from create-next-app), react and react-dom 19.3.0, code-inspector-plugin 2.0.9, bippy 0.7.3, Node 22.21.
- **Method:** a throwaway create-next-app project in scratch space, probed with Playwright and Chromium. No spike code is in the repo.

The true lines in the test app:
- page.tsx: section 10, h1 11, the `<Item>` call 16, the `<Button>` call 19;
- Counter.tsx: root div 9, button 10, `<Button>` call 13;
- Item.tsx: li 3;
- Button.tsx: button 5.

## Results

| Case | A: build-time `data-insp-path` | B: runtime `_debugStack` + bippy + Next endpoint |
|---|---|---|
| (a) client component root `<div>` | `page.tsx:13` ✗ (call site) | `Counter.tsx:9` ✓ |
| (a) inner `<button>` | `Counter.tsx:10` ✓ | `Counter.tsx:10` ✓ |
| (b) server `<section>` / `<h1>` | `page.tsx:10` / `:11` ✓ | `src/app/page.tsx:10` / `:11` ✓ |
| (c) `<li>` rendered by `.map` | `page.tsx:16` ✗ (all items) | `Item.tsx:3` ✓ |
| (d) Button inside a client component | `Counter.tsx:13` ✗ | `Button.tsx:5` ✓ |
| (d) Button inside a server component | `page.tsx:19` ✗ | `Button.tsx:5` ✓ |
| Fragment root (`<><span/></>`) | call site ✗ | `Frag.tsx:4` ✓ |
| Library component (`next/link`) | call site (props spread) | `node_modules/next/…/link.tsx:787`. Walking the owner stack to the first frame inside the project gives the right one. |

**Why A gives the call site:** code-inspector rewrites each component's root element to take `data-insp-path` from its props when the caller passes one. So the outermost caller always wins, and no option turns that off. It's a design choice in the plugin, not a bug.

**HMR (3 lines inserted at the top of each file):**
- A updates live.
- B updates live for server frames. For client frames it updates only with bippy's source-map cache turned off, `getSource(fiber, false)`; with the cache on, client lines stay stale until a reload.

## Decision

**Q1: method B alone.**
- It is the only method that was correct in every case.
- It needs zero user configuration beyond the script tag kingkai already injects.
- Mixing in A would make behaviour depend on the element.

Reasons against A, besides accuracy:
- Its default hotkey (Alt+Shift) clashes with ours.
- Its IDE server listens on `*:5678`, all interfaces.
- 2.0.9 bundles agent integrations, including a `bypassPermissions` option: too much surface for a dev dependency.

If "where it is used" is ever wanted, B's owner stack already has it as its second frame.

**Q2: path forms.** All of B's raw frame URLs are resolved **inside the overlay**, never in Python:

| Raw frame | How the overlay resolves it | Path it gets |
|---|---|---|
| client `http://<dev origin>/_next/static/chunks/<hash>._.js:L:C` | bippy source maps (`getSource(fiber, false)`) | `file:///abs/path` |
| server `about://React/<Env>/file:///…/.next/dev/server/chunks/ssr/….js?…` (Env seen: `Prerender`; may be double-encoded) | `POST /__nextjs_original-stack-frames` (fields `line1`/`column1`; 1–8 ms) | **relative to the Next.js app root**, e.g. `src/app/page.tsx` |

So the payload carries either an absolute `file://` URL or a path relative to the **Next.js app root**. In a monorepo, the Next.js app root may not be the Claude project root. That's why the Next snippet also renders `data-kingkai-app-root` (the server's `process.cwd()`), and the overlay makes relative paths absolute before sending.

## Probe used (shape of the overlay resolver)

```js
async (el) => {
  const key = Object.keys(el).find((k) => k.startsWith("__reactFiber$"));
  const fiber = key && el[key];
  if (!fiber) return { error: "no fiber" };
  const src = await getSource(fiber, false);            // bippy/source; false = no map cache (HMR)
  if (!src) return { error: "no source" };
  const env = /^about:\/\/React\/([^/]+)\//.exec(src.fileName);
  if (!env) return { file: src.fileName, line: src.lineNumber, col: src.columnNumber };
  const r = await fetch("/__nextjs_original-stack-frames", { method: "POST", body: JSON.stringify({
    frames: [{ file: src.fileName, methodName: src.functionName ?? "", line1: src.lineNumber,
               column1: src.columnNumber, arguments: [] }],
    isServer: true, isEdgeServer: false, isAppDirectory: true }) });
  const o = (await r.json())[0]?.value?.originalStackFrame;
  return { file: o?.file, line: o?.line1, col: o?.column1 };
}
```

## Risks and mitigations

- **B depends on React internals (`__reactFiber$`, `_debugStack`), a private Next.js endpoint, and bippy's URL parsing.**
  - Pin bippy in `overlay/package.json`.
  - E2E covers each case on `examples/next-demo`.
  - The overlay shows "couldn't locate source" instead of guessing.
- **Text nodes have no fiber key.** Use `parentElement`.
- **`captureOwnerStack()` returns null in DOM handlers.** That doesn't matter: `_debugStack` is captured when the element is created.

## Spec changes made from this spike

- **§8.1 payload:** `source` becomes an ordered `candidates` list (owner-stack frames, innermost first, at most 10). Python picks the first candidate that passes `parse_reference`. That moves the "first frame inside the project" rule into Python, next to S4.
- **§8.2:** decision B, `data-kingkai-app-root`, and bippy pinned.
- **§13:** Q1 and Q2 resolved.
