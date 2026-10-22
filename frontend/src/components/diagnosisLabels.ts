const categoryLabels = new Map<string, string>([
  ["conceptual", "概念理解"],
  ["strategic", "解题策略"],
  ["procedural", "操作步骤"],
  ["expression", "表达方式"],
]);

export function diagnosisCategoryLabel(category: string): string {
  return categoryLabels.get(category) ?? category;
}
