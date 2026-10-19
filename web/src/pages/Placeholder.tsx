export function Placeholder({ title, phase, about }: { title: string; phase: number; about: string }) {
  return (
    <div className="page">
      <h1>{title}</h1>
      <p className="subtitle">{about}</p>
      {phase > 0 && <div className="card empty">Coming in phase {phase}.</div>}
    </div>
  );
}
