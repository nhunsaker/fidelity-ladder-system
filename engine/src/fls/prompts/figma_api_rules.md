# Writing Figma plugin-API code through the MCP write tool

Constraints of the execution environment, summarized so a builder can work without loading the
vendor's skill package. When the host DOES have that skill available, load it as well; it is more
complete. These rules are the floor.

## Execution model
- Code runs as plain JavaScript in an async context that is already wrapped for you. Use top-level
  `await` and top-level `return`. Never wrap the body in an async IIFE.
- `return` is the only output channel. `console.log` is discarded.
- A failed script is atomic: nothing is applied. Read the error, fix the script, then retry. Never
  blind-retry the same code.
- Work in small steps and validate after each. One giant script is the most common source of bugs.
- Always return the ids of every node you created or changed.

## Things that throw
- `figma.notify()` is not implemented.
- `figma.currentPage = page` is not supported. Use `await figma.setCurrentPageAsync(page)`, and call
  it at most once per script.
- `getPluginData` / `setPluginData` are unavailable; the shared variants work.
- `loadAllPagesAsync` and `createImageAsync` are unavailable.
- Page context resets to the first page at the start of every script, so re-select the page each time.

## Values
- Colors are 0 to 1, not 0 to 255. `{r: 0.96, g: 0.96, b: 0.96}` is the 0xF5 surface grey.
  The three numbers being equal is what makes it grey; wireframes are grey unless the
  instructions say otherwise.
- Fills and strokes are read-only arrays. Clone, modify, then reassign.
- Await every promise. An unawaited font load or page switch fails silently.

## Text
Every text mutation follows one recipe: load the font, await it, then mutate. Skipping the load
throws "Cannot write to node with unloaded font". When editing existing text, read its current fonts
rather than assuming a default. Font style strings are exact and spaced: "Semi Bold", not "SemiBold".

## Layout
- Use the auto-layout constructor for any container whose children relate to each other. Absolute
  x and y decide where a container sits on the canvas; auto-layout decides how its children behave
  inside it. A container without auto-layout has no defense against text reflow.
- Append a child to its auto-layout parent BEFORE setting hug or fill sizing. Those values are
  rejected on a node that is not yet in a valid structural position. Fixed always works.
- Nodes appended straight to the page land at 0,0. Scan the page's existing children and place new
  top-level nodes clear of them.

## Useful shortcuts
- Batch property writes in a single set call rather than one statement per property.
- A CSS-like query selector searches nodes without manual recursion.
- A node can screenshot itself, which is cheaper than a separate screenshot call.
