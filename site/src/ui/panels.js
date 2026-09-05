/*
  The parts of the page that are text rather than 3D.

  Nothing here knows about three.js or about the state machine. It is handed a
  step and writes it out, which is why it can be rewritten without touching
  anything else.
*/
const evidence = () => document.getElementById("evidence");
const receipt = () => document.getElementById("receipt");

// How many lines stay on screen. Older ones leave rather than scroll: a
// growing wall of text pulls attention off the globe, which is the thing
// worth looking at.
const KEEP = 7;

// A tool that errored is recorded in the trace and belongs there. Reading it
// out as though it were an observation puts "mat1 and mat2 shapes cannot be
// multiplied" on screen beside a claim about Lahore, which tells a visitor
// nothing and costs the page its composure.
const FAILED = /\bfailed:/i;

// Machine names into something a person reads. The trace is written for
// debugging and the page is not.
const WHO = {
  observe: "observed",
  first_pass: "read",
  alternative: "considered",
  place_lookup: "gazetteer",
  solar_position: "sun",
  country_metas: "road",
  geocell_classifier: "classifier",
  verify: "checked",
  claim: "claims",
  constraints: "constraints",
};

export function clearEvidence() {
  lastKey = "";
  evidence().replaceChildren();
  const box = receipt();
  box.hidden = true;
  box.classList.remove("refused");
}

let lastKey = "";

export function renderEvidence(step) {
  const text = step.summary ?? "";
  if (!text || FAILED.test(text)) return;

  /*
    Collapse consecutive near-repeats.

    A gazetteer lookup that matched four addresses on the same avenue emits
    four lines that differ only in a postcode, and on screen that is a stutter
    rather than four findings. Keyed on the source plus the first forty
    characters, which is enough to catch the repeat and short enough not to
    swallow two genuinely different results from the same tool.
  */
  const key = `${step.source}|${text.slice(0, 40)}`;
  if (key === lastKey) return;
  lastKey = key;

  const line = document.createElement("div");
  line.className = "line";

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = WHO[step.source] ?? step.source ?? step.kind;

  line.append(who, document.createTextNode(text));
  const holder = evidence();
  holder.append(line);
  while (holder.children.length > KEEP) holder.firstChild.remove();
}

export function renderReceipt(final) {
  const box = receipt();
  const answer = final?.answer;

  if (!answer) {
    // Not a failure. A run that declined is the design working, and saying so
    // plainly is more interesting than hiding it.
    box.classList.add("refused");
    box.innerHTML = `
      <div class="level">no answer stated</div>
      <div class="value">The evidence did not support one.</div>
      <dl><dt>why</dt><dd>Nothing on the board cleared its threshold.</dd></dl>`;
    box.hidden = false;
    return;
  }

  // The chain, coarsest first, each with its confidence drawn as a length as
  // well as printed as a number. The bar is the honest part: a claim at 0.31
  // should not look like a claim at 0.94 just because both are two digits.
  const rows = (answer.chain ?? []).map((c) => {
    const pct = Math.round((c.confidence ?? 0) * 100);
    return `<dt>${c.level}</dt>
            <dd>${escape(c.value)} · ${pct}%
              <span class="bar"><span class="bar-fill"
                    style="width:${pct}%"></span></span>
            </dd>`;
  }).join("");

  box.classList.remove("refused");
  box.innerHTML = `
    <div class="level">${answer.level} · stated ${answer.stated ?? "—"}</div>
    <div class="value">${escape(answer.value)}</div>
    <dl>${rows}</dl>`;
  box.hidden = false;
}

// Trace values are written by a model. They reach the page as text, never as
// markup, whatever they happen to contain.
function escape(value) {
  const node = document.createElement("span");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}
