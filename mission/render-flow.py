#!/usr/bin/env python3
"""Render the lane graph to pictures. `lanes.py` is the only source.

Two outputs, because they answer different questions:
  flow.drawio  — editable, for someone reshaping the flow in draw.io
  flow.mmd     — Mermaid, rendered inline by GitHub and most IDEs, and spliced
                 into README.md between its generated markers

Hand-drawing either one is how a diagram comes to disagree with the code it
documents: the old flow.drawio still showed `P` as the lane root two stages
after `I` and `Gi` existed. Run this after touching LANE_CARDS.

    python3 mission/render-flow.py            # write both, update README
    python3 mission/render-flow.py --check    # exit 1 if anything is stale
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lanes

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
README = os.path.join(REPO, "README.md")
BEGIN = "<!-- BEGIN generated: mission/render-flow.py -->"
END = "<!-- END generated -->"

# The two lanes the shipped example boards use: one without integration cards,
# one with. Enough to show every card the template can file.
LANES = [(1, "lane 1 — integration-tests: false", False),
         (2, "lane 2 — integration-tests: true", True)]

IDEA, PLAN, REVIEW, BUILD = "#e1d5e7", "#dae8fc", "#ffe6cc", "#d5e8d4"
FILL = {"I": IDEA, "Gi": BUILD, "P": PLAN, "RVp": REVIEW, "Gp": BUILD,
        "TW": BUILD, "C": BUILD, "RVa": REVIEW, "TI": BUILD, "RVc": REVIEW, "Gc": BUILD}
GATES = {"Gi", "Gp", "Gc"}
SHORT = {"I": "refine idea", "Gi": "GATE — human accepts idea", "P": "plan",
         "RVp": "review", "Gp": "GATE — human commits plan", "TW": "tests RED",
         "C": "implement", "RVa": "review", "TI": "failsafe ITs",
         "RVc": "final review", "Gc": "GATE — human commits code"}
WHO = {"I": "researcher", "P": "manager", "RVp": "reviewer", "TW": "tester",
       "C": "coder", "RVa": "reviewer", "TI": "tester", "RVc": "reviewer",
       "Gi": "human", "Gp": "human", "Gc": "human"}


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def drawio():
    W, H, DX, DY, PER_ROW = 150, 46, 175, 92, 5
    cells, edges, y = [], [], 20
    for lane, title, its in LANES:
        cells.append(f'        <mxCell id="t{lane}" value="{_esc(title)}" '
                     f'style="text;fontSize=14;fontStyle=1" vertex="1" parent="1">\n'
                     f'          <mxGeometry x="40" y="{y}" width="620" height="24" as="geometry" />\n'
                     f'        </mxCell>')
        y += 34
        cards = lanes.lane_cards(lane, integration_tests=its)
        prev = None
        for i, c in enumerate(cards):
            row, col = divmod(i, PER_ROW)
            style = f"rounded=1;whiteSpace=wrap;html=1;fillColor={FILL[c['code']]};"
            if c["code"] in GATES:
                style += "strokeWidth=2;"
            cells.append(
                f'        <mxCell id="{c["id"]}" value="{_esc(c["id"] + " " + SHORT[c["code"]])}" '
                f'style="{style}" vertex="1" parent="1">\n'
                f'          <mxGeometry x="{40 + col * DX}" y="{y + row * DY}" '
                f'width="{W}" height="{H}" as="geometry" />\n        </mxCell>')
            if prev:
                edges.append(
                    f'        <mxCell id="e-{prev}-{c["id"]}" '
                    f'style="edgeStyle=orthogonalEdgeStyle;rounded=1;" edge="1" parent="1" '
                    f'source="{prev}" target="{c["id"]}">\n'
                    f'          <mxGeometry relative="1" as="geometry" />\n        </mxCell>')
            prev = c["id"]
        y += ((len(cards) - 1) // PER_ROW + 1) * DY + 20
        if lane == 1:
            edges.append(
                '        <mxCell id="e-lane1-lane2" value="lane 2 starts" '
                'style="edgeStyle=orthogonalEdgeStyle;rounded=1;dashed=1;" edge="1" parent="1" '
                'source="Gc1" target="I2">\n'
                '          <mxGeometry relative="1" as="geometry" />\n        </mxCell>')
    cells.append('        <mxCell id="rework" value="REWORK (up to 3 rounds)&#10;'
                 'RVp REJECT → P-rev → re-review → PASS&#10;'
                 'no rework loop on I: the idea gate is the loop" '
                 'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;dashed=1;" '
                 'vertex="1" parent="1">\n'
                 '          <mxGeometry x="820" y="60" width="280" height="70" as="geometry" />\n'
                 '        </mxCell>')
    cells.append('        <mxCell id="key" value="purple=idea (researcher) · blue=plan (manager) · '
                 'orange=review (reviewer) · green=build/test · thick=HUMAN GATE (0 agent time)" '
                 'style="text;fontSize=11;fontStyle=2" vertex="1" parent="1">\n'
                 f'          <mxGeometry x="40" y="{y}" width="900" height="20" as="geometry" />\n'
                 '        </mxCell>')
    return ('<mxfile host="app.diagrams.net" agent="kanban-render-flow" version="24.0.0">\n'
            '  <diagram id="lane-flow" name="Lane flow (generic template)">\n'
            f'    <mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" page="1" '
            f'pageWidth="1160" pageHeight="{y + 60}">\n'
            '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n'
            + "\n".join(cells + edges) + "\n      </root>\n    </mxGraphModel>\n"
            "  </diagram>\n</mxfile>\n")


def mermaid():
    out = ["flowchart LR"]
    for lane, title, its in LANES:
        cards = lanes.lane_cards(lane, integration_tests=its)
        out.append(f'  subgraph L{lane}["{title}"]')
        out.append("    direction LR")
        for c in cards:
            code, cid = c["code"], c["id"]
            label = f"{cid}<br/>{SHORT[code]}<br/><i>{WHO[code]}</i>"
            out.append(f'    {cid}{{{{"{label}"}}}}' if code in GATES
                       else f'    {cid}["{label}"]')
        out.append("    " + " --> ".join(c["id"] for c in cards))
        out.append("  end")
    out.append("  Gc1 -. lane 2 starts .-> I2")
    out.append("  classDef idea fill:#e1d5e7,stroke:#9673a6;")
    out.append("  classDef plan fill:#dae8fc,stroke:#6c8ebf;")
    out.append("  classDef review fill:#ffe6cc,stroke:#d79b00;")
    out.append("  classDef build fill:#d5e8d4,stroke:#82b366;")
    out.append("  classDef gate fill:#d5e8d4,stroke:#333,stroke-width:3px;")
    by_class = {"idea": [], "plan": [], "review": [], "build": [], "gate": []}
    for lane, _t, its in LANES:
        for c in lanes.lane_cards(lane, integration_tests=its):
            code = c["code"]
            key = ("gate" if code in GATES else
                   "idea" if code == "I" else
                   "plan" if code == "P" else
                   "review" if code in ("RVp", "RVa", "RVc") else "build")
            by_class[key].append(c["id"])
    for name, ids in by_class.items():
        if ids:
            out.append(f"  class {','.join(ids)} {name};")
    return "\n".join(out) + "\n"


def readme_block(mmd):
    return (f"{BEGIN}\n\n```mermaid\n{mmd}```\n\n"
            f"*Generated from `mission/lanes.py` by `mission/render-flow.py`; "
            f"editable copy in `mission/flow.drawio`.*\n\n{END}")


def splice(text, block):
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{README}: generated markers not found")
    head = text.split(BEGIN)[0]
    tail = text.split(END, 1)[1]
    return head + block + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any output is out of date; write nothing")
    args = ap.parse_args()
    targets = {os.path.join(HERE, "flow.drawio"): drawio(),
               os.path.join(HERE, "flow.mmd"): mermaid()}
    readme = open(README).read()
    targets[README] = splice(readme, readme_block(mermaid()))
    stale = [p for p, want in targets.items()
             if not os.path.exists(p) or open(p).read() != want]
    if args.check:
        for p in stale:
            print(f"stale: {os.path.relpath(p, REPO)}")
        return 1 if stale else 0
    for p, want in targets.items():
        with open(p, "w") as f:
            f.write(want)
    print("wrote " + ", ".join(sorted(os.path.relpath(p, REPO) for p in targets)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
