/**
 * FR-EXPORT - the analysis as a Markdown file. Assembled only from what the
 * API sent: the reporter's text, the engine's figures, the verified flags with
 * their citations, the method version and the disclaimer. Nothing is computed
 * here; figures are copied as served.
 */

import { formatUsd } from "./api";
import type { Impact, WordingFlag, Withheld } from "./types";

export interface ExportInput {
  impact: Impact;
  report: string;
  verified: { flag: WordingFlag; badge: string }[];
  withheld: Withheld[];
  header: string | null;
  replay: { message: string } | null;
  costUsd?: string | null;
}

const DISCLAIMER =
  "Indicative first view on synthetic data - not a catastrophe-model output and not advice. " +
  "Figures are deterministic loss-engine estimates; wording flags are machine-verified citations " +
  "for an analyst to review.";

export function analysisMarkdown(input: ExportInput, generatedAt = new Date()): string {
  const { impact } = input;
  const t = impact.totals;
  const lines: string[] = [
    `# CatSight analysis - ${impact.event.name}`,
    "",
    `Generated ${generatedAt.toISOString().replace("T", " ").slice(0, 16)} UTC · ` +
      `perspective: Lion Re (reinsurer) · basis: ${impact.as_if ? "as-if on the current book" : "actual"} · ` +
      `method ${impact.methodology?.version ?? "n/a"}`,
  ];
  if (input.replay) lines.push("", `> ${input.replay.message}`);

  lines.push(
    "",
    "## Headline figures",
    "",
    "| | |",
    "|---|---|",
    `| Insurers' claims (gross) | ${formatUsd(t.gross)} |`,
    `| Insurers keep | ${formatUsd(t.retained)} |`,
    `| Reinsurers pay (ceded) | ${formatUsd(t.ceded)} |`,
    `| **Our net (Lion Re)** | **${formatUsd(t.our_net)}** |`,
    `| Treaties responding / not | ${t.treaties_matched} / ${t.treaties_excluded} |`,
    "",
    "## Treaties that responded",
    "",
    "| Treaty | Insurer | Type | Gross | Ceded | Our net |",
    "|---|---|---|---|---|---|",
    ...impact.treaties.map(
      (r) => `| ${r.treaty_id} | ${r.cedent} | ${r.type} | ${formatUsd(r.gross)} | ${formatUsd(r.ceded)} | ${formatUsd(r.our_net)} |`,
    ),
    "",
    "## Wording to review",
    "",
    input.header ? `_${input.header}_` : "_The wording check did not run._",
    "",
  );
  if (input.verified.length === 0 && input.header) {
    lines.push("No clause in the matched wordings changes the answer for this event.", "");
  }
  for (const { flag, badge } of input.verified) {
    lines.push(
      `- **${flag.severity} · ${flag.treaty_id} · ${flag.issue_type}** - ${flag.explanation}`,
      `  > "${flag.citation.quote}"`,
      `  _${badge}_`,
    );
  }
  if (input.withheld.length) {
    lines.push("", `Withheld (failed verification, not shown as findings): ${input.withheld.length}`);
    for (const w of input.withheld) lines.push(`- ${w.treaty_id} ${w.issue_type}: ${w.reason ?? "no reason recorded"}`);
  }

  lines.push("", "## Analyst report", "", input.report.trim(), "");
  if (impact.excluded.length) {
    lines.push("## Did not respond", "", ...impact.excluded.map((e) => `- ${e.treaty_id}: ${e.reason}`), "");
  }
  lines.push(
    "---",
    "",
    DISCLAIMER,
    input.costUsd ? `Model cost of this run: $${input.costUsd}.` : "",
    "Synthetic portfolio and wordings; cedent names are fictional. Hazard: NOAA IBTrACS / USGS ShakeMap.",
    "",
  );
  return lines.filter((line, i, all) => !(line === "" && all[i - 1] === "")).join("\n");
}

export function downloadMarkdown(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
