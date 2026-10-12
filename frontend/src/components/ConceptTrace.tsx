const steps = ["代码提交", "编译证据", "概念根因", "提示阶梯", "理解验证", "记忆确认"];

export function ConceptTrace({ activeStep }: { activeStep: number }) {
  return (
    <ol className="concept-trace" aria-label="概念脉络轨迹">
      {steps.map((step, index) => (
        <li key={step} className={index < activeStep ? "is-complete" : index === activeStep ? "is-current" : ""} aria-current={index === activeStep ? "step" : undefined} aria-label={`${step}，${index < activeStep ? "已完成" : index === activeStep ? "当前步骤" : "尚未开始"}`}>
          <span className="trace-index" aria-hidden="true">{index + 1}</span>
          <span>{step}</span>
        </li>
      ))}
    </ol>
  );
}
