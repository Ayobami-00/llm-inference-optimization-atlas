const descriptions: Record<string, string> = {
  INSTANCE_OF: "Classifies the source as a concrete instance of the target concept.",
  HAS_CHARACTERISTIC: "Records a workload or system characteristic that shapes this entity.",
  USES_TRAFFIC_REGIME: "Applies the target arrival, concurrency, or session pattern.",
  HAS_QUALITY_CONTRACT: "Binds the source to the quality checks it must satisfy.",
  HAS_SLO: "Binds the source to its latency, reliability, and goodput requirements.",
  USES_MODEL: "Runs or evaluates the target model revision.",
  EXECUTED_ON: "Places the source execution on the target hardware topology.",
  USES_RUNTIME: "Executes the source through the target pinned runtime build.",
  USES_CONFIGURATION: "Materializes or selects the target resolved configuration.",
  SUGGESTS: "Indicates that the source observation makes the target explanation plausible.",
  ASSOCIATED_WITH: "Records a scoped association without claiming a causal mechanism.",
  HYPOTHESIZED_TO_CAUSE: "States a falsifiable causal mechanism proposed before measurement.",
  VALIDATED_AS_BOTTLENECK: "Shows that Atlas evidence identified the target as a limiting factor.",
  TARGETS: "Shows which bottleneck or system pressure an optimization is designed to address.",
  TESTS: "Connects an experiment to the hypothesis or intervention it evaluates.",
  HAS_RUN: "Connects an experiment to one of its exact, reproducible executions.",
  COMPARES: "Uses the target run or configuration as part of a controlled comparison.",
  PRODUCES: "Shows the evidence artifact created from the source analysis or experiment.",
  SUPPORTS: "Provides Atlas experimental evidence consistent with the target claim.",
  CONTRADICTS: "Provides Atlas evidence inconsistent with the target claim.",
  REPLICATES: "Repeats the target evidence while recording the axes that changed.",
  IMPROVES: "Reports a measured improvement in the target metric or outcome.",
  DEGRADES: "Reports a measured degradation in the target metric or outcome.",
  NO_SIGNIFICANT_EFFECT: "Reports that the measured effect was not statistically resolved.",
  INTERACTS_WITH: "Records that the effect depends on another intervention or condition.",
  APPLIES_UNDER: "Restricts the claim to the target workload, system, or operating condition.",
  LIMITED_BY: "Identifies a boundary or condition that constrains the source claim.",
  JUSTIFIES: "Uses an accepted finding as part of the target deployment rationale.",
  REJECTS: "Records an alternative that the decision considered but did not select.",
  CITES: "Points to an external source for definition, prior work, or mechanism context.",
  SUPERSEDES: "Replaces an earlier artifact while preserving its historical record.",
  DERIVED_FROM: "Records the upstream artifact from which the source was produced.",
};

export function relationLabel(value: string): string {
  if (value === "USES_CONFIGURATION") return "selects / uses";
  return value.replaceAll("_", " ").toLowerCase();
}

export function relationDescription(value: string): string {
  return descriptions[value] ?? "Records an explicit, scoped relationship between these evidence entities.";
}
