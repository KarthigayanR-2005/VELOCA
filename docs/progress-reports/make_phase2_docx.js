const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, AlignmentType, LevelFormat
} = require("docx");

const PAGE = { width: 12240, height: 15840 }; // US Letter
const brand = "2F6FED";
const dark = "1A1A1A";
const gray = "5B6270";
const lightBg = "EEF3FF";

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 300, after: 150 },
    children: [new TextRun({ text, bold: true, color: brand, size: 30 })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 260, after: 120 },
    children: [new TextRun({ text, bold: true, color: dark, size: 24 })],
  });
}
function body(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 140 },
    children: [new TextRun({ text, size: 22, color: dark, ...opts })],
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullet-list", level },
    spacing: { after: 80 },
    children: [new TextRun({ text, size: 22, color: dark })],
  });
}
function statusRow(label, value, valueColor) {
  return new TableRow({
    children: [
      new TableCell({
        width: { size: 4500, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: lightBg },
        margins: { top: 100, bottom: 100, left: 150, right: 150 },
        children: [new Paragraph({ children: [new TextRun({ text: label, bold: true, size: 20, color: dark })] })],
      }),
      new TableCell({
        width: { size: 5200, type: WidthType.DXA },
        margins: { top: 100, bottom: 100, left: 150, right: 150 },
        children: [new Paragraph({ children: [new TextRun({ text: value, size: 20, color: valueColor || dark })] })],
      }),
    ],
  });
}

const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullet-list",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 450, hanging: 260 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 900, hanging: 260 } } } },
        ],
      },
    ],
  },
  sections: [
    {
      properties: { page: { size: PAGE, margin: { top: 900, bottom: 900, left: 1100, right: 1100 } } },
      children: [
        new Paragraph({
          spacing: { after: 40 },
          children: [new TextRun({ text: "VELOCA — Progress Report", bold: true, size: 44, color: brand })],
        }),
        new Paragraph({
          spacing: { after: 300 },
          children: [new TextRun({ text: "Phase 2 — Making the network react to load, and breaking it on purpose", size: 22, color: gray, italics: true })],
        }),

        new Table({
          width: { size: 9700, type: WidthType.DXA },
          columnWidths: [4500, 5200],
          rows: [
            statusRow("Phase", "Phase 2 of 5 — Flash-Surge Injection"),
            statusRow("Status", "Complete and verified working", "1E8E3E"),
            statusRow("Date", "9 September 2026"),
          ],
        }),

        new Paragraph({ spacing: { before: 300 }, children: [] }),

        h1("What this step was about"),
        body(
          "Phase 1 built a calm, steady fake network — six nodes quietly reporting numbers that barely moved. That's not very useful for testing a system meant to react to trouble. " +
          "Phase 2's job was twofold: first, make the network actually BEHAVE like a real one under stress — so pushing more traffic through it causes real slowdowns and drops, not just cosmetic wobble. " +
          "Second, build two tools to deliberately cause that stress on demand: one to simulate a traffic surge, and one to simulate faults (a node going down, a link getting slow, a link losing packets)."
        ),

        h1("What was actually built"),

        h2("1. Nodes that genuinely get congested under load"),
        body("Each of the six nodes now runs a small, realistic \"traffic jam\" model instead of just wobbling around a fixed number:"),
        bullet("Every node has a capacity — a ceiling on how much it can handle at once, based on its weakest connected link."),
        bullet("When more traffic arrives than a node can handle, a backlog (queue) starts building up, exactly like cars backing up at a bottleneck."),
        bullet("The bigger that backlog gets, the higher the delay (latency) climbs — slowly at first, then very sharply once the node is close to maxed out, which is how real congestion behaves."),
        bullet("If the backlog fills up completely, the node starts dropping traffic (packet loss), just like an overflowing buffer would."),
        bullet("Nodes also pass a slice of their traffic to their neighbours, so a problem on one node can genuinely ripple outward to the nodes next to it — not just stay isolated."),
        body("Everything settles back to calm and normal the moment the extra load goes away — nothing stays artificially broken."),

        h2("2. A \"load generator\" to simulate a traffic surge"),
        body("A new command-line tool, loadgen, can aim a traffic surge at any node(s) and shape it three ways:"),
        bullet("spike — a sharp, sudden jump up and back down"),
        bullet("ramp — a slower, smoother build-up and wind-down"),
        bullet("plateau-only — an instant jump that holds steady, then an instant drop"),
        body("It runs for as long as requested, then automatically hands the node back to its normal traffic level, and writes down exactly what it sent (as a file) so the exact same test can be checked or repeated later."),

        h2("3. A \"chaos\" tool to simulate faults"),
        body("A second command-line tool, chaos, can deliberately break things on a timer:"),
        bullet("kill — a node goes down and stops reporting entirely, like a crash"),
        bullet("latency — a node gets slower for a chosen amount of time"),
        bullet("loss — a specific connection between two nodes starts dropping a percentage of its traffic for a chosen amount of time"),
        body("Every fault it triggers is written down precisely (exactly what, on what, at what time, for how long) into an \"answer key\" file. This matters a lot later: when the AI in Phase 3 tries to detect and diagnose problems automatically, this file is the ground truth used to check whether it got the right answer."),

        h2("4. Visible on the dashboard, markers included"),
        body("The dashboard now also shows how much traffic is being pushed at each node (\"offered load\"), and every time a surge or a fault starts or ends, a marker appears on all the graphs at that exact moment — so it's immediately obvious, just by looking, when something was deliberately triggered and how the network responded."),

        h2("5. One-command demo"),
        body("Running a single command now launches a ready-made demo scenario: two nodes get hit with a sharp traffic surge, and shortly after, a connection between two other nodes starts dropping packets — all logged and marked on the dashboard automatically."),

        h1("What was verified working"),
        bullet("Running the demo surge made the targeted nodes visibly slow down, back up, and start dropping some traffic — then cleanly return to normal once the surge ended."),
        bullet("The single weakest connection shared by the two surged nodes turned out to be exactly the point that got overwhelmed — confirming the model behaves like a real bottleneck, not a random effect."),
        bullet("The deliberately broken connection showed up clearly and precisely as extra dropped traffic on that connection, matching the exact percentage requested."),
        bullet("Running the identical demo twice with the same settings produced two very closely matching results — proving the simulation is a fair, repeatable test bed and not just random noise."),
        bullet("The \"answer key\" file recorded both fault events with the exact timing and settings used, ready for later automated checking."),

        h1("An honest caveat"),
        body(
          "One effect is real but subtle rather than dramatic: the deliberately broken connection sits between two nodes that, during this particular demo, were also receiving a lot of extra traffic " +
          "spilling over from the surged nodes right next to them. That extra traffic more than made up for what the broken connection was losing, so the affected node's overall numbers actually went up, not down, during the test. " +
          "The fault itself is working exactly as designed — it can be seen directly and precisely in the sending node's own \"dropped traffic\" reading — it's just masked in the bigger picture by a stronger, unrelated effect happening at the same time. " +
          "This kind of nuance is exactly the sort of thing worth calling out plainly rather than glossing over."
        ),

        h1("What this sets up for next"),
        body("With a network that now reacts realistically to both stress and faults, and tools to trigger both on demand with an exact record of what happened, the next steps will:"),
        bullet("Add the AI layer that watches all this happen and learns which causes lead to which effects (Phase 3)"),
        bullet("Let the system automatically reroute traffic to heal itself when it recognises a problem (Phase 4)"),
        bullet("Compare how well the AI-driven healing does against simply reacting to symptoms, using repeatable tests like the ones built here (Phase 5)"),

        h1("In one sentence"),
        body("The fake network can now genuinely get sick — and there are tools to make it sick on purpose, on a timer, with a precise medical record of what was done — which is exactly what the AI in the next phase will need to learn from.", { bold: true }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  require("fs").writeFileSync(process.argv[2] || "VELOCA_Phase2_Progress_Report.docx", buf);
  console.log("written");
});
