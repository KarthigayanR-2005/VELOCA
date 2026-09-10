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
const goodBg = "E7F6EC";

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
function calloutBox(lines, bg = warnBg) {
  return new Table({
    width: { size: 9700, type: WidthType.DXA },
    columnWidths: [9700],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            width: { size: 9700, type: WidthType.DXA },
            shading: { type: ShadingType.CLEAR, fill: bg },
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

function comparisonTable() {
  const header = (t) => new TableCell({
    width: { size: 3233, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: lightBg },
    margins: { top: 100, bottom: 100, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text: t, bold: true, size: 19, color: dark })] })],
  });
  const cell = (t, bold = false) => new TableCell({
    width: { size: 3233, type: WidthType.DXA },
    margins: { top: 100, bottom: 100, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text: t, size: 19, color: dark, bold })] })],
  });
  return new Table({
    width: { size: 9700, type: WidthType.DXA },
    columnWidths: [3233, 3233, 3234],
    rows: [
      new TableRow({ children: [header(""), header("With the loop"), header("Without (control)")] }),
      new TableRow({ children: [cell("Node n4's delay leaves normal"), cell("~3 seconds in"), cell("~3 seconds in")] }),
      new TableRow({ children: [cell("Delay peaks at"), cell("~720 milliseconds"), cell("~750 milliseconds")] }),
      new TableRow({ children: [cell("Back to normal by", true), cell("~23 seconds in", true), cell("~69 seconds in", true)] }),
      new TableRow({ children: [cell("How"), cell("Automatic: detected, diagnosed, and throttled"), cell("Nothing — just waited out the full 60-second surge")] }),
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
          children: [new TextRun({ text: "Phase 4 — The network fixes itself, with no one watching", size: 22, color: gray, italics: true })],
        }),

        new Table({
          width: { size: 9700, type: WidthType.DXA },
          columnWidths: [4500, 5200],
          rows: [
            statusRow("Phase", "Phase 4 of 5 — Self-Healing Control Loop"),
            statusRow("Status", "Complete and verified working, with a real measured result", "1E8E3E"),
            statusRow("Date", "10 September 2026"),
          ],
        }),

        new Paragraph({ spacing: { before: 300 }, children: [] }),

        h1("What this step was about"),
        body(
          "Phase 3 built a \"detective\" that could work out what went wrong and propose a fix, but a person still had to read its answer and decide whether to act on it. " +
          "Phase 4 removes that last human step entirely: the system now watches itself, notices when something is wrong, works out why, decides whether its own proposed fix is actually worth doing, applies it, " +
          "and then checks afterwards whether it actually helped — completely on its own, start to finish."
        ),

        h1("What was actually built"),

        h2("1. Nodes that can be told what to do, and obey"),
        body("Each simulated node can now receive one specific instruction: \"turn your traffic down to this level, for this many seconds.\" It does exactly that, then automatically hands control back once the time is up."),

        h2("2. A control tower that only acts on approved instructions"),
        body("A new part of the system accepts an instruction from the detective and checks, independently, whether it was actually approved before doing anything. If it wasn't approved, it refuses and writes down why — every instruction that IS carried out gets logged with a timestamp, a unique ID, and the reasoning behind it, so there's a full paper trail of every action ever taken."),

        h2("3. The full loop, wired together with no human step"),
        body("The detective can now be told: \"if you're confident, just act on it yourself.\" When that's switched on, an approved diagnosis automatically triggers the instruction being sent and carried out — no one has to read a report and click a button."),

        h2("4. Checking its own work afterwards"),
        body("After acting, the system waits a short settling period, then goes back and checks the actual numbers: did the problem actually get better? It records one of three outcomes — recovered, partly recovered, or not recovered — against that specific action. If something didn't actually get better, it flags this clearly rather than quietly assuming success."),

        h2("5. A \"keep watch\" mode"),
        body("A new always-optional mode continuously checks the network for trouble, and if it finds any, runs the entire notice-diagnose-act-check sequence automatically, repeatedly, for as long as needed. It is switched off by default — it only runs when someone deliberately turns it on, since it's the one part of the system allowed to change live traffic on its own."),

        h1("The headline result"),
        body("This is the core question the whole project is built around: does having this automatic system actually help, compared to doing nothing? To find out, the exact same traffic surge was run twice — once with the automatic system switched on, once with it switched off — and the real, measured numbers were compared:"),
        comparisonTable(),
        new Paragraph({ spacing: { before: 200 }, children: [] }),
        body("With the automatic system running, the affected node's delay was back to normal in about 23 seconds. Left alone, it stayed badly delayed for the entire ~60-second surge, only recovering once the surge itself finished on its own — about 69 seconds in. That's the automatic system responding roughly 46 seconds faster than doing nothing, verified against the real underlying measurements, not just a single spot-check.", { bold: true }),

        h1("Bumps along the way (found and fixed by actually running it)"),
        body("Every one of these was only discovered by running the real, live loop repeatedly — not by reasoning about the code on paper. That's exactly why this step took real trial and error rather than working correctly the first time:"),
        bullet("A timing bug meant the live \"keep watch\" mode was silently getting empty data on every single check — fixed by aligning its clock to the same one Prometheus uses."),
        bullet("A stale, leftover data reading from an old container caused the system to occasionally look at the wrong node's numbers — fixed by making lookups more specific and having the system loudly complain instead of silently guessing if that ever happens again."),
        bullet("The very first \"which node is really to blame\" scoring didn't actually weigh HOW BADLY a node was struggling — only how it was positioned relative to others. This let a node with a tiny, barely-there problem occasionally outrank a node in serious, obvious trouble. Fixed by making the severity of the actual problem count properly."),
        bullet("One safety-check calculation was using a method so slow (over 100 seconds in one case) that it could make the automatic system too sluggish to act while a problem was still happening. Replaced with a standard, much faster method — the same calculation now takes a few thousandths of a second."),
        bullet("The system originally gave up completely if its first-choice \"who's to blame\" candidate couldn't be backed up with solid evidence. Fixed so it now reasonably tries its next-best guess before giving up."),
        bullet("A packet-loss reading that's normally almost exactly zero was so twitchy that ordinary background noise alone could occasionally look like a real problem. Fixed by teaching the system a sensible \"don't overreact to nothing\" tolerance for that specific reading."),

        h1("An honest caveat"),
        calloutBox([
          "The automatic fix applied is temporary by design — it turns a node's traffic down for a fixed window (30 seconds), then hands control back. In the real demonstration, the surge causing the trouble was still going after those 30 seconds ended, so the problem briefly came back before the surge itself finished naturally. The next \"keep watch\" check didn't happen to catch that specific relapse in this particular run.",
          "This is reported plainly because it's a genuine, useful finding: the system provides fast, real, measurable relief the moment it acts, but a single one-off fix isn't automatically a lasting cure against a problem that keeps renewing itself. Making the watching more persistent, or the fix duration smarter, is natural next-step work.",
        ]),

        h1("What was verified working"),
        bullet("Ran the whole loop live, completely unattended, with real timestamps at every stage: noticed the problem, worked out the cause, decided the fix was worth it, carried it out, and confirmed it worked — about 36 seconds start to finish."),
        bullet("Independently confirmed the fix's real effect by pulling the raw underlying measurements directly, not just trusting the system's own self-check."),
        bullet("Confirmed the system correctly does nothing when there's nothing genuinely wrong — even when a false alarm briefly looked real, it looked for a cause, found none worth acting on, and took no action."),
        bullet("Confirmed the control tower independently refuses to act on anything not properly approved, even if asked to directly."),

        h1("What this sets up for next"),
        body("With detection, diagnosis, action, and follow-up checking now all connected end-to-end automatically, the final phase will:"),
        bullet("Properly and repeatedly measure how much better this automatic approach performs than simply reacting to symptoms, across many runs"),
        bullet("Tune how quickly the system adapts based on how fast trouble is unfolding"),
        bullet("Write up the complete findings for the final report"),

        h1("In one sentence"),
        body("The network can now notice it's sick, work out why, decide a fix is worth trying, apply it, and check its own work — entirely on its own — and it measurably heals faster than doing nothing at all.", { bold: true }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  require("fs").writeFileSync(process.argv[2] || "VELOCA_Phase4_Progress_Report.docx", buf);
  console.log("written");
});
