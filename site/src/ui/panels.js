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
  // Not "claims". A claim step means the board *proposed* one, and whether it
  // was ever asserted is `stated`, which is null on every claim in a run that
  // refused. Labelling those "claims Chile (country)" and then printing "the
  // evidence did not support one" underneath is a page contradicting itself:
  // it reads as a bug, and the thing it is describing is the whole design.
  claim: "proposed",
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
    /*
      A run that declined, and it has to say what it got instead.

      "Nothing on the board cleared its threshold" is true and useless. Printed
      under a left column listing South America, Chile and the Central Valley,
      it reads as the page contradicting itself, and the honest content — that
      there *was* a best guess and it was not good enough — is exactly the thing
      being withheld.

      So: name the strongest candidate and print what it scored. On the Chile
      run that is 0.45, and the reason is visible in its parts: the model liked
      it at 1.00 and the solar constraint left 7.5% of the world admissible.
      A number a reader can check beats a sentence they have to take on trust.
    */
    const best = (final?.candidates ?? [])
      .slice()
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0];

    box.classList.add("refused");
    const closest = best
      ? `<dt>closest</dt>
         <dd>${escape(best.label)} · ${(best.score ?? 0).toFixed(2)}
           <span class="bar"><span class="bar-fill"
                 style="width:${Math.round((best.score ?? 0) * 100)}%"></span></span>
         </dd>
         <dt>why</dt>
         <dd>${(best.prior ?? 0).toFixed(2)} prior ×
             ${(best.admissibility ?? 0).toFixed(3)} admissible</dd>`
      : `<dt>why</dt><dd>Nothing reached the board.</dd>`;

    box.innerHTML = `
      <div class="level">no answer stated</div>
      <div class="value">Considered, and not enough.</div>
      <dl>${closest}</dl>`;
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
