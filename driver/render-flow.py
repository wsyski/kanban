#!/usr/bin/env python3
"""Render the lane graph to pictures. `lanes.py` is the only source.

Two outputs, because they answer different questions:
  flow.drawio  — editable, for someone reshaping the flow in draw.io
  flow.mmd     — Mermaid, rendered inline by GitHub and most IDEs, and spliced
                 into README.md between its generated markers

Hand-drawing either one is how a diagram comes to disagree with the code it
documents: the old flow.drawio still showed `P` as the lane root two stages
after `I` and `Gi` existed. Run this after touching LANE_CARDS.

    python3 driver/render-flow.py            # write both, update README
    python3 driver/render-flow.py --check    # exit 1 if anything is stale
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "template"))                    # lanes lives there
import lanes

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
README = os.path.join(REPO, "README.md")
BEGIN = "<!-- BEGIN generated: driver/render-flow.py -->"
END = "<!-- END generated -->"

# The two lanes the shipped example boards use: one without integration cards,
# one with. Enough to show every card the template can file.
LANES = [(1, "lane 1 — integration-tests: false", False),
         (2, "lane 2 — integration-tests: true", True)]

IDEA, PLAN, REVIEW, BUILD = "#e1d5e7", "#dae8fc", "#ffe6cc", "#d5e8d4"
FILL = {"I": IDEA, "Gi": BUILD, "P": PLAN, "RVp": REVIEW, "Gp": BUILD,
        "TW": BUILD, "C": BUILD, "RVa": REVIEW, "TI": BUILD, "RVc": REVIEW, "Gc": BUILD}
GATES = set(lanes.board_schema.GATE_CODES)   # the one declaration (review I12)
SHORT = {"I": "refine idea", "Gi": "GATE — human accepts idea", "P": "plan",
         "RVp": "review", "Gp": "GATE — human commits plan", "TW": "unit tests",
         "C": "implement", "RVa": "review", "TI": "integration tests",
         "RVc": "final review", "Gc": "GATE — human commits code"}
WHO = {code: "human" if assignee == "human-gate" else assignee
       for code, _body, assignee, _parent, _skill in lanes.LANE_CARDS}


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def drawio():
    W, H, DX, DY, PER_ROW = 150, 60, 175, 106, 5   # H fits card + role on two lines
    cells, edges, y = [], [], 20
    for lane, title, its in LANES:
        cells.append(f'        <mxCell id="t{lane}" value="{_esc(title)}" '
                     f'style="text;fontSize=14;fontStyle=1" vertex="1" parent="1">\n'
                     f'          <mxGeometry x="40" y="{y}" width="620" height="24" as="geometry" />\n'
                     f'        </mxCell>')
        y += 34
        cards = lanes.lane_cards(lane, integration_tests=its)
        for i, c in enumerate(cards):
            row, col = divmod(i, PER_ROW)
            style = f"rounded=1;whiteSpace=wrap;html=1;fillColor={FILL[c['code']]};"
            if c["code"] in GATES:
                style += "strokeWidth=2;"
            cells.append(
                f'        <mxCell id="{c["id"]}" '
                f'value="{_esc(c["id"] + " " + SHORT[c["code"]])}&#10;{_esc(WHO[c["code"]])}" '
                f'style="{style}" vertex="1" parent="1">\n'
                f'          <mxGeometry x="{40 + col * DX}" y="{y + row * DY}" '
                f'width="{W}" height="{H}" as="geometry" />\n        </mxCell>')
            # Edges from the card's own parents, never from filing order: TW and C are
            # siblings under the plan gate (lanes.PARENTS), and a positional chain
            # would draw a picture of a graph the driver does not run.
            for parent in c["parents"]:
                edges.append(
                    f'        <mxCell id="e-{parent}-{c["id"]}" '
                    f'style="edgeStyle=orthogonalEdgeStyle;rounded=1;" edge="1" parent="1" '
                    f'source="{parent}" target="{c["id"]}">\n'
                    f'          <mxGeometry relative="1" as="geometry" />\n        </mxCell>')
        y += ((len(cards) - 1) // PER_ROW + 1) * DY + 20
        if lane == 1:
            edges.append(
                '        <mxCell id="e-lane1-lane2" value="lane 2 starts" '
                'style="edgeStyle=orthogonalEdgeStyle;rounded=1;dashed=1;" edge="1" parent="1" '
                'source="Gc1" target="I2">\n'
                '          <mxGeometry relative="1" as="geometry" />\n        </mxCell>')
    cells.append('        <mxCell id="rework" value="REWORK LOOPS&#10;'
                 # every loop is bounded by the lane's max-reworks; the diagram is
                 # generic, so it draws the house default (comments PRIOR-R6: the old
                 # labels said 3/2/2, which no option ever produced)
                 f'RVp REJECT → P-rev → RVp-r&#10;'
                 f'RVa/RVc REJECT → C-rev → RVa-r&#10;'
                 f'Gi REWORK → I-rev → Gi-r&#10;'
                 f'(each: max-reworks, default {lanes.MAX_REWORKS})" '
                 'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;dashed=1;" '
                 'vertex="1" parent="1">\n'
                 '          <mxGeometry x="820" y="60" width="280" height="90" as="geometry" />\n'
                 '        </mxCell>')
    cells.append('        <mxCell id="key" value="purple=idea · blue=plan · '
                 'orange=review · green=build/test · thick=HUMAN GATE (0 agent time)" '
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
        for c in cards:
            for parent in c["parents"]:
                out.append(f"    {parent} --> {c['id']}")
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
            f"*Generated from `template/lanes.py` by `driver/render-flow.py`; "
            f"editable copy in `driver/flow.drawio`.*\n\n{END}")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
    try:
        with open(README, encoding="utf-8") as f:
            targets[README] = splice(f.read(), readme_block(mermaid()))
    except FileNotFoundError:
        # None, not absent: `stale` is built FROM `targets`, so a README left out of the
        # dict would never be examined and `--check` would report a clean tree. CI runs
        # `--check`, and a missing README was a traceback there instead of this line
        # (2026-09-23 review, Important 20).
        targets[README] = None
    stale = [p for p, want in targets.items()
             if want is None or not os.path.exists(p) or _read(p) != want]
    if args.check:
        for p in stale:
            print(f"stale: {os.path.relpath(p, REPO)}"
                  + (" (missing — nothing to splice the diagram into)"
                     if targets[p] is None else ""))
        return 1 if stale else 0
    if targets[README] is None:
        raise SystemExit(f"{README}: missing — nothing to splice the diagram into")
    for p, want in targets.items():
        with open(p, "w") as f:
            f.write(want)
    print("wrote " + ", ".join(sorted(os.path.relpath(p, REPO) for p in targets)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
