import Icon from "./Icon";

/** Step rail for the creation wizard. Forward jumps are locked until the earlier steps validate. */
export default function WizardStepper({ steps, current, onJump }) {
  return (
    <ol className="wiz-steps" aria-label="Wizard progress">
      {steps.map((s, i) => (
        <li key={s.id}>
          <button type="button" className={`wiz-step ${i === current ? "on" : ""} ${i < current ? "done" : ""}`}
            aria-current={i === current ? "step" : undefined} disabled={i > current} onClick={() => onJump(i)}>
            <span className="num" aria-hidden="true">{i < current ? <Icon name="check" size={12} /> : i + 1}</span>
            <span>{s.title}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}
