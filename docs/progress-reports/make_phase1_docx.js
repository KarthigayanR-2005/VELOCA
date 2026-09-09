const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, AlignmentType, LevelFormat, convertInchesToTwip
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
          children: [new TextRun({ text: "Velocity-Adaptive Causal Discovery for Self-Healing Networks", size: 22, color: gray, italics: true })],
        }),

        new Table({
          width: { size: 9700, type: WidthType.DXA },
          columnWidths: [4500, 5200],
          rows: [
            statusRow("Phase", "Phase 1 of 5 — Foundation"),
            statusRow("Status", "Complete and verified working", "1E8E3E"),
            statusRow("Date", "8 September 2026"),
          ],
        }),

        new Paragraph({ spacing: { before: 300 }, children: [] }),

        h1("What this step was about"),
        body(
          "Before any \"smart\" (AI) part of this project can be built, there needs to be a small computer network to practice on. " +
          "This step built exactly that: a tiny fake network that behaves like a real one — nodes sending traffic, reporting their health, " +
          "and a central dashboard showing what's happening. No AI yet. This is the stage/practice ground the AI will run on later."
        ),

        h1("What was actually built"),

        h2("1. A small pretend network"),
        body("Six \"nodes\" (think of them as six routers/computers) connected to each other, arranged like a hexagon with a few crossing links — so traffic can take more than one path, similar to a real network."),

        h2("2. Six little programs pretending to be those nodes"),
        body("Each node runs its own small program that keeps reporting made-up but realistic numbers every second, such as:"),
        bullet("How much data it's pushing through (throughput)"),
        bullet("How delayed its traffic is (latency)"),
        bullet("How backed-up its queue is (queue depth)"),
        bullet("How much data it's losing (packet loss)"),
        body("The numbers wobble slightly each second (like real traffic does) but stay close to a steady baseline — so it looks alive, not robotic."),

        h2("3. A \"control tower\" watching all six nodes"),
        body("One central program listens to all six nodes and keeps track of:"),
        bullet("Which nodes are currently alive (reporting in regularly)"),
        bullet("Each node's latest numbers"),
        body("This can be checked any time from a simple web address, and it currently shows all 6 nodes as alive and reporting."),

        h2("4. A messaging system connecting everything"),
        body("The six node-programs and the control tower don't talk directly — they publish/listen through a lightweight messaging service (like a shared radio channel), which keeps the pieces independent and easy to expand later."),

        h2("5. Dashboards to see it happen"),
        body("A monitoring dashboard was set up that automatically shows live graphs for all six nodes side-by-side across throughput, latency, queue depth, and packet loss — no manual setup needed, it appears the moment the system starts."),

        h2("6. One command to run everything"),
        body("Instead of starting each piece by hand, the whole system (network, control tower, messaging, dashboards) starts with a single command, and stops with another single command."),

        h1("What was verified working"),
        bullet("All 6 simulated nodes came online and stayed “alive” in the control tower's view"),
        bullet("The monitoring system successfully picked up live data from all 6 nodes"),
        bullet("The dashboard showed real, moving graphs for all 6 nodes across every tracked metric"),

        h1("What this sets up for next"),
        body("With a living, observable network now in place, the next steps (later phases) will:"),
        bullet("Inject sudden traffic surges / faults into this network so there's something interesting to detect (Phase 2)"),
        bullet("Add the AI layer that learns cause-and-effect from the network's behaviour (Phase 3)"),
        bullet("Let the system automatically reroute traffic to heal itself when something goes wrong (Phase 4)"),
        bullet("Tune and evaluate how well it all works compared to a simpler, non-AI approach (Phase 5)"),

        h1("In one sentence"),
        body("A realistic, watchable fake network is now up and running end-to-end — the stage is set for the AI brain to be added next.", { bold: true }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  require("fs").writeFileSync(process.argv[2] || "VELOCA_Phase1_Progress_Report.docx", buf);
  console.log("written");
});
