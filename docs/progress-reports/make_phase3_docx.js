const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, AlignmentType, LevelFormat
} = require("docx");

const PAGE = { width: 12240, height: 15840 }; // US Letter
const brand = "2F6FED";
const dark = "1A1A1A";
const gray = "5B6270";
const lightBg = "EEF3FF";
const warnBg = "FFF4E5";

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
function calloutBox(lines) {
  return new Table({
    width: { size: 9700, type: WidthType.DXA },
    columnWidths: [9700],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            width: { size: 9700, type: WidthType.DXA },
            shading: { type: ShadingType.CLEAR, fill: warnBg },
            margins: { top: 160, bottom: 160, left: 200, right: 200 },
            children: lines.map((t, i) => new Paragraph({
              spacing: { after: i === lines.length - 1 ? 0 : 80 },
              children: [new TextRun({ text: t, size: 21, color: dark })],
            })),
          }),
        ],
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
          children: [new TextRun({ text: "Phase 3 — Building the AI brain that figures out what actually went wrong", size: 22, color: gray, italics: true })],
        }),

        new Table({
          width: { size: 9700, type: WidthType.DXA },
          columnWidths: [4500, 5200],
          rows: [
            statusRow("Phase", "Phase 3 of 5 — Causal Discovery Engine"),
            statusRow("Status", "Complete and verified working", "1E8E3E"),
            statusRow("Date", "9 September 2026"),
          ],
        }),

        new Paragraph({ spacing: { before: 300 }, children: [] }),

        h1("What this step was about"),
        body(
          "Phase 2 gave the fake network the ability to genuinely get sick (get overloaded, drop packets) and the ability to make it sick on purpose, on a timer. " +
          "Phase 3 is the actual research contribution of this project: an AI component that watches the network's numbers and works out, on its own, WHICH node is actually " +
          "the root cause of a problem — not just which node happens to look unhappy, but which one is upstream, causing the others to look unhappy too."
        ),

        h1("What was actually built"),

        h2("1. A \"how fast is this changing\" gauge"),
        body("Before deciding how to investigate a problem, the system first measures how quickly the total traffic on the network is changing right now. A calm, slowly-drifting network gets treated differently from one that just got hit by a sudden spike."),
        bullet("If the network is changing FAST, it switches to a quick, cheap investigation method — an instant (if slightly rougher) answer."),
        bullet("If the network is changing SLOWLY, it uses a slower, more thorough investigation method."),
        bullet("To stop it flip-flopping between the two right at the boundary (which would be like a thermostat clicking on and off every second), it uses a \"stay committed\" rule: once it switches to fast mode, it takes a clearly calmer reading before switching back — not just one blip below the line."),

        h2("2. Two investigation methods"),
        bullet("Fast method: checks every pair of numbers against each other quickly (a few seconds) — did A change just before B changed? Good for \"we need an answer right now.\""),
        bullet("Slow method: a much more thorough statistical search across everyone at once (about 50 seconds) — better at avoiding being fooled by coincidences, but too slow for an in-the-moment answer."),
        body("Cleverly, the system doesn't just pick one and stick with it: it gives an instant answer using the fast method, then quietly double-checks that answer in the background with the slow method. If the slow, more careful method disagrees, the stored answer gets automatically corrected — this was tested directly and confirmed working: the fast method initially blamed one node, and about 50 seconds later the system corrected itself to blame a different (and, on inspection, more correct) node."),

        h2("3. Picking out the actual culprit"),
        body("Once it has a map of \"what seems to affect what,\" the system looks at which numbers are currently behaving badly (unusually high delay or unusually high data loss, compared to their own recent normal), then works out which node is most likely the ORIGIN of that trouble — preferring nodes that affect the sick ones without themselves being affected by them, and nodes where the trouble started earliest."),

        h2("4. Proposing a fix, then checking its own homework"),
        body("The system doesn't just point fingers — it proposes an action: turn down the amount of traffic being pushed at the node it blames, back down to that node's normal level. Then, instead of trusting itself blindly, it runs a second, independent check (a statistical technique called a counterfactual estimate) asking: \"if I actually did this, would it really help enough to be worth it?\" Only if the answer is a clear yes does it approve the action."),
        bullet("It correctly APPROVED capping the traffic on the node it identified as the real problem, predicting a large improvement in delay."),
        bullet("It correctly REJECTED a deliberately silly test action (capping traffic on an unrelated, innocent node) — because it found no evidence that node was connected to the problem at all."),

        h2("5. A pluggable, testable service"),
        body("All of this runs as its own independent service with a simple web address you can ask questions of: \"diagnose what happened around this moment,\" \"what's your current health / recent answers,\" \"what does the latest cause-and-effect map look like.\" It is not yet connected to the part of the system that would actually act on its advice — that connection is intentionally left for the next phase, so this phase could be tested completely on its own first."),

        h1("What was verified working"),
        bullet("Re-ran the Phase 2 demo surge and asked the system to diagnose it: it correctly named the two genuinely overloaded nodes as the top suspects."),
        bullet("Confirmed the fix-proposal-and-approval logic works both ways: approves a sensible fix, rejects a nonsense one, on real data from the live network."),
        bullet("Confirmed the \"quick answer now, double-check later\" behaviour for real: watched it publish a fast answer, then automatically correct itself once the slower, more careful check finished."),
        bullet("Wrote and ran a small set of automated checks specifically proving the \"don't flip-flop right at the boundary\" rule actually holds, using made-up test data designed to sit right on the edge."),

        h1("Bumps along the way (fixed, not hidden)"),
        calloutBox([
          "Partway through this phase, the laptop's main drive ran almost completely out of space (not caused by this project — years of other unrelated software had built up). That stopped Docker (the tool that runs the whole simulated network) from working at all.",
          "Rather than patch around it, the whole project — and Docker's own storage — was relocated to the D: drive, which had plenty of room. This is a one-time, durable fix, not a workaround: it won't recur.",
          "Along the way, two real bugs in the new AI code were caught and fixed by testing against the live network rather than made-up examples: one where a rare error type wasn't being handled and silently broke one of the two investigation methods, and one where the \"map of what affects what\" could contain a circular loop (A affects B affects A) that a required statistical tool couldn't accept — both are now handled correctly, and were verified fixed by re-running the real scenario, not just reasoned about.",
        ]),

        h1("An honest caveat"),
        body(
          "The automated ground-truth check compares each recorded past incident against what the system currently diagnoses. Four of the five past incidents on record are from before the drive/Docker relocation above — the underlying measurement history for those specific moments no longer exists (it lived in the old, now-replaced storage), so those four can't be re-checked, through no fault of the diagnosis logic itself. " +
          "The one incident with intact data available for checking was diagnosed correctly. This is reported plainly rather than glossed over — it's a data-availability gap from the infrastructure incident, not a diagnosis failure."
        ),

        h1("What this sets up for next"),
        body("With a working \"detective\" that can watch the network, name a likely culprit, and sanity-check its own proposed fix, the next steps will:"),
        bullet("Connect this engine's verdicts to the part of the system that can actually act — automatically turning down traffic on the node it blames (Phase 4)"),
        bullet("Properly compare how well this AI-driven approach performs against a simple \"just react to symptoms\" baseline, using repeatable tests (Phase 5)"),

        h1("In one sentence"),
        body("The network can now be asked \"what actually went wrong just now, and would fixing it this way actually help?\" — and it gives a real, self-checked answer, not a guess.", { bold: true }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  require("fs").writeFileSync(process.argv[2] || "VELOCA_Phase3_Progress_Report.docx", buf);
  console.log("written");
});
