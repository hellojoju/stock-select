export default function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <section className="panel"><h2>{icon}{title}</h2>{children}</section>;
}
